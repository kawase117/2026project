"""Use the local Codex CLI to extract machine and number data from tweet images."""

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import ACCOUNTS, DB_PATH


BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "extraction_schema.json"
JST = ZoneInfo("Asia/Tokyo")
DEFAULT_PRIORITY_HALLS = "kamata7_kamata1,rakuen_kamata"
PROMPT = """この画像はパチスロホールの予告・答え合わせ投稿です。
目的は「どの機種の、どの台番号に設定が入っていたか」を構造化して抽出することです。
画像に根拠がある機種名と台番号だけを entries に入れてください。台番号は先頭ゼロを失わない文字列にしてください。

hall_hint は画像内に見えるホール名の生表記です。画像に書かれている表記をそのまま入れ、勝手に正規化・言い換えしないでください。ホール名が見えなければ null にしてください。
表記ゆれの例:
- マルハンメガシティ2000-蒲田1: 「マルハン蒲田1」「メガシティ蒲田1」「メガワン」「サトウ」（店長名呼び）
- マルハンメガシティ2000-蒲田7: 「マルハン蒲田7」「メガシティ蒲田7」
- 楽園蒲田店: 「楽園」「楽園蒲田」
- 他の候補: ヒロキ東口店 / みとや大森町店 / ARROW池上店 / レイトギャップ平和島 / 金時京急蒲田店 / 金時蒲田東口店 / ザ-シティ-ベルシティ雑色店

date_hint は画像が対象とする営業日です。画像に年まで書かれていれば YYYY-MM-DD、月日だけなら画像の表記に基づく M/D を返してください。画像から年を読めない場合に年を推測・補完してはいけません。月日自体が読めなければ null にしてください。年の補完は Codex CLI ではなく Python 側がツイートの posted_at_jst を使って行います。

note は「全台系」「高設定示唆」など機種単位の補足だけを入れ、なければ null にしてください。
必ず指定されたスキーマに合う JSON オブジェクトだけを返してください。"""


def now_jst() -> str:
    return datetime.now(JST).isoformat()


def parse_csv_option(value: str | None) -> list[str]:
    """Parse a comma-separated CLI value while ignoring empty elements."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def initialize_extractions_tables(connection: sqlite3.Connection) -> None:
    """Create/migrate extraction tables without deleting existing records."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS extractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT,
            image_path TEXT,
            hall TEXT,
            event_target TEXT,
            machine_numbers TEXT,
            raw_response TEXT,
            status TEXT,
            extracted_at_jst TEXT,
            hall_hint TEXT,
            date_hint TEXT
        )
        """
    )
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(extractions)").fetchall()}
    for column_name in ("hall_hint", "date_hint"):
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE extractions ADD COLUMN {column_name} TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS extraction_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT,
            image_path TEXT,
            handle TEXT,
            hall TEXT,
            hall_hint TEXT,
            date_hint TEXT,
            machine_name TEXT,
            machine_number TEXT,
            note TEXT,
            extracted_at_jst TEXT
        )
        """
    )
    connection.commit()


def codex_command(image_path: str, output_path: str) -> list[str]:
    """Build the verified non-interactive Codex invocation."""
    codex = shutil.which("codex.cmd") or shutil.which("codex")
    if not codex:
        raise RuntimeError("Local Codex CLI was not found (expected codex or codex.cmd on PATH)")
    return [
        codex,
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--image",
        image_path,
        "--output-schema",
        str(SCHEMA_PATH),
        "--output-last-message",
        output_path,
        PROMPT,
    ]


def validate_extraction(parsed: object) -> dict:
    """Validate the response beyond the JSON Schema enforced by Codex."""
    if not isinstance(parsed, dict):
        raise ValueError("Codex response must be a JSON object")
    if parsed.get("hall_hint") is not None and not isinstance(parsed.get("hall_hint"), str):
        raise ValueError("hall_hint must be a string or null")
    if parsed.get("date_hint") is not None and not isinstance(parsed.get("date_hint"), str):
        raise ValueError("date_hint must be a string or null")
    entries = parsed.get("entries")
    if not isinstance(entries, list):
        raise ValueError("entries must be an array")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("machine_name"), str):
            raise ValueError("each entry must contain a string machine_name")
        numbers = entry.get("machine_numbers")
        if not isinstance(numbers, list) or not all(isinstance(number, str) for number in numbers):
            raise ValueError("each machine_numbers value must be an array of strings")
        if entry.get("note") is not None and not isinstance(entry.get("note"), str):
            raise ValueError("note must be a string or null")
    return parsed


