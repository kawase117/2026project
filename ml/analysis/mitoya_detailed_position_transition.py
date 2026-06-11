"""
みとや大森町店：詳細ポジション遷移分析（セクション×末尾×角番 × DD系列）

4→4, 7→7, 4→7, 7→4 の全パターンについて、
セクション、末尾、角番ごとにポジション遷移を分析

「前回イベント日で高成績だったセクション/末尾/角番が
 次回イベント日でも高成績か、別のセクション/末尾/角番に移るか」
"""

import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np

DB_PATH = Path("db/みとや大森町店.db")

def load_xday_data():
    """X_day（イベント日）のセクション×末尾×角番成績を読み込み"""
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql(
        """
        SELECT
            date,
            machine_number,
            last_digit,
            diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date, machine_number
        """,
        conn,
    )

    # 台配置情報
    layout = pd.read_sql(
        """
        SELECT
            machine_number,
            section,
            rank_from_aisle
        FROM machine_layout
        """,
        conn,
    )

    conn.close()

    df = df.merge(layout, on="machine_number", how="left")

    # X_day判定
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date_dt"].dt.day
    df["dd_mod"] = df["dd"] % 10
    df["is_xday"] = df["dd_mod"].isin([4, 7]).astype(int)
    df["dd_group"] = df["dd_mod"].apply(lambda x: "4系" if x == 4 else ("7系" if x == 7 else None))

    # 角番フラグ
    df["is_aisle_corner"] = (df["rank_from_aisle"] == 1).astype(int)
    section_max_aisle = df.groupby("section")["rank_from_aisle"].transform("max")
    df["is_far_corner"] = (df["rank_from_aisle"] == section_max_aisle).astype(int)
    df["corner_type"] = df["is_aisle_corner"].apply(lambda x: "通路側" if x == 1 else "奥側")

    return df[df["dd_group"].notna()].copy()


def get_xday_list(df):
    """イベント日のリストを取得"""
    xdays = df[df["is_xday"] == 1].copy()
    xdays_sorted = xdays.sort_values("date_dt")[["date", "dd_group"]].drop_duplicates("date").reset_index(drop=True)
    return xdays_sorted


