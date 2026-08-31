"""ホール予告の事前登録と答え合わせ。

なぜ台選択ルール（prereg/forward）と別に要るか:
    forward.py が検証しているのは「我々が過去データから作ったスコアが当たるか」である。
    一方ホール自身は、対象日より前に「全⑤⑥×2機種あり」「Lカバネリが1/2⑤⑥」といった
    具体的な予告を出している。これは我々のスコアより遥かに情報量が多い可能性があるのに、
    現状は毎回セッションで読んで捨てており、蓄積がゼロだった。

    予告と統計は競合しない。役割が違う。
        予告が「何が起きるか」（全台系が2機種ある）を教え、
        統計が「どれか」（30機種のうちどの2機種か）を絞る。
    単独で台を当てるより桁違いに易しい問題設定になる。

反証可能性が最大の設計課題:
    「全⑤⑥×2機種あり」は、そのままでは **毎日どこかの2機種が良い** ので反証できない。
    反証可能にするには「全台系とは何か」の閾値が要り、その閾値は結果を見る前に
    凍結されていなければならない。よって threshold は announce JSON の一部として
    登録時に凍結し、採点時は読むだけにする（後から動かせない）。

    閾値は「対象日より前のデータ」から分位点で決める（baserate サブコマンド）。
    当日データは一切使わない。

全台系スコア（2種類、同じ土俵で並走させる）:
    "gratio_mean_diff"（既定）:
        G比（機種平均回転数 / プール平均回転数）× 平均差枚。
        `run_backtest.score_history("hist_model_gratio_mean_diff")` と同じ定義で、
        2026-08-01 の正解ラベル6件検証で最上位だった指標。
        ⚠️ hit104率（機械割104%超え率）を主指標にしてはならない。Var(機械割) ∝ 1/games
        なので回転数の多寡を設定差として計上してしまう
        （instinct: answer-check-metric-hit104-over-mean-diff）。
        ⚠️ **既知のバイアス**: 台数を見ないため少台数機種に有利。2026-08-06、
        みとや大森町 2026-08-04 でカバネリ17台（score +1,339, rank 5/36）が
        やじきた道中記参る！4台（score +2,323, rank 1/36）に負けた。
        カバネリの実勝率は10/17で上位2台が総和の78%を占め、真の全台系では
        なかった可能性が高いが、本来検出したい大規模投入ほど不利という
        構造は残る（README「新台は除外せず層別する」節・「閾値の実データ校正」節）。

    "winrate_lb95_gratio"（2026-08-06 追加、上記バイアスの対抗指標）:
        勝率のWilson下限95% × G比 × max(平均差枚, 0)。
        「その機種の設置台のうち、当日ホール平均を上回った台の割合」を
        Wilson score interval の下限で保守的に見積もる。台数が少ないほど
        下限が強く縮むため、"少数台が偶然跳ねただけ" を構造的に罰し、
        逆に多数台で安定して上回った機種を相対的に有利にする。
        ⚠️ **未検証**。gratio_mean_diff のように正解ラベルで検証していない。
        既存指標を置き換えるのではなく、`zentaikei.metric` で指標を選び、
        両方を同じ予告に対して走らせて比較すること
        （`score()` は選ばれた1指標だけを判定に使うが、baserate は
        `--metric` で個別に閾値を出せる）。

予告と結果報告を混ぜないこと:
    同一アカウントが予告も答え合わせも投稿する（`scraper/twitter_monitor/config.py`
    の ACCOUNTS で kawasakislot / 999999Q9Q は role="予告+答え合わせ"）。結果報告を
    予告として登録すると的中率が定義上 100% になる。よって `source.kind` は "予告"
    のみ受け付け、`posted_at < target_date 00:00` を機械的に検証する。

db_max ガードは「登録者が結果を知っていること」を防げない:
    register は `target_date <= db_max` を拒否する。これは対象日の実績を DB から
    見て登録することを防ぐガードだが、DB 取込は実時間より 1〜3 日遅れるのが常態で、
    その間は **すでに終わった日** でも target_date > db_max となり通過する。
    2026-08-11 時点で db_max=20260808 だったため、X の結果報告で内容を知っている
    8/9・8/10 の予告を「事前登録」として登録できる状態にあった。

    ブロックはしない（取込遅延中の正当な追いつき登録まで止まるため）。代わりに
    台帳へ `registered_at`（実時間）と `late_registration` を記録し、印が付いたものを
    的中率・base_rate の集計から除外する。`is_late_registration()` を参照。

    ⚠️ 同じ理屈を forward.plan の db_max ガードに適用してはならない。あちらは
    picks がデータに対して決定論的で人間の知識が混入せず、db_max ガードは
    「対象日当日のロスターを代理に使ってしまう」ことを防ぐ別目的のものである。

カテゴリ集計では機種への再配分を検出できない:
    「ジャグが25%以上」のような主張をカテゴリ平均の水準で測ると、ホールが
    カテゴリ内で特定機種に集中投入した場合に見逃す
    （instinct: category-aggregate-hides-reallocation）。よって category_share は
    「カテゴリの平均が高いか」ではなく **「閾値を超えた機種のうち何割がそのカテゴリか」**
    として定義する。

使い方:
    venv\\Scripts\\python.exe -m backtest.announce baserate 楽園蒲田店 --before 20260807
    venv\\Scripts\\python.exe -m backtest.announce register backtest/announce/xxx.json
    venv\\Scripts\\python.exe -m backtest.announce score backtest/announce/xxx.json
    venv\\Scripts\\python.exe -m backtest.announce audit-censoring 楽園蒲田店

announce JSON の形:
    {
      "announce_id": "rakuen__20260807__kawasakislot",
      "hall": "楽園蒲田店",
      "target_date": "20260807",
      "source": {
        "account": "kawasakislot",
        "url": "https://x.com/kawasakislot/status/...",
        "posted_at": "2026-08-06T21:30:00+09:00",
        "kind": "予告"
      },
      "raw_text": "投稿本文をそのまま",
      "zentaikei": {
        "metric": "gratio_mean_diff",
        "threshold": 1200.0,
        "min_machines": 3
      },
      "claims": [
        {"type": "zentaikei_count", "n_models": 2},
        {"type": "model_named", "machine_name": "甲鉄城のカバネリ 海門(うなと)決戦", "note": "1/2⑤⑥"},
        {"type": "category_share", "category": "jug_flag", "min_share": 0.25},
        {"type": "position_rule", "field": "rank_from_aisle", "values": [3, 8]}
      ],
      "result": null
    }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.censoring import bounds_for, censoring_summary, max_understatement_hi, warning_text
from backtest.run_backtest import load_frame

ANNOUNCE_DIR = Path(__file__).resolve().parent / "announce"
LEDGER = ANNOUNCE_DIR / "LEDGER.jsonl"

# source.kind に許すのはこれだけ。結果報告・店長投稿を予告として登録させない。
ALLOWED_KINDS = {"予告"}

CLAIM_TYPES = {
    "zentaikei_count",  # 全台系が n_models 機種ある
    "model_named",  # 特定機種を名指し（全台系＝機種平均が閾値超え）
    "model_named_ratio",  # 特定機種を名指し（1/N⑤⑥＝一部の台だけ高設定）
    "category_share",  # 閾値超え機種のうち当該カテゴリが min_share 以上
    "position_rule",  # 特定位置（角番・末尾等）に仕掛けがある
}

CATEGORY_FIELDS = {"jug_flag", "hana_flag", "oki_flag", "bt_flag"}
POSITION_FIELDS = {"rank_from_aisle", "rank_from_min", "rank_from_max", "last_digit", "section"}

# 機種タイプのセグメント。末尾・角番の効果はセグメントごとに符号が違うため、
# プールした位置別集計は結論を反転させる（2026-08-07 楽園蒲田で実証）。
#
#   予告「末尾7が1/2⑤⑥」を全機種プールで採点すると残差 -35枚（10末尾中6位）で
#   「外れ・デコイ」に見えた。セグメントに割ると JUG(117台) 末尾7 が残差 +1,191 で
#   出率1位、HANA(16台) が +2,182 で2位、一方 AT/その他(350台) が -514 で9位。
#   最大セグメントの AT が JUG/HANA を打ち消していた。同じ予告は「ジャグ20%⑤⑥」
#   「8/7➔ハナハナ・ハナビ」も述べており、セグメント内では予告と実績が整合していた。
#
# したがって position_rule は segment を指定できるようにし、指定が無い場合でも
# `by_segment` を常に併記する。プールの数字だけを見て棄却してはならない。
# instinct: feedback-lastdigit-kakuban-segment-split
SEGMENT_ORDER = [("JUG", "jug_flag"), ("HANA", "hana_flag"), ("OKI", "oki_flag"), ("BT", "bt_flag")]
SEGMENTS = {name for name, _ in SEGMENT_ORDER} | {"AT"}


def assign_segment(day: pd.DataFrame) -> pd.Series:
    """各行を機種タイプのセグメントに割り当てる。どのフラグも立たない行は AT。

    フラグは排他である保証がないので SEGMENT_ORDER の優先順で最初に当たったものを
    採る（JUG > HANA > OKI > BT > AT）。reversed で回して上書きすることで、
    先頭ほど優先度が高くなる。
    """
    seg = pd.Series("AT", index=day.index, dtype=object)
    for name, field in reversed(SEGMENT_ORDER):
        if field in day.columns:
            seg = seg.mask(day[field] == 1, name)
    return seg


# 全台系スコアの算出方式。gratio_mean_diff が検証済みの既定。winrate_lb95_gratio は
# 少台数機種が有利になるバイアスへの対抗指標として2026-08-06に追加した未検証の候補
# （モジュール docstring を参照）。
ALLOWED_METRICS = {"gratio_mean_diff", "winrate_lb95_gratio"}

# 新台の扱い（2026-08-06 計測）。
#
# 新台は「設定不問で高回転」するため G比が構造的に膨らむ。6ホール・2026-05-08 以降・
# 30,039 機種日で計測した結果:
#
#   導入0-6日   : G比中央値 1.42 / 平均差枚 -315 / 平均score -668 / 閾値+1800超え 10.5%
#   導入60日+   : G比中央値 0.84 / 平均差枚  +40 / 平均score +100 / 閾値+1800超え  4.8%
#
# 重要なのは向きである。新台は **平均的には負けている**（平均差枚 -315）。
# 「新台は販促で高設定」という通説はこの期間・このホール群では成立しない。
# それでも閾値超え率が 2.2 倍なのは、G比が 1.7 倍なので平均差枚が少しプラスへ
# 振れるだけでスコアが跳ねるからで、期待値ではなく分散が大きいということ。
# 実際、閾値超え機種の 15.5% が導入30日未満（母集団比率は 9.1%）で 1.7 倍の過剰代表。
#
# ⚠️ だからといって新台を候補から除外してはならない。ホールが新台に全台系を
# 入れることは実在する（kawasakislot「新設島に導入された鉄拳6は導入当日・翌日と
# 2日連続で全56」）。除外すると本物を取り逃がす。
# 正しい対処は **層別** である。予告が新台を名指ししたら NEW のベースレートと、
# 既存台なら ESTABLISHED のベースレートと比べる。単一のベースレートで的中率を
# 測ると、新台を名指しするだけで「予告は有効」に見えてしまう。
# ⚠️ この実測値は metric="gratio_mean_diff"・閾値+1,800 でのみ有効。
# winrate_lb95_gratio は score のスケールが異なり、新台バイアスの向きも
# 未計測（Wilson下限は少数台を保守的に評価するので、gratio_mean_diff より
# 新台優遇が弱い可能性が高いが未検証）。
NEW_MACHINE_DAYS = 30
BASE_RATE_OVER_THRESHOLD = {"new": 0.105, "established": 0.048}


def announce_digest(obj: dict) -> str:
    """result を除いた予告本体のダイジェスト。台帳と突き合わせて改ざんを検出する。"""
    body = {k: v for k, v in obj.items() if k not in ("result", "announce_digest")}
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _target_midnight(target: str, posted: datetime) -> datetime:
    """target_date の 0 時を、posted と比較可能な tz で返す。"""
    naive = datetime.fromisoformat(f"{target[:4]}-{target[4:6]}-{target[6:8]}T00:00:00")
    return naive.replace(tzinfo=posted.tzinfo) if posted.tzinfo else naive


def validate(obj: dict) -> None:
    """予告の形式を検証する。ここを通らないものは台帳に載せない。"""
    for key in ("announce_id", "hall", "target_date", "source", "zentaikei", "claims"):
        if key not in obj:
            raise ValueError(f"必須キーが無い: {key}")

    src = obj["source"]
    for key in ("account", "url", "posted_at", "kind"):
        if key not in src:
            raise ValueError(f"source.{key} が無い")
    if src["kind"] not in ALLOWED_KINDS:
        raise ValueError(
            f"source.kind={src['kind']!r} は登録できない（許可: {sorted(ALLOWED_KINDS)}）。"
            "結果報告・店長投稿を予告として登録すると的中率が定義上100%になる。"
        )

    target = obj["target_date"]
    if len(target) != 8 or not target.isdigit():
        raise ValueError("target_date は YYYYMMDD 形式")

    # 予告は対象日より前に投稿されていなければならない。事後の投稿は予告ではない。
    posted = datetime.fromisoformat(src["posted_at"])
    if posted >= _target_midnight(target, posted):
        raise ValueError(
            f"posted_at={src['posted_at']} は target_date={target} の当日0時以降。"
            "これは予告ではなく実況・結果報告である。"
        )

    z = obj["zentaikei"]
    if z.get("metric") not in ALLOWED_METRICS:
        raise ValueError(f"zentaikei.metric は {sorted(ALLOWED_METRICS)} のいずれか")
    if not isinstance(z.get("threshold"), (int, float)) or isinstance(z.get("threshold"), bool):
        raise ValueError("zentaikei.threshold は数値。baserate サブコマンドで決めて凍結すること")
    if int(z.get("min_machines", 0)) < 1:
        raise ValueError("zentaikei.min_machines は 1 以上")

    if not obj["claims"]:
        raise ValueError("claims が空。反証可能な主張が1件も無い予告は登録しない")
    for c in obj["claims"]:
        t = c.get("type")
        if t not in CLAIM_TYPES:
            raise ValueError(f"未知の claim type: {t!r}（許可: {sorted(CLAIM_TYPES)}）")
        if t == "zentaikei_count" and int(c.get("n_models", 0)) < 1:
            raise ValueError("zentaikei_count.n_models は 1 以上")
        if t == "model_named" and not c.get("machine_name"):
            raise ValueError("model_named.machine_name が無い")
        if t == "model_named_ratio":
            if not c.get("machine_name"):
                raise ValueError("model_named_ratio.machine_name が無い")
            if int(c.get("ratio", 0)) < 2:
                raise ValueError(
                    "model_named_ratio.ratio は 2 以上の整数（『1/2⑤⑥』なら 2、『1/3』なら 3）。"
                    "ratio=1 は全台系の主張なので model_named を使うこと。"
                )
        if t == "category_share":
            if c.get("category") not in CATEGORY_FIELDS:
                raise ValueError(f"category_share.category は {sorted(CATEGORY_FIELDS)} のいずれか")
            if not 0 < float(c.get("min_share", 0)) <= 1:
                raise ValueError("category_share.min_share は 0 < x <= 1")
        if t == "position_rule":
            if c.get("field") not in POSITION_FIELDS:
                raise ValueError(f"position_rule.field は {sorted(POSITION_FIELDS)} のいずれか")
            if not c.get("values"):
                raise ValueError("position_rule.values が空")
            if c.get("segment") is not None and c["segment"] not in SEGMENTS:
                raise ValueError(
                    f"position_rule.segment は {sorted(SEGMENTS)} のいずれか、または未指定。"
                    "未指定はホール全機種プールでの判定になるので、予告が機種タイプを"
                    "限定している場合（『ジャグ20%⑤⑥』等）は必ず指定すること。"
                )


def _winrate_lb95(win_sum: pd.Series, n: pd.Series) -> pd.Series:
    """Wilson score interval の下限95%。台数が少ないほど強く縮む。

    2値（勝ち/負け）の母比率信頼区間として、正規近似（p±1.96*sqrt(p(1-p)/n)）より
    小標本で安定する。n=1台で全勝でも下限は約0.21までしか上がらない一方、
    n=17で10/17勝なら下限は約0.36と、単純な勝率0.59より保守的だが実台数の
    情報が反映される。
    """
    p = win_sum / n
    z = 1.96
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (center - half).clip(lower=0, upper=1)


def model_scores(
    day: pd.DataFrame,
    min_machines: int,
    first_seen: pd.Series | None = None,
    metric: str = "gratio_mean_diff",
) -> pd.DataFrame:
    """1日分のフレームから機種ごとの全台系スコアを返す。

    metric="gratio_mean_diff"（既定・検証済み）:
        score = G比（機種平均回転数 / プール平均回転数）× 平均差枚。
        ⚠️ 台ごとの平均差枚を単純平均してはいけない。低回転台が外れ値になって
        系統的に下振れする（feedback-scoring-must-separate-setting-from-pnl）。
        groupby(machine_name).mean() は行（台×日）を等重みで扱う総和ベース平均であり、
        台ごとの事前平均を平均する二重平均ではない。
        ⚠️ 台数を見ないため少台数機種に有利（モジュール docstring 参照）。

    metric="winrate_lb95_gratio"（未検証・対抗指標）:
        score = 勝率のWilson下限95%（対プール平均）× G比 × max(平均差枚, 0)。
        「少数台が偶然跳ねただけ」を構造的に罰する設計だが、正解ラベルでの
        検証はまだ無い。gratio_mean_diff と同じ予告に対して両方走らせて
        比較すること。

    打ち切り（censoring）:
        `n_censored_hi` / `n_censored_lo` 列を必ず返す。`n_censored_hi > 0` の機種は
        差枚が元サイト側の表示上限に張り付いた台を含むため、mean_diff も score も
        **真値の下界** である。閾値未満を「外れ」と断定してはいけない
        （楽園蒲田店のみ該当。詳細は backtest/censoring.py）。

    Args:
        first_seen: machine_name -> DB初出日(datetime) の対応。渡すと `age_days`
            列（導入からの経過日数）が付く。新台はG比が構造的に膨らむため
            スコアの分散が大きく、閾値超えのベースレートが既存台と違う
            （NEW_MACHINE_DAYS と下のコメントを参照）。
    """
    if metric not in ALLOWED_METRICS:
        raise ValueError(f"未知の metric: {metric!r}（許可: {sorted(ALLOWED_METRICS)}）")

    cols = ["n_machines", "gratio", "mean_diff", "sum_diff", "sum_games", "score"]
    pool_mean_games = day["games_normalized"].mean()
    if not pool_mean_games or pd.isna(pool_mean_games):
        return pd.DataFrame(columns=cols)

    g = day.groupby("machine_name")
    out = pd.DataFrame(
        {
            "n_machines": g["machine_number"].nunique(),
            "gratio": g["games_normalized"].mean() / pool_mean_games,
            "mean_diff": g["diff_coins_normalized"].mean(),
            "sum_diff": g["diff_coins_normalized"].sum(),
            "sum_games": g["games_normalized"].sum(),
        }
    )

    # 打ち切り台数。`load_frame` 経由なら必ず列がある。手組みフレームで
    # 呼ばれた場合（テスト・アドホック分析）は 0 として扱う。
    # n_censored_hi > 0 の機種は mean_diff も score も **真値の下界** であり、
    # 閾値未満でも「外れ」と断定してはいけない（censoring.py 参照）。
    for col in ("censored_hi", "censored_lo"):
        name = f"n_{col}"
        out[name] = g[col].sum().reindex(out.index, fill_value=0).astype(int) if col in day.columns else 0

    if metric == "gratio_mean_diff":
        out["score"] = out["gratio"] * out["mean_diff"]
    else:
        pool_mean_diff = day["diff_coins_normalized"].mean()
        win = (day["diff_coins_normalized"] > pool_mean_diff).astype(float)
        win_sum = win.groupby(day["machine_name"]).sum().reindex(out.index, fill_value=0)
        out["win_rate_lb95"] = _winrate_lb95(win_sum, out["n_machines"].astype(float))
        out["score"] = out["win_rate_lb95"] * out["gratio"] * out["mean_diff"].clip(lower=0)

    if first_seen is not None and not day.empty:
        d0 = pd.Timestamp(str(day["date"].iloc[0]))
        out["age_days"] = [int((d0 - first_seen[name]).days) if name in first_seen.index else -1 for name in out.index]
    return out[out["n_machines"] >= min_machines].sort_values("score", ascending=False)


def baserate(
    hall: str,
    before: str,
    days: int,
    min_machines: int,
    pct: float,
    metric: str = "gratio_mean_diff",
    threshold: float | None = None,
) -> dict:
    """対象日より前のデータから、全台系の閾値とベースレートを出す。

    当日データは一切使わない。閾値を登録時に凍結するための材料であって、
    採点時にこれを呼び直して閾値を作り変えてはならない。

    `models_over_threshold_per_day` が重要である。ここが例えば平均 2.0 なら
    「全台系が2機種ある」という予告は **毎日成り立つ**（＝情報量ゼロ）ことになり、
    その claim は的中しても意味を持たない。予告の価値は機種の名指しにある。

    ⚠️ gratio_mean_diff で分位点閾値を使うと、閾値超え数が恒等的に
    「候補数×(1-pct)」に一致し観測にならない（README「閾値は分位点ではなく
    絶対値で固定する」参照）。そのため運用では gratio_mean_diff の閾値は
    ここではなく絶対値 +1,800 を使う。winrate_lb95_gratio は score の
    スケールが全く異なるため、この関数の分位点をそのまま初期値の参考にしてよい。

    threshold: 指定すると、分位点閾値とは別に絶対値 `threshold` 基準の
        `fixed_threshold` ブロック（p_at_least_N 込み）を追加で返す。
        運用で使うのは基本的にこちら（gratio_mean_diff は +1,800 固定）。
        未指定なら従来どおり分位点閾値のみを返す（後方互換）。
    """
    df = load_frame(hall)
    d0 = pd.Timestamp(before)
    lo = d0 - pd.Timedelta(days=days)
    hist = df[(df["dt"] >= lo) & (df["dt"] < d0)]
    if hist.empty:
        raise ValueError(f"窓 [{lo.date()}, {d0.date()}) に履歴が無い")

    rows = []
    for date, day in hist.groupby("date"):
        ms = model_scores(day, min_machines, metric=metric)
        for name, r in ms.iterrows():
            rows.append({"date": date, "machine_name": name, "score": r["score"]})
    scores = pd.DataFrame(rows)
    if scores.empty:
        raise ValueError(f"min_machines={min_machines} を満たす機種が窓内に無い")

    pct_threshold = float(scores["score"].quantile(pct))
    all_days = scores["date"].unique()
    counts = scores[scores["score"] >= pct_threshold].groupby("date").size().reindex(all_days, fill_value=0)

    result = {
        "hall": hall,
        "metric": metric,
        "window": [str(lo.date()), str(d0.date())],
        "n_days": int(len(all_days)),
        "n_model_days": int(len(scores)),
        "min_machines": min_machines,
        "percentile": pct,
        "threshold": round(pct_threshold, 1),
        "models_over_threshold_per_day": {
            "mean": round(float(counts.mean()), 2),
            "median": float(counts.median()),
            "max": int(counts.max()),
        },
        "candidate_models_per_day": round(float(scores.groupby("date").size().mean()), 1),
    }

    if threshold is not None:
        fixed_counts = scores[scores["score"] > threshold].groupby("date").size().reindex(all_days, fill_value=0)
        result["fixed_threshold"] = {
            "threshold": threshold,
            "models_over_threshold_per_day": {
                "mean": round(float(fixed_counts.mean()), 2),
                "median": float(fixed_counts.median()),
                "max": int(fixed_counts.max()),
            },
            **{f"p_at_least_{n}": round(float((fixed_counts >= n).mean()), 3) for n in (1, 2, 3, 4, 10)},
        }

    return result


def named_context(
    hall: str,
    machines: list[str],
    as_of: str,
    days: int = 30,
    min_machines: int = 3,
    threshold: float = 1800.0,
    metric: str = "gratio_mean_diff",
) -> dict:
    """予告本文で名指しされた機種群の、直近N日窓でのランキング・閾値超え率を出す。

    予告登録のたびに named_machine_context をスクラッチスクリプトで計算していた
    作業（match_machine_names/baserate を切り出した時と同じ動機）をここに一本化する。
    machines は match-name で確定済みの正式表記（machine_master 側）を渡すこと。
    あいまい照合はしない。

    as_of を含む days 日分の窓（休業日等で実日数が days に満たない場合はある分だけ
    使う）。rank は as_of 1日分のみで作った min_machines 以上のプールでの順位
    （score 降順、1-indexed）で、名指し機種が min_machines 未満の少数台設置でも
    窓内の出現自体は min_machines=1 で拾う（プール順位の算出とは別）。
    """
    df = load_frame(hall)
    dates = sorted(df["date"].astype(str).unique())
    if as_of not in dates:
        raise ValueError(f"as_of={as_of} はDBに存在しない日付")
    as_of_idx = dates.index(as_of)
    window_dates = dates[max(0, as_of_idx - days + 1) : as_of_idx + 1]

    as_of_day = df[df["date"] == as_of]
    pool = model_scores(as_of_day, min_machines, metric=metric)
    n_candidates = len(pool)

    per_day_scores = []
    for d in window_dates:
        day = df[df["date"] == d]
        if day.empty:
            continue
        per_day_scores.append(model_scores(day, 1, metric=metric))

    models = []
    for name in machines:
        scores_list = []
        n_machines_list = []
        over = 0
        for sc in per_day_scores:
            if name in sc.index:
                row = sc.loc[name]
                scores_list.append(float(row["score"]))
                n_machines_list.append(int(row["n_machines"]))
                if row["score"] > threshold:
                    over += 1
        n_days_present = len(scores_list)
        rank = int(pool.index.get_loc(name)) + 1 if name in pool.index else None
        models.append(
            {
                "name": name,
                "n_machines": n_machines_list[-1] if n_machines_list else None,
                "rank": rank,
                "of": n_candidates,
                "n_days_present": n_days_present,
                "over_threshold": over,
                "rate": round(over / n_days_present, 3) if n_days_present else None,
                "mean_score": round(sum(scores_list) / len(scores_list), 1) if scores_list else None,
            }
        )

    hall_over_rate = round(float((pool["score"] > threshold).sum()) / n_candidates, 3) if n_candidates else None

    return {
        "as_of": as_of,
        "window_days": days,
        "n_candidates_ge3machines": n_candidates,
        "hall_over_threshold_rate_approx": hall_over_rate,
        "threshold": threshold,
        "models": models,
    }


def db_max_date(hall: str) -> str:
    """ホールのDB最終収録日を返す（登録前の下ごしらえ用）。

    register 内部でも同じ判定をするが、baserate の --before に渡す値を
    決めるには登録前に単独で知る必要がある。毎回 scratchpad に使い捨て
    スクリプトを書いて確認していた作業（mirror_evidence_2026-08-25.md
    セクション4-A）をこのサブコマンドに一本化する。
    """
    return str(load_frame(hall)["date"].max())


def match_machine_names(hall: str, text: str, cutoff: float = 0.6) -> list[dict]:
    """予告本文の自由文から、そのホールの実在機種名候補をあいまい照合する。

    ツイート本文は機種名を略称・別表記で書くことが多く、model_named claim の
    machine_name には machine_master 側の正式表記が必要になる。この照合を
    毎回 scratchpad で書き直していた（mirror_evidence_2026-08-25.md
    セクション4-A、独立した3セッションで同一パターンを確認）。

    完全な部分文字列一致を最優先し、無ければ機種名とテキストの最長共通
    部分列の長さで近似スコアを付ける。あくまで候補提示であり、最終的な
    machine_name の採否は人間が判断すること（自動確定はしない）。
    """
    import difflib

    names = sorted(load_frame(hall)["machine_name"].dropna().unique().tolist())
    results = []
    for name in names:
        if name in text:
            results.append({"machine_name": name, "match": "substring", "score": 1.0})
            continue
        match = difflib.SequenceMatcher(None, name, text).find_longest_match(0, len(name), 0, len(text))
        if match.size >= max(3, len(name) * cutoff):
            score = round(match.size / len(name), 3)
            results.append({"machine_name": name, "match": "partial", "score": score})
    results.sort(key=lambda r: -r["score"])
    return results


def audit_censoring(hall: str) -> list[dict]:
    """既に採点済みの予告を、現在の打ち切り知識で再点検する（読み取り専用）。

    採点結果ファイルは一切書き換えない（`score()` の「作り直し禁止」を尊重）。
    この関数がやるのは、hit=False の `model_named` claim のうち「打ち切りが
    無ければ閾値に届いていた可能性があるもの」を洗い出すことだけである。
    的中率を集計するときにこの一覧を見て、対象を『判定不能』として扱うかどうかは
    呼び出し側（人間）が決める。

    古い採点結果 JSON は censoring 情報を持たない（この機能の実装前に採点された
    ため）。よって当時の score を再現するのではなく、現在の DB を `model_scores`
    で読み直して「その機種がその日に打ち切られていたか」だけを見る。
    採点結果に記録された score・hit 自体はそのまま参照する。
    """
    df = load_frame(hall)
    out: list[dict] = []
    # ファイル名の接頭辞（announce_id）はホール名のローマ字略称で、"hall" フィールドの
    # 日本語表記とは一致しない（例: rakuen__... の hall は "楽園蒲田店"）。
    # よってファイル名ではなく中身の "hall" で絞る。
    for path in sorted(ANNOUNCE_DIR.glob("*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("hall") != hall or obj.get("result") is None:
            continue
        target = obj["target_date"]
        day = df[df["date"] == target]
        if day.empty:
            continue
        min_machines = int(obj["zentaikei"]["min_machines"])
        thr = float(obj["zentaikei"]["threshold"])
        metric = obj["zentaikei"].get("metric", "gratio_mean_diff")
        ms = model_scores(day, min_machines, metric=metric)
        for c in obj["result"]["claims"]:
            if c["type"] != "model_named" or c.get("hit") is not False:
                continue
            name = c["claim"]["machine_name"]
            if name not in ms.index:
                continue
            note = _censoring_note(ms.loc[name], hall)
            cap = note.get("max_score_understatement")
            if cap is None:
                continue
            deficit = round(thr - float(c["score"]), 1)
            out.append(
                {
                    "announce_id": obj["announce_id"],
                    "target_date": target,
                    "machine_name": name,
                    "recorded_score": c["score"],
                    "threshold": thr,
                    "deficit": deficit,
                    "max_score_understatement": cap,
                    "reclassify_as_indeterminate": cap >= deficit,
                }
            )
    return out


def _age_bucket(age_days: int) -> str:
    """新台/既存台の層。ベースレートが違うので的中率を混ぜて集計しない。"""
    if age_days < 0:
        return "unknown"
    return "new" if age_days < NEW_MACHINE_DAYS else "established"


def _censoring_note(row: pd.Series, hall: str) -> dict:
    """機種1行分の打ち切り注記。打ち切りが無ければ空 dict（JSON を汚さない）。

    `hit` は **書き換えない**。閾値は登録時に凍結されており、採点式を後から
    動かすのは台帳の設計思想に反する。代わりに「その hit がどちら向きに
    信用できないか」を残す:

        censoring_bias="lower_bound" … 右打ち切りあり。score は真値の下界。
            hit=True はそのまま正しい（下界が閾値を超えているなら真値も超える）。
            hit=False は **判定不能に近い**。集計時に外れとして数える前に、
            打ち切りが無ければ超えていた可能性を検討すること。
        censoring_bias="upper_bound" … 左打ち切りあり。score は真値の上界。
            hit=False はそのまま正しい。hit=True は過大評価の疑いがある。
        censoring_bias="both" … 両方混在。向きが決まらない。

    右打ち切りには規制上限（`REGULATORY_MAX_DIFF`）による見誤りの最大幅がある。
    `max_score_understatement` は「打ち切られた台が全部ちょうど規制上限だったら
    score はどこまで伸びたか」の最悪ケース。閾値との差がこれより小さければ、
    打ち切りが無かった場合に届いていた可能性を捨ててはいけない。
    """
    hi = int(row.get("n_censored_hi", 0) or 0)
    lo = int(row.get("n_censored_lo", 0) or 0)
    if not hi and not lo:
        return {}
    bias = "both" if hi and lo else ("lower_bound" if hi else "upper_bound")
    out = {"n_censored_hi": hi, "n_censored_lo": lo, "censoring_bias": bias}
    if hi:
        cap = max_understatement_hi(hall)
        n_machines = int(row.get("n_machines", 0) or 0)
        gratio = float(row.get("gratio", 0.0) or 0.0)
        if cap is not None and n_machines:
            # 打ち切られた hi 台が全部 REGULATORY_MAX_DIFF だったと仮定した場合の
            # mean_diff の伸び幅。他の台は動かさない最悪ケース。
            max_mean_diff_gain = hi * cap / n_machines
            out["max_score_understatement"] = round(gratio * max_mean_diff_gain, 1)
    return out


def _judge_claims(obj: dict, day: pd.DataFrame, first_seen: pd.Series | None = None) -> list[dict]:
    """各 claim を当日実績で判定する。判定式は登録時に凍結された内容のみを使う。

    hit は True / False / None の3値。None は「判定不能」であり、外れではない
    （撤去・台数不足・比較対象が空など）。集計時に False と混ぜないこと。

    model_named には `age_bucket` と `base_rate` を併記する。新台は閾値超え率が
    既存台の 2.2 倍あるため、両者を混ぜて的中率を出すと予告を過大評価する
    （BASE_RATE_OVER_THRESHOLD のコメントを参照）。
    """
    z = obj["zentaikei"]
    thr = float(z["threshold"])
    min_machines = int(z["min_machines"])
    metric = z.get("metric", "gratio_mean_diff")
    ms = model_scores(day, min_machines, first_seen, metric=metric)
    has_age = "age_days" in ms.columns
    over = ms[ms["score"] >= thr]

    out: list[dict] = []
    for c in obj["claims"]:
        t = c["type"]
        entry: dict = {"type": t, "claim": c}

        if t == "zentaikei_count":
            entry["observed_n_models"] = int(len(over))
            entry["candidate_models"] = int(len(ms))
            entry["models"] = [
                {
                    "machine_name": k,
                    "score": round(float(v["score"]), 1),
                    "n_machines": int(v["n_machines"]),
                    "mean_diff": round(float(v["mean_diff"]), 1),
                    **_censoring_note(v, obj["hall"]),
                    **({"age_days": int(v["age_days"])} if has_age else {}),
                }
                for k, v in over.iterrows()
            ]
            if has_age:
                entry["n_new_machines_over"] = int((over["age_days"] < NEW_MACHINE_DAYS).sum())
            entry["hit"] = bool(len(over) >= int(c["n_models"]))

        elif t == "model_named":
            name = c["machine_name"]
            if name not in ms.index:
                entry["hit"] = None
                entry["note"] = f"当日 {name} が設置{min_machines}台以上の候補に無い（撤去・台数不足・表記ゆれ）"
            else:
                row = ms.loc[name]
                entry["score"] = round(float(row["score"]), 1)
                entry["mean_diff"] = round(float(row["mean_diff"]), 1)
                entry["gratio"] = round(float(row["gratio"]), 3)
                entry["n_machines"] = int(row["n_machines"])
                entry["rank"] = int((ms["score"] > row["score"]).sum()) + 1
                entry["candidate_models"] = int(len(ms))
                entry.update(_censoring_note(row, obj["hall"]))
                if has_age:
                    age = int(row["age_days"])
                    bucket = _age_bucket(age)
                    entry["age_days"] = age
                    entry["age_bucket"] = bucket
                    # 的中率を評価するとき、この claim はこのベースレートと比べる。
                    entry["base_rate"] = BASE_RATE_OVER_THRESHOLD.get(bucket)
                entry["hit"] = bool(row["score"] >= thr)

        elif t == "category_share":
            field = c["category"]
            if over.empty:
                entry["hit"] = None
                entry["note"] = "閾値超えの機種が0件のため比率が定義されない"
            else:
                flags = day.drop_duplicates("machine_name").set_index("machine_name")[field]
                in_cat = sum(1 for k in over.index if bool(flags.get(k, 0)))
                share = in_cat / len(over)
                entry["observed_share"] = round(share, 3)
                entry["in_category"] = in_cat
                entry["n_over"] = int(len(over))
                entry["hit"] = bool(share >= float(c["min_share"]))

        elif t == "position_rule":
            field, values = c["field"], c["values"]
            segment = c.get("segment")
            sub = day.dropna(subset=[field]).copy()
            if sub.empty:
                entry["hit"] = None
                entry["note"] = f"{field} が当日データに無い"
            else:
                # 同日×同機種の平均を引いた残差で見る。機種構成の混入を除くため。
                sub["resid"] = sub["diff_coins_normalized"] - sub.groupby("machine_name")[
                    "diff_coins_normalized"
                ].transform("mean")
                sub["segment"] = assign_segment(sub)

                # segment 未指定でも常に併記する。プールの符号だけを見て棄却すると
                # セグメント限定の本物を取り逃がす（SEGMENT_ORDER のコメント参照）。
                entry["by_segment"] = _position_by_segment(sub, field, values)

                scope = sub if segment is None else sub[sub["segment"] == segment]
                entry["judged_segment"] = segment or "ALL(pooled)"
                if segment is not None and scope.empty:
                    entry["hit"] = None
                    entry["note"] = f"segment={segment} の台が当日データに無い"
                else:
                    r = _position_effect(scope, field, values)
                    if r is None:
                        entry["hit"] = None
                        entry["note"] = "対象/対象外のどちらかが空で比較できない"
                    else:
                        entry.update(r)
                        entry["hit"] = bool(r["effect_resid_diff"] > 0)

        elif t == "model_named_ratio":
            entry.update(_judge_model_named_ratio(c, day, ms, min_machines))

        out.append(entry)
    return out


def _position_effect(sub: pd.DataFrame, field: str, values: list) -> dict | None:
    """対象位置と対象外の残差平均の差。比較が成立しなければ None。"""
    tgt = sub[sub[field].isin(values)]
    oth = sub[~sub[field].isin(values)]
    if tgt.empty or oth.empty:
        return None
    return {
        "n_target": int(len(tgt)),
        "n_other": int(len(oth)),
        "effect_resid_diff": round(float(tgt["resid"].mean() - oth["resid"].mean()), 1),
        "target_payout": _payout(tgt),
        "other_payout": _payout(oth),
    }


def _payout(g: pd.DataFrame) -> float | None:
    """総和ベースの出率。台ごとの出率を平均してはいけない（低回転台が外れ値になる）。"""
    games = float(g["games_normalized"].sum())
    if games <= 0:
        return None
    return round(1 + float(g["diff_coins_normalized"].sum()) / (games * 3), 4)


def _position_by_segment(sub: pd.DataFrame, field: str, values: list) -> list[dict]:
    """セグメント別の位置効果。台数が少ないセグメントも隠さず出す。

    ⚠️ HANA / OKI は末尾あたり1〜2台しかないことが普通で、単日では推定できない。
    `n_target` を見て小さければ判断に使わないこと。数字が出ることと
    推定できることは別である。
    """
    out = []
    for seg_name, g in sub.groupby("segment"):
        r = _position_effect(g, field, values)
        row = {"segment": str(seg_name), "n_machines": int(g["machine_number"].nunique())}
        row.update(r if r is not None else {"note": "対象/対象外のどちらかが空"})
        out.append(row)
    return sorted(out, key=lambda x: -(x.get("effect_resid_diff") or float("-inf")))


def _judge_model_named_ratio(c: dict, day: pd.DataFrame, ms: pd.DataFrame, min_machines: int) -> dict:
    """「1/N⑤⑥」型の主張を判定する。

    なぜ model_named（機種平均が閾値超えか）では測れないか:
        「1/3⑤⑥」は残り 2/3 が低設定という主張でもある。機種平均は構造的に薄まり、
        全台系用の閾値には原理的に届かない。2026-08-07 楽園蒲田のエウレカ（25台）は
        +1,000枚超が9台（9/25≒1/3）で台数分布としては主張どおりだったのに、
        機種平均は +463枚で hit=False になった。判定式が主張に対応していなかった。

    どう測るか:
        主張が正しければ、その機種の **上位 1/N 台** はホール全体の同じ上位分位より
        強いはずである。よって「機種の上位k台（k=ceil(n/N)）の平均差枚」を
        「ホール全体の上位 1/N 分位の平均差枚（当該機種を除く）」と比べる。
        機種平均ではなく上位側だけを見るので、低設定台による希釈を受けない。

    ⚠️ 台単位で「この台は⑤⑥だった」と結果指標から断定はできない
        （instinct: feedback-scoring-must-separate-setting-from-pnl）。
        ここで判定しているのは「上位1/N台が同分位のホール水準を超えたか」であって、
        設定そのものではない。閾値超え台数 `n_over_hall_quantile` は参考値として
        併記するが hit の根拠にはしない。
    """
    name = c["machine_name"]
    ratio = int(c["ratio"])
    mine = day[day["machine_name"] == name]
    n = int(mine["machine_number"].nunique())
    if n < min_machines:
        return {
            "hit": None,
            "note": f"当日 {name} が設置{min_machines}台以上の候補に無い（n={n}。撤去・台数不足・表記ゆれ）",
        }

    k = -(-n // ratio)  # ceil(n / ratio)
    mine_sorted = mine.sort_values("diff_coins_normalized", ascending=False)
    top_k_mean = float(mine_sorted["diff_coins_normalized"].head(k).mean())

    others = day[day["machine_name"] != name]
    if others.empty:
        return {"hit": None, "note": "比較対象（当該機種以外の台）が空"}
    q = others["diff_coins_normalized"].quantile(1 - 1 / ratio)
    hall_top_mean = float(others[others["diff_coins_normalized"] >= q]["diff_coins_normalized"].mean())

    out = {
        "n_machines": n,
        "ratio": ratio,
        "top_k": k,
        "model_top_k_mean_diff": round(top_k_mean, 1),
        "hall_top_quantile_mean_diff": round(hall_top_mean, 1),
        "excess_vs_hall_quantile": round(top_k_mean - hall_top_mean, 1),
        "model_mean_diff": round(float(mine["diff_coins_normalized"].mean()), 1),
        # 参考値。hit の根拠にはしない（台単位の設定は結果指標では判定できない）。
        "n_over_hall_quantile": int((mine["diff_coins_normalized"] >= q).sum()),
        "hit": bool(top_k_mean > hall_top_mean),
    }
    if name in ms.index:
        out["model_named_score"] = round(float(ms.loc[name, "score"]), 1)
        out["model_named_rank"] = int((ms["score"] > ms.loc[name, "score"]).sum()) + 1
    return out


def score(obj: dict) -> dict:
    """凍結済み予告を当日実績で採点する。"""
    if obj.get("result") is not None:
        raise ValueError("この予告は既に採点済み。結果の作り直しは禁止。")
    _verify_ledger(obj)

    df = load_frame(obj["hall"])
    target = obj["target_date"]
    day = df[df["date"] == target]
    if day.empty:
        raise ValueError(f"{target} のデータが DB にまだ無い。取り込み後に再実行すること。")

    # 機種のDB初出日。対象日以前のデータだけで決まるのでリークしない。
    first_seen = df[df["date"] <= target].groupby("machine_name")["dt"].min()

    # 差枚の打ち切りは機種平均を歪める。楽園蒲田店は両側で打ち切られており、
    # 右打ち切りを含む機種のスコアは真値の下界になる（censoring.py 参照）。
    # 採点結果に残し、CLI では stderr にも出す。黙って集計しない。
    cens = censoring_summary(day)
    b = bounds_for(obj["hall"])
    if b is not None:
        cens["bounds"] = list(b)
    msg = warning_text(cens, obj["hall"], context=f"{target}")
    if msg:
        print(msg, file=sys.stderr)

    obj["result"] = {
        "scored_at_data_max": str(df["date"].max()),
        "hall_baseline_mean_diff": round(float(day["diff_coins_normalized"].mean()), 1),
        "hall_n_machines": int(day["machine_number"].nunique()),
        "new_machine_days": NEW_MACHINE_DAYS,
        "censoring": cens,
        "claims": _judge_claims(obj, day, first_seen),
    }
    return obj


def _ledger_entries() -> dict[str, str]:
    if not LEDGER.exists():
        return {}
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["key"]] = rec["announce_digest"]
    return out


def is_late_registration(target_date: str, now: datetime | None = None) -> bool:
    """対象日を過ぎてからの登録か。実時間（壁時計）で判定する。

    なぜ db_max ではなく実時間で見るか:
        register は `target_date <= db_max` を拒否するが、これは「対象日当日の
        実績を DB から見て登録する」ことを防ぐガードであって、**登録者が既に
        結果を知っていること** は防げない。DB 取込は実時間より 1〜3 日遅れるのが
        常態で、その間 `target_date` が過去日でも db_max より後になり通過する。
        2026-08-11 時点で db_max=20260808 だったため、X の報告で結果を知っている
        8/9・8/10 の予告を「事前登録」として登録できる状態にあった。

        ブロックはしない。取込遅延中の正当な追いつき登録まで止まるからである
        （同じ理由で forward.plan の db_max ガードは正しく、実時間判定に
        変えてはならない。あちらは picks が決定論的で人間の知識が混入しない）。
        代わりに印を残し、base_rate 集計から除外できるようにする。
    """
    now = now or datetime.now().astimezone()
    # 「対象日を過ぎてから」＝対象日の"翌日"0時以降。対象日自身の0時と比べると、
    # 同日中の(正当な)登録まで late 扱いになってしまう。
    next_day_midnight = _target_midnight(target_date, now) + timedelta(days=1)
    return now >= next_day_midnight


def _append_ledger(obj: dict) -> None:
    now = datetime.now().astimezone()
    rec = {
        "key": obj["announce_id"],
        "announce_digest": announce_digest(obj),
        "hall": obj["hall"],
        "target_date": obj["target_date"],
        "account": obj["source"]["account"],
        # posted_at は「発信者が対象日より前に投稿したか」の保証。
        # registered_at は「登録者が結果を知る前に登録したか」の記録。別物である。
        "posted_at": obj["source"]["posted_at"],
        "registered_at": now.isoformat(timespec="seconds"),
        # True のものは的中率・base_rate の集計から除外すること。
        "late_registration": is_late_registration(obj["target_date"], now),
        "threshold": obj["zentaikei"]["threshold"],
        "claims": [c["type"] for c in obj["claims"]],
    }
    ANNOUNCE_DIR.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _verify_ledger(obj: dict) -> None:
    recorded = _ledger_entries().get(obj["announce_id"])
    if recorded is None:
        raise ValueError(
            f"台帳に {obj['announce_id']} の記録が無い。register を通していないか台帳が失われている。"
            "この予告は証拠として採点できない。"
        )
    actual = announce_digest(obj)
    if actual != recorded:
        raise ValueError(f"予告が登録後に書き換えられている。台帳={recorded} / 現在={actual}。採点を中止。")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ホール予告の事前登録と答え合わせ")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser("register", help="予告を検証して台帳に凍結する")
    p_reg.add_argument("path")

    p_sc = sub.add_parser("score", help="凍結済み予告を実績で採点する")
    p_sc.add_argument("path")

    p_dm = sub.add_parser("dbmax", help="ホールのDB最終収録日を表示する（baserateの--beforeに使う）")
    p_dm.add_argument("hall")

    p_mn = sub.add_parser("match-name", help="予告本文から実在機種名の候補をあいまい照合する（登録前の下ごしらえ用）")
    p_mn.add_argument("hall")
    p_mn.add_argument("text")
    p_mn.add_argument("--cutoff", type=float, default=0.6)

    p_br = sub.add_parser("baserate", help="全台系の閾値とベースレートを出す（登録前に使う）")
    p_br.add_argument("hall")
    p_br.add_argument("--before", required=True, help="YYYYMMDD。この日より前のデータだけを使う")
    p_br.add_argument("--days", type=int, default=90)
    p_br.add_argument("--min-machines", type=int, default=3)
    p_br.add_argument("--pct", type=float, default=0.95, help="閾値の分位点（既定 0.95）")
    p_br.add_argument("--metric", default="gratio_mean_diff", choices=sorted(ALLOWED_METRICS))
    p_br.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="絶対値閾値（例 1800.0）。指定すると fixed_threshold ブロック（p_at_least_N込み）を追加出力する",
    )

    p_nc = sub.add_parser(
        "named-context", help="名指し機種の直近N日ランキング・閾値超え率を出す（登録前の下ごしらえ用）"
    )
    p_nc.add_argument("hall")
    p_nc.add_argument(
        "--machines", required=True, help="カンマ区切りの正式表記machine_name（match-nameで確定済み前提）"
    )
    p_nc.add_argument("--as-of", required=True, help="YYYYMMDD。この日を含めて過去に遡る")
    p_nc.add_argument("--days", type=int, default=30)
    p_nc.add_argument(
        "--min-machines", type=int, default=3, help="ランキングプール算出用（窓内の出現集計には使わない）"
    )
    p_nc.add_argument("--threshold", type=float, default=1800.0)
    p_nc.add_argument("--metric", default="gratio_mean_diff", choices=sorted(ALLOWED_METRICS))

    p_ac = sub.add_parser(
        "audit-censoring",
        help="採点済み予告を打ち切り情報で再点検する（読み取り専用、台帳・結果ファイルは書き換えない）",
    )
    p_ac.add_argument("hall")

    args = p.parse_args(argv)
    ANNOUNCE_DIR.mkdir(parents=True, exist_ok=True)

    if args.cmd == "dbmax":
        print(db_max_date(args.hall))
        return 0

    if args.cmd == "match-name":
        res = match_machine_names(args.hall, args.text, args.cutoff)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "baserate":
        res = baserate(args.hall, args.before, args.days, args.min_machines, args.pct, args.metric, args.threshold)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "named-context":
        machines = [m.strip() for m in args.machines.split(",") if m.strip()]
        res = named_context(args.hall, machines, args.as_of, args.days, args.min_machines, args.threshold, args.metric)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "audit-censoring":
        res = audit_censoring(args.hall)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    path = Path(args.path)
    obj = json.loads(path.read_text(encoding="utf-8"))

    if args.cmd == "register":
        validate(obj)
        db_max = str(load_frame(obj["hall"])["date"].max())
        if obj["target_date"] <= db_max:
            raise SystemExit(
                f"target_date={obj['target_date']} は DB 最終日 {db_max} 以下。実績が出た後の登録は事前登録にならない。"
            )
        if obj["announce_id"] in _ledger_entries():
            raise SystemExit(f"既に登録済み: {obj['announce_id']}（登録し直しは禁止）")
        obj["result"] = None
        obj["announce_digest"] = announce_digest(obj)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _append_ledger(obj)
        if is_late_registration(obj["target_date"]):
            print(
                f"⚠️ 対象日 {obj['target_date']} を過ぎてからの登録である。"
                "DB 取込が遅れているため db_max ガードは通過したが、登録者が既に結果を"
                "知っている可能性がある。台帳に late_registration=true を記録した。"
                "的中率・base_rate の集計からは除外すること。",
                file=sys.stderr,
            )
        print(f"凍結: {obj['announce_id']}", file=sys.stderr)
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        obj = score(obj)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(obj["result"], ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    # Windows 既定の cp932 コンソールでは、raw_text の絵文字や ⑤⑥ などの全角記号を
    # 含む JSON ダンプで UnicodeEncodeError になる。台帳追記は済んでいるのに
    # コマンドが exit 1 で落ちるため、register が失敗したように見える。
    # stderr も「凍結:」「⚠️ 対象日…」の出力先なので両方 reconfigure する。
    # scripts/compile_instincts.py と同じ対処（commit f9ced01）。
    # import してライブラリとして使う場合に影響しないよう __main__ に限定。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
