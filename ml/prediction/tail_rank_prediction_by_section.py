from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ml.last_digit.utils import resolve_db_path


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "tail_rank_prediction_by_section"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CATBOOST_PARAMS = {
    "iterations": 500,
    "learning_rate": 0.05,
    "depth": 6,
    "loss_function": "RMSE",
    "eval_metric": "RMSE",
    "task_type": "GPU",
    "devices": "0",
    "random_seed": 42,
    "verbose": 50,
    "early_stopping_rounds": 50,
}

AT_SECTION_LABELS = {"501-522", "574-590"}
JUG_SECTION_LABELS = {"675-691"}
VAR_SECTION_LABELS = {"723-733"}

MIN_GAMES = 100
NEW_MANAGER_DATE = pd.Timestamp("2026-05-01")


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: int
    train_dates: tuple[pd.Timestamp, ...]
    val_dates: tuple[pd.Timestamp, ...]


def print_section(title: str) -> None:
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _mode_or_default(values: pd.Series, default: str) -> str:
    mode = values.dropna()
    if mode.empty:
        return default
    out = mode.astype(str).mode(dropna=True)
    if out.empty:
        return default
    return str(out.iloc[0])


def _fallback_section(machine_number: object) -> str:
    if pd.isna(machine_number):
        return "unknown"
    number = int(machine_number)
    return f"{number}-{number}"


def _normalize_section_label(
    section: object,
    section_min: object = None,
    section_max: object = None,
    machine_number: object = None,
) -> str:
    section_text = "" if pd.isna(section) else str(section).strip()
    if section_text and section_text.lower() != "unknown":
        return section_text
    if not pd.isna(section_min) and not pd.isna(section_max):
        return f"{int(section_min)}-{int(section_max)}"
    return _fallback_section(machine_number)


def _derive_machine_type(row: pd.Series) -> str:
    if int(row.get("jug_flag", 0) or 0) == 1:
        return "jug"
    if int(row.get("hana_flag", 0) or 0) == 1:
        return "hana"
    if int(row.get("oki_flag", 0) or 0) == 1:
        return "oki"
    if int(row.get("bt_flag", 0) or 0) == 1:
        return "bt"
    return "other"


def _is_x_day(value: object) -> bool:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return False
    return int(ts.day) % 10 in {4, 7}


def _section_is_at(section: str) -> bool:
    return section in AT_SECTION_LABELS


def _section_is_jug(section: str) -> bool:
    return section in JUG_SECTION_LABELS


def _section_is_variety(section: str) -> bool:
    return section in VAR_SECTION_LABELS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tail rank prediction by section.")
    parser.add_argument("--db-path", default="db/みとや大森町店.db", help="Path to the SQLite DB.")
    parser.add_argument(
        "--db-glob",
        default="*みとや大森町店*.db",
        help="Glob used when --db-path is omitted or unavailable.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/tail_rank_prediction_by_section",
        help="Directory for prediction outputs.",
    )
    parser.add_argument("--train-days", type=int, default=72, help="Walk-forward training window.")
    parser.add_argument("--val-days", type=int, default=30, help="Walk-forward validation window.")
    parser.add_argument("--step-days", type=int, default=30, help="Walk-forward step size.")
    parser.add_argument("--min-games", type=int, default=MIN_GAMES, help="Minimum games per raw machine row.")
    parser.add_argument("--include-non-xday", dest="xday_only", action="store_false", help="Train on all days.")
    parser.set_defaults(xday_only=True)
    parser.add_argument("--task-type", default="GPU", choices=["GPU", "CPU"], help="CatBoost task type.")
    parser.add_argument("--devices", default="0", help="CatBoost GPU devices string.")
    parser.add_argument("--section-filter", default="", help="Comma-separated section filter.")
    return parser


