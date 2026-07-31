"""全ホールの台別・直近N日カード。台選びの一次スクリーニング用。

実行:
    venv\\Scripts\\python.exe -m eda.machine_cards
    venv\\Scripts\\python.exe -m eda.machine_cards --asof 20260727 --days 30 --show 蒲田7 --top 10

設計上の約束:
    - 窓は「基準日を含まない過去N暦日の閉区間 [asof-N, asof-1]」。営業日ではなく暦日。
      休業日は行が存在しないだけ。asof 省略時は各DBの max(date)+1日 とみなす
      （＝最新営業日までを窓に含める）。
    - 主順位指標は mean_diff（枚）。payout_w は低稼働台に敏感なので副指標として併記する。
    - last7 は「直近7暦日内に存在する行」。欠損日は出さない（休業か未稼働かを区別しない）。
    - 台番号の中身は窓内で入れ替わりうる（例: 蒲田7の台2026 はマギレコ→モンキーターンV→
      カバネリと3回変わっている）。n_machine_names >= 2 の台は machine_name_history を見ること。
    - 蒲田7の鉄台2026 は除外しない。除外必須なのは末尾・角番シグナルの「検定」であって
      台選びではない（kamata7_theory.md §8.1）。混同防止のため is_iron_machine 列で明示する。
    - games による足切りはしない（設定シグナルの測定に使ってはならない — CLAUDE.md）。
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from eda.briefing_common import (
    all_halls,
    hall_db_path,
    iron_machines,
    load_hall_frame,
    payout_w,
    use_utf8_stdout,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "eda" / "results" / "briefing"
OUT_PATH = OUT_DIR / "machine_cards.csv"


def _latest_date(hall: str) -> str:
    conn = sqlite3.connect(hall_db_path(hall))
    try:
        return conn.execute("select max(date) from machine_detailed_results").fetchone()[0]
    finally:
        conn.close()


def _window(asof: str, days: int) -> tuple[str, str]:
    """[asof-days, asof-1] の閉区間を返す。"""
    end = datetime.strptime(asof, "%Y%m%d") - timedelta(days=1)
    start = datetime.strptime(asof, "%Y%m%d") - timedelta(days=days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _card(group: pd.DataFrame) -> pd.Series:
    s = group.sort_values("date")
    names = list(dict.fromkeys(s["machine_name"]))
    last7_from = (datetime.strptime(s["date"].max(), "%Y%m%d") - timedelta(days=6)).strftime("%Y%m%d")
    recent = s[s["date"] >= last7_from]
    return pd.Series(
        {
            "machine_name": names[-1],
            "n_machine_names": len(names),
            "machine_name_history": "→".join(names),
            "category": s["category"].iloc[-1],
            "n_days": len(s),
            "mean_games": s["games"].mean(),
            "mean_diff": s["diff"].mean(),
            "payout_w": payout_w(s),
            "plus_day_rate": (s["diff"] > 0).mean(),
            "last7": " ".join(f"{r.date[4:]}:{r.diff:+.0f}({r.games:.0f}G)" for r in recent.itertuples()),
        }
    )


def build(halls: list[str] | None = None, *, asof: str | None = None, days: int = 30) -> pd.DataFrame:
    frames = []
    for hall in halls or all_halls():
        hall_asof = asof or (datetime.strptime(_latest_date(hall), "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        start, end = _window(hall_asof, days)
        df = load_hall_frame(hall, date_from=start, date_to=end, drop_special_days=False)
        if df.empty:
            continue
        cards = df.groupby(["hall", "machine_number"]).apply(_card, include_groups=False).reset_index()
        cards["asof"] = hall_asof
        cards["window_from"], cards["window_to"] = start, end
        cards["is_iron_machine"] = cards["machine_number"].isin(iron_machines(hall))
        cards["rank_in_hall"] = cards["mean_diff"].rank(ascending=False, method="min").astype(int)
        cards["rank_in_hall_category"] = (
            cards.groupby("category")["mean_diff"].rank(ascending=False, method="min").astype(int)
        )
        frames.append(cards)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["hall", "rank_in_hall"]).reset_index(drop=True)


def main() -> None:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(description="台別 直近N日カード")
    ap.add_argument("--asof", default=None, help="YYYYMMDD。省略時は各DBの最新営業日+1")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--show", default=None, help="このホールの上位を表示")
    ap.add_argument("--category", default=None, help="--show と併用してカテゴリで絞る")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    out = build(asof=args.asof, days=args.days)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"書き出し: {OUT_PATH}  ({len(out)} 台 / {out['hall'].nunique()} ホール)")
    multi = int((out["n_machine_names"] >= 2).sum())
    print(f"窓内で機種が入れ替わった台: {multi} 件（machine_name_history 列を確認）")

    if args.show:
        sub = out[out["hall"] == args.show]
        if args.category:
            sub = sub[sub["category"] == args.category]
        cols = [
            "machine_number",
            "machine_name",
            "category",
            "n_days",
            "mean_games",
            "mean_diff",
            "payout_w",
            "plus_day_rate",
            "is_iron_machine",
        ]
        title = f"\n### {args.show}" + (f" / {args.category}" if args.category else "") + f" 上位{args.top}"
        print(title)
        print(sub.head(args.top)[cols].to_string(index=False, float_format=lambda x: f"{x:9.2f}"))


if __name__ == "__main__":
    main()
