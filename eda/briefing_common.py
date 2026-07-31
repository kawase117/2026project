"""毎朝ブリーフィング用の共通ローダ・集計ヘルパ。

eda/core.py の load_hall_df とは目的が異なるため別モジュールにしている:

- load_hall_df はロード時に MIN_GAMES=400 を強制する。これは「表示用の運用規約」であり、
  水準の把握には使ってはならない（CLAUDE.md）。games は設定の下流（低設定→早く見切られる）
  なので games>=N は低設定日を選択的に落とす選択バイアスを生む。
  本モジュールの既定は min_games=None（足切りなし）。
- load_hall_df は machine_master を JOIN しないためカテゴリが取れない。
- 機械割（games加重）を計算しない。

ホール名辞書とイベントDDは eda.core から import し、定義の二重管理を避ける。

契約:
    差枚 diff は「枚」。回転数 games は「G（回転）」。
    機械割は games加重 (Σgames*3 + Σdiff) / (Σgames*3) * 100（3枚貸し前提）。
    ★台ごとに機械割を出してから単純平均する方式は使わない（低回転台が外れ値を作るため）。
    games == 0 の行は機械割の分母から除外する。これは選択バイアス目的の足切りではなく、
    0除算を避けるための数学的な無効行処理。
    日付は TEXT "YYYYMMDD"。「直近N日」は基準日を含まない過去N暦日の閉区間
    [基準日-N, 基準日-1]（営業日ではなく暦日。休業日は行が存在しないだけ）。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

from eda.core import DB_DIR, HALL_DBS, HALL_EVENT_DIGITS

CATEGORY_AT = "AT一般"
CATEGORY_UNKNOWN = "UNKNOWN"
CATEGORIES = ["JUG", "HANA", "OKI", "BT", CATEGORY_AT]
_FLAG_TO_CATEGORY = [("jug_flag", "JUG"), ("hana_flag", "HANA"), ("oki_flag", "OKI"), ("bt_flag", "BT")]
_FLAGS = [f for f, _ in _FLAG_TO_CATEGORY]

# ★キーは eda.core の短縮ホール名（HALL_DBS のキー）で統一する。
# DB ファイル名で引くと hall_short_name を通さない経路で静かに空振りする。

# 蒲田7の7/7は全台設定6の特殊日。水準比較からは除外する（kamata7_0707_all_setting6）。
SPECIAL_DAYS = {"蒲田7": {"0707"}}

# 蒲田7の鉄台。末尾・角番シグナルの検定では除外必須だが、台選びでは除外してはならない
# （kamata7_theory.md §8.1）。ここでは注釈用にのみ保持する。
IRON_MACHINES = {"蒲田7": {2026}}


def iron_machines(hall: str) -> set[int]:
    """短縮名・DBファイル名のどちらで渡されても鉄台集合を返す。"""
    return IRON_MACHINES.get(hall_short_name(hall), set())


def use_utf8_stdout() -> None:
    """Windows の cp932 で日本語出力が化けるのを防ぐ。"""
    sys.stdout.reconfigure(encoding="utf-8")


def hall_db_path(hall: str) -> Path:
    """ホール短縮名（"みとや"）でも DB ファイル名（"みとや大森町店"）でも解決する。"""
    if hall in HALL_DBS:
        return DB_DIR / HALL_DBS[hall]
    direct = DB_DIR / f"{hall}.db"
    if direct.exists():
        return direct
    raise ValueError(f"不明なホール: {hall!r}. 利用可能: {sorted(HALL_DBS)}")


def hall_short_name(hall: str) -> str:
    """DB ファイル名から eda.core の短縮ホール名を引く（HALL_EVENT_DIGITS 参照用）。"""
    if hall in HALL_DBS:
        return hall
    for short, fname in HALL_DBS.items():
        if fname == f"{hall}.db":
            return short
    raise ValueError(f"短縮名に解決できないホール: {hall!r}")


def all_halls() -> list[str]:
    return list(HALL_DBS)


def _audit_master(master: pd.DataFrame, hall: str) -> None:
    """カテゴリ集計を壊す master の異常を fail-loud で検出する。

    現データ（2026-07-27 時点・全9ホール）では重複キー0・複数フラグ0・未一致0% だが、
    将来 master が更新されて壊れたとき黙って誤集計するのを防ぐ。
    """
    dup = int(master["machine_name_normalized"].duplicated().sum())
    if dup:
        raise ValueError(
            f"{hall}: machine_master の machine_name_normalized が {dup} 件重複している。"
            "LEFT JOIN で台×日行が増殖するため、キー単位に畳んでから使うこと。"
        )
    multi_mask = master[_FLAGS].fillna(0).sum(axis=1) > 1
    if int(multi_mask.sum()):
        names = master.loc[multi_mask, "machine_name_normalized"].tolist()
        raise ValueError(
            f"{hall}: 複数カテゴリフラグが立った機種が {int(multi_mask.sum())} 件ある（{names[:5]}）。"
            "カテゴリ合計が壊れるため、優先順位で黙って分類せず master を修正すること。"
        )


def load_hall_frame(
    hall: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    min_games: int | None = None,
    drop_special_days: bool = True,
) -> pd.DataFrame:
    """台×日粒度のフレームを返す。

    Args:
        hall: DB ファイル名（"みとや大森町店"）または短縮名（"みとや"）。
        date_from / date_to: "YYYYMMDD"。両端を含む閉区間。
        min_games: 既定 None（足切りなし）。値を指定すると選択バイアスが入るため、
            結果には必ず「高稼働日に条件づけた率」と注記すること。
        drop_special_days: 蒲田7の7/7（全台設定6）等を落とす。水準比較では True。

    Returns:
        列: hall, date, year_month, dd, day_of_week, is_event_dd, machine_number,
            machine_name, games, diff, bb_count, rb_count, category, is_valid_games
        category は JUG/HANA/OKI/BT/AT一般/UNKNOWN。UNKNOWN は master 未一致で、
        AT一般には混ぜない（混ぜると未登録の新機種が AT の水準を汚す）。
    """
    path = hall_db_path(hall)
    conn = sqlite3.connect(path)
    try:
        master = pd.read_sql("select * from machine_master", conn)
        _audit_master(master, hall)
        where = ["1=1"]
        if date_from:
            where.append(f"r.date >= '{date_from}'")
        if date_to:
            where.append(f"r.date <= '{date_to}'")
        if min_games is not None:
            where.append(f"r.games_normalized >= {int(min_games)}")
        df = pd.read_sql(
            "select r.date, r.machine_number, r.machine_name, "
            "r.games_normalized as games, r.diff_coins_normalized as diff, "
            "r.bb_count, r.rb_count "
            f"from machine_detailed_results r where {' and '.join(where)}",
            conn,
        )
    finally:
        conn.close()

    keep = ["machine_name_normalized", *_FLAGS]
    df = df.merge(master[keep], left_on="machine_name", right_on="machine_name_normalized", how="left")
    if len(df) and df["machine_name_normalized"].isna().mean() > 0.05:
        rate = df["machine_name_normalized"].isna().mean()
        names = sorted(df.loc[df["machine_name_normalized"].isna(), "machine_name"].unique())[:5]
        raise ValueError(
            f"{hall}: machine_master 未一致が {rate:.1%} ある（例: {names}）。"
            "UNKNOWN カテゴリに落ちて水準比較が歪むため、先に update-machine-master を実行すること。"
        )

    matched = df["machine_name_normalized"].notna()
    category = pd.Series(CATEGORY_UNKNOWN, index=df.index, dtype=object)
    category[matched] = CATEGORY_AT
    for flag, name in _FLAG_TO_CATEGORY:
        category[matched & (df[flag] == 1)] = name
    df["category"] = category
    df = df.drop(columns=["machine_name_normalized", *_FLAGS])

    df["hall"] = str(hall)
    df["year_month"] = df["date"].str[:6]
    df["dd"] = df["date"].str[6:8].astype(int)
    dates = pd.to_datetime(df["date"], format="%Y%m%d")
    df["day_of_week"] = dates.dt.weekday.map(dict(enumerate("月火水木金土日")))
    event_digits = set(HALL_EVENT_DIGITS.get(hall_short_name(hall), []))
    df["is_event_dd"] = df["dd"].isin(event_digits)
    # games==0 は機械割の分母にできない。行自体は残し、集計側でこのフラグを見る。
    df["is_valid_games"] = df["games"] > 0

    if drop_special_days:
        special = SPECIAL_DAYS.get(hall_short_name(hall), set())
        if special:
            df = df[~df["date"].str[4:8].isin(special)]

    return df.reset_index(drop=True)


def payout_w(frame: pd.DataFrame) -> float:
    """games加重機械割 %。games==0 の行は分母から除外。有効行が無ければ NaN。"""
    v = frame[frame["is_valid_games"]] if "is_valid_games" in frame else frame[frame["games"] > 0]
    g = v["games"].sum()
    if g <= 0:
        return float("nan")
    return (g * 3 + v["diff"].sum()) / (g * 3) * 100


def daily_payout(frame: pd.DataFrame) -> pd.Series:
    """日次の games加重機械割。日次系列でのブートストラップCIを取るときに使う。"""
    return frame.groupby("date").apply(payout_w, include_groups=False)