def extract_image(image_path: str) -> tuple[dict, str]:
    """Extract one image without opening or otherwise using the SQLite database."""
    if not SCHEMA_PATH.exists():
        raise RuntimeError(f"Codex output schema is missing: {SCHEMA_PATH}")
    image = Path(image_path)
    if not image.is_file():
        raise FileNotFoundError(f"Image not found: {image}")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir=BASE_DIR) as output_file:
        output_path = output_file.name
    try:
        result = subprocess.run(
            codex_command(str(image), output_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
            # `codex exec` always tries to read additional input from stdin first,
            # even though the prompt is already passed as a positional argument.
            # Without this, stdin is inherited from the parent process; when the
            # parent has no usable stdin (scheduled task, no console), codex hangs
            # or fails immediately with "Reading additional input from stdin...".
            # Confirmed 2026-08-13: every extraction failed this way from
            # 2026-08-12 13:00 JST onward until this fix (reproduced manually,
            # exit 124 without this vs exit 0 in ~12s with it).
            stdin=subprocess.DEVNULL,
        )
        response = Path(output_path).read_text(encoding="utf-8") if Path(output_path).exists() else ""
        raw_response = response or (result.stdout + result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"codex exec exited {result.returncode}: {raw_response}")
        parsed = validate_extraction(json.loads(response))
        return parsed, raw_response
    finally:
        Path(output_path).unlink(missing_ok=True)


def complete_date_hint(date_hint: str | None, posted_at_jst: str) -> str | None:
    """Normalize a full date or complete a month/day using the tweet's JST year."""
    if date_hint is None:
        return None
    value = date_hint.strip()
    if not value:
        return None
    # Campaign images often carry a range ("8/8〜8/16"); keep the start date so the
    # machine data survives instead of failing the whole extraction.
    value = re.split(r"[～〜~]|--|\s+to\s+", value)[0].strip()
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value).isoformat()
    match = re.fullmatch(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", value)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return date(year, month, day).isoformat()

    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})", value)
    if not match:
        raise ValueError(f"Unsupported date_hint format: {date_hint!r}")
    month, day = (int(part) for part in match.groups())
    posted_at = datetime.fromisoformat(posted_at_jst.replace("Z", "+00:00"))
    year = posted_at.year - 1 if month > posted_at.month else posted_at.year
    return date(year, month, day).isoformat()


def select_pending_images(
    connection: sqlite3.Connection,
    handles: list[str],
    halls: list[str],
    priority_halls: list[str],
    limit: int | None,
    newest_first: bool,
    redo_failed: bool,
) -> list[tuple[str, str, str, str]]:
    """Return tweet/image/handle/timestamp rows in the requested processing order."""
    selected_handles = set(handles)
    if halls:
        hall_handles = {handle for handle, details in ACCOUNTS.items() if details["hall"] in halls}
        selected_handles = selected_handles & hall_handles if selected_handles else hall_handles

    conditions = [
        "st.has_image = 1",
        "NOT EXISTS (SELECT 1 FROM extractions AS ok WHERE ok.image_path = ti.image_path AND ok.status = 'success')",
    ]
    parameters: list[object] = []
    if not redo_failed:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM extractions AS attempted WHERE attempted.image_path = ti.image_path)"
        )
    if handles or halls:
        if not selected_handles:
            return []
        placeholders = ", ".join("?" for _ in selected_handles)
        conditions.append(f"st.handle IN ({placeholders})")
        parameters.extend(sorted(selected_handles))

    priority_handles = sorted(handle for handle, details in ACCOUNTS.items() if details["hall"] in priority_halls)
    if priority_handles:
        placeholders = ", ".join("?" for _ in priority_handles)
        priority_order = f"CASE WHEN st.handle IN ({placeholders}) THEN 0 ELSE 1 END,"
        parameters.extend(priority_handles)
    else:
        priority_order = ""
    direction = "DESC" if newest_first else "ASC"
    sql = f"""
        SELECT ti.tweet_id, ti.image_path, st.handle, st.posted_at_jst
        FROM tweet_images AS ti
        JOIN seen_tweets AS st ON st.tweet_id = ti.tweet_id
        WHERE {' AND '.join(conditions)}
        ORDER BY {priority_order} st.posted_at_jst {direction}, ti.id {direction}
    """
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(limit)
    return connection.execute(sql, parameters).fetchall()