def load_raw_rows(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as con:
        raw = pd.read_sql_query(
            """
            SELECT
              m.date,
              m.machine_number,
              m.machine_name,
              m.last_digit,
              m.games_normalized,
              m.diff_coins_normalized
            FROM machine_detailed_results m
            ORDER BY m.date, m.machine_number
            """,
            con,
        )
        layout = (
            pd.read_sql_query(
                """
                SELECT
                  machine_number,
                  section,
                  section_min,
                  section_max
                FROM machine_layout
                """,
                con,
            )
            if _table_exists(con, "machine_layout")
            else pd.DataFrame(columns=["machine_number", "section", "section_min", "section_max"])
        )
        master = (
            pd.read_sql_query(
                """
                SELECT
                  machine_name_normalized,
                  jug_flag,
                  hana_flag,
                  oki_flag,
                  bt_flag
                FROM machine_master
                """,
                con,
            )
            if _table_exists(con, "machine_master")
            else pd.DataFrame(
                columns=["machine_name_normalized", "jug_flag", "hana_flag", "oki_flag", "bt_flag"]
            )
        )

    if raw.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "machine_number",
                "machine_name",
                "last_digit",
                "games_normalized",
                "diff_coins_normalized",
                "section",
                "machine_type",
            ]
        )

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(
        subset=["date", "machine_number", "machine_name", "last_digit", "games_normalized", "diff_coins_normalized"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"] >= int(min_games)].copy()
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()
    work["last_digit"] = work["last_digit"].astype(str)

    if not layout.empty:
        layout = layout.copy()
        if "machine_number" in layout.columns:
            layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
        for col in ("section_min", "section_max"):
            if col in layout.columns:
                layout[col] = pd.to_numeric(layout[col], errors="coerce")
        work = work.merge(layout, on="machine_number", how="left")
    else:
        work["section"] = ""
        work["section_min"] = np.nan
        work["section_max"] = np.nan

    if not master.empty:
        master = master.rename(columns={"machine_name_normalized": "machine_name"})
        work = work.merge(master, on="machine_name", how="left")
    else:
        for col in ["jug_flag", "hana_flag", "oki_flag", "bt_flag"]:
            work[col] = 0

    for col in ["jug_flag", "hana_flag", "oki_flag", "bt_flag"]:
        if col not in work.columns:
            work[col] = 0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0).astype(int)

    if "section" not in work.columns:
        work["section"] = ""
    work["section"] = work.apply(
        lambda row: _normalize_section_label(
            row.get("section"),
            row.get("section_min"),
            row.get("section_max"),
            row.get("machine_number"),
        ),
        axis=1,
    )
    work["machine_type"] = work.apply(_derive_machine_type, axis=1)
    work = work[work["section"].ne("unknown")].copy()
    work["date"] = work["date"].dt.normalize()
    return work.reset_index(drop=True)


def assign_tail_rank_targets(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "section",
                "last_digit",
                "avg_diff_coins",
                "machine_count",
                "machine_type",
                "target_tail_rank_by_section",
                "target_tail_score_by_section",
            ]
        )

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work = work.dropna(
        subset=["date", "machine_number", "last_digit", "diff_coins_normalized", "games_normalized", "section"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()
    work["machine_type"] = work["machine_type"].fillna("other").astype(str)

    group_cols = ["date", "section", "last_digit"]
    agg = (
        work.groupby(group_cols, sort=True)
        .agg(
            avg_diff_coins=("diff_coins_normalized", "mean"),
            machine_count=("diff_coins_normalized", "size"),
            machine_type=("machine_type", lambda s: _mode_or_default(s, "other")),
        )
        .reset_index()
    )

    agg["last_digit_num"] = pd.to_numeric(agg["last_digit"], errors="coerce").fillna(99).astype(int)
    agg = agg.sort_values(["date", "section", "avg_diff_coins", "last_digit_num"], ascending=[True, True, False, True])
    agg["target_tail_rank_by_section"] = agg.groupby(["date", "section"]).cumcount() + 1
    agg["target_tail_score_by_section"] = (1.0 - (agg["target_tail_rank_by_section"] - 1) * 0.15).clip(lower=0.0)
    agg = agg.drop(columns=["last_digit_num"]).reset_index(drop=True)
    return agg


def add_tail_prediction_features(ranked: pd.DataFrame) -> pd.DataFrame:
    if ranked.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "section",
                "last_digit",
                "avg_diff_coins",
                "machine_count",
                "machine_type",
                "target_tail_rank_by_section",
                "target_tail_score_by_section",
            ]
        )

    work = ranked.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work = work.dropna(subset=["date", "section", "last_digit", "target_tail_rank_by_section"]).copy()
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["dd"] = work["date"].dt.day.astype(int)
    work["weekday_num"] = work["date"].dt.dayofweek.astype(int)
    work["month"] = work["date"].dt.month.astype(int)
    work["dd_mod10"] = work["dd"] % 10
    work["is_dd4"] = (work["dd"] == 4).astype(int)
    work["is_dd7"] = (work["dd"] == 7).astype(int)
    work["is_dd14"] = (work["dd"] == 14).astype(int)
    work["is_dd17"] = (work["dd"] == 17).astype(int)
    work["is_dd24"] = (work["dd"] == 24).astype(int)
    work["is_dd27"] = (work["dd"] == 27).astype(int)
    work["is_xday"] = work["dd_mod10"].isin([4, 7]).astype(int)
    work["is_new_manager"] = (work["date"] >= NEW_MANAGER_DATE).astype(int)
    work["section"] = work["section"].astype(str).str.strip()
    work["machine_type"] = work["machine_type"].fillna("other").astype(str).str.strip()
    work["section_digit_combo"] = work["section"] + "__" + work["last_digit"]
    work["is_at_digit2"] = (work["last_digit"].eq("2") & work["section"].isin(AT_SECTION_LABELS)).astype(int)
    work["is_jug675_digit7"] = (work["last_digit"].eq("7") & work["section"].isin(JUG_SECTION_LABELS)).astype(int)
    work["is_var723_digit7"] = (work["last_digit"].eq("7") & work["section"].isin(VAR_SECTION_LABELS)).astype(int)
    work["is_dd4_at_digit2"] = (work["is_at_digit2"].eq(1) & work["is_dd4"].eq(1)).astype(int)
    work["is_dd17_jug_digit7"] = (work["is_jug675_digit7"].eq(1) & work["is_dd17"].eq(1)).astype(int)
    work["is_dd27_var_digit7"] = (work["is_var723_digit7"].eq(1) & work["is_dd27"].eq(1)).astype(int)

    work = work.sort_values(["section", "last_digit", "date"]).reset_index(drop=True)
    group_cols = ["section", "last_digit"]
    work["section_digit_rolling7_mean"] = work.groupby(group_cols)["avg_diff_coins"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=1).mean()
    )
    work["section_digit_rolling30_mean"] = work.groupby(group_cols)["avg_diff_coins"].transform(
        lambda s: s.shift(1).rolling(30, min_periods=1).mean()
    )
    work["section_digit_trend"] = work["section_digit_rolling7_mean"] - work["section_digit_rolling30_mean"]
    work["_xday_rank"] = work["target_tail_rank_by_section"].where(work["is_xday"].eq(1))
    work["prev_xday_section_digit_rank"] = work.groupby(group_cols)["_xday_rank"].transform(lambda s: s.shift(1).ffill())
    work = work.drop(columns=["_xday_rank"])
    return work.reset_index(drop=True)


