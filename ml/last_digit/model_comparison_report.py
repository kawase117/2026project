from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_MODELS = [
    "xgb_ranker_ndcg",
    "xgb_ranker_pairwise",
    "catboost_ranker_pairlogit",
    "lgbm_ranker_lambdarank",
]

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def _colorize_delta(v: float) -> str:
    if pd.isna(v):
        return "NaN"
    s = f"{v:+.4f}"
    if v > 0:
        return f"{GREEN}{s}{RESET}"
    if v < 0:
        return f"{RED}{s}{RESET}"
    return s


def _find_daily_csv(input_dir: Path, model_name: str) -> Path | None:
    patterns = [
        f"*_{model_name}_testperiod_daily.csv",
        f"*{model_name}*testperiod_daily.csv",
    ]
    for pat in patterns:
        hits = sorted(input_dir.glob(pat))
        if hits:
            return hits[-1]
    return None


def _load_model_daily(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    for col in ("precision", "recall", "f1", "hit_at_2", "hit_at_3"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = df["month"].astype(str)
    df["weekday"] = df["weekday"].astype(str)
    df["expert"] = df["expert"].astype(str)
    df["status"] = df["status"].astype(str)
    return df


def _summary_table(model_frames: dict[str, pd.DataFrame], baseline: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, df in model_frames.items():
        ok = df[df["status"].eq("ok")].copy()
        rows.append(
            {
                "model": model + (" (baseline)" if model == baseline else ""),
                "model_key": model,
                "precision": float(ok["precision"].mean()) if not ok.empty else np.nan,
                "recall": float(ok["recall"].mean()) if not ok.empty else np.nan,
                "f1": float(ok["f1"].mean()) if not ok.empty else np.nan,
                "hit_at_2": float(ok["hit_at_2"].mean()) if not ok.empty else np.nan,
                "hit_at_3": float(ok["hit_at_3"].mean()) if not ok.empty else np.nan,
                "n_days": int(ok["date"].nunique()) if not ok.empty else 0,
                "n_rows_ok": int(len(ok)),
                "n_rows_total": int(len(df)),
            }
        )
    out = pd.DataFrame(rows)
    base = out[out["model_key"] == baseline]
    if base.empty:
        for col in ("precision", "recall", "f1", "hit_at_2", "hit_at_3"):
            out[f"delta_{col}_vs_{baseline}"] = np.nan
        return out
    base_row = base.iloc[0]
    for col in ("precision", "recall", "f1", "hit_at_2", "hit_at_3"):
        out[f"delta_{col}_vs_{baseline}"] = out[col] - float(base_row[col])
    return out


def _weekday_table(model_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, df in model_frames.items():
        ok = df[df["status"].eq("ok")].copy()
        if ok.empty:
            continue
        ok["weekday_bucket"] = np.where(ok["weekday"].eq("Wednesday"), "Wednesday", "Non-Wednesday")
        g = (
            ok.groupby("weekday_bucket", sort=True)
            .agg(
                f1=("f1", "mean"),
                hit_at_2=("hit_at_2", "mean"),
                n_days=("date", "nunique"),
                n_rows=("date", "size"),
            )
            .reset_index()
        )
        g.insert(0, "model", model)
        rows.append(g)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _expert_table(model_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, df in model_frames.items():
        ok = df[df["status"].eq("ok")].copy()
        if ok.empty:
            continue
        g = (
            ok.groupby("expert", sort=True)
            .agg(
                f1=("f1", "mean"),
                hit_at_2=("hit_at_2", "mean"),
                n_days=("date", "nunique"),
                n_rows=("date", "size"),
            )
            .reset_index()
        )
        g.insert(0, "model", model)
        rows.append(g)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _monthly_table(model_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, df in model_frames.items():
        ok = df[df["status"].eq("ok")].copy()
        if ok.empty:
            continue
        g = (
            ok.groupby("month", sort=True)
            .agg(
                hit_at_2=("hit_at_2", "mean"),
                f1=("f1", "mean"),
                n_days=("date", "nunique"),
                n_rows=("date", "size"),
            )
            .reset_index()
        )
        g.insert(0, "model", model)
        rows.append(g)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _build_comments(model_frames: dict[str, pd.DataFrame], missing_models: list[str]) -> list[str]:
    comments: list[str] = []
    if missing_models:
        comments.append(f"Missing model outputs: {', '.join(missing_models)}")
    for model, df in model_frames.items():
        if "status" not in df.columns:
            continue
        n_unavail = int((~df["status"].eq("ok")).sum())
        if n_unavail > 0:
            comments.append(f"{model}: {n_unavail} rows were non-ok and excluded from aggregate metrics.")
    return comments


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create model comparison report from test-period daily outputs.")
    p.add_argument("--input-dir", default="db/experiments/model_comparison")
    p.add_argument("--baseline-model", default="xgb_ranker_ndcg")
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--output-prefix", default="db/experiments/model_comparison/comparison")
    return p


def main() -> int:
    args = build_parser().parse_args()
    input_dir = Path(args.input_dir)
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    models = [m.strip() for m in str(args.models).split(",") if m.strip()]
    model_frames: dict[str, pd.DataFrame] = {}
    model_files: dict[str, str] = {}
    missing_models: list[str] = []

    for model in models:
        path = _find_daily_csv(input_dir, model)
        if path is None:
            missing_models.append(model)
            continue
        model_files[model] = str(path)
        model_frames[model] = _load_model_daily(path)

    if args.baseline_model not in model_frames:
        raise ValueError(
            f"Baseline model output not found: {args.baseline_model}. "
            f"found={sorted(model_frames.keys())}, missing={missing_models}"
        )

    summary = _summary_table(model_frames, baseline=args.baseline_model)
    weekday = _weekday_table(model_frames)
    expert = _expert_table(model_frames)
    monthly = _monthly_table(model_frames)
    comments = _build_comments(model_frames, missing_models)

    summary_csv = output_prefix.with_name(output_prefix.name + "_summary.csv")
    weekday_csv = output_prefix.with_name(output_prefix.name + "_weekday.csv")
    expert_csv = output_prefix.with_name(output_prefix.name + "_expert.csv")
    monthly_csv = output_prefix.with_name(output_prefix.name + "_monthly.csv")
    json_out = output_prefix.with_name(output_prefix.name + "_report.json")

    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    if not weekday.empty:
        weekday.to_csv(weekday_csv, index=False, encoding="utf-8-sig")
    if not expert.empty:
        expert.to_csv(expert_csv, index=False, encoding="utf-8-sig")
    if not monthly.empty:
        monthly.to_csv(monthly_csv, index=False, encoding="utf-8-sig")

    payload = {
        "input_dir": str(input_dir),
        "baseline_model": args.baseline_model,
        "model_files": model_files,
        "missing_models": missing_models,
        "comments": comments,
        "summary": summary.to_dict(orient="records"),
        "weekday": weekday.to_dict(orient="records"),
        "expert": expert.to_dict(orient="records"),
        "monthly": monthly.to_dict(orient="records"),
    }
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    display = summary.copy()
    delta_cols = [c for c in display.columns if c.startswith("delta_")]
    for c in delta_cols:
        display[c] = display[c].apply(_colorize_delta)

    print("\n=== Overall Summary (with baseline deltas) ===")
    print(display.to_string(index=False))
    print("\n=== Weekday (Wednesday vs Non-Wednesday) ===")
    print(weekday.to_string(index=False) if not weekday.empty else "(empty)")
    print("\n=== Expert Breakdown ===")
    print(expert.to_string(index=False) if not expert.empty else "(empty)")
    print("\n=== Monthly Trend ===")
    print(monthly.to_string(index=False) if not monthly.empty else "(empty)")
    if comments:
        print("\n=== Comments ===")
        for c in comments:
            print(f"- {c}")

    print(f"\nSaved: {summary_csv}")
    print(f"Saved: {weekday_csv}")
    print(f"Saved: {expert_csv}")
    print(f"Saved: {monthly_csv}")
    print(f"Saved: {json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
