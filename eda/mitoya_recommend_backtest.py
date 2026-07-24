from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_prompt_common import (  # noqa: E402
    X_DDS,
    add_debut_phase,
    add_event_category,
    connect_mitoya_db,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
)
from eda.mitoya_recommend import (  # noqa: E402
    AVOID_SEGMENTS,
    SECTION_TO_SEGMENT,
    SEGMENT_SECTIONS,
    _score_machine,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DEFAULT_SPLIT_DATE = "20250707"
DEFAULT_TOP_N = 10
DEFAULT_RANDOM_SAMPLES = 100
MIN_GAMES = 1000

SUMMARY_EVENT_TYPES = ("all", "xdds", "non_xdds")
WINDOW_ORDER = ("pre", "post")

# eda/mitoya_recommend_optimize.py の walk-forward 最適化結果
# (eda/results/mitoya_optimize_best.json, lift@10_avg=255.4)。
# 学習データは 2025-01〜2026-04 が主体で、2026-04-27 のレジーム破断より前の値である。
# 履歴として保持し、post-regime の上書きとの差分を追えるようにしておく。
#
# h_nonjug_corner24_xdds / h_nonjug_corner59_xdds は最適化対象ではなかったが、
# mitoya_recommend._score_machine が独自に +200 / +50 を加点していた値である。
# バックテスト側に対応する特徴量が無く、推薦の実挙動を検証できていなかったため取り込んだ。
PRE_REGIME_WEIGHTS: dict[str, float] = {
    "section_baseline_scale": 0.0,
    "h_jug_corner1": 500.0,
    "h_jug_corner24": 250.0,
    "h_jug_corner59": 0.0,
    "h_jug_xdds": 100.0,
    "h_jug_section_641_657": 80.0,
    "h_jug_section_675_691": 40.0,
    "h_jug_section_658_674": 10.0,
    "h_nonjug_xdds": 300.0,
    "h_nonjug_corner1_xdds": 300.0,
    "h_nonjug_corner24_xdds": 200.0,
    "h_nonjug_corner59_xdds": 50.0,
    "h_nonjug_corner1_nonevent_penalty": -100.0,
    "dd24_boost": 200.0,
    "v_jug_xdds": 100.0,
    "v_jug_section_723_733": 20.0,
    "v_jug_section_734_744": 10.0,
    "v_jug_section_712_722": 5.0,
    "mixed_805_debut_xdds": 300.0,
    "mixed_805_growth_xdds_penalty": -100.0,
}

# 2026-04-27 のレジーム破断（店長交代）を受けた手動上書き。
# 根拠は document/mitoya_theory.md 冒頭の 2026-07-24 追記。
# 最適化スクリプトの再実行では**ない**ため、値は保守的に置いている。
# post のサンプルは79日（X_DDS日17日）しかなく、再最適化はデータが積まれてから行う。
POST_REGIME_OVERRIDES: dict[str, float] = {
    # h_jug corner1 は「消失」ではなく符号反転。post X_DDS日 -432 vs corner2+ +46
    # (pre-vs-post MWU p<0.0001、機種内z -0.311 CI[-0.587,-0.044]、対象3台とも同方向)。
    # 裾でも P(diff>2000)=3.9% vs 9.3%、P(diff>5000)=0/51日 と全分位で corner2+ 以下。
    # 点推定の差は -478 だが n=51 と薄いため、その半分以下の -200 に留める。
    "h_jug_corner1": -200.0,
    # h_jug は角番だけでなく X_DDS 効果そのものも消えている (post +18 vs 非イベント +34)。
    "h_jug_xdds": 0.0,
}

CURRENT_WEIGHTS: dict[str, float] = {**PRE_REGIME_WEIGHTS, **POST_REGIME_OVERRIDES}


@dataclass(frozen=True)
class WalkForwardCase:
    window: str
    test_date: str
    dd: int
    is_xdds: bool
    train: pd.DataFrame
    test: pd.DataFrame
    section_baselines: dict[str, float]
    feature_frame: pd.DataFrame


def corner_bucket_from_rank(rank_from_aisle: object) -> str:
    value = pd.to_numeric(pd.Series([rank_from_aisle]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    value = int(value)
    if value == 1:
        return "corner1"
    if value <= 4:
        return "corner2-4"
    if value <= 9:
        return "corner5-9"
    return "corner10+"


def prepare_backtest_frame(frame: pd.DataFrame | None = None, *, min_games: int = MIN_GAMES) -> pd.DataFrame:
    if frame is None:
        frame = load_mitoya_frame(join_layout=True)
    work = frame.copy()

    if "date_dt" not in work.columns:
        work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    if "dd" not in work.columns:
        work["dd"] = pd.to_numeric(work["date_dt"].dt.day, errors="coerce").astype("Int64")

    work = work.loc[pd.to_numeric(work.get("games"), errors="coerce") >= min_games].copy()
    work = add_event_category(work)
    work = add_debut_phase(work)

    if "segment" not in work.columns:
        work["segment"] = work["section"].map(SECTION_TO_SEGMENT).fillna("unknown")
    if "corner_bucket" not in work.columns:
        work["corner_bucket"] = work["rank_from_aisle"].apply(corner_bucket_from_rank)

    work["date"] = work["date"].astype(str)
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce").astype("Int64")
    work["is_xdds"] = work["dd"].isin(X_DDS)
    return work.reset_index(drop=True)


def build_section_baselines(train: pd.DataFrame) -> dict[str, float]:
    if train.empty:
        return {}
    series = pd.to_numeric(train.groupby("section")["diff"].mean(), errors="coerce")
    return {str(section): float(value) for section, value in series.items() if pd.notna(value)}


def build_feature_frame(
    df: pd.DataFrame,
    *,
    dd: int,
    section_baselines: dict[str, float],
) -> pd.DataFrame:
    work = df.copy()
    work["dd"] = int(dd)
    work["is_xdds"] = bool(dd in X_DDS)
    work["section_baseline_raw"] = work["section"].map(section_baselines).fillna(0.0).astype(float)

    work["h_jug_corner1"] = ((work["segment"] == "h_jug") & (work["corner_bucket"] == "corner1")).astype(int)
    work["h_jug_corner24"] = ((work["segment"] == "h_jug") & (work["corner_bucket"] == "corner2-4")).astype(int)
    work["h_jug_corner59"] = ((work["segment"] == "h_jug") & (work["corner_bucket"] == "corner5-9")).astype(int)
    work["h_jug_xdds"] = ((work["segment"] == "h_jug") & work["is_xdds"]).astype(int)
    work["h_jug_section_641_657"] = ((work["segment"] == "h_jug") & (work["section"] == "641-657")).astype(int)
    work["h_jug_section_675_691"] = ((work["segment"] == "h_jug") & (work["section"] == "675-691")).astype(int)
    work["h_jug_section_658_674"] = ((work["segment"] == "h_jug") & (work["section"] == "658-674")).astype(int)

    work["h_nonjug_xdds"] = ((work["segment"] == "h_nonjug") & work["is_xdds"]).astype(int)
    # 523-539 の角1は角1プレミアムから除外する。全期間プールで 523-539角1=-27 は
    # 他セクション角1=+797 より有意に低く（MWU p=0.019）、523-539 内では角1と角2+に
    # 差がない（p=0.50）。dd24_boost が既に 523-539 を外しているのと同じ扱い。
    work["h_nonjug_corner1_xdds"] = (
        (work["segment"] == "h_nonjug")
        & work["is_xdds"]
        & (work["corner_bucket"] == "corner1")
        & (work["section"] != "523-539")
    ).astype(int)
    work["h_nonjug_corner24_xdds"] = (
        (work["segment"] == "h_nonjug") & work["is_xdds"] & (work["corner_bucket"] == "corner2-4")
    ).astype(int)
    work["h_nonjug_corner59_xdds"] = (
        (work["segment"] == "h_nonjug") & work["is_xdds"] & (work["corner_bucket"] == "corner5-9")
    ).astype(int)
    work["h_nonjug_corner1_nonevent_penalty"] = (
        (work["segment"] == "h_nonjug") & (~work["is_xdds"]) & (work["corner_bucket"] == "corner1")
    ).astype(int)
    work["dd24_boost"] = (
        (work["segment"] == "h_nonjug")
        & (work["dd"] == 24)
        & (work["corner_bucket"] == "corner1")
        & (work["section"] != "523-539")
    ).astype(int)

    work["v_jug_xdds"] = ((work["segment"] == "v_jug") & work["is_xdds"]).astype(int)
    work["v_jug_section_723_733"] = ((work["segment"] == "v_jug") & (work["section"] == "723-733")).astype(int)
    work["v_jug_section_734_744"] = ((work["segment"] == "v_jug") & (work["section"] == "734-744")).astype(int)
    work["v_jug_section_712_722"] = ((work["segment"] == "v_jug") & (work["section"] == "712-722")).astype(int)

    work["mixed_805_debut_xdds"] = (
        (work["segment"] == "mixed_805") & work["is_xdds"] & (work["debut_phase"] == "debut")
    ).astype(int)
    work["mixed_805_growth_xdds_penalty"] = (
        (work["segment"] == "mixed_805") & work["is_xdds"] & (work["debut_phase"] == "growth")
    ).astype(int)

    return work


def current_weight_vector(
    *,
    overrides: dict[str, float] | None = None,
) -> dict[str, float]:
    weights = dict(CURRENT_WEIGHTS)
    if overrides:
        weights.update(overrides)
    return weights


def score_features(feature_frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    score = pd.Series(0.0, index=feature_frame.index, dtype=float)
    score = score + feature_frame["section_baseline_raw"].astype(float) * float(weights["section_baseline_scale"])
    for key, weight in weights.items():
        if key == "section_baseline_scale":
            continue
        if key not in feature_frame.columns:
            continue
        score = score + feature_frame[key].astype(float) * float(weight)
    return score


def _score_with_weights(
    row: pd.Series, dd: int, section_baselines: dict[str, float], weights: dict[str, float]
) -> float:
    feature_frame = build_feature_frame(pd.DataFrame([row]), dd=dd, section_baselines=section_baselines)
    return float(score_features(feature_frame, weights).iloc[0])


def _build_cases(prepared: pd.DataFrame, *, split_date: str = DEFAULT_SPLIT_DATE) -> list[WalkForwardCase]:
    cases: list[WalkForwardCase] = []
    for window_name, window_df in (
        ("pre", prepared.loc[prepared["date"] < split_date].copy()),
        ("post", prepared.loc[prepared["date"] >= split_date].copy()),
    ):
        dates = sorted(window_df["date"].dropna().unique().tolist())
        for test_date in dates:
            train = window_df.loc[window_df["date"] < test_date].copy()
            test = window_df.loc[window_df["date"] == test_date].copy()
            if train.empty or test.empty:
                continue
            dd = int(pd.to_numeric(test["dd"].iloc[0], errors="coerce"))
            section_baselines = build_section_baselines(train)
            feature_frame = build_feature_frame(test, dd=dd, section_baselines=section_baselines)
            cases.append(
                WalkForwardCase(
                    window=window_name,
                    test_date=str(test_date),
                    dd=dd,
                    is_xdds=bool(dd in X_DDS),
                    train=train,
                    test=test,
                    section_baselines=section_baselines,
                    feature_frame=feature_frame,
                )
            )
    return cases


def _random_baseline(
    candidate_pool: pd.DataFrame,
    *,
    n_draw: int,
    n_samples: int,
    seed: int,
) -> float:
    if candidate_pool.empty or n_draw <= 0:
        return float("nan")
    values = pd.to_numeric(candidate_pool["diff"], errors="coerce").dropna().to_numpy()
    if len(values) == 0:
        return float("nan")

    rng = np.random.default_rng(seed)
    draws = []
    replace = len(values) < n_draw
    for _ in range(n_samples):
        chosen = rng.choice(values, size=n_draw, replace=replace)
        draws.append(float(np.mean(chosen)))
    return float(np.mean(draws)) if draws else float("nan")


def _actual_hits(recommended: pd.DataFrame, actual: pd.DataFrame, k: int) -> int:
    if recommended.empty or actual.empty:
        return 0
    recommended_keys = set(pd.to_numeric(recommended["machine_number"], errors="coerce").dropna().astype(int).tolist())
    actual_top = (
        actual.sort_values("diff", ascending=False)
        .head(k)["machine_number"]
        .pipe(pd.to_numeric, errors="coerce")
        .dropna()
        .astype(int)
        .tolist()
    )
    return len(recommended_keys.intersection(set(actual_top)))


def _summarize_daily_result(row: pd.DataFrame, recommended: pd.DataFrame, random_avg: float) -> dict[str, object]:
    top_diff = (
        float(pd.to_numeric(recommended["diff"], errors="coerce").mean()) if not recommended.empty else float("nan")
    )
    win_rate = (
        float((pd.to_numeric(recommended["diff"], errors="coerce") > 0).mean())
        if not recommended.empty
        else float("nan")
    )
    return {
        "avg_diff_top10": top_diff,
        "avg_diff_random": random_avg,
        "lift": top_diff - random_avg if pd.notna(top_diff) and pd.notna(random_avg) else float("nan"),
        "hit@3": _actual_hits(recommended, row, 3),
        "hit@5": _actual_hits(recommended, row, 5),
        "hit@10": _actual_hits(recommended, row, 10),
        "win_rate": win_rate,
        "n_machines": float(len(recommended)),
    }


def build_backtest_outputs(
    frame: pd.DataFrame | None = None,
    *,
    top_n: int = DEFAULT_TOP_N,
    random_samples: int = DEFAULT_RANDOM_SAMPLES,
    min_games: int = MIN_GAMES,
    split_date: str = DEFAULT_SPLIT_DATE,
    weights: dict[str, float] | None = None,
) -> dict[str, pd.DataFrame]:
    prepared = prepare_backtest_frame(frame, min_games=min_games)
    cases = _build_cases(prepared, split_date=split_date)
    weight_vector = current_weight_vector(overrides=weights)

    daily_rows: list[dict[str, object]] = []
    detail_rows: list[pd.DataFrame] = []
    for case in cases:
        scored = case.feature_frame.copy()
        scored["score"] = score_features(scored, weight_vector)
        scored = scored.loc[~scored["segment"].isin(AVOID_SEGMENTS)].copy()
        scored = scored.sort_values(["score", "machine_number"], ascending=[False, True], kind="mergesort")
        recommended = scored.head(top_n).reset_index(drop=True)
        random_avg = _random_baseline(
            scored,
            n_draw=min(top_n, len(scored)),
            n_samples=random_samples,
            seed=int(case.test_date),
        )
        daily_row = {
            "test_date": case.test_date,
            "dd": case.dd,
            "is_xdds": case.is_xdds,
            "window": case.window,
        }
        daily_row.update(_summarize_daily_result(case.test, recommended, random_avg))
        daily_rows.append(daily_row)

        if not recommended.empty:
            detail_rows.append(
                recommended.assign(
                    test_date=case.test_date,
                    window=case.window,
                    rank=np.arange(1, len(recommended) + 1),
                )
            )

    daily = pd.DataFrame(
        daily_rows,
        columns=[
            "test_date",
            "dd",
            "is_xdds",
            "window",
            "avg_diff_top10",
            "avg_diff_random",
            "lift",
            "hit@3",
            "hit@5",
            "hit@10",
            "win_rate",
            "n_machines",
        ],
    )
    daily["event_type"] = np.where(daily["is_xdds"], "xdds", "non_xdds")
    summary_rows: list[dict[str, object]] = []
    for window in WINDOW_ORDER:
        window_df = daily.loc[daily["window"] == window].copy()
        for event_type in SUMMARY_EVENT_TYPES:
            scoped = window_df
            if event_type == "xdds":
                scoped = scoped.loc[scoped["is_xdds"]].copy()
            elif event_type == "non_xdds":
                scoped = scoped.loc[~scoped["is_xdds"]].copy()
            summary_rows.append(
                {
                    "window": window,
                    "event_type": event_type,
                    "avg_lift": float(scoped["lift"].mean()) if not scoped.empty else float("nan"),
                    "avg_hit@3": float(scoped["hit@3"].mean()) if not scoped.empty else float("nan"),
                    "avg_hit@5": float(scoped["hit@5"].mean()) if not scoped.empty else float("nan"),
                    "avg_hit@10": float(scoped["hit@10"].mean()) if not scoped.empty else float("nan"),
                    "avg_win_rate": float(scoped["win_rate"].mean()) if not scoped.empty else float("nan"),
                    "n_test_days": int(len(scoped)),
                }
            )
    summary = pd.DataFrame(
        summary_rows,
        columns=[
            "window",
            "event_type",
            "avg_lift",
            "avg_hit@3",
            "avg_hit@5",
            "avg_hit@10",
            "avg_win_rate",
            "n_test_days",
        ],
    )
    details = pd.concat(detail_rows, ignore_index=True) if detail_rows else pd.DataFrame()
    report = build_backtest_report(daily, summary, details, weights=weight_vector, split_date=split_date)
    return {
        "daily": daily,
        "summary": summary,
        "details": details,
        "report": pd.DataFrame({"report": [report]}),
    }


def build_backtest_report(
    daily: pd.DataFrame,
    summary: pd.DataFrame,
    details: pd.DataFrame,
    *,
    weights: dict[str, float],
    split_date: str,
) -> str:
    lines = [
        "# みとや大森町 推薦バックテスト",
        "",
        f"- split_date: `{split_date}`",
        f"- top_n: `10`",
        f"- random_samples: `100`",
        "",
        "## Weights",
        "",
        render_markdown_table(pd.DataFrame([{"weight_name": key, "value": value} for key, value in weights.items()])),
        "",
        "## Summary",
        "",
        render_markdown_table(summary),
        "",
        "## Daily Preview",
        "",
        render_markdown_table(daily.head(10)),
        "",
        "## Recommendation Preview",
        "",
        render_markdown_table(details.head(20)) if not details.empty else "_no rows_",
    ]
    return "\n".join(lines).strip() + "\n"


def run_backtest(
    frame: pd.DataFrame | None = None,
    *,
    output_dir: Path | None = None,
    top_n: int = DEFAULT_TOP_N,
    random_samples: int = DEFAULT_RANDOM_SAMPLES,
    min_games: int = MIN_GAMES,
    split_date: str = DEFAULT_SPLIT_DATE,
    weights: dict[str, float] | None = None,
) -> dict[str, pd.DataFrame]:
    outputs = build_backtest_outputs(
        frame,
        top_n=top_n,
        random_samples=random_samples,
        min_games=min_games,
        split_date=split_date,
        weights=weights,
    )
    outdir = output_dir or ensure_results_dir()
    outdir.mkdir(parents=True, exist_ok=True)
    outputs["daily"].to_csv(outdir / "mitoya_backtest_daily.csv", index=False, encoding="utf-8-sig")
    outputs["summary"].to_csv(outdir / "mitoya_backtest_summary.csv", index=False, encoding="utf-8-sig")
    (outdir / "mitoya_backtest_report.md").write_text(
        outputs["report"].iloc[0]["report"],
        encoding="utf-8",
    )
    return outputs


def _load_live_frame() -> pd.DataFrame:
    with connect_mitoya_db():
        pass
    return prepare_backtest_frame(None)


def main() -> None:
    parser = argparse.ArgumentParser(description="みとや大森町 推薦バックテスト")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--random-samples", type=int, default=DEFAULT_RANDOM_SAMPLES)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    parser.add_argument("--split-date", type=str, default=DEFAULT_SPLIT_DATE)
    args = parser.parse_args()

    run_backtest(
        frame=None,
        output_dir=args.output_dir,
        top_n=args.top_n,
        random_samples=args.random_samples,
        min_games=args.min_games,
        split_date=args.split_date,
    )


if __name__ == "__main__":
    main()
