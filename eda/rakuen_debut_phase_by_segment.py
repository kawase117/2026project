from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dashboard.utils.theory_engine import load_hall_config, load_theory_frame  # noqa: E402
from eda.core import compute_debut_features  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = BASE_DIR / "db" / "楽園蒲田店.db"
OUT_DIR = BASE_DIR / "eda" / "results" / "rakuen_debut_phase_by_segment"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HALL_KEY = "rakuen"
MIN_GAMES = 2000
PHASE_ORDER = ["1-14日", "15-60日", "61-180日", "181日+"]
NON_NEW_PHASES = ["15-60日", "61-180日", "181日+"]
SEGMENT_ORDER: list[str] | None = None


def _fmt(value: object, digits: int = 1) -> str:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return ""
        return f"{float(value):.{digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if pd.isna(value):
        return ""
    return str(value)


def _table_to_markdown(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 1) -> str:
    work = frame.copy()
    if columns is not None:
        work = work.loc[:, columns]
    if work.empty:
        return "No rows."
    headers = [str(col) for col in work.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(_fmt(row[col], digits=float_digits) for col in work.columns) + " |")
    return "\n".join(lines)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _load_segment_order() -> list[str]:
    config = load_hall_config(HALL_KEY)
    order = config.get("segment_scheme", {}).get("order", [])
    return [str(value) for value in order]


def get_segment_order() -> list[str]:
    global SEGMENT_ORDER
    if SEGMENT_ORDER is None:
        SEGMENT_ORDER = _load_segment_order()
    return SEGMENT_ORDER


def load_base() -> pd.DataFrame:
    frame = load_theory_frame(DB_PATH)
    if frame.empty:
        raise ValueError(f"failed to load theory frame from {DB_PATH}")

    work = compute_debut_features(frame, db_start_grace_days=0)
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["segment"] = work["segment"].astype("string")
    work = work.loc[work["games_normalized"].ge(MIN_GAMES)].copy()
    work = work.loc[work["segment"].isin(get_segment_order())].copy()
    work = work.loc[~work["pre_existing"].fillna(False)].copy()
    work["plus"] = (work["diff_coins_normalized"] > 0).astype(int)
    work["days_since_debut"] = pd.to_numeric(work["days_since_debut"], errors="coerce")
    work = work.dropna(subset=["days_since_debut", "segment", "diff_coins_normalized", "plus"]).copy()
    return work.reset_index(drop=True)