def build_prediction_dataset(
    db_path: Path,
    *,
    xday_only: bool = True,
    min_games: int = MIN_GAMES,
    section_filter: Iterable[str] | None = None,
) -> pd.DataFrame:
    raw = load_raw_rows(db_path, min_games=min_games)
    ranked = assign_tail_rank_targets(raw)
    ranked = add_tail_prediction_features(ranked)
    if xday_only:
        ranked = ranked[ranked["is_xday"].eq(1)].copy()
    if section_filter:
        section_filter_set = {str(x).strip() for x in section_filter if str(x).strip()}
        ranked = ranked[ranked["section"].isin(section_filter_set)].copy()
    return ranked.reset_index(drop=True)


def build_walk_forward_folds(
    dates: Sequence[pd.Timestamp],
    *,
    train_days: int,
    val_days: int,
    step_days: int,
) -> list[WalkForwardFold]:
    ordered = tuple(pd.Timestamp(d).normalize() for d in dates)
    if train_days <= 0 or val_days <= 0 or step_days <= 0:
        raise ValueError("train_days, val_days, and step_days must be positive.")
    if len(ordered) < train_days + 1:
        return []

    folds: list[WalkForwardFold] = []
    fold_id = 1
    start = train_days
    while start < len(ordered):
        train_slice = ordered[start - train_days : start]
        val_slice = ordered[start : min(start + val_days, len(ordered))]
        if not val_slice:
            break
        folds.append(
            WalkForwardFold(
                fold_id=fold_id,
                train_dates=tuple(train_slice),
                val_dates=tuple(val_slice),
            )
        )
        fold_id += 1
        start += step_days
    return folds


def _prepare_model_frame(frame: pd.DataFrame, features: list[str], cat_features: list[str]) -> pd.DataFrame:
    work = frame.copy()
    for col in features:
        if col in cat_features:
            work[col] = work[col].fillna("unknown").astype(str)
        else:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    return work


def _get_catboost_classes():
    try:
        from catboost import CatBoostRegressor, Pool
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("catboost is required to train the model.") from exc
    return CatBoostRegressor, Pool


