"""ホール×カテゴリ別のイベント日カレンダー（単一の情報源）。

## なぜ作ったか

イベント日の定義が 2026-08-01 時点で3箇所に分裂しており、うち1つが劣化版だった:

1. `eda/core.py` の `HALL_EVENT_DIGITS` + `is_x_day`
   = DDリスト OR 月末 OR 強ゾロ目。ホール単位で1本のDDリストしか持てない。
   みとやで DD{1,30}、楽園で DD{10,30} が欠落している。
2. `eda/section_lateral_expansion.py` の `HALL_CONFIGS[*].event_dds` + `strong_zorome`
   = 4ホールのみ収録。楽園は正しい。
3. `eda/briefing_common.py` の `is_event_dd`
   = DDリストのみを見る**劣化版**。月末も強ゾロ目も落ちる。

3 を使った分析で「楽園はイベント日に全カテゴリで9〜13pp弱い」という誤った結論が出た
（正しい定義では全カテゴリ +2.0〜+2.8pp のプラス）。原因は楽園の最強イベント日 DD30 が
非イベント日側に混入し、非イベント日の水準を押し上げていたこと。

## 何が必要だったか

実測の結果、必要な構造は「ホール単位の1本のDDリスト」ではなく
**ホール × カテゴリ**の2段階だと分かった:

- 楽園はカテゴリ別に別カレンダーを持つ（ジャグ限定日 DD{5,15,25} は
  ジャグのみ +5.56pp、他4カテゴリはマイナス）
- 蒲田7はカテゴリ別カレンダーを持たない（JUG・AT一般とも7系が主軸）
- 月末・強ゾロ目を全ホール一律に OR する `is_x_day` の設計は実測で支持されない。
  残差がほぼゼロ（±1pp）のホール×カテゴリが大半で、一律加算は対比を薄める。
  効くのは みとやOKI（月末+6.04 / 強ゾロ目+5.57）等の一部セルのみ

## status の意味（最重要）

このモジュールの肝は `status` である。イベント日は探索で見つけただけのものと、
事前登録+フォワードで確認したものが混在する。**両者を同じ確からしさで使うと、
今日と同じ「発見が検証を経ずに本番へ流れ込む」問題を形を変えて再生産する。**

- `confirmed`   … 事前登録+フォワード、または独立した2手法で再現済み。本番で使ってよい
- `watching`    … 実測で候補として浮上し、事前登録済みだが結果待ち
- `unconfirmed` … 探索スキャンで見えただけ。多重比較補正なし。**本番の特徴量に使わない**

呼び出し側は `min_status` で足切りできる。既定は `confirmed` のみ。

## 移行方針

`eda/core.py` の `HALL_EVENT_DIGITS` は27ファイルが参照しているため**そのまま残す**。
一括置換は今日と同種の「気づかれないバグ」を新たに作るリスクの方が高い。
問題が判明した経路（`eda/briefing_common.py` 等）から個別に本モジュールへ移し、
全て移り終えた時点で古い方を削除する。

## 未確定（意図的に空にしてある）

ARROW・ヒロキ・ザシティ・金時の4ホールは、theory文書に根拠の記載が無いまま
`HALL_EVENT_DIGITS` が使われていた。2026-08-01の棚卸しで初めて実測が付いたが、
いずれも単一手法・全期間平均・多重比較補正なしのため `unconfirmed` ですら
書き込んでいない。四半期別＋2手法で追試してから埋めること。
（→ `document/instincts/2026-08-01-eventday-audit-methodology.yaml`）
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from typing import Iterable, Literal

import pandas as pd

Status = Literal["confirmed", "watching", "unconfirmed"]

_STATUS_RANK: dict[str, int] = {"confirmed": 2, "watching": 1, "unconfirmed": 0}

# load_hall_frame が返すカテゴリ。UNKNOWN は master 未一致で、どのカレンダーにも属さない。
VALID_CATEGORIES = frozenset({"JUG", "HANA", "OKI", "BT", "AT一般"})


@dataclass(frozen=True)
class CategoryEventProfile:
    """1ホール1カテゴリぶんのイベント日定義。

    Attributes:
        event_dds: イベント扱いする日（月内日番号）。
        status: confirmed / watching / unconfirmed。モジュール docstring 参照。
        source: 根拠の所在。theory文書の節番号か、事前登録の rule_id を書く。
        measured_period: この定義を導いた期間（"2025Q3-2026Q3" 等）。
            イベント日は時間とともに動くため、いつ測ったかを必ず残す。
        use_month_end: 月末をイベント日に含めるか。暦を見て動的に判定する
            （30/31のハードコードは 2/4/6/9/11月で外れるため禁止）。
        use_strong_zorome: 強ゾロ目（月==日）をイベント日に含めるか。
    """

    event_dds: frozenset[int]
    status: Status
    source: str
    measured_period: str
    use_month_end: bool = False
    use_strong_zorome: bool = False
    note: str = ""


@dataclass(frozen=True)
class HallEventCalendar:
    """1ホールぶん。カテゴリごとに別のプロファイルを持てる。

    `shared` はカテゴリ別カレンダーを持たないホール用。蒲田7のように
    JUG・AT一般とも同じ体系（7のつく日）が主軸なら、カテゴリごとに
    同じ値を繰り返さず `shared` に1本だけ置く。
    """

    label: str
    by_category: dict[str, CategoryEventProfile] = field(default_factory=dict)
    shared: CategoryEventProfile | None = None


# ---------------------------------------------------------------------------
# 定義本体
#
# 埋める順序は「事前登録+フォワードで confirmed になったものから」。
# 探索で見えただけの値をここに書くと、status を見ずに使われて今日と同じことになる。
# ---------------------------------------------------------------------------

EVENT_CALENDAR: dict[str, HallEventCalendar] = {
    "楽園": HallEventCalendar(
        label="楽園蒲田店",
        by_category={
            # §3.1a はカテゴリ別カレンダーを実測で確定させた唯一の例。
            # 2026-08-01 に別経路（機種内残差スキャン）でも再現したため confirmed。
            "JUG": CategoryEventProfile(
                event_dds=frozenset({22, 11, 5, 15, 25}),
                status="confirmed",
                source="rakuen_theory.md §3.1a",
                measured_period="2025-01〜2026-07",
                note=(
                    "DD{5,15,25}は『ジャグ限定日』。ジャグのみ+5.56pp、他4カテゴリはマイナス。"
                    "回転数が増えない=客に気づかれていない型で、回転数交絡を受けない唯一のシグナル。"
                ),
            ),
            "AT一般": CategoryEventProfile(
                event_dds=frozenset({30, 22, 11, 10}),
                status="confirmed",
                source="rakuen_theory.md §3.1a",
                measured_period="2025-01〜2026-07",
                note="DD30が最強(+2.41で1位)。ジャグの取り分は薄い。",
            ),
            "HANA": CategoryEventProfile(
                event_dds=frozenset({7, 17, 27, 30, 22}),
                status="confirmed",
                source="rakuen_theory.md §3.1a",
                measured_period="2025-01〜2026-07",
                note="{11,22,30}系とほぼ無関係な独立カレンダー。41台と小規模で確度は落ちる。",
            ),
            # OKI は月末+3.19pp・強ゾロ目-1.17pp と符号が割れており未確定。
            # 単一手法・全期間平均のため書き込まない。
        },
    ),
    "蒲田1": HallEventCalendar(
        label="マルハンメガシティ2000-蒲田1",
        by_category={
            # 2026年に7系{7,17,27}が単調減衰し1系{1,11,21,31}が逆転した。
            # 事前登録済みで結果待ちのため watching。
            "JUG": CategoryEventProfile(
                event_dds=frozenset({1, 11, 21, 31}),
                status="watching",
                source="prereg:k1_jug_dd1kei_rbz_top3 (freeze_hash=5c176bc76465f438)",
                measured_period="2026Q1-2026Q3",
                note=(
                    "対照ルール k1_jug_plain_rbz_top3 と同時登録。"
                    "フォワード12エントリー日到達時に判定（〜2026-12-01）。"
                    "7系は依然プラス圏だが減衰中(+2.07→+1.20)。"
                ),
            ),
            # AT一般は2026Q3で1系+1.46・7系+2.94と振れ幅が大きく判定不能。
        },
    ),
    "蒲田7": HallEventCalendar(
        label="マルハンメガシティ2000-蒲田7",
        # カテゴリ別カレンダーは成立しない。JUG・AT一般とも7系が主軸なので shared に置く。
        shared=CategoryEventProfile(
            event_dds=frozenset({7, 17, 27}),
            status="unconfirmed",
            source="kamata7_theory.md 2.8b節（2026-08-01訂正）",
            measured_period="2025Q3-2026Q3",
            note=(
                "AT一般で全5四半期プラス(+1.08〜+2.84)。1系{1,11,21,31}はほぼゼロ〜マイナス。"
                "既存instinct kamata7-event-day-complete-definition は告知体系として"
                "1のつく日も含めるが、実測の効果量では7系が明確に強い。"
                "告知と効果は別。事前登録は未実施のため unconfirmed。"
            ),
        ),
    ),
    # みとや: X_DDS{1,4,7,14,17,24,27,30} は実データから逆引き確定済みだが、
    #   四半期別の再確認と2手法での照合が未実施のため保留。
    #   OKIの月末+6.04pp/強ゾロ目+5.57ppは今回初検出で追試が必要。
    # ARROW / ヒロキ / ザシティ / 金時 / レイトギャップ: docstring の「未確定」参照。
}


# ---------------------------------------------------------------------------
# 判定API
# ---------------------------------------------------------------------------


def _to_timestamp(date: str | pd.Timestamp) -> pd.Timestamp:
    """ "YYYYMMDD" 文字列と Timestamp のどちらでも受ける。"""
    if isinstance(date, pd.Timestamp):
        return date
    return pd.Timestamp(str(date))


def get_profile(hall: str, category: str, *, min_status: Status = "confirmed") -> CategoryEventProfile | None:
    """ホール×カテゴリのプロファイルを引く。

    カテゴリ別定義が無ければ `shared` にフォールバックする。
    `min_status` 未満のものは None を返す（既定では confirmed 以外を弾く）。

    Returns:
        該当が無い、または status が min_status 未満なら None。
        None が返るのは「イベント日が無い」ではなく「**信頼できる定義が無い**」意味。
        呼び出し側はイベント日軸を使わない判断をすること。
    """
    cal = EVENT_CALENDAR.get(hall)
    if cal is None:
        return None
    profile = cal.by_category.get(category) or cal.shared
    if profile is None:
        return None
    if _STATUS_RANK[profile.status] < _STATUS_RANK[min_status]:
        return None
    return profile


def is_event_day(
    date: str | pd.Timestamp,
    hall: str,
    category: str,
    *,
    min_status: Status = "confirmed",
) -> bool:
    """その日がそのホール・カテゴリのイベント日か。

    信頼できる定義が無い場合は False を返す。「イベント日ではない」と
    「定義が無い」を区別したいときは `get_profile` を直接使うこと。
    """
    profile = get_profile(hall, category, min_status=min_status)
    if profile is None:
        return False

    ts = _to_timestamp(date)
    if ts.day in profile.event_dds:
        return True
    if profile.use_strong_zorome and ts.month == ts.day:
        return True
    if profile.use_month_end:
        # 暦を見る。30/31のハードコードは 2/4/6/9/11月で外れる。
        if ts.day == calendar.monthrange(ts.year, ts.month)[1]:
            return True
    return False


def annotate_event_days(
    frame: pd.DataFrame,
    hall: str,
    *,
    min_status: Status = "confirmed",
    date_col: str = "date",
    category_col: str = "category",
    out_col: str = "is_event_day",
) -> pd.DataFrame:
    """台×日フレームにイベント日フラグを付けて返す（元のフレームは変更しない）。

    `eda/briefing_common.py` の `load_hall_frame` が返すフレームをそのまま渡せる。
    同ファイルの `is_event_dd` 列は月末・強ゾロ目を落とす劣化版なので、
    そちらではなく本関数を使うこと。

    定義が無いカテゴリの行は False になる。どのカテゴリが定義なしだったかは
    `coverage_report` で確認できる。
    """
    out = frame.copy()
    ts = pd.to_datetime(out[date_col].astype(str), format="%Y%m%d")
    out[out_col] = [is_event_day(t, hall, c, min_status=min_status) for t, c in zip(ts, out[category_col], strict=True)]
    return out


def coverage_report(halls: Iterable[str] | None = None) -> pd.DataFrame:
    """どのホール×カテゴリにどの status の定義があるかの一覧。

    「定義が無いのに気づかず False で集計していた」を防ぐために使う。
    """
    rows = []
    targets = list(halls) if halls is not None else list(EVENT_CALENDAR)
    for hall in targets:
        cal = EVENT_CALENDAR.get(hall)
        if cal is None:
            rows.append({"hall": hall, "category": "-", "status": "未登録", "source": ""})
            continue
        for cat in sorted(VALID_CATEGORIES):
            p = cal.by_category.get(cat) or cal.shared
            rows.append(
                {
                    "hall": hall,
                    "category": cat,
                    "status": p.status if p else "未登録",
                    "event_dds": sorted(p.event_dds) if p else [],
                    "measured_period": p.measured_period if p else "",
                    "source": p.source if p else "",
                }
            )
    return pd.DataFrame(rows)