def add_debut_phase(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["debut_phase"] = pd.cut(
        work["days_since_debut"],
        bins=[-0.5, 14, 60, 180, float("inf")],
        labels=PHASE_ORDER,
        include_lowest=True,
        right=True,
    )
    work["debut_phase"] = pd.Categorical(work["debut_phase"], categories=PHASE_ORDER, ordered=True)
    return work


def summarize_segment_phase(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = add_debut_phase(frame)
    segment_totals = (
        work.groupby("segment", observed=True)
        .agg(
            segment_avg_diff=("diff_coins_normalized", "mean"),
            segment_hit_rate=("plus", "mean"),
            segment_n=("plus", "size"),
            segment_machine_names=("machine_name", "nunique"),
        )
        .reset_index()
    )
    segment_totals["segment_hit_rate"] = segment_totals["segment_hit_rate"] * 100
    segment_totals = segment_totals.set_index("segment").reindex(get_segment_order()).reset_index()
    segment_totals["segment_n"] = segment_totals["segment_n"].fillna(0).astype(int)
    segment_totals["segment_machine_names"] = segment_totals["segment_machine_names"].fillna(0).astype(int)

    phase_summary = (
        work.groupby(["segment", "debut_phase"], observed=True)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            hit_rate=("plus", "mean"),
            n=("plus", "size"),
            n_machine_names=("machine_name", "nunique"),
        )
        .reset_index()
    )
    phase_summary["hit_rate"] = phase_summary["hit_rate"] * 100
    phase_summary["debut_phase"] = pd.Categorical(phase_summary["debut_phase"], categories=PHASE_ORDER, ordered=True)
    phase_summary = phase_summary.merge(segment_totals, on="segment", how="left")
    full_index = pd.MultiIndex.from_product([get_segment_order(), PHASE_ORDER], names=["segment", "debut_phase"])
    phase_summary = phase_summary.set_index(["segment", "debut_phase"]).reindex(full_index).reset_index()
    phase_summary["n"] = phase_summary["n"].fillna(0).astype(int)
    phase_summary["n_machine_names"] = phase_summary["n_machine_names"].fillna(0).astype(int)
    phase_summary["excess_diff"] = phase_summary["avg_diff"] - phase_summary["segment_avg_diff"]
    phase_summary["excess_hit_pp"] = phase_summary["hit_rate"] - phase_summary["segment_hit_rate"]

    phase_summary["segment"] = pd.Categorical(phase_summary["segment"], categories=get_segment_order(), ordered=True)
    phase_summary = phase_summary.sort_values(["segment", "debut_phase"]).reset_index(drop=True)
    segment_totals["segment"] = pd.Categorical(segment_totals["segment"], categories=get_segment_order(), ordered=True)
    segment_totals = segment_totals.sort_values("segment").reset_index(drop=True)
    return phase_summary, segment_totals


def choose_recommendation(group: pd.DataFrame) -> pd.Series:
    non_new = group[group["debut_phase"].isin(NON_NEW_PHASES) & group["n"].gt(0)].copy()
    if non_new.empty:
        return pd.Series({"recommended_phase": "N/A", "recommendation_reason": "non-new-phase data missing"})
    best = non_new.sort_values(["excess_diff", "excess_hit_pp", "n"], ascending=[False, False, False]).iloc[0]
    if best["excess_diff"] > 0:
        reason = "excess_diffが最も大きく、相対的に優位"
    else:
        reason = "全非新台フェーズがマイナスだが、相対的にはこのフェーズが最良"
    return pd.Series({"recommended_phase": str(best["debut_phase"]), "recommendation_reason": reason})


def build_report(phase_summary: pd.DataFrame, segment_totals: pd.DataFrame) -> str:
    lines: list[str] = []
    lines.append("# 楽園蒲田店 debut_phase by segment report")
    lines.append("")
    lines.append("## 1. 手法概要")
    lines.append(f"- DB: `{DB_PATH}`")
    lines.append(f"- フィルタ: `games_normalized >= {MIN_GAMES}`")
    lines.append(
        "- 導入日数は `eda.core.compute_debut_features()` の `days_since_debut` を再利用し、`pre_existing=True` は除外した"
    )
    lines.append("- フェーズ定義: `1-14日 / 15-60日 / 61-180日 / 181日+`")
    lines.append("- セグメント定義: `dashboard/config/hall_configs/rakuen.yaml` の `segment_scheme` を使用")
    lines.append("- `excess_diff` / `excess_hit_pp` は各セグメント内の全非pre-existing台平均との差分")
    lines.append("- `1-14日` は新台バイアスが混ざりやすいので、推奨判定では別扱いにした")
    lines.append("")

    lines.append("## 2. セグメント別のフェーズ別結果")
    table = phase_summary[
        [
            "segment",
            "debut_phase",
            "n",
            "n_machine_names",
            "avg_diff",
            "segment_avg_diff",
            "excess_diff",
            "hit_rate",
            "segment_hit_rate",
            "excess_hit_pp",
        ]
    ].copy()
    lines.append(_table_to_markdown(table, float_digits=1))
    lines.append("")

    lines.append("## 3. 61-180日プラス転換は全セグメントで成立するか")
    check = (
        phase_summary.loc[phase_summary["debut_phase"] == "61-180日", ["segment", "n", "excess_diff", "excess_hit_pp"]]
        .merge(segment_totals[["segment", "segment_avg_diff", "segment_hit_rate"]], on="segment", how="left")
        .copy()
    )
    check["diff_plus"] = check["excess_diff"] > 0
    check["hit_plus"] = check["excess_hit_pp"] > 0
    check["both_plus"] = check["diff_plus"] & check["hit_plus"]
    lines.append(_table_to_markdown(check, float_digits=1))
    lines.append("")
    lines.append(
        f"- 61-180日で `excess_diff > 0` かつ `excess_hit_pp > 0` を同時に満たすセグメント数: {int(check['both_plus'].sum())}/{len(check)}"
    )
    lines.append("")

    lines.append("## 4. 本館1F_Nの経過日数効果")
    honkan1f = phase_summary[phase_summary["segment"] == "本館1F_N"].copy()
    lines.append(
        _table_to_markdown(
            honkan1f[
                [
                    "segment",
                    "debut_phase",
                    "n",
                    "avg_diff",
                    "segment_avg_diff",
                    "excess_diff",
                    "hit_rate",
                    "segment_hit_rate",
                    "excess_hit_pp",
                ]
            ],
            float_digits=1,
        )
    )
    lines.append("")
    if not honkan1f.empty:
        best_phase = (
            honkan1f.loc[honkan1f["debut_phase"].isin(NON_NEW_PHASES)]
            .sort_values(["excess_diff", "excess_hit_pp", "n"], ascending=[False, False, False])
            .iloc[0]
        )
        lines.append(
            f"- 本館1F_N の非新台フェーズでは `{best_phase['debut_phase']}` が相対最良。"
            f" ただし `segment_avg_diff` 自体が {best_phase['segment_avg_diff']:.1f} 円/台 と強くマイナスなら、"
            "「優遇」より「被害の相対縮小」と読むのが安全。"
        )
        lines.append(
            f"- なお、本館1F_N は絶対値では全観測フェーズがマイナスだが、`15-60日` と `61-180日` は"
            " segment 平均を上回るため、"
            "「経過日数に関わらず常にマイナス」とまでは言えない。"
        )
    lines.append("")

    lines.append("## 5. セグメント別推奨フェーズ")
    rec_rows = []
    for segment in get_segment_order():
        group = phase_summary[phase_summary["segment"] == segment].copy()
        row = choose_recommendation(group)
        row["segment"] = segment
        rec_rows.append(row)
    rec = pd.DataFrame(rec_rows).merge(segment_totals, on="segment", how="left")
    lines.append(
        _table_to_markdown(
            rec[
                [
                    "segment",
                    "recommended_phase",
                    "recommendation_reason",
                    "segment_avg_diff",
                    "segment_hit_rate",
                ]
            ],
            float_digits=1,
        )
    )
    lines.append("")

    lines.append("## 6. 総括（全体傾向とセグメント固有の違い）")
    globals_61_180 = phase_summary[phase_summary["debut_phase"] == "61-180日"].copy()
    positive_segments = globals_61_180[(globals_61_180["excess_diff"] > 0) & (globals_61_180["excess_hit_pp"] > 0)]
    lines.append(
        f"- 61-180日が両指標でプラスのセグメントは {len(positive_segments)}/{len(globals_61_180)}。"
        " 全体結論はセグメントへ完全には一般化できず、少なくとも一部で崩れる。"
    )
    honkan1f_61_180 = honkan1f[honkan1f["debut_phase"] == "61-180日"]
    if not honkan1f_61_180.empty:
        row = honkan1f_61_180.iloc[0]
        lines.append(
            f"- 本館1F_N の 61-180日 は excess_diff={row['excess_diff']:.1f} 円/台, "
            f"excess_hit_pp={row['excess_hit_pp']:.1f}pp。"
            " このセグメントは 61-180日 でも segment 平均を上回るので、"
            "常時マイナスではなく局所的な改善がある。"
        )
    lines.append("- 新台期の 1-14日 は混雑/話題化/導入バイアスが入りやすく、推奨帯の決定には直接使わない。")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    base = load_base()
    print("rows:", len(base))
    print("date range:", base["date"].min(), "-", base["date"].max())
    phase_summary, segment_totals = summarize_segment_phase(base)
    phase_summary.to_csv(OUT_DIR / "debut_phase_by_segment.csv", index=False, encoding="utf-8-sig")
    report = build_report(phase_summary, segment_totals)
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")
    print(phase_summary.to_string(index=False))
    print(f"saved: {OUT_DIR / 'debut_phase_by_segment.csv'}")
    print(f"saved: {OUT_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
