# -*- coding: utf-8 -*-
"""Phase 0: 高設定ラベルのベースレート定量化（4ホール）

目的:
  - Aタイプ(ジャグラー)トラック: BB/RB二項尤度による設定事後分布で
    P(設定5以上) が高い台が1日に何台あるかをホール別に測る
  - ATトラック: 高稼働かつ機械割104%+ の台数分布を測る（粗いプロキシ）
  - DD別（日付の日）の高設定出現分布 → イベント日構造の確認

出力: 標準出力に集計テーブルのみ（行レベルデータは出さない）
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ml.experiments.jug_rb_setting_prediction.config import (  # noqa: E402
    JUGGLER_FAMILY_MATCHERS,
    JUGGLER_FAMILY_SPECS,
)

HALLS = {
    "楽園蒲田": PROJECT_ROOT / "db" / "楽園蒲田店.db",
    "蒲田7": PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db",
    "蒲田1": PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db",
    "みとや": PROJECT_ROOT / "db" / "みとや大森町店.db",
}

MIN_GAMES_JUG = 2500  # RB推定に足るG数
MIN_GAMES_AT = 4000  # AT高設定プロキシの稼働条件
P56_HIGH = 0.80  # 一様事前での高設定判定閾値（事前楽観を厳しめ閾値で相殺）
AT_PAYOUT_HIGH = 104.0  # AT高設定プロキシの機械割閾値(%)

# みとやイベントDD（確定定義: メモリ mitoya-event-definition-confirmed）
MITOYA_EVENT_DDS = {1, 4, 7, 14, 17, 24, 27, 30}


def match_family(name: str) -> str | None:
    for key, kw in JUGGLER_FAMILY_MATCHERS:
        if kw in name:
            return key
    return None


def jug_posterior_p56(df: pd.DataFrame) -> pd.Series:
    """一様事前・BB/RB二項尤度（組合せ項は設定間で相殺）で P(設定>=5) を返す"""
    out = np.full(len(df), np.nan)
    for fam, grp in df.groupby("family"):
        specs = JUGGLER_FAMILY_SPECS[fam]["settings"]
        n = grp["games_normalized"].to_numpy(dtype=float)
        bb = grp["bb_count"].to_numpy(dtype=float)
        rb = grp["rb_count"].to_numpy(dtype=float)
        logliks = []
        for s in range(1, 7):
            pb = specs[s]["bb_probability"]
            pr = specs[s]["rb_probability"]
            ll = bb * np.log(pb) + (n - bb) * np.log1p(-pb) + rb * np.log(pr) + (n - rb) * np.log1p(-pr)
            logliks.append(ll)
        ll = np.vstack(logliks)  # (6, m)
        ll -= ll.max(axis=0, keepdims=True)
        post = np.exp(ll)
        post /= post.sum(axis=0, keepdims=True)
        out[df.index.get_indexer(grp.index)] = post[4] + post[5]
    return pd.Series(out, index=df.index, name="p56")


def load_hall(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = sqlite3.connect(path)
    df = pd.read_sql_query(
        """
        select date, machine_name, machine_number,
               games_normalized, diff_coins_normalized, bb_count, rb_count
        from machine_detailed_results
        where games_normalized > 0
        """,
        con,
    )
    master = pd.read_sql_query(
        "select machine_name_normalized, jug_flag, hana_flag, bt_flag from machine_master",
        con,
    )
    con.close()
    return df, master


def main() -> None:
    for hall, path in HALLS.items():
        df, master = load_hall(path)
        df["dd"] = df["date"].str[6:8].astype(int)
        df = df.merge(master, left_on="machine_name", right_on="machine_name_normalized", how="left")
        unmatched = df["jug_flag"].isna().mean()

        n_days = df["date"].nunique()
        print(f"\n{'=' * 70}\n[{hall}] 営業日数={n_days} master未マッチ率={unmatched:.1%}")

        # --- Aタイプ(ジャグ)トラック ---
        jug = df[df["machine_name"].str.contains("ジャグラー", na=False)].copy()
        jug["family"] = jug["machine_name"].map(match_family)
        jug = jug.dropna(subset=["family"])
        jug_hi = jug[jug["games_normalized"] >= MIN_GAMES_JUG].copy()
        if len(jug_hi):
            jug_hi["p56"] = jug_posterior_p56(jug_hi)
            jug_hi["is_high"] = jug_hi["p56"] >= P56_HIGH
            daily = jug_hi.groupby("date").agg(
                n_eval=("is_high", "size"), n_high=("is_high", "sum"), dd=("dd", "first")
            )
            n_jug_daily = jug.groupby("date")["machine_number"].size().mean()
            print(
                f"[ジャグ] 設置台/日={n_jug_daily:.0f} "
                f"評価対象(>={MIN_GAMES_JUG}G)/日={daily['n_eval'].mean():.1f} "
                f"高設定判定(P56>={P56_HIGH})/日 平均={daily['n_high'].mean():.2f}"
            )
            zero_share = (daily["n_high"] == 0).mean()
            print(f"[ジャグ] 高設定0台の日の割合={zero_share:.1%}  machine-day率={jug_hi['is_high'].mean():.2%}")
            by_dd = daily.groupby("dd")["n_high"].mean().round(2)
            print("[ジャグ] DD別 平均高設定台数:")
            print("  " + "  ".join(f"{d:02d}:{v}" for d, v in by_dd.items()))
            if hall == "みとや":
                ev = daily["dd"].isin(MITOYA_EVENT_DDS)
                print(
                    f"[ジャグ][みとや] イベントDD平均={daily.loc[ev, 'n_high'].mean():.2f} "
                    f"非イベント平均={daily.loc[~ev, 'n_high'].mean():.2f} "
                    f"非イベントで0台の日={(daily.loc[~ev, 'n_high'] == 0).mean():.1%}"
                )
        else:
            print("[ジャグ] 評価対象なし")

        # --- ATトラック（bt_flag=1） ---
        at = df[(df["bt_flag"] == 1)].copy()
        at["payout"] = 100.0 + at["diff_coins_normalized"] / (at["games_normalized"] * 3.0) * 100.0
        at_hi = at[at["games_normalized"] >= MIN_GAMES_AT].copy()
        if len(at_hi):
            at_hi["is_high"] = at_hi["payout"] >= AT_PAYOUT_HIGH
            daily_at = at_hi.groupby("date").agg(n_eval=("is_high", "size"), n_high=("is_high", "sum"))
            all_dates = pd.Index(sorted(df["date"].unique()), name="date")
            daily_at = daily_at.reindex(all_dates)
            daily_at["n_high"] = daily_at["n_high"].fillna(0)
            daily_at["dd"] = all_dates.str[6:8].astype(int)
            n_at_daily = at.groupby("date")["machine_number"].size().mean()
            print(
                f"[AT] 設置台/日={n_at_daily:.0f} "
                f"評価対象(>={MIN_GAMES_AT}G)/日={daily_at['n_eval'].mean():.1f} "
                f"高設定プロキシ(機械割>={AT_PAYOUT_HIGH}%)/日 平均={daily_at['n_high'].mean():.2f}"
            )
            print(
                f"[AT] 高設定0台の日の割合={(daily_at['n_high'] == 0).mean():.1%}  "
                f"machine-day率={at_hi['is_high'].mean():.2%}"
            )
            by_dd_at = daily_at.groupby("dd")["n_high"].mean().round(2)
            print("[AT] DD別 平均高設定プロキシ台数:")
            print("  " + "  ".join(f"{d:02d}:{v}" for d, v in by_dd_at.items()))
        else:
            print("[AT] 評価対象なし")


if __name__ == "__main__":
    main()
