"""
みとや大森町店：同一DD末尾グループ内での遷移分析

DD4 → DD14 → DD24（4系同士）での遷移
DD7 → DD17 → DD27（7系同士）での遷移

つまり、同じDD末尾グループ内での「次回イベント日」でのポジション遷移を分析
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


def get_sorted_xdays(df):
    """イベント日をDD別にソートして返す"""
    xdays = df[df["is_xday"] == 1].copy()
    xdays_sorted = xdays.sort_values("date_dt")[["date", "dd_group", "dd"]].drop_duplicates("date")
    return xdays_sorted.reset_index(drop=True)


def analyze_section_transition_same_group(df):
    """同一DD末尾グループ内でのセクション遷移を分析"""
    print("=" * 80)
    print("1. セクション別の遷移（同一DD末尾グループ内）")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×セクション別の成績
    daily_section = df_xday.groupby(["date", "dd_group", "dd", "section"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()

    # 日ごとの最高セクションを抽出
    idx_max = daily_section.groupby(["date", "dd_group"])["diff_coins_normalized"].idxmax()
    best_section = daily_section.loc[idx_max, ["date", "dd_group", "dd", "section", "diff_coins_normalized"]].reset_index(drop=True)
    best_section.columns = ["date", "dd_group", "dd", "best_section", "best_section_diff"]
    best_section["date_dt"] = pd.to_datetime(best_section["date"], format="%Y%m%d")
    best_section = best_section.sort_values("date_dt")

    print(f"\nイベント日ごとの最高セクション: {len(best_section)} 日")

    # 4系グループ内の遷移（DD4 → DD14 → DD24）
    print(f"\n【4系グループ内の遷移（DD4 → DD14 → DD24）】")
    best_section_4 = best_section[best_section["dd_group"] == "4系"].copy().reset_index(drop=True)

    trans_4to4 = []
    for i in range(len(best_section_4) - 1):
        trans_4to4.append({
            "prev_date": best_section_4.iloc[i]["date"],
            "prev_dd": int(best_section_4.iloc[i]["dd"]),
            "prev_section": best_section_4.iloc[i]["best_section"],
            "prev_diff": best_section_4.iloc[i]["best_section_diff"],
            "next_date": best_section_4.iloc[i+1]["date"],
            "next_dd": int(best_section_4.iloc[i+1]["dd"]),
            "next_section": best_section_4.iloc[i+1]["best_section"],
            "next_diff": best_section_4.iloc[i+1]["best_section_diff"],
            "same_section": best_section_4.iloc[i]["best_section"] == best_section_4.iloc[i+1]["best_section"]
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

    # 7系グループ内の遷移（DD7 → DD17 → DD27）
    print(f"\n【7系グループ内の遷移（DD7 → DD17 → DD27）】")
    best_section_7 = best_section[best_section["dd_group"] == "7系"].copy().reset_index(drop=True)

    trans_7to7 = []
    for i in range(len(best_section_7) - 1):
        trans_7to7.append({
            "prev_date": best_section_7.iloc[i]["date"],
            "prev_dd": int(best_section_7.iloc[i]["dd"]),
            "prev_section": best_section_7.iloc[i]["best_section"],
            "prev_diff": best_section_7.iloc[i]["best_section_diff"],
            "next_date": best_section_7.iloc[i+1]["date"],
            "next_dd": int(best_section_7.iloc[i+1]["dd"]),
            "next_section": best_section_7.iloc[i+1]["best_section"],
            "next_diff": best_section_7.iloc[i+1]["best_section_diff"],
            "same_section": best_section_7.iloc[i]["best_section"] == best_section_7.iloc[i+1]["best_section"]
        })

    if trans_7to7:
        df_7to7 = pd.DataFrame(trans_7to7)
        print(f"遷移ケース数: {len(df_7to7)}")
        print(f"同じセクションが持続: {df_7to7['same_section'].sum()} 回 ({df_7to7['same_section'].sum() / len(df_7to7) * 100:.1f}%)")
        print(f"別のセクションに遷移: {(~df_7to7['same_section']).sum()} 回 ({(~df_7to7['same_section']).sum() / len(df_7to7) * 100:.1f}%)")

        # セクション遷移の詳細
        section_trans = df_7to7.groupby(["prev_section", "next_section"]).size().reset_index(name="count")
        section_trans = section_trans.sort_values("count", ascending=False)
        print(f"\nセクション遷移パターン (Top 10):")
        for _, row in section_trans.head(10).iterrows():
            print(f"  {row['prev_section']} → {row['next_section']}: {row['count']} 回")


def analyze_digit_transition_same_group(df):
    """同一DD末尾グループ内での末尾遷移を分析"""
    print("\n" + "=" * 80)
    print("2. 末尾別の遷移（同一DD末尾グループ内）")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×末尾別の成績
    daily_digit = df_xday.groupby(["date", "dd_group", "dd", "last_digit"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()

    # 日ごとの最高末尾を抽出
    idx_max = daily_digit.groupby(["date", "dd_group"])["diff_coins_normalized"].idxmax()
    best_digit = daily_digit.loc[idx_max, ["date", "dd_group", "dd", "last_digit", "diff_coins_normalized"]].reset_index(drop=True)
    best_digit.columns = ["date", "dd_group", "dd", "best_digit", "best_digit_diff"]
    best_digit["date_dt"] = pd.to_datetime(best_digit["date"], format="%Y%m%d")
    best_digit = best_digit.sort_values("date_dt")

    print(f"\nイベント日ごとの最高末尾: {len(best_digit)} 日")

    # 4系グループ内の遷移
    print(f"\n【4系グループ内の遷移】")
    best_digit_4 = best_digit[best_digit["dd_group"] == "4系"].copy().reset_index(drop=True)

    trans_4to4 = []
    for i in range(len(best_digit_4) - 1):
        trans_4to4.append({
            "prev_date": best_digit_4.iloc[i]["date"],
            "prev_dd": int(best_digit_4.iloc[i]["dd"]),
            "prev_digit": int(best_digit_4.iloc[i]["best_digit"]),
            "prev_diff": best_digit_4.iloc[i]["best_digit_diff"],
            "next_date": best_digit_4.iloc[i+1]["date"],
            "next_dd": int(best_digit_4.iloc[i+1]["dd"]),
            "next_digit": int(best_digit_4.iloc[i+1]["best_digit"]),
            "next_diff": best_digit_4.iloc[i+1]["best_digit_diff"],
            "same_digit": best_digit_4.iloc[i]["best_digit"] == best_digit_4.iloc[i+1]["best_digit"]
        })

    if trans_4to4:
        df_4to4 = pd.DataFrame(trans_4to4)
        print(f"遷移ケース数: {len(df_4to4)}")
        print(f"同じ末尾が持続: {df_4to4['same_digit'].sum()} 回 ({df_4to4['same_digit'].sum() / len(df_4to4) * 100:.1f}%)")
        print(f"別の末尾に遷移: {(~df_4to4['same_digit']).sum()} 回 ({(~df_4to4['same_digit']).sum() / len(df_4to4) * 100:.1f}%)")

    # 7系グループ内の遷移
    print(f"\n【7系グループ内の遷移】")
    best_digit_7 = best_digit[best_digit["dd_group"] == "7系"].copy().reset_index(drop=True)

    trans_7to7 = []
    for i in range(len(best_digit_7) - 1):
        trans_7to7.append({
            "prev_date": best_digit_7.iloc[i]["date"],
            "prev_dd": int(best_digit_7.iloc[i]["dd"]),
            "prev_digit": int(best_digit_7.iloc[i]["best_digit"]),
            "prev_diff": best_digit_7.iloc[i]["best_digit_diff"],
            "next_date": best_digit_7.iloc[i+1]["date"],
            "next_dd": int(best_digit_7.iloc[i+1]["dd"]),
            "next_digit": int(best_digit_7.iloc[i+1]["best_digit"]),
            "next_diff": best_digit_7.iloc[i+1]["best_digit_diff"],
            "same_digit": best_digit_7.iloc[i]["best_digit"] == best_digit_7.iloc[i+1]["best_digit"]
        })

    if trans_7to7:
        df_7to7 = pd.DataFrame(trans_7to7)
        print(f"遷移ケース数: {len(df_7to7)}")
        print(f"同じ末尾が持続: {df_7to7['same_digit'].sum()} 回 ({df_7to7['same_digit'].sum() / len(df_7to7) * 100:.1f}%)")
        print(f"別の末尾に遷移: {(~df_7to7['same_digit']).sum()} 回 ({(~df_7to7['same_digit']).sum() / len(df_7to7) * 100:.1f}%)")


def analyze_corner_transition_same_group(df):
    """同一DD末尾グループ内での角番遷移を分析"""
    print("\n" + "=" * 80)
    print("3. 角番別の遷移（同一DD末尾グループ内）")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×角番別の成績
    daily_corner = df_xday.groupby(["date", "dd_group", "dd", "corner_type"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()

    # 日ごとの最高角番を抽出
    idx_max = daily_corner.groupby(["date", "dd_group"])["diff_coins_normalized"].idxmax()
    best_corner = daily_corner.loc[idx_max, ["date", "dd_group", "dd", "corner_type", "diff_coins_normalized"]].reset_index(drop=True)
    best_corner.columns = ["date", "dd_group", "dd", "best_corner", "best_corner_diff"]
    best_corner["date_dt"] = pd.to_datetime(best_corner["date"], format="%Y%m%d")
    best_corner = best_corner.sort_values("date_dt")

    print(f"\nイベント日ごとの最高角番: {len(best_corner)} 日")

    # 4系グループ内の遷移
    print(f"\n【4系グループ内の遷移】")
    best_corner_4 = best_corner[best_corner["dd_group"] == "4系"].copy().reset_index(drop=True)

    trans_4to4 = []
    for i in range(len(best_corner_4) - 1):
        trans_4to4.append({
            "prev_date": best_corner_4.iloc[i]["date"],
            "prev_dd": int(best_corner_4.iloc[i]["dd"]),
            "prev_corner": best_corner_4.iloc[i]["best_corner"],
            "prev_diff": best_corner_4.iloc[i]["best_corner_diff"],
            "next_date": best_corner_4.iloc[i+1]["date"],
            "next_dd": int(best_corner_4.iloc[i+1]["dd"]),
            "next_corner": best_corner_4.iloc[i+1]["best_corner"],
            "next_diff": best_corner_4.iloc[i+1]["best_corner_diff"],
            "same_corner": best_corner_4.iloc[i]["best_corner"] == best_corner_4.iloc[i+1]["best_corner"]
        })

    if trans_4to4:
        df_4to4 = pd.DataFrame(trans_4to4)
        print(f"遷移ケース数: {len(df_4to4)}")
        print(f"同じ角番が持続: {df_4to4['same_corner'].sum()} 回 ({df_4to4['same_corner'].sum() / len(df_4to4) * 100:.1f}%)")
        print(f"別の角番に遷移: {(~df_4to4['same_corner']).sum()} 回 ({(~df_4to4['same_corner']).sum() / len(df_4to4) * 100:.1f}%)")

    # 7系グループ内の遷移
    print(f"\n【7系グループ内の遷移】")
    best_corner_7 = best_corner[best_corner["dd_group"] == "7系"].copy().reset_index(drop=True)

    trans_7to7 = []
    for i in range(len(best_corner_7) - 1):
        trans_7to7.append({
            "prev_date": best_corner_7.iloc[i]["date"],
            "prev_dd": int(best_corner_7.iloc[i]["dd"]),
            "prev_corner": best_corner_7.iloc[i]["best_corner"],
            "prev_diff": best_corner_7.iloc[i]["best_corner_diff"],
            "next_date": best_corner_7.iloc[i+1]["date"],
            "next_dd": int(best_corner_7.iloc[i+1]["dd"]),
            "next_corner": best_corner_7.iloc[i+1]["best_corner"],
            "next_diff": best_corner_7.iloc[i+1]["best_corner_diff"],
            "same_corner": best_corner_7.iloc[i]["best_corner"] == best_corner_7.iloc[i+1]["best_corner"]
        })

    if trans_7to7:
        df_7to7 = pd.DataFrame(trans_7to7)
        print(f"遷移ケース数: {len(df_7to7)}")
        print(f"同じ角番が持続: {df_7to7['same_corner'].sum()} 回 ({df_7to7['same_corner'].sum() / len(df_7to7) * 100:.1f}%)")
        print(f"別の角番に遷移: {(~df_7to7['same_corner']).sum()} 回 ({(~df_7to7['same_corner']).sum() / len(df_7to7) * 100:.1f}%)")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("みとや大森町店：同一DD末尾グループ内での遷移分析")
    print("（DD4→DD14→DD24 および DD7→DD17→DD27）")
    print("=" * 80)

    df = load_xday_data()
    xdays = get_sorted_xdays(df)
    print(f"\nイベント日データ読み込み完了")
    print(f"総イベント日数: {len(xdays)}")

    # 分析実行
    analyze_section_transition_same_group(df)
    analyze_digit_transition_same_group(df)
    analyze_corner_transition_same_group(df)

    print("\n" + "=" * 80)
    print("分析完了")
    print("=" * 80)
