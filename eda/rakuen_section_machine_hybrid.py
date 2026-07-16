from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.section_lateral_expansion import (  # noqa: E402
    HALL_CONFIGS,
    HallConfig,
    _load_hall_frame,
    _markdown_table,
    _write_csv,
    is_event_day,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_section_machine_hybrid"
DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_GAMES = 2500
DEFAULT_EVAL_DAYS = 120
DEFAULT_SECTION_TOP_K = 3
DEFAULT_MACHINE_TOP_KS = (3, 5, 10)
MIN_SAME_TYPE_DATES = 10
WINDOW_EXPAND_STEP = 30

EVENT_SECTION_POOL = ("1209-1216",)
NONEVENT_SECTION_POOL = ("3117-3120",)

SECTION_KEY_COLUMNS = ["section", "floor", "section_min", "section_max", "section_size"]
MACHINE_KEY_COLUMNS = ["section", "machine_number", "machine_name"]


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    scope: str
    top_sections: int
    top_machines_per_section: int | None


def _parse_top_ks(raw: str | tuple[int, ...]) -> tuple[int, ...]:
    if isinstance(raw, tuple):
        return tuple(int(value) for value in raw)
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not values:
        raise ValueError("top_machine_ks cannot be empty")
    parsed = tuple(int(value) for value in values)
    if any(value <= 0 for value in parsed):
        raise ValueError("top_machine_ks must contain positive integers")
    return parsed


def _format_value(value: object, *, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _normalize_eval_dates(frame: pd.DataFrame, *, eval_days: int) -> pd.Index:
    unique_dates = pd.Index(sorted(pd.Timestamp(value).normalize() for value in frame["date_dt"].dropna().unique()))
    if len(unique_dates) <= int(eval_days):
        return unique_dates
    return unique_dates[-int(eval_days) :]


def _event_label(target_dt: pd.Timestamp, cfg: HallConfig) -> str:
    return "event" if is_event_day(target_dt, cfg) else "nonevent"


def _build_training_windows(
    frame: pd.DataFrame,
    target_dt: pd.Timestamp,
    *,
    cfg: HallConfig,
    event_type: str,
    window_days: int,
) -> tuple[int, pd.DataFrame, pd.DataFrame]:
    first_date = pd.Timestamp(frame["date_dt"].min()).normalize()
    effective_window = int(window_days)
    history = pd.DataFrame()
    split_history = pd.DataFrame()

    while True:
        window_start = target_dt - pd.Timedelta(days=effective_window)
        history = frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()
        if history.empty:
            if window_start <= first_date:
                return effective_window, history, split_history
            effective_window += WINDOW_EXPAND_STEP
            continue

        history["hit_flag"] = pd.to_numeric(history["diff_coins_normalized"], errors="coerce").gt(0).astype(int)
        event_mask = [is_event_day(pd.Timestamp(value), cfg) for value in history["date_dt"]]
        if event_type == "event":
            split_history = history.loc[event_mask].copy()
        else:
            split_history = history.loc[[not flag for flag in event_mask]].copy()

        if split_history["date_dt"].nunique() >= MIN_SAME_TYPE_DATES or window_start <= first_date:
            return effective_window, history, split_history
        effective_window += WINDOW_EXPAND_STEP


def _section_scores(train: pd.DataFrame) -> pd.DataFrame:
    if train.empty:
        return pd.DataFrame(columns=SECTION_KEY_COLUMNS + ["section_score", "section_train_rows", "section_train_diff"])
    scores = (
        train.groupby(SECTION_KEY_COLUMNS, as_index=False)
        .agg(
            section_score=("hit_flag", "mean"),
            section_train_rows=("machine_number", "size"),
            section_train_diff=("diff_coins_normalized", "mean"),
        )
        .copy()
    )
    scores["section_score"] = pd.to_numeric(scores["section_score"], errors="coerce")
    scores["section_train_rows"] = pd.to_numeric(scores["section_train_rows"], errors="coerce")
    scores["section_train_diff"] = pd.to_numeric(scores["section_train_diff"], errors="coerce")
    return scores


def _machine_scores(train: pd.DataFrame) -> pd.DataFrame:
    if train.empty:
        return pd.DataFrame(columns=MACHINE_KEY_COLUMNS + ["machine_score", "machine_train_rows", "machine_train_diff"])
    scores = (
        train.groupby(MACHINE_KEY_COLUMNS, as_index=False)
        .agg(
            machine_score=("hit_flag", "mean"),
            machine_train_rows=("machine_number", "size"),
            machine_train_diff=("diff_coins_normalized", "mean"),
        )
        .copy()
    )
    scores["machine_score"] = pd.to_numeric(scores["machine_score"], errors="coerce")
    scores["machine_train_rows"] = pd.to_numeric(scores["machine_train_rows"], errors="coerce")
    scores["machine_train_diff"] = pd.to_numeric(scores["machine_train_diff"], errors="coerce")
    return scores


def _actual_section_frame(actual: pd.DataFrame) -> pd.DataFrame:
    if actual.empty:
        return pd.DataFrame(columns=SECTION_KEY_COLUMNS + ["actual_rows", "actual_hit_rate", "actual_avg_diff"])
    actual_sections = (
        actual.groupby(SECTION_KEY_COLUMNS, as_index=False)
        .agg(
            actual_rows=("machine_number", "size"),
            actual_hit_rate=("hit_flag", "mean"),
            actual_avg_diff=("diff_coins_normalized", "mean"),
        )
        .copy()
    )
    actual_sections["actual_hit_rate"] = pd.to_numeric(actual_sections["actual_hit_rate"], errors="coerce")
    actual_sections["actual_avg_diff"] = pd.to_numeric(actual_sections["actual_avg_diff"], errors="coerce")
    return actual_sections


def _rank_sections(section_eval: pd.DataFrame, *, pool: tuple[str, ...] | None, top_sections: int) -> pd.DataFrame:
    work = section_eval.copy()
    if pool is not None:
        work = work[work["section"].isin(pool)].copy()
    if work.empty:
        return work
    work = work.sort_values(
        ["section_score", "section_train_rows", "section_train_diff", "section_min", "section", "floor"],
        ascending=[False, False, False, True, True, True],
        na_position="last",
        kind="mergesort",
    ).reset_index(drop=True)
    return work.head(int(top_sections)).copy()


def _select_machine_rows(
    actual: pd.DataFrame,
    machine_scores: pd.DataFrame,
    selected_sections: pd.DataFrame,
    *,
    top_machines_per_section: int | None,
) -> pd.DataFrame:
    if selected_sections.empty or actual.empty:
        return pd.DataFrame()

    selected = actual[actual["section"].isin(selected_sections["section"].astype(str))].copy()
    if selected.empty:
        return pd.DataFrame()

    selected = selected.merge(machine_scores, on=MACHINE_KEY_COLUMNS, how="left", validate="m:1")
    selected["machine_score"] = pd.to_numeric(selected["machine_score"], errors="coerce")
    selected["machine_train_rows"] = pd.to_numeric(selected["machine_train_rows"], errors="coerce")
    selected["machine_train_diff"] = pd.to_numeric(selected["machine_train_diff"], errors="coerce")

    selected = selected.sort_values(
        ["section", "machine_score", "machine_train_rows", "machine_train_diff", "machine_number"],
        ascending=[True, False, False, False, True],
        na_position="last",
        kind="mergesort",
    ).copy()
    selected["machine_rank_in_section"] = selected.groupby("section", dropna=False).cumcount() + 1

    if top_machines_per_section is not None:
        selected = selected[selected["machine_rank_in_section"].le(int(top_machines_per_section))].copy()

    return selected.reset_index(drop=True)


def _daily_metrics(
    actual: pd.DataFrame,
    selected_rows: pd.DataFrame,
    *,
    date: pd.Timestamp,
    day_type: str,
    strategy: StrategyConfig,
    selected_sections: pd.DataFrame,
) -> dict[str, object] | None:
    if actual.empty or selected_rows.empty:
        return None

    actual_hit_rate = float(actual["hit_flag"].mean())
    actual_avg_diff = float(actual["diff_coins_normalized"].mean())
    selected_hit_rate = float(selected_rows["hit_flag"].mean())
    selected_avg_diff = float(selected_rows["diff_coins_normalized"].mean())
    lift = float(selected_hit_rate / actual_hit_rate) if actual_hit_rate > 0 else float("nan")

    return {
        "date": date.strftime("%Y-%m-%d"),
        "day_type": day_type,
        "strategy": strategy.name,
        "scope": strategy.scope,
        "top_sections": int(strategy.top_sections),
        "top_machines_per_section": int(strategy.top_machines_per_section or 0),
        "n_selected_sections": int(selected_sections["section"].nunique()),
        "n_selected_rows": int(len(selected_rows)),
        "actual_rows": int(len(actual)),
        "actual_hit_rate": actual_hit_rate,
        "actual_avg_diff": actual_avg_diff,
        "selected_hit_rate": selected_hit_rate,
        "selected_avg_diff": selected_avg_diff,
        "lift": lift,
        "diff_excess": float(selected_avg_diff - actual_avg_diff),
    }


def _build_group_concentration(
    events: pd.DataFrame,
    *,
    entity_col: str,
    entity_label_col: str,
    entity_type: str,
) -> pd.DataFrame:
    columns = [
        "day_type",
        "strategy",
        "entity_type",
        "entity",
        "entity_label",
        "selected_days",
        "selection_rate",
        "slot_share",
        "group_top1_entity",
        "group_top1_label",
        "group_top1_share",
        "group_top2_entity",
        "group_top2_label",
        "group_top2_share",
        "scope_selected_hit_rate",
        "entity_hit_rate",
        "hit_rate_delta_pp",
        "scope_selected_avg_diff",
        "entity_avg_diff",
        "avg_diff_delta",
    ]
    if events.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for (day_type, strategy), subset in events.groupby(["day_type", "strategy"], sort=True):
        total_slots = int(len(subset))
        n_days = int(subset["date"].nunique())
        scope_hit_rate = float(subset["hit_flag"].mean()) if total_slots else float("nan")
        scope_avg_diff = float(subset["diff_coins_normalized"].mean()) if total_slots else float("nan")
        counts = (
            subset.groupby([entity_col, entity_label_col], as_index=False)
            .agg(
                selected_days=("date", "nunique"),
                entity_hit_rate=("hit_flag", "mean"),
                entity_avg_diff=("diff_coins_normalized", "mean"),
            )
            .copy()
        )
        counts["selection_rate"] = counts["selected_days"] / max(n_days, 1)
        counts["slot_share"] = counts["selected_days"] / max(total_slots, 1)
        counts = counts.sort_values(
            ["selected_days", "entity_hit_rate", "entity_avg_diff", entity_col],
            ascending=[False, False, False, True],
            kind="mergesort",
        ).reset_index(drop=True)
        top1 = counts.iloc[0]
        top2 = counts.iloc[1] if len(counts) > 1 else None
        for row in counts.itertuples(index=False):
            rows.append(
                {
                    "day_type": day_type,
                    "strategy": strategy,
                    "entity_type": entity_type,
                    "entity": getattr(row, entity_col),
                    "entity_label": getattr(row, entity_label_col),
                    "selected_days": int(row.selected_days),
                    "selection_rate": float(row.selection_rate),
                    "slot_share": float(row.slot_share),
                    "group_top1_entity": getattr(top1, entity_col),
                    "group_top1_label": getattr(top1, entity_label_col),
                    "group_top1_share": float(top1.slot_share),
                    "group_top2_entity": "none" if top2 is None else getattr(top2, entity_col),
                    "group_top2_label": "none" if top2 is None else getattr(top2, entity_label_col),
                    "group_top2_share": 0.0 if top2 is None else float(top2.slot_share),
                    "scope_selected_hit_rate": scope_hit_rate,
                    "entity_hit_rate": float(row.entity_hit_rate),
                    "hit_rate_delta_pp": float((float(row.entity_hit_rate) - scope_hit_rate) * 100.0),
                    "scope_selected_avg_diff": scope_avg_diff,
                    "entity_avg_diff": float(row.entity_avg_diff),
                    "avg_diff_delta": float(float(row.entity_avg_diff) - scope_avg_diff),
                }
            )
    frame = pd.DataFrame(rows, columns=columns)
    return frame.sort_values(
        ["day_type", "strategy", "entity_type", "slot_share", "entity"],
        ascending=[True, True, True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _machine_dependency_summary(machine_events: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "day_type",
        "strategy",
        "selected_slots",
        "unique_machines",
        "top1_machine_number",
        "top1_machine_name",
        "top1_share",
        "top2_machine_number",
        "top2_machine_name",
        "top2_share",
        "top1_selected_days",
        "top2_selected_days",
        "top1_hit_rate",
        "top2_hit_rate",
        "top1_avg_diff",
        "top2_avg_diff",
        "rest_hit_rate",
        "rest_avg_diff",
        "top1_vs_rest_hit_pp",
        "top2_vs_rest_hit_pp",
        "top1_vs_rest_avg_diff",
        "top2_vs_rest_avg_diff",
        "verdict",
    ]
    if machine_events.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for (day_type, strategy), subset in machine_events.groupby(["day_type", "strategy"], sort=True):
        total_slots = int(len(subset))
        counts = (
            subset.groupby(["machine_number", "machine_name"], as_index=False)
            .agg(
                selected_days=("date", "nunique"),
                hit_rate=("hit_flag", "mean"),
                avg_diff=("diff_coins_normalized", "mean"),
            )
            .copy()
        )
        counts = counts.sort_values(
            ["selected_days", "hit_rate", "avg_diff", "machine_number"],
            ascending=[False, False, False, True],
            kind="mergesort",
        ).reset_index(drop=True)
        if counts.empty:
            continue
        top1 = counts.iloc[0]
        top2 = counts.iloc[1] if len(counts) > 1 else None
        top2_selected = counts.head(2)
        rest = counts.iloc[2:].copy()
        rest_hit_rate = float(rest["hit_rate"].mean()) if not rest.empty else float("nan")
        rest_avg_diff = float(rest["avg_diff"].mean()) if not rest.empty else float("nan")
        top1_share = float(top1.selected_days / max(total_slots, 1))
        top2_share = float(top2_selected["selected_days"].sum() / max(total_slots, 1))
        top1_vs_rest_hit_pp = (
            float((float(top1.hit_rate) - rest_hit_rate) * 100.0) if pd.notna(rest_hit_rate) else float("nan")
        )
        top2_vs_rest_hit_pp = (
            float((float(top2_selected["hit_rate"].mean()) - rest_hit_rate) * 100.0)
            if pd.notna(rest_hit_rate)
            else float("nan")
        )
        top1_vs_rest_avg_diff = float(float(top1.avg_diff) - rest_avg_diff) if pd.notna(rest_avg_diff) else float("nan")
        top2_vs_rest_avg_diff = (
            float(float(top2_selected["avg_diff"].mean()) - rest_avg_diff) if pd.notna(rest_avg_diff) else float("nan")
        )
        if top2_share >= 0.50:
            verdict = "strong_dependency"
        elif top1_share >= 0.30:
            verdict = "moderate_dependency"
        else:
            verdict = "spread"
        if (
            pd.notna(top1_vs_rest_avg_diff)
            and top1_vs_rest_avg_diff > 0
            and pd.notna(top2_vs_rest_avg_diff)
            and top2_vs_rest_avg_diff > 0
        ):
            verdict = f"{verdict}_backed"
        elif pd.notna(top1_vs_rest_avg_diff) and pd.notna(top2_vs_rest_avg_diff):
            verdict = f"{verdict}_mixed"

        rows.append(
            {
                "day_type": day_type,
                "strategy": strategy,
                "selected_slots": total_slots,
                "unique_machines": int(len(counts)),
                "top1_machine_number": int(top1.machine_number),
                "top1_machine_name": str(top1.machine_name),
                "top1_share": top1_share,
                "top2_machine_number": "none" if top2 is None else int(top2.machine_number),
                "top2_machine_name": "none" if top2 is None else str(top2.machine_name),
                "top2_share": top2_share,
                "top1_selected_days": int(top1.selected_days),
                "top2_selected_days": 0 if top2 is None else int(top2.selected_days),
                "top1_hit_rate": float(top1.hit_rate),
                "top2_hit_rate": float(top2.hit_rate) if top2 is not None else float("nan"),
                "top1_avg_diff": float(top1.avg_diff),
                "top2_avg_diff": float(top2.avg_diff) if top2 is not None else float("nan"),
                "rest_hit_rate": rest_hit_rate,
                "rest_avg_diff": rest_avg_diff,
                "top1_vs_rest_hit_pp": top1_vs_rest_hit_pp,
                "top2_vs_rest_hit_pp": top2_vs_rest_hit_pp,
                "top1_vs_rest_avg_diff": top1_vs_rest_avg_diff,
                "top2_vs_rest_avg_diff": top2_vs_rest_avg_diff,
                "verdict": verdict,
            }
        )

    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values(["day_type", "strategy"], kind="mergesort")
        .reset_index(drop=True)
    )


def _build_report(
    *,
    db_path: Path,
    frame: pd.DataFrame,
    eval_dates: pd.Index,
    comparison: pd.DataFrame,
    selection_concentration: pd.DataFrame,
    top_machine_dependency: pd.DataFrame,
    strategies: tuple[StrategyConfig, ...],
    window_days: int,
    min_games: int,
) -> str:
    lines: list[str] = []
    lines.append("# 楽園蒲田店 section-machine hybrid walk-forward")
    lines.append("")
    lines.append("## 1. 手法概要")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- 評価期間: `{eval_dates[0].date()}` から `{eval_dates[-1].date()}`")
    lines.append(f"- 評価日数: `{len(eval_dates)}`")
    lines.append(f"- 学習窓: `{window_days}` 日")
    lines.append(f"- フィルタ: `games_normalized >= {min_games}`")
    lines.append(f"- event days: `{sorted(HALL_CONFIGS['rakuen'].event_dds)}`")
    lines.append(f"- strong zorome: `{bool(HALL_CONFIGS['rakuen'].strong_zorome)}`")
    lines.append(
        "- 日タイプごとに直近同種日だけを使って section score / machine score を作り、"
        "all-hall top3 と theory-pool sec_only / sec+mac を比較する。"
    )
    lines.append(
        f"- theory pool: event=`{', '.join(EVENT_SECTION_POOL)}` / nonevent=`{', '.join(NONEVENT_SECTION_POOL)}`"
    )
    lines.append(f"- strategies: `{', '.join(strategy.name for strategy in strategies)}`")
    lines.append("")

    lines.append("## 2. Hybrid絞り込みの効果（sec_only vs sec+mac）")
    if comparison.empty:
        lines.append("No rows.")
    else:
        focus = comparison.loc[
            :,
            [
                "day_type",
                "strategy",
                "n_days",
                "n_selected_rows_mean",
                "actual_hit_rate_mean",
                "selected_hit_rate_mean",
                "lift_mean",
                "actual_avg_diff_mean",
                "selected_avg_diff_mean",
                "diff_excess_mean",
            ],
        ].copy()
        focus["actual_hit_rate_mean"] = focus["actual_hit_rate_mean"].round(4)
        focus["selected_hit_rate_mean"] = focus["selected_hit_rate_mean"].round(4)
        focus["lift_mean"] = focus["lift_mean"].round(4)
        focus["actual_avg_diff_mean"] = focus["actual_avg_diff_mean"].round(1)
        focus["selected_avg_diff_mean"] = focus["selected_avg_diff_mean"].round(1)
        focus["diff_excess_mean"] = focus["diff_excess_mean"].round(1)
        lines.append(_markdown_table(focus, float_digits=4))
    lines.append("")

    lines.append("## 3. 絞りすぎのリスク検証")
    if comparison.empty:
        lines.append("No rows.")
    else:
        risk = comparison.loc[
            comparison["strategy"].astype(str).str.contains("candidate", na=False),
            [
                "day_type",
                "strategy",
                "top_machines_per_section",
                "n_days",
                "selected_hit_rate_mean",
                "lift_mean",
                "diff_excess_mean",
                "n_selected_rows_mean",
            ],
        ].copy()
        risk["selected_hit_rate_mean"] = risk["selected_hit_rate_mean"].round(4)
        risk["lift_mean"] = risk["lift_mean"].round(4)
        risk["diff_excess_mean"] = risk["diff_excess_mean"].round(1)
        lines.append(_markdown_table(risk, float_digits=4))
        lines.append("")
        top_slice = comparison[comparison["strategy"].astype(str).str.contains("candidate", na=False)].copy()
        if not top_slice.empty:
            best_row = top_slice.sort_values(
                ["day_type", "selected_hit_rate_mean", "lift_mean", "diff_excess_mean"],
                ascending=[True, False, False, False],
                kind="mergesort",
            ).iloc[0]
            lines.append(
                f"- 最高の候補は `{best_row['strategy']}` / {best_row['day_type']} で "
                f"lift={best_row['lift_mean']:.3f}, diff_excess={best_row['diff_excess_mean']:.1f}円。"
            )
            lines.append("- もし sec+mac で lift が sec_only を下回るなら、台まで絞りすぎた可能性を優先的に疑う。")
    lines.append("")

    lines.append("## 4. 選択の偏り検証（セクション別・台別集中度）")
    if selection_concentration.empty:
        lines.append("No rows.")
    else:
        section_rows = selection_concentration[selection_concentration["entity_type"].eq("section")].copy()
        machine_rows = selection_concentration[selection_concentration["entity_type"].eq("machine")].copy()
        if not section_rows.empty:
            section_preview = section_rows.head(12).copy()
            section_preview["selection_rate"] = section_preview["selection_rate"].round(4)
            section_preview["slot_share"] = section_preview["slot_share"].round(4)
            section_preview["group_top1_share"] = section_preview["group_top1_share"].round(4)
            section_preview["group_top2_share"] = section_preview["group_top2_share"].round(4)
            section_preview["hit_rate_delta_pp"] = section_preview["hit_rate_delta_pp"].round(1)
            section_preview["avg_diff_delta"] = section_preview["avg_diff_delta"].round(1)
            lines.append("### Section concentration")
            lines.append(
                _markdown_table(
                    section_preview,
                    columns=[
                        "day_type",
                        "strategy",
                        "entity_label",
                        "selected_days",
                        "selection_rate",
                        "slot_share",
                        "group_top1_label",
                        "group_top1_share",
                        "group_top2_label",
                        "group_top2_share",
                        "hit_rate_delta_pp",
                        "avg_diff_delta",
                    ],
                    float_digits=4,
                )
            )
            lines.append("")
        if not machine_rows.empty:
            machine_preview = machine_rows.head(12).copy()
            machine_preview["selection_rate"] = machine_preview["selection_rate"].round(4)
            machine_preview["slot_share"] = machine_preview["slot_share"].round(4)
            machine_preview["group_top1_share"] = machine_preview["group_top1_share"].round(4)
            machine_preview["group_top2_share"] = machine_preview["group_top2_share"].round(4)
            machine_preview["hit_rate_delta_pp"] = machine_preview["hit_rate_delta_pp"].round(1)
            machine_preview["avg_diff_delta"] = machine_preview["avg_diff_delta"].round(1)
            lines.append("### Machine concentration")
            lines.append(
                _markdown_table(
                    machine_preview,
                    columns=[
                        "day_type",
                        "strategy",
                        "entity_label",
                        "selected_days",
                        "selection_rate",
                        "slot_share",
                        "group_top1_label",
                        "group_top1_share",
                        "group_top2_label",
                        "group_top2_share",
                        "hit_rate_delta_pp",
                        "avg_diff_delta",
                    ],
                    float_digits=4,
                )
            )
    lines.append("")

    lines.append("## 5. 台固有性の定量化（top1/top2シェア）")
    if top_machine_dependency.empty:
        lines.append("No rows.")
    else:
        dep_preview = top_machine_dependency.loc[
            :,
            [
                "day_type",
                "strategy",
                "top1_machine_number",
                "top1_machine_name",
                "top1_share",
                "top2_machine_number",
                "top2_machine_name",
                "top2_share",
                "top1_hit_rate",
                "top2_hit_rate",
                "top1_avg_diff",
                "top2_avg_diff",
                "rest_hit_rate",
                "rest_avg_diff",
                "verdict",
            ],
        ].copy()
        dep_preview["top1_share"] = dep_preview["top1_share"].round(4)
        dep_preview["top2_share"] = dep_preview["top2_share"].round(4)
        dep_preview["top1_hit_rate"] = dep_preview["top1_hit_rate"].round(4)
        dep_preview["top2_hit_rate"] = dep_preview["top2_hit_rate"].round(4)
        dep_preview["top1_avg_diff"] = dep_preview["top1_avg_diff"].round(1)
        dep_preview["top2_avg_diff"] = dep_preview["top2_avg_diff"].round(1)
        dep_preview["rest_hit_rate"] = dep_preview["rest_hit_rate"].round(4)
        dep_preview["rest_avg_diff"] = dep_preview["rest_avg_diff"].round(1)
        lines.append(_markdown_table(dep_preview, float_digits=4))
    lines.append("")

    lines.append("## 6. 総括（推奨する絞り込み段階と注意点）")
    if comparison.empty:
        lines.append("No rows.")
    else:
        best = comparison.sort_values(
            ["selected_hit_rate_mean", "lift_mean", "diff_excess_mean"],
            ascending=[False, False, False],
            kind="mergesort",
        ).iloc[0]
        best_name = str(best["strategy"])
        lines.append(
            f"- 総合的な第一候補は `{best_name}`。`selected_hit_rate_mean={best['selected_hit_rate_mean']:.4f}`、"
            f"`lift_mean={best['lift_mean']:.3f}`、`diff_excess_mean={best['diff_excess_mean']:.1f}`円。"
        )
        if not top_machine_dependency.empty:
            backed = top_machine_dependency.sort_values(
                ["top2_share", "top1_share", "top1_vs_rest_avg_diff"],
                ascending=[False, False, False],
                kind="mergesort",
            ).iloc[0]
            lines.append(
                f"- 最も集中した台推薦は `{backed['strategy']}` / `{backed['day_type']}` で "
                f"top1_share={backed['top1_share']:.1%}, top2_share={backed['top2_share']:.1%}, "
                f"verdict={backed['verdict']}。"
            )
        lines.append("- sec+mac で lift が悪化し、かつ top1/top2 の実績差が縮むなら、台までの絞り込みは過剰。")
        lines.append("- 逆に top1/top2 の実績が scope 平均を上回るなら、集中は単なる偏りではなく実力反映とみなせる。")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_hybrid_outputs(
    frame: pd.DataFrame | None = None,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_games: int = DEFAULT_MIN_GAMES,
    eval_days: int = DEFAULT_EVAL_DAYS,
    top_sections: int = DEFAULT_SECTION_TOP_K,
    top_machine_ks: tuple[int, ...] = DEFAULT_MACHINE_TOP_KS,
) -> dict[str, pd.DataFrame]:
    cfg = HALL_CONFIGS["rakuen"]
    if frame is None:
        frame, _coords = _load_hall_frame(cfg, min_games=min_games)

    work = frame.copy()
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["section_min"] = pd.to_numeric(work["section_min"], errors="coerce")
    work["section_max"] = pd.to_numeric(work["section_max"], errors="coerce")
    work["section_size"] = pd.to_numeric(work["section_size"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(
        subset=[
            "date_dt",
            "machine_number",
            "machine_name",
            "section",
            "floor",
            "section_min",
            "section_max",
            "section_size",
            "games_normalized",
            "diff_coins_normalized",
        ]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["section_min"] = work["section_min"].astype(int)
    work["section_max"] = work["section_max"].astype(int)
    work["section_size"] = work["section_size"].astype(int)
    work["hit_flag"] = work["diff_coins_normalized"].gt(0).astype(int)
    work = work.sort_values(["date_dt", "floor", "section_min", "machine_number"]).reset_index(drop=True)

    eval_dates = _normalize_eval_dates(work, eval_days=eval_days)
    strategies = (
        StrategyConfig("all_hall_top3_sec_only", "all_hall", int(top_sections), None),
        StrategyConfig("candidate_sec_only", "candidate", int(top_sections), None),
        StrategyConfig("candidate_sec+mac_top3", "candidate", int(top_sections), 3),
        StrategyConfig("candidate_sec+mac_top5", "candidate", int(top_sections), 5),
        StrategyConfig("candidate_sec+mac_top10", "candidate", int(top_sections), 10),
    )

    daily_rows: list[dict[str, object]] = []
    section_events: list[pd.DataFrame] = []
    machine_events: list[pd.DataFrame] = []

    for target_dt in eval_dates:
        day_type = _event_label(pd.Timestamp(target_dt), cfg)
        _effective_window, history, same_type_history = _build_training_windows(
            work,
            pd.Timestamp(target_dt),
            cfg=cfg,
            event_type=day_type,
            window_days=window_days,
        )
        if history.empty or same_type_history.empty:
            continue

        actual = work.loc[work["date_dt"].eq(target_dt)].copy()
        if actual.empty:
            continue

        section_scores = _section_scores(same_type_history)
        machine_scores = _machine_scores(same_type_history)
        actual_sections = _actual_section_frame(actual)
        section_eval = actual_sections.merge(section_scores, on=SECTION_KEY_COLUMNS, how="left", validate="1:1")
        section_eval["section_score"] = pd.to_numeric(section_eval["section_score"], errors="coerce")
        section_eval["section_train_rows"] = pd.to_numeric(section_eval["section_train_rows"], errors="coerce")
        section_eval["section_train_diff"] = pd.to_numeric(section_eval["section_train_diff"], errors="coerce")
        section_eval = section_eval.sort_values(
            ["section_score", "section_train_rows", "section_train_diff", "section_min", "section", "floor"],
            ascending=[False, False, False, True, True, True],
            na_position="last",
            kind="mergesort",
        ).reset_index(drop=True)

        candidate_pool = EVENT_SECTION_POOL if day_type == "event" else NONEVENT_SECTION_POOL
        for strategy in strategies:
            pool = None if strategy.scope == "all_hall" else candidate_pool
            selected_sections = _rank_sections(section_eval, pool=pool, top_sections=strategy.top_sections)
            if selected_sections.empty:
                continue

            selected_rows = _select_machine_rows(
                actual,
                machine_scores,
                selected_sections,
                top_machines_per_section=strategy.top_machines_per_section,
            )
            if selected_rows.empty:
                continue

            metrics = _daily_metrics(
                actual,
                selected_rows,
                date=pd.Timestamp(target_dt),
                day_type=day_type,
                strategy=strategy,
                selected_sections=selected_sections,
            )
            if metrics is None:
                continue

            metrics["effective_window_days"] = int(_effective_window)
            metrics["candidate_pool"] = "all_hall" if strategy.scope == "all_hall" else ",".join(candidate_pool)
            metrics["selected_section_rank_1"] = (
                "" if selected_sections.empty else str(selected_sections.iloc[0]["section"])
            )
            metrics["selected_section_rank_2"] = (
                "" if len(selected_sections) < 2 else str(selected_sections.iloc[1]["section"])
            )
            metrics["selected_section_rank_3"] = (
                "" if len(selected_sections) < 3 else str(selected_sections.iloc[2]["section"])
            )
            daily_rows.append(metrics)

            sec_rows = selected_rows.loc[
                :,
                [
                    "date_dt",
                    "date",
                    "section",
                    "floor",
                    "section_min",
                    "section_max",
                    "section_size",
                    "machine_number",
                    "machine_name",
                    "hit_flag",
                    "diff_coins_normalized",
                ],
            ].copy()
            sec_rows["date"] = pd.Timestamp(target_dt).strftime("%Y-%m-%d")
            sec_rows["date_dt"] = pd.Timestamp(target_dt)
            sec_rows["day_type"] = day_type
            sec_rows["strategy"] = strategy.name
            sec_rows["entity_type"] = "machine"
            machine_events.append(sec_rows)

            section_rows = selected_sections.loc[
                :,
                [
                    "section",
                    "floor",
                    "section_min",
                    "section_max",
                    "section_size",
                    "section_score",
                    "section_train_rows",
                    "section_train_diff",
                ],
            ].copy()
            section_rows = section_rows.merge(actual_sections, on=SECTION_KEY_COLUMNS, how="left", validate="1:1")
            section_rows["date"] = pd.Timestamp(target_dt).strftime("%Y-%m-%d")
            section_rows["date_dt"] = pd.Timestamp(target_dt)
            section_rows["day_type"] = day_type
            section_rows["strategy"] = strategy.name
            section_rows["entity_type"] = "section"
            section_rows["hit_flag"] = section_rows["actual_hit_rate"]
            section_rows["diff_coins_normalized"] = section_rows["actual_avg_diff"]
            section_rows["entity_label"] = section_rows["section"].astype(str)
            section_events.append(section_rows)

    daily = pd.DataFrame(daily_rows)
    if daily.empty:
        comparison = pd.DataFrame(
            columns=[
                "day_type",
                "strategy",
                "scope",
                "top_sections",
                "top_machines_per_section",
                "n_days",
                "n_selected_rows_mean",
                "actual_hit_rate_mean",
                "selected_hit_rate_mean",
                "lift_mean",
                "actual_avg_diff_mean",
                "selected_avg_diff_mean",
                "diff_excess_mean",
            ]
        )
    else:
        rows: list[dict[str, object]] = []
        for (day_type, strategy), subset in daily.groupby(["day_type", "strategy"], sort=True):
            rows.append(
                {
                    "day_type": day_type,
                    "strategy": strategy,
                    "scope": str(subset["scope"].iloc[0]),
                    "top_sections": int(subset["top_sections"].iloc[0]),
                    "top_machines_per_section": int(subset["top_machines_per_section"].iloc[0]),
                    "n_days": int(subset["date"].nunique()),
                    "n_selected_rows_mean": float(subset["n_selected_rows"].mean()),
                    "actual_hit_rate_mean": float(subset["actual_hit_rate"].mean()),
                    "selected_hit_rate_mean": float(subset["selected_hit_rate"].mean()),
                    "lift_mean": float(subset["lift"].mean()),
                    "actual_avg_diff_mean": float(subset["actual_avg_diff"].mean()),
                    "selected_avg_diff_mean": float(subset["selected_avg_diff"].mean()),
                    "diff_excess_mean": float(subset["diff_excess"].mean()),
                }
            )
        comparison = (
            pd.DataFrame(rows)
            .sort_values(
                ["day_type", "scope", "top_machines_per_section", "strategy"],
                ascending=[True, True, True, True],
                kind="mergesort",
            )
            .reset_index(drop=True)
        )

    section_events_frame = pd.concat(section_events, ignore_index=True) if section_events else pd.DataFrame()
    machine_events_frame = pd.concat(machine_events, ignore_index=True) if machine_events else pd.DataFrame()
    selection_concentration = pd.concat(
        [
            _build_group_concentration(
                section_events_frame, entity_col="section", entity_label_col="entity_label", entity_type="section"
            ),
            _build_group_concentration(
                machine_events_frame,
                entity_col="machine_number",
                entity_label_col="machine_name",
                entity_type="machine",
            ),
        ],
        ignore_index=True,
    )
    top_machine_dependency = _machine_dependency_summary(machine_events_frame)
    report = _build_report(
        db_path=cfg.db_path,
        frame=work,
        eval_dates=eval_dates,
        comparison=comparison,
        selection_concentration=selection_concentration,
        top_machine_dependency=top_machine_dependency,
        strategies=strategies,
        window_days=window_days,
        min_games=min_games,
    )
    return {
        "daily": daily.reset_index(drop=True),
        "comparison": comparison,
        "selection_concentration": selection_concentration,
        "top_machine_dependency": top_machine_dependency,
        "report": pd.DataFrame({"report": [report]}),
    }


def run_hybrid_analysis(
    frame: pd.DataFrame | None = None,
    *,
    output_dir: Path | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_games: int = DEFAULT_MIN_GAMES,
    eval_days: int = DEFAULT_EVAL_DAYS,
    top_sections: int = DEFAULT_SECTION_TOP_K,
    top_machine_ks: tuple[int, ...] = DEFAULT_MACHINE_TOP_KS,
) -> dict[str, pd.DataFrame]:
    outputs = build_hybrid_outputs(
        frame,
        window_days=window_days,
        min_games=min_games,
        eval_days=eval_days,
        top_sections=top_sections,
        top_machine_ks=top_machine_ks,
    )
    outdir = output_dir or DEFAULT_OUTPUT_DIR
    outdir.mkdir(parents=True, exist_ok=True)
    _write_csv(outputs["comparison"], outdir / "hybrid_walkforward_comparison.csv")
    _write_csv(outputs["selection_concentration"], outdir / "selection_concentration.csv")
    _write_csv(outputs["top_machine_dependency"], outdir / "top_machine_dependency.csv")
    _write_text(outdir / "report.md", outputs["report"].iloc[0]["report"])
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Rakuen section-machine hybrid walk-forward analysis")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS)
    parser.add_argument("--top-sections", type=int, default=DEFAULT_SECTION_TOP_K)
    parser.add_argument("--top-machine-ks", type=_parse_top_ks, default=DEFAULT_MACHINE_TOP_KS)
    args = parser.parse_args()

    run_hybrid_analysis(
        frame=None,
        output_dir=args.output_dir,
        window_days=args.window_days,
        min_games=args.min_games,
        eval_days=args.eval_days,
        top_sections=args.top_sections,
        top_machine_ks=tuple(args.top_machine_ks),
    )


if __name__ == "__main__":
    main()
