"""ホール×年月×カテゴリ の games加重機械割マトリクス。

用途は「相対水準の把握」であって、ホール横断の共通法則探索ではない
（各ホール独自戦略が前提 — feedback_no_cross_hall_pooling）。

実行:
    venv\\Scripts\\python.exe -m eda.hall_monthly_matrix
    venv\\Scripts\\python.exe -m eda.hall_monthly_matrix --date-from 20260101 --show みとや大森町店

設計上の約束:
    - ALL は カテゴリ行の再集計ではなく、台×日の生行から直接集計する（二重計上防止）。
    - n_days は台×日行数ではなく date のユニーク数。ALL でもカテゴリ別 n_days は合計しない。
    - payout_event_dd / payout_normal_dd は DD区分ごとに分母 Σgames*3 を別に持つ。
      日別 payout の単純平均はしない。
    - rel_to_peer は「自ホールを除いた」他ホール同月同カテゴリの等重み平均との差。
      自ホールを含めると大規模ホールほど自己参照が強くなる。
      ホール規模で重み付けると「全ホール平均との差」ではなく「全台平均との差」になるため
      等重みにする。
    - 既定は min_games なし。games による足切りは設定シグナルの測定に使ってはならない
      （CLAUDE.md）。--min-games を指定した場合は filter_note 列に明記する。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from eda.briefing_common import CATEGORIES, all_halls, load_hall_frame, payout_w, use_utf8_stdout

OUT_DIR = Path(__file__).resolve().parents[1] / "eda" / "results" / "briefing"
OUT_PATH = OUT_DIR / "hall_monthly_matrix.csv"

# 他ホール平均（peer_mean）の算出に参加させる最低観測量。これ未満のセルは
# peer から外す（月初だけ数日しか無いホールが平均を引っ張るのを防ぐ）。
PEER_MIN_DAYS = 10


def _cell_stats(frame: pd.DataFrame) -> dict:
    valid = frame[frame["is_valid_games"]]
    ev = frame[frame["is_event_dd"]]
    nm = frame[~frame["is_event_dd"]]
    p_ev, p_nm = payout_w(ev), payout_w(nm)
    return {
        "n_days": frame["date"].nunique(),
        "n_machine_days": len(frame),
        "n_zero_games": int((~frame["is_valid_games"]).sum()),
        "total_games": int(valid["games"].sum()),
        "payout_w": payout_w(frame),
        "payout_event_dd": p_ev,
        "payout_normal_dd": p_nm,
        "event_gap": p_ev - p_nm,
        "n_event_days": ev["date"].nunique(),
        "first_date": frame["date"].min(),
        "last_date": frame["date"].max(),
    }


def build(
    halls: list[str] | None = None,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    min_games: int | None = None,
) -> pd.DataFrame:
    halls = halls or all_halls()
    rows = []
    for hall in halls:
        df = load_hall_frame(hall, date_from=date_from, date_to=date_to, min_games=min_games)
        if df.empty:
            continue
        hall_label = df["hall"].iloc[0]
        for ym, month in df.groupby("year_month"):
            # ALL は生行から直接（カテゴリ行の合計ではない）
            rows.append({"hall": hall_label, "year_month": ym, "category": "ALL", **_cell_stats(month)})
            for cat, cell in month.groupby("category"):
                rows.append({"hall": hall_label, "year_month": ym, "category": cat, **_cell_stats(cell)})

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # rel_to_peer: 自ホールを除いた他ホールの等重み平均との差。
    # groupby.apply は pandas 3.0 でグルーピング列を落とすため、merge で組む。
    out["_eligible"] = (out["n_days"] >= PEER_MIN_DAYS) & out["payout_w"].notna()
    el = out[out["_eligible"]]
    agg = el.groupby(["year_month", "category"])["payout_w"].agg(_sum="sum", _n="count").reset_index()
    out = out.merge(agg, on=["year_month", "category"], how="left")
    out[["_sum", "_n"]] = out[["_sum", "_n"]].fillna(0)
    # 自分が peer 適格なら自分を除く。不適格なら peer 全体をそのまま使う。
    out["peer_n_halls"] = (out["_n"] - out["_eligible"].astype(int)).astype(int)
    peer_sum = out["_sum"] - out["payout_w"].where(out["_eligible"], 0).fillna(0)
    out["peer_mean"] = (peer_sum / out["peer_n_halls"]).where(out["peer_n_halls"] > 0)
    out["rel_to_peer"] = out["payout_w"] - out["peer_mean"]
    out = out.drop(columns=["_eligible", "_sum", "_n"])
    out["filter_note"] = (
        "min_games=None (足切りなし)"
        if min_games is None
        else f"min_games>={min_games} 高稼働日に条件づけた率。設定シグナルの推論には使えない"
    )
    order = ["ALL", *CATEGORIES, "UNKNOWN"]
    out["_o"] = out["category"].map({c: i for i, c in enumerate(order)}).fillna(99)
    return out.sort_values(["hall", "year_month", "_o"]).drop(columns="_o").reset_index(drop=True)


def main() -> None:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(description="ホール×年月×カテゴリ 機械割マトリクス")
    ap.add_argument("--date-from", default="20250101")
    ap.add_argument("--date-to", default=None)
    ap.add_argument("--min-games", type=int, default=None)
    ap.add_argument("--show", default=None, help="このホールの ALL/JUG/AT一般 を標準出力に表示")
    args = ap.parse_args()

    out = build(date_from=args.date_from, date_to=args.date_to, min_games=args.min_games)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"書き出し: {OUT_PATH}  ({len(out)} 行 / {out['hall'].nunique()} ホール)")
    print(f"注釈: {out['filter_note'].iloc[0]}")

    if args.show:
        sub = out[(out["hall"] == args.show) & out["category"].isin(["ALL", "JUG", "AT一般"])]
        cols = ["year_month", "category", "n_days", "payout_w", "event_gap", "n_event_days", "rel_to_peer"]
        print(f"\n### {args.show}")
        print(sub[cols].to_string(index=False, float_format=lambda x: f"{x:8.2f}"))


if __name__ == "__main__":
    main()
