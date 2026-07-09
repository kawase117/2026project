from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import (
    DEFAULT_HALL,
    DEFAULT_OUTPUT_ROOT,
    HALL_DBS,
    HALL_SLUGS,
    JUGGLER_FAMILY_MATCHERS,
    JUGGLER_FAMILY_SPECS,
    JUGGLER_UNKNOWN_FAMILY_KEY,
)


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _resolve_db_path(hall: str, db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    try:
        return HALL_DBS[hall]
    except KeyError as exc:  # pragma: no cover - guarded by argparse choices
        raise KeyError(f"unknown hall: {hall}") from exc


def _normalize_machine_name(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def classify_machine_name(machine_name: str) -> tuple[str, str, bool]:
    normalized = _normalize_machine_name(machine_name)
    for family_key, keyword in JUGGLER_FAMILY_MATCHERS:
        if keyword in normalized:
            return family_key, family_key, False
    if "ジャグラー" in normalized:
        return JUGGLER_UNKNOWN_FAMILY_KEY, "", True
    return "", "", False


def load_machine_name_frame(db_path: Path, *, hall: str) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                machine_name,
                COUNT(*) AS n_rows,
                MIN(date) AS first_date,
                MAX(date) AS last_date
            FROM machine_detailed_results
            WHERE machine_name LIKE '%ジャグラー%'
            GROUP BY machine_name
            ORDER BY machine_name
            """,
            conn,
        )
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "hall",
                "machine_name",
                "n_rows",
                "first_date",
                "last_date",
                "family_key",
                "family_name",
                "resolved_family_key",
                "resolved_family_name",
                "is_unknown_family",
                "warning",
            ]
        )

    rows: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        machine_name = _normalize_machine_name(row["machine_name"])
        family_key, resolved_family_key, is_unknown_family = classify_machine_name(machine_name)
        resolved_family = JUGGLER_FAMILY_SPECS.get(resolved_family_key)
        rows.append(
            {
                "hall": hall,
                "machine_name": machine_name,
                "n_rows": int(row["n_rows"]),
                "first_date": str(row["first_date"]),
                "last_date": str(row["last_date"]),
                "family_key": family_key,
                "family_name": JUGGLER_FAMILY_SPECS.get(family_key, {}).get("family_name", ""),
                "resolved_family_key": resolved_family_key,
                "resolved_family_name": resolved_family["family_name"] if resolved_family else "",
                "is_unknown_family": bool(is_unknown_family),
                "warning": "excluded_unknown_juggler" if is_unknown_family else "",
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values(["is_unknown_family", "machine_name"], kind="mergesort").reset_index(drop=True)


def build_machine_catalog(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    if "hall" not in work.columns:
        work["hall"] = hall
    if "machine_name" not in work.columns:
        raise KeyError("machine_name column is required")
    work["machine_name"] = work["machine_name"].map(_normalize_machine_name)
    work = work[work["machine_name"].str.contains("ジャグラー", na=False)].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "hall",
                "machine_name",
                "n_rows",
                "first_date",
                "last_date",
                "family_key",
                "family_name",
                "resolved_family_key",
                "resolved_family_name",
                "is_unknown_family",
                "warning",
            ]
        )

    rows = []
    for machine_name, group in work.groupby("machine_name", sort=True):
        family_key, resolved_family_key, is_unknown_family = classify_machine_name(machine_name)
        resolved_family = JUGGLER_FAMILY_SPECS.get(resolved_family_key)
        rows.append(
            {
                "hall": hall,
                "machine_name": machine_name,
                "n_rows": int(group.get("n_rows", pd.Series([len(group)])).iloc[0]),
                "first_date": str(group.get("first_date", pd.Series([""])).iloc[0]),
                "last_date": str(group.get("last_date", pd.Series([""])).iloc[0]),
                "family_key": family_key,
                "family_name": JUGGLER_FAMILY_SPECS.get(family_key, {}).get("family_name", ""),
                "resolved_family_key": resolved_family_key,
                "resolved_family_name": resolved_family["family_name"] if resolved_family else "",
                "is_unknown_family": bool(is_unknown_family),
                "warning": "excluded_unknown_juggler" if is_unknown_family else "",
            }
        )
    return (
        pd.DataFrame(rows).sort_values(["is_unknown_family", "machine_name"], kind="mergesort").reset_index(drop=True)
    )


def build_setting_prob_master(catalog: pd.DataFrame) -> pd.DataFrame:
    if catalog.empty:
        return pd.DataFrame(
            columns=[
                "hall",
                "machine_name",
                "family_key",
                "family_name",
                "resolved_family_key",
                "resolved_family_name",
                "is_unknown_family",
                "warning",
                "setting",
                "rb_probability",
                "bb_probability",
                "payout_rate",
            ]
        )

    rows: list[dict[str, object]] = []
    for row in catalog.to_dict("records"):
        source_key = str(row["family_key"]) if row["family_key"] else ""
        if bool(row["is_unknown_family"]):
            continue
        resolved_key = str(row["resolved_family_key"]) if row["resolved_family_key"] else ""
        spec_key = resolved_key if resolved_key in JUGGLER_FAMILY_SPECS else None
        if spec_key is None:
            continue
        spec = JUGGLER_FAMILY_SPECS[spec_key]
        for setting in sorted(spec["settings"]):
            setting_spec = spec["settings"][setting]
            rows.append(
                {
                    "hall": row["hall"],
                    "machine_name": row["machine_name"],
                    "family_key": source_key,
                    "family_name": row["family_name"],
                    "resolved_family_key": spec_key,
                    "resolved_family_name": spec["family_name"],
                    "is_unknown_family": bool(row["is_unknown_family"]),
                    "warning": row["warning"],
                    "setting": int(setting),
                    "rb_probability": float(setting_spec["rb_probability"]),
                    "bb_probability": float(setting_spec["bb_probability"]),
                    "payout_rate": float(setting_spec["payout_rate"]),
                }
            )
    return pd.DataFrame(rows).sort_values(["machine_name", "setting"], kind="mergesort").reset_index(drop=True)


def _render_table(df: pd.DataFrame, *, max_rows: int | None = None) -> str:
    if df.empty:
        return "_empty_"
    work = df.copy()
    if max_rows is not None and len(work) > max_rows:
        work = work.head(max_rows).copy()
    return "\n".join(
        ["| " + " | ".join(map(str, work.columns)) + " |"]
        + [
            "| " + " | ".join(map(lambda value: str(value), row)) + " |"
            for row in work.itertuples(index=False, name=None)
        ]
    )


def build_stage1_outputs(*, db_path: Path, hall: str) -> dict[str, pd.DataFrame | str]:
    catalog = load_machine_name_frame(db_path, hall=hall)
    master = build_setting_prob_master(catalog)
    unknown_names = catalog.loc[catalog["is_unknown_family"].fillna(False), "machine_name"].tolist()
    report = "\n\n".join(
        [
            f"# Stage 1 Machine Catalog - {hall}",
            f"- DB: `{db_path}`",
            f"- unique juggler names: {len(catalog)}",
            f"- unknown families: {len(unknown_names)}",
            f"- excluded from master: {len(unknown_names)}",
            f"- output slug: `{_hall_slug(hall)}`",
            "## Machine Catalog",
            _render_table(catalog, max_rows=200),
            "## Setting Prob Master",
            _render_table(master, max_rows=200),
        ]
    )
    return {"machine_catalog": catalog, "setting_prob_master": master, "report": report}


def save_stage1_outputs(outputs: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog = outputs["machine_catalog"]
    master = outputs["setting_prob_master"]
    report = outputs["report"]
    assert isinstance(catalog, pd.DataFrame)
    assert isinstance(master, pd.DataFrame)
    assert isinstance(report, str)
    catalog.to_csv(output_dir / "stage1_machine_catalog.csv", index=False, encoding="utf-8-sig")
    master.to_csv(output_dir / "stage1_setting_prob_master.csv", index=False, encoding="utf-8-sig")
    (output_dir / "stage1_summary.md").write_text(report, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 juggler RB setting catalog")
    parser.add_argument("--hall", choices=tuple(HALL_DBS.keys()), default=DEFAULT_HALL)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    args = build_parser().parse_args(argv)
    db_path = _resolve_db_path(args.hall, args.db_path)
    output_dir = Path(args.output_dir) if args.output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall)
    outputs = build_stage1_outputs(db_path=db_path, hall=args.hall)
    save_stage1_outputs(outputs, output_dir)
    print(output_dir)
    print(output_dir / "stage1_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