def store_success(
    connection: sqlite3.Connection,
    tweet_id: str,
    image_path: str,
    handle: str,
    posted_at_jst: str,
    parsed: dict,
    raw_response: str,
) -> None:
    hall = ACCOUNTS[handle]["hall"]
    hall_hint = parsed["hall_hint"]
    date_hint = complete_date_hint(parsed["date_hint"], posted_at_jst)
    extracted_at = now_jst()
    connection.execute(
        """
        INSERT INTO extractions
        (tweet_id, image_path, hall, event_target, machine_numbers, raw_response,
         status, extracted_at_jst, hall_hint, date_hint)
        VALUES (?, ?, ?, NULL, NULL, ?, 'success', ?, ?, ?)
        """,
        (tweet_id, image_path, hall, raw_response, extracted_at, hall_hint, date_hint),
    )
    for entry in parsed["entries"]:
        for machine_number in entry["machine_numbers"]:
            connection.execute(
                """
                INSERT INTO extraction_entries
                (tweet_id, image_path, handle, hall, hall_hint, date_hint,
                 machine_name, machine_number, note, extracted_at_jst)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tweet_id,
                    image_path,
                    handle,
                    hall,
                    hall_hint,
                    date_hint,
                    entry["machine_name"],
                    machine_number,
                    entry["note"],
                    extracted_at,
                ),
            )


def store_failure(
    connection: sqlite3.Connection,
    tweet_id: str,
    image_path: str,
    handle: str,
    error: Exception,
) -> None:
    hall = ACCOUNTS.get(handle, {}).get("hall")
    connection.execute(
        """
        INSERT INTO extractions
        (tweet_id, image_path, hall, event_target, machine_numbers, raw_response,
         status, extracted_at_jst, hall_hint, date_hint)
        VALUES (?, ?, ?, NULL, NULL, ?, 'failed', ?, NULL, NULL)
        """,
        (tweet_id, image_path, hall, str(error), now_jst()),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handles", help="Comma-separated account handles to process")
    parser.add_argument("--halls", help="Comma-separated config.py hall values to process")
    parser.add_argument(
        "--priority-halls",
        nargs="?",
        const=DEFAULT_PRIORITY_HALLS,
        default=DEFAULT_PRIORITY_HALLS,
        help=f"Comma-separated halls to process first (default: {DEFAULT_PRIORITY_HALLS})",
    )
    parser.add_argument("--limit", type=int, help="Maximum number of images to process")
    parser.add_argument(
        "--newest-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Process newer tweets first (default: true; use --no-newest-first for oldest first)",
    )
    parser.add_argument(
        "--redo-failed",
        action="store_true",
        help="Retry images that have failed records but no success record",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    handles = parse_csv_option(args.handles)
    halls = parse_csv_option(args.halls)
    priority_halls = parse_csv_option(args.priority_halls)
    unknown_handles = sorted(set(handles) - set(ACCOUNTS))
    known_halls = {details["hall"] for details in ACCOUNTS.values()}
    unknown_halls = sorted(set(halls) - known_halls)
    unknown_priority_halls = sorted(set(priority_halls) - known_halls)
    if unknown_handles:
        raise SystemExit(f"Unknown handle(s): {', '.join(unknown_handles)}")
    if unknown_halls:
        raise SystemExit(f"Unknown hall(s): {', '.join(unknown_halls)}")
    if unknown_priority_halls:
        raise SystemExit(f"Unknown priority hall(s): {', '.join(unknown_priority_halls)}")
    if not DB_PATH.exists():
        raise SystemExit(f"Tweet database not found: {DB_PATH}. Run scrape_tweets.py first.")

    with sqlite3.connect(DB_PATH, timeout=60) as connection:
        initialize_extractions_tables(connection)
        rows = select_pending_images(
            connection,
            handles=handles,
            halls=halls,
            priority_halls=priority_halls,
            limit=args.limit,
            newest_first=args.newest_first,
            redo_failed=args.redo_failed,
        )
        try:
            for tweet_id, image_path, handle, posted_at_jst in rows:
                try:
                    parsed, raw_response = extract_image(image_path)
                    store_success(
                        connection,
                        tweet_id,
                        image_path,
                        handle,
                        posted_at_jst,
                        parsed,
                        raw_response,
                    )
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    KeyError,
                    json.JSONDecodeError,
                    subprocess.TimeoutExpired,
                ) as error:
                    connection.rollback()
                    store_failure(connection, tweet_id, image_path, handle, error)
                connection.commit()
        except KeyboardInterrupt:
            connection.rollback()
            print("\n中断しました。処理済み画像は保存されています。")
            return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