def analyze_section_transition(df, xdays):
    """セクション別での高成績遷移を分析"""
    print("=" * 80)
    print("1. セクション別の最高成績遷移分析")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×セクション別の成績
    daily_section = df_xday.groupby(["date", "section", "dd_group"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()

    # 日ごとの最高セクションを抽出
    idx_max = daily_section.groupby(["date", "dd_group"])["diff_coins_normalized"].idxmax()
    best_section = daily_section.loc[idx_max, ["date", "dd_group", "section", "diff_coins_normalized"]].reset_index(drop=True)
    best_section.columns = ["date", "dd_group", "best_section", "best_section_diff"]
    best_section["date_dt"] = pd.to_datetime(best_section["date"], format="%Y%m%d")

    print(f"\nイベント日ごとの最高セクション: {len(best_section)} 日")

    # 4→4の遷移
    print(f"\n【4系→4系の遷移（同じDD系列内での遷移）】")
    trans_4to4 = []
    for i in range(len(best_section) - 1):
        if best_section.iloc[i]["dd_group"] == "4系" and best_section.iloc[i+1]["dd_group"] == "4系":
            trans_4to4.append({
                "prev_date": best_section.iloc[i]["date"],
                "prev_section": best_section.iloc[i]["best_section"],
                "prev_diff": best_section.iloc[i]["best_section_diff"],
                "next_date": best_section.iloc[i+1]["date"],
                "next_section": best_section.iloc[i+1]["best_section"],
                "next_diff": best_section.iloc[i+1]["best_section_diff"],
                "same_section": best_section.iloc[i]["best_section"] == best_section.iloc[i+1]["best_section"]
            })

    if trans_4to4:
        df_4to4 = pd.DataFrame(trans_4to4)
        print(f"遷移ケース数: {len(df_4to4)}")
        print(f"同じセクションが持続: {df_4to4['same_section'].sum()} 回 ({df_4to4['same_section'].sum() / len(df_4to4) * 100:.1f}%)")
        print(f"別のセクションに遷移: {(~df_4to4['same_section']).sum()} 回 ({(~df_4to4['same_section']).sum() / len(df_4to4) * 100:.1f}%)")

        # セクション遷移の詳細
        section_trans = df_4to4.groupby(["prev_section", "next_section"]).size().reset_index(name="count")
        section_trans = section_trans.sort_values("count", ascending=False)
        print(f"\nセクション遷移パターン (Top 10):")
        for _, row in section_trans.head(10).iterrows():
            print(f"  {row['prev_section']} → {row['next_section']}: {row['count']} 回")

    # 7→7の遷移
    print(f"\n【7系→7系の遷移（同じDD系列内での遷移）】")
    trans_7to7 = []
    for i in range(len(best_section) - 1):
        if best_section.iloc[i]["dd_group"] == "7系" and best_section.iloc[i+1]["dd_group"] == "7系":
            trans_7to7.append({
                "prev_date": best_section.iloc[i]["date"],
                "prev_section": best_section.iloc[i]["best_section"],
                "prev_diff": best_section.iloc[i]["best_section_diff"],
                "next_date": best_section.iloc[i+1]["date"],
                "next_section": best_section.iloc[i+1]["best_section"],
                "next_diff": best_section.iloc[i+1]["best_section_diff"],
                "same_section": best_section.iloc[i]["best_section"] == best_section.iloc[i+1]["best_section"]
            })

    if trans_7to7:
        df_7to7 = pd.DataFrame(trans_7to7)
        print(f"遷移ケース数: {len(df_7to7)}")
        print(f"同じセクションが持続: {df_7to7['same_section'].sum()} 回 ({df_7to7['same_section'].sum() / len(df_7to7) * 100:.1f}%)")
        print(f"別のセクションに遷移: {(~df_7to7['same_section']).sum()} 回 ({(~df_7to7['same_section']).sum() / len(df_7to7) * 100:.1f}%)")

    # 4→7の遷移
    print(f"\n【4系→7系の遷移（異なるDD系列への遷移）】")
    trans_4to7 = []
    for i in range(len(best_section) - 1):
        if best_section.iloc[i]["dd_group"] == "4系" and best_section.iloc[i+1]["dd_group"] == "7系":
            trans_4to7.append({
                "prev_date": best_section.iloc[i]["date"],
                "prev_section": best_section.iloc[i]["best_section"],
                "prev_diff": best_section.iloc[i]["best_section_diff"],
                "next_date": best_section.iloc[i+1]["date"],
                "next_section": best_section.iloc[i+1]["best_section"],
                "next_diff": best_section.iloc[i+1]["best_section_diff"],
                "same_section": best_section.iloc[i]["best_section"] == best_section.iloc[i+1]["best_section"]
            })

    if trans_4to7:
        df_4to7 = pd.DataFrame(trans_4to7)
        print(f"遷移ケース数: {len(df_4to7)}")
        print(f"同じセクションが持続: {df_4to7['same_section'].sum()} 回 ({df_4to7['same_section'].sum() / len(df_4to7) * 100:.1f}%)")
        print(f"別のセクションに遷移: {(~df_4to7['same_section']).sum()} 回 ({(~df_4to7['same_section']).sum() / len(df_4to7) * 100:.1f}%)")


def analyze_last_digit_transition(df, xdays):
    """末尾別での高成績遷移を分析"""
    print("\n" + "=" * 80)
    print("2. 末尾別の最高成績遷移分析")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×末尾別の成績
    daily_digit = df_xday.groupby(["date", "last_digit", "dd_group"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()

    # 日ごとの最高末尾を抽出
    idx_max = daily_digit.groupby(["date", "dd_group"])["diff_coins_normalized"].idxmax()
    best_digit = daily_digit.loc[idx_max, ["date", "dd_group", "last_digit", "diff_coins_normalized"]].reset_index(drop=True)
    best_digit.columns = ["date", "dd_group", "best_digit", "best_digit_diff"]
    best_digit["date_dt"] = pd.to_datetime(best_digit["date"], format="%Y%m%d")

    print(f"\nイベント日ごとの最高末尾: {len(best_digit)} 日")

    # 4→4の遷移
    print(f"\n【4系→4系の遷移】")
    trans_4to4 = []
    for i in range(len(best_digit) - 1):
        if best_digit.iloc[i]["dd_group"] == "4系" and best_digit.iloc[i+1]["dd_group"] == "4系":
            trans_4to4.append({
                "prev_date": best_digit.iloc[i]["date"],
                "prev_digit": best_digit.iloc[i]["best_digit"],
                "prev_diff": best_digit.iloc[i]["best_digit_diff"],
                "next_date": best_digit.iloc[i+1]["date"],
                "next_digit": best_digit.iloc[i+1]["best_digit"],
                "next_diff": best_digit.iloc[i+1]["best_digit_diff"],
                "same_digit": best_digit.iloc[i]["best_digit"] == best_digit.iloc[i+1]["best_digit"]
            })

    if trans_4to4:
        df_4to4 = pd.DataFrame(trans_4to4)
        print(f"遷移ケース数: {len(df_4to4)}")
        print(f"同じ末尾が持続: {df_4to4['same_digit'].sum()} 回 ({df_4to4['same_digit'].sum() / len(df_4to4) * 100:.1f}%)")
        print(f"別の末尾に遷移: {(~df_4to4['same_digit']).sum()} 回 ({(~df_4to4['same_digit']).sum() / len(df_4to4) * 100:.1f}%)")

    # 7→7の遷移
    print(f"\n【7系→7系の遷移】")
    trans_7to7 = []
    for i in range(len(best_digit) - 1):
        if best_digit.iloc[i]["dd_group"] == "7系" and best_digit.iloc[i+1]["dd_group"] == "7系":
            trans_7to7.append({
                "prev_date": best_digit.iloc[i]["date"],
                "prev_digit": best_digit.iloc[i]["best_digit"],
                "prev_diff": best_digit.iloc[i]["best_digit_diff"],
                "next_date": best_digit.iloc[i+1]["date"],
                "next_digit": best_digit.iloc[i+1]["best_digit"],
                "next_diff": best_digit.iloc[i+1]["best_digit_diff"],
                "same_digit": best_digit.iloc[i]["best_digit"] == best_digit.iloc[i+1]["best_digit"]
            })

    if trans_7to7:
        df_7to7 = pd.DataFrame(trans_7to7)
        print(f"遷移ケース数: {len(df_7to7)}")
        print(f"同じ末尾が持続: {df_7to7['same_digit'].sum()} 回 ({df_7to7['same_digit'].sum() / len(df_7to7) * 100:.1f}%)")
        print(f"別の末尾に遷移: {(~df_7to7['same_digit']).sum()} 回 ({(~df_7to7['same_digit']).sum() / len(df_7to7) * 100:.1f}%)")

    # 4→7の遷移
    print(f"\n【4系→7系の遷移】")
    trans_4to7 = []
    for i in range(len(best_digit) - 1):
        if best_digit.iloc[i]["dd_group"] == "4系" and best_digit.iloc[i+1]["dd_group"] == "7系":
            trans_4to7.append({
                "prev_date": best_digit.iloc[i]["date"],
                "prev_digit": best_digit.iloc[i]["best_digit"],
                "prev_diff": best_digit.iloc[i]["best_digit_diff"],
                "next_date": best_digit.iloc[i+1]["date"],
                "next_digit": best_digit.iloc[i+1]["best_digit"],
                "next_diff": best_digit.iloc[i+1]["best_digit_diff"],
                "same_digit": best_digit.iloc[i]["best_digit"] == best_digit.iloc[i+1]["best_digit"]
            })

    if trans_4to7:
        df_4to7 = pd.DataFrame(trans_4to7)
        print(f"遷移ケース数: {len(df_4to7)}")
        print(f"同じ末尾が持続: {df_4to7['same_digit'].sum()} 回 ({df_4to7['same_digit'].sum() / len(df_4to7) * 100:.1f}%)")
        print(f"別の末尾に遷移: {(~df_4to7['same_digit']).sum()} 回 ({(~df_4to7['same_digit']).sum() / len(df_4to7) * 100:.1f}%)")


def analyze_corner_transition(df, xdays):
    """角番別での高成績遷移を分析"""
    print("\n" + "=" * 80)
    print("3. 角番別の最高成績遷移分析")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×角番別の成績
    daily_corner = df_xday.groupby(["date", "corner_type", "dd_group"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()

    # 日ごとの最高角番を抽出
    idx_max = daily_corner.groupby(["date", "dd_group"])["diff_coins_normalized"].idxmax()
    best_corner = daily_corner.loc[idx_max, ["date", "dd_group", "corner_type", "diff_coins_normalized"]].reset_index(drop=True)
    best_corner.columns = ["date", "dd_group", "best_corner", "best_corner_diff"]
    best_corner["date_dt"] = pd.to_datetime(best_corner["date"], format="%Y%m%d")

    print(f"\nイベント日ごとの最高角番: {len(best_corner)} 日")

    # 4→4の遷移
    print(f"\n【4系→4系の遷移】")
    trans_4to4 = []
    for i in range(len(best_corner) - 1):
        if best_corner.iloc[i]["dd_group"] == "4系" and best_corner.iloc[i+1]["dd_group"] == "4系":
            trans_4to4.append({
                "prev_date": best_corner.iloc[i]["date"],
                "prev_corner": best_corner.iloc[i]["best_corner"],
                "prev_diff": best_corner.iloc[i]["best_corner_diff"],
                "next_date": best_corner.iloc[i+1]["date"],
                "next_corner": best_corner.iloc[i+1]["best_corner"],
                "next_diff": best_corner.iloc[i+1]["best_corner_diff"],
                "same_corner": best_corner.iloc[i]["best_corner"] == best_corner.iloc[i+1]["best_corner"]
            })

    if trans_4to4:
        df_4to4 = pd.DataFrame(trans_4to4)
        print(f"遷移ケース数: {len(df_4to4)}")
        print(f"同じ角番が持続: {df_4to4['same_corner'].sum()} 回 ({df_4to4['same_corner'].sum() / len(df_4to4) * 100:.1f}%)")
        print(f"別の角番に遷移: {(~df_4to4['same_corner']).sum()} 回 ({(~df_4to4['same_corner']).sum() / len(df_4to4) * 100:.1f}%)")

    # 7→7の遷移
    print(f"\n【7系→7系の遷移】")
    trans_7to7 = []
    for i in range(len(best_corner) - 1):
        if best_corner.iloc[i]["dd_group"] == "7系" and best_corner.iloc[i+1]["dd_group"] == "7系":
            trans_7to7.append({
                "prev_date": best_corner.iloc[i]["date"],
                "prev_corner": best_corner.iloc[i]["best_corner"],
                "prev_diff": best_corner.iloc[i]["best_corner_diff"],
                "next_date": best_corner.iloc[i+1]["date"],
                "next_corner": best_corner.iloc[i+1]["best_corner"],
                "next_diff": best_corner.iloc[i+1]["best_corner_diff"],
                "same_corner": best_corner.iloc[i]["best_corner"] == best_corner.iloc[i+1]["best_corner"]
            })

    if trans_7to7:
        df_7to7 = pd.DataFrame(trans_7to7)
        print(f"遷移ケース数: {len(df_7to7)}")
        print(f"同じ角番が持続: {df_7to7['same_corner'].sum()} 回 ({df_7to7['same_corner'].sum() / len(df_7to7) * 100:.1f}%)")
        print(f"別の角番に遷移: {(~df_7to7['same_corner']).sum()} 回 ({(~df_7to7['same_corner']).sum() / len(df_7to7) * 100:.1f}%)")

    # 4→7の遷移
    print(f"\n【4系→7系の遷移】")
    trans_4to7 = []
    for i in range(len(best_corner) - 1):
        if best_corner.iloc[i]["dd_group"] == "4系" and best_corner.iloc[i+1]["dd_group"] == "7系":
            trans_4to7.append({
                "prev_date": best_corner.iloc[i]["date"],
                "prev_corner": best_corner.iloc[i]["best_corner"],
                "prev_diff": best_corner.iloc[i]["best_corner_diff"],
                "next_date": best_corner.iloc[i+1]["date"],
                "next_corner": best_corner.iloc[i+1]["best_corner"],
                "next_diff": best_corner.iloc[i+1]["best_corner_diff"],
                "same_corner": best_corner.iloc[i]["best_corner"] == best_corner.iloc[i+1]["best_corner"]
            })

    if trans_4to7:
        df_4to7 = pd.DataFrame(trans_4to7)
        print(f"遷移ケース数: {len(df_4to7)}")
        print(f"同じ角番が持続: {df_4to7['same_corner'].sum()} 回 ({df_4to7['same_corner'].sum() / len(df_4to7) * 100:.1f}%)")
        print(f"別の角番に遷移: {(~df_4to7['same_corner']).sum()} 回 ({(~df_4to7['same_corner']).sum() / len(df_4to7) * 100:.1f}%)")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("みとや大森町店：詳細ポジション遷移分析")
    print("（セクション×末尾×角番 × 4→4, 7→7, 4→7, 7→4）")
    print("=" * 80)

    df = load_xday_data()
    xdays = get_xday_list(df)
    print(f"\nイベント日データ読み込み完了")
    print(f"総イベント日数: {len(xdays)}")

    # 分析実行
    analyze_section_transition(df, xdays)
    analyze_last_digit_transition(df, xdays)
    analyze_corner_transition(df, xdays)

    print("\n" + "=" * 80)
    print("分析完了")
    print("=" * 80)