def _fit_catboost_model(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    features: list[str],
    cat_features: list[str],
    task_type: str,
    devices: str,
) -> tuple[object, np.ndarray]:
    CatBoostRegressor, Pool = _get_catboost_classes()
    tr = _prepare_model_frame(train_df, features, cat_features)
    va = _prepare_model_frame(val_df, features, cat_features)
    cat_indices = [features.index(name) for name in cat_features]
    train_pool = Pool(tr[features], label=train_df["target_tail_score_by_section"], cat_features=cat_indices)
    val_pool = Pool(va[features], label=val_df["target_tail_score_by_section"], cat_features=cat_indices)
    params = dict(CATBOOST_PARAMS)
    params["task_type"] = task_type
    params["devices"] = devices
    try:
        model = CatBoostRegressor(**params)
        model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    except Exception:
        if task_type != "GPU":
            raise
        cpu_params = {k: v for k, v in params.items() if k not in {"task_type", "devices"}}
        cpu_params["task_type"] = "CPU"
        model = CatBoostRegressor(**cpu_params)
        model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    return model, val_pool


def predict_section_walk_forward(
    section_df: pd.DataFrame,
    *,
    train_days: int,
    val_days: int,
    step_days: int,
    task_type: str,
    devices: str,
) -> pd.DataFrame:
    if section_df.empty:
        return pd.DataFrame()

    features = [
        "section",
        "last_digit",
        "machine_type",
        "section_digit_combo",
        "dd",
        "weekday_num",
        "month",
        "dd_mod10",
        "is_dd4",
        "is_dd7",
        "is_dd14",
        "is_dd17",
        "is_dd24",
        "is_dd27",
        "is_xday",
        "is_new_manager",
        "prev_xday_section_digit_rank",
        "section_digit_rolling7_mean",
        "section_digit_rolling30_mean",
        "section_digit_trend",
        "is_at_digit2",
        "is_jug675_digit7",
        "is_var723_digit7",
        "is_dd4_at_digit2",
        "is_dd17_jug_digit7",
        "is_dd27_var_digit7",
    ]
    cat_features = ["section", "last_digit", "machine_type", "section_digit_combo"]

    available_features = [name for name in features if name in section_df.columns]
    available_cat_features = [name for name in cat_features if name in available_features]
    dates = tuple(sorted(pd.to_datetime(section_df["date"], errors="coerce").dropna().unique()))
    folds = build_walk_forward_folds(dates, train_days=train_days, val_days=val_days, step_days=step_days)
    if not folds:
        return pd.DataFrame()

    predictions: list[pd.DataFrame] = []
    for fold in folds:
        train_df = section_df[section_df["date"].isin(fold.train_dates)].copy()
        val_df = section_df[section_df["date"].isin(fold.val_dates)].copy()
        if train_df.empty or val_df.empty:
            continue
        model, _ = _fit_catboost_model(
            train_df,
            val_df,
            features=available_features,
            cat_features=available_cat_features,
            task_type=task_type,
            devices=devices,
        )
        val_df = _prepare_model_frame(val_df, available_features, available_cat_features)
        val_df["pred_tail_score"] = model.predict(val_df[available_features])
        val_df["fold_id"] = fold.fold_id
        predictions.append(val_df)

    if not predictions:
        return pd.DataFrame()

    out = pd.concat(predictions, ignore_index=True)
    out["pred_tail_rank"] = out.groupby(["date", "section"])["pred_tail_score"].rank(
        ascending=False,
        method="first",
    ).astype(int)
    return out


