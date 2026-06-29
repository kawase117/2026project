from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from .config import PROJECT_ROOT
from .predict_gated import main as predict_gated_main
from .predict_section import main as predict_section_main

DATABASE_DIR = PROJECT_ROOT / "database"
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

from incremental_db_updater import IncrementalDBUpdater

SCRAPER_PATH = PROJECT_ROOT / "scraper" / "anaslo-scraper_multi.py"
DEFAULT_HALL_ARG = "蒲田7"
DEFAULT_HALL_NAME = "マルハンメガシティ2000-蒲田7"
HALL_ALIASES = {
    "蒲田7": DEFAULT_HALL_NAME,
    "蒲田七": DEFAULT_HALL_NAME,
    "kamata7": DEFAULT_HALL_NAME,
}


class PipelineError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run scrape -> DB update -> predict_gated for a single target day"
    )
    parser.add_argument("--date", help="Target date in YYYYMMDD format; defaults to yesterday")
    parser.add_argument("--hall", default=DEFAULT_HALL_ARG, help="Hall alias or exact hall name")
    parser.add_argument("--skip-scrape", action="store_true", help="Skip scraper step when JSON already exists")
    parser.add_argument("--skip-db", action="store_true", help="Skip DB update step when DB already contains the date")
    return parser


def resolve_hall_name(hall_arg: str) -> str:
    return HALL_ALIASES.get(hall_arg, hall_arg)


def resolve_target_date(date_arg: str | None, *, today: date | None = None) -> str:
    if date_arg:
        try:
            parsed = date.fromisoformat(f"{date_arg[:4]}-{date_arg[4:6]}-{date_arg[6:8]}")
        except ValueError as exc:
            raise PipelineError(f"invalid --date value: {date_arg}") from exc
        return parsed.strftime("%Y%m%d")

    base = today or date.today()
    return (base - timedelta(days=1)).strftime("%Y%m%d")


def db_path_for_hall(hall_name: str) -> Path:
    safe_hall_name = hall_name.replace(" ", "_").replace("（", "(").replace("）", ")")
    return PROJECT_ROOT / "db" / f"{safe_hall_name}.db"


def json_path_for(hall_name: str, date_str: str) -> Path:
    return PROJECT_ROOT / "data" / hall_name / f"{date_str}_{hall_name}_data.json"


def _json_exists(path: Path) -> bool:
    return path.exists()


def _db_has_date(db_path: Path, date_str: str) -> bool:
    if not db_path.exists():
        return False

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM machine_detailed_results WHERE date = ? LIMIT 1",
                (date_str,),
            )
            return cursor.fetchone() is not None
    except sqlite3.Error:
        return False


@lru_cache(maxsize=1)
def scraper_supports_cli() -> bool:
    try:
        text = SCRAPER_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    return "--date" in text and "--hall" in text and "argparse" in text


def run_scraper(date_str: str, hall_name: str) -> None:
    if not scraper_supports_cli():
        raise PipelineError(
            "scraper/anaslo-scraper_multi.py does not support --date/--hall in this repo; "
            "use --skip-scrape with pre-generated JSON"
        )

    subprocess.run(
        [sys.executable, str(SCRAPER_PATH), "--date", date_str, "--hall", hall_name],
        check=True,
    )


def run_db_update(hall_name: str, db_path: Path) -> dict:
    updater = IncrementalDBUpdater(hall_name=hall_name, db_path=str(db_path))
    return updater.run()


def run_predict_gated(date_str: str, db_path: Path) -> int:
    try:
        result = predict_gated_main(["--date", date_str, "--db-path", str(db_path)])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return code
    return int(result or 0)


def run_predict_section(date_str: str, db_path: Path) -> int:
    try:
        result = predict_section_main([
            "--date", date_str,
            "--db-path", str(db_path),
            "--top-sections", "10",
            "--top-machines-per-section", "5",
        ])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return code
    return int(result or 0)


def run_pipeline(args: argparse.Namespace) -> int:
    hall_name = resolve_hall_name(args.hall)
    date_str = resolve_target_date(args.date)
    json_path = json_path_for(hall_name, date_str)
    db_path = db_path_for_hall(hall_name)

    print(f"[DATE] target={date_str}")
    print(f"[HALL] hall={hall_name}")
    print(f"[JSON] {json_path}")
    print(f"[DB] {db_path}")

    if _json_exists(json_path):
        print(f"[SKIP] scrape: existing JSON found at {json_path}", file=sys.stderr)
    else:
        if args.skip_scrape:
            raise PipelineError(
                f"JSON file not found for {date_str}: {json_path}. "
                "Use --skip-scrape only when the file already exists."
            )
        print("[STEP] scrape", file=sys.stderr)
        run_scraper(date_str, hall_name)
        if not _json_exists(json_path):
            raise PipelineError(f"scrape finished but JSON is still missing: {json_path}")
        print(f"[OK] scrape -> {json_path}", file=sys.stderr)

    if _db_has_date(db_path, date_str):
        print(f"[SKIP] db: {date_str} already present in {db_path}", file=sys.stderr)
    else:
        if args.skip_db:
            raise PipelineError(
                f"DB does not contain {date_str} yet: {db_path}. "
                "Use --skip-db only when the date is already registered."
            )
        print("[STEP] db", file=sys.stderr)
        result = run_db_update(hall_name, db_path)
        if not _db_has_date(db_path, date_str):
            message = result.get("message", "DB update finished but target date is still missing")
            raise PipelineError(f"{message}: {date_str} not found in {db_path}")
        print(f"[OK] db -> {result.get('message', 'updated')}", file=sys.stderr)

    if not _db_has_date(db_path, date_str):
        raise PipelineError(f"predict_gated requires {date_str} in DB: {db_path}")

    print("[STEP] predict_section", file=sys.stderr)
    section_rc = run_predict_section(date_str, db_path)
    if section_rc != 0:
        print(f"WARNING: predict_section failed with exit code {section_rc}", file=sys.stderr)
    else:
        print("[OK] predict_section", file=sys.stderr)

    print("[STEP] predict_gated", file=sys.stderr)
    predict_rc = run_predict_gated(date_str, db_path)
    if predict_rc != 0:
        raise PipelineError(f"predict_gated failed with exit code {predict_rc}")
    print("[OK] predict_gated", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    try:
        return run_pipeline(args)
    except PipelineError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