def evaluate_prediction_frame(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {
            "spearman": float("nan"),
            "rank_accuracy": float("nan"),
            "precision_at_3": float("nan"),
            "mae_rank": float("nan"),
        }

    spearman_values: list[float] = []
    rank_accuracy_values: list[float] = []
    precision_at_3_values: list[float] = []
    mae_rank_values: list[float] = []

    for _, grp in frame.groupby(["date", "section"], sort=False):
        if len(grp) < 2:
            continue
        actual_rank = pd.to_numeric(grp["target_tail_rank_by_section"], errors="coerce")
        pred_rank = pd.to_numeric(grp["pred_tail_rank"], errors="coerce")
        if actual_rank.isna().all() or pred_rank.isna().all():
            continue
        rho, _ = spearmanr(actual_rank, pred_rank)
        if pd.notna(rho):
            spearman_values.append(float(rho))
        top_actual = set(
            grp.sort_values(["target_tail_rank_by_section", "last_digit"], ascending=[True, True])
            .head(min(3, len(grp)))["last_digit"]
            .astype(str)
        )
        top_pred = set(
            grp.sort_values(["pred_tail_rank", "last_digit"], ascending=[True, True])
            .head(min(3, len(grp)))["last_digit"]
            .astype(str)
        )
        top1_actual = (
            grp.sort_values(["target_tail_rank_by_section", "last_digit"], ascending=[True, True])
            .iloc[0]["last_digit"]
        )
        top1_pred = grp.sort_values(["pred_tail_rank", "last_digit"], ascending=[True, True]).iloc[0]["last_digit"]
        rank_accuracy_values.append(float(str(top1_actual) == str(top1_pred)))
        precision_at_3_values.append(float(len(top_actual & top_pred) / max(1, min(3, len(grp)))))
        mae_rank_values.append(float(np.abs(actual_rank - pred_rank).mean()))

    return {
        "spearman": float(np.nanmean(spearman_values)) if spearman_values else float("nan"),
        "rank_accuracy": float(np.nanmean(rank_accuracy_values)) if rank_accuracy_values else float("nan"),
        "precision_at_3": float(np.nanmean(precision_at_3_values)) if precision_at_3_values else float("nan"),
        "mae_rank": float(np.nanmean(mae_rank_values)) if mae_rank_values else float("nan"),
    }


def summarize_section_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "n_validation_rows",
                "n_validation_dates",
                "spearman",
                "rank_accuracy",
                "precision_at_3",
                "mae_rank",
            ]
        )

    rows = []
    for section, grp in predictions.groupby("section", sort=True):
        metrics = evaluate_prediction_frame(grp)
        rows.append(
            {
                "section": section,
                "n_validation_rows": int(len(grp)),
                "n_validation_dates": int(grp["date"].nunique()),
                **metrics,
            }
        )
    return pd.DataFrame(rows).sort_values(["spearman", "section"], ascending=[False, True]).reset_index(drop=True)


def run_pipeline(
    db_path: Path,
    *,
    output_dir: Path,
    train_days: int,
    val_days: int,
    step_days: int,
    xday_only: bool,
    min_games: int,
    task_type: str,
    devices: str,
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dataset = build_prediction_dataset(
        db_path,
        xday_only=xday_only,
        min_games=min_games,
        section_filter=section_filter,
    )
    if dataset.empty:
        return pd.DataFrame(), pd.DataFrame()

    predictions: list[pd.DataFrame] = []
    for section, section_df in dataset.groupby("section", sort=True):
        section_pred = predict_section_walk_forward(
            section_df.copy(),
            train_days=train_days,
            val_days=val_days,
            step_days=step_days,
            task_type=task_type,
            devices=devices,
        )
        if section_pred.empty:
            continue
        predictions.append(section_pred)

    if predictions:
        pred_df = pd.concat(predictions, ignore_index=True)
        pred_df["date"] = pd.to_datetime(pred_df["date"], errors="coerce").dt.strftime("%Y%m%d")
        pred_df = pred_df.sort_values(["section", "date", "pred_tail_rank", "last_digit"]).reset_index(drop=True)
    else:
        pred_df = pd.DataFrame()

    metrics_df = summarize_section_metrics(pred_df)

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "tail_rank_prediction_by_section_validation.csv"
    metrics_path = output_dir / "tail_rank_prediction_by_section_metrics.csv"
    pred_df.to_csv(pred_path, index=False)
    metrics_df.to_csv(metrics_path, index=False)

    return pred_df, metrics_df


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    section_filter = [x.strip() for x in args.section_filter.split(",") if x.strip()]
    db_path = Path(args.db_path)
    if not db_path.exists():
        db_path = resolve_db_path("", args.db_glob)
    output_dir = Path(args.output_dir)

    print_section("1. Load and prepare dataset")
    print(f"  db_path: {db_path}")
    print(f"  xday_only: {args.xday_only}")
    print(f"  train_days: {args.train_days} / val_days: {args.val_days} / step_days: {args.step_days}")

    pred_df, metrics_df = run_pipeline(
        db_path,
        output_dir=output_dir,
        train_days=args.train_days,
        val_days=args.val_days,
        step_days=args.step_days,
        xday_only=args.xday_only,
        min_games=args.min_games,
        task_type=args.task_type,
        devices=args.devices,
        section_filter=section_filter,
    )

    print_section("2. Validation metrics")
    if metrics_df.empty:
        print("  No validation results were produced.")
    else:
        print(metrics_df.to_string(index=False))

    if not pred_df.empty:
        print_section("3. Validation predictions sample")
        print(pred_df.head(20).to_string(index=False))
        print(f"\n  Saved: {output_dir / 'tail_rank_prediction_by_section_validation.csv'}")
        print(f"  Saved: {output_dir / 'tail_rank_prediction_by_section_metrics.csv'}")
    else:
        print("  No predictions were generated.")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
