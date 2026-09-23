"""Generate a per-day announce watch digest from the Twitter monitor state.

使い方
------
    venv/Scripts/python.exe -X utf8 -m backtest.daily_digest announce-watch --date 20260924

引数なしなら実行時のJST日付を使う。出力は backtest/daily_digest/watches/{date}.json。

再利用方針
----------
「予告か」の判定・対象日の抽出・言及の強さ判定は
scraper/twitter_monitor/run_daily.py の is_forecast() / target_date_of() /
mention_strength() をそのまま使う（別実装を作らない）。
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
MONITOR_DIR = BASE_DIR / "scraper" / "twitter_monitor"

if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from run_daily import HALL_KEYWORDS, is_forecast, mention_strength, target_date_of  # noqa: E402

from backtest.announce import db_max_date  # noqa: E402


JST = ZoneInfo("Asia/Tokyo")
STATE_DB = MONITOR_DIR / "state.db"
LEDGER_PATH = BASE_DIR / "backtest" / "announce" / "LEDGER.jsonl"
ANNOUNCE_DIR = BASE_DIR / "backtest" / "announce"
WATCH_DIR = BASE_DIR / "backtest" / "daily_digest" / "watches"


def _now_jst(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(JST)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware; naive datetime is not allowed")
    return now.astimezone(JST)


def _parse_date(value: str) -> date:
    if len(value) != 8 or not value.isdigit():
        raise ValueError("date must be YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("date must be a valid YYYYMMDD date") from exc


def _jst_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("datetime values must be timezone-aware; naive datetime is not allowed")
    return parsed.astimezone(JST)


def _load_ledger() -> tuple[list[dict], set[tuple[str, str]]]:
    rows = []
    registered = set()

    if not LEDGER_PATH.exists():
        return rows, registered

    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        rows.append(row)
        if row.get("hall") and row.get("target_date"):
            registered.add((row["hall"], row["target_date"]))

    return rows, registered


def _claim_stats(ledger_rows: list[dict], account: str, hall: str) -> dict | None:
    """アカウント×ホール単位で過去の的中率を集計する。

    account_track_record は account情報が announce JSON 側に一件も無いホールに
    ついてのみ None を返す（= このホールでは account によるアカウント別追跡が
    そもそもできないスキーマだった、という意味）。account フィールドが欠けている
    個々のレコード（24/80件、旧フォーマット）は、その1件だけを読み飛ばす
    （2026-09-24 実測: source.account 有り56件・無し24件。1件でも欠けたら
    return None していた旧実装は、ほぼ全ホールの実績を隠してしまうバグだった）。
    """
    totals = {"n_claims": 0, "n_hit": 0, "n_miss": 0, "n_unknown": 0}
    hall_supports_account = False

    for ledger_row in ledger_rows:
        if ledger_row.get("hall") != hall:
            continue

        key = ledger_row.get("key")
        if not key:
            continue

        result_path = ANNOUNCE_DIR / f"{key}.json"
        if not result_path.exists():
            continue

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as _exc:
            continue

        result_account = (result.get("source") or {}).get("account")
        if result_account is None:
            # このレコードは旧フォーマットで account を持たない。このレコード
            # だけを除外し、他のレコードの集計は続ける（ホール全体を諦めない）。
            continue

        hall_supports_account = True
        if result_account != account:
            continue

        for claim in (result.get("result") or {}).get("claims") or []:
            hit = claim.get("hit")
            totals["n_claims"] += 1
            if hit is True:
                totals["n_hit"] += 1
            elif hit is False:
                totals["n_miss"] += 1
            else:
                totals["n_unknown"] += 1

    if not hall_supports_account:
        # このホールの announce JSON には account 情報が一件も無い
        # （スキーマ未対応、または該当ホールの登録が無い）。推測で埋めない。
        return None

    known = totals["n_hit"] + totals["n_miss"]
    return {
        "hall": hall,
        **totals,
        "hit_rate_known": totals["n_hit"] / known if known else None,
    }


def _register_note(registered: bool, blocked: bool) -> str:
    if blocked:
        return "target_date <= db_max のため登録不可（事後登録）"
    if registered:
        return "登録済み"
    return "未登録。target_date > db_max なので当日中に announce.py register へ回せる"


def build_digest(run_date: date, generated_at: datetime | None = None) -> dict:
    run_date_text = run_date.strftime("%Y%m%d")
    generated = _now_jst(generated_at)

    ledger_rows, registered_targets = _load_ledger()
    halls = [{"hall": hall, "announces": []} for hall in HALL_KEYWORDS]
    hall_output = {entry["hall"]: entry for entry in halls}
    db_max_cache: dict[str, str] = {}

    with sqlite3.connect(STATE_DB) as connection:
        rows = connection.execute(
            """
            SELECT
                handle,
                tweet_url,
                posted_at_jst,
                COALESCE(full_text, tweet_text, '')
            FROM seen_tweets
            WHERE substr(posted_at_jst, 1, 10) = ?
            ORDER BY posted_at_jst, tweet_id
            """,
            (run_date.isoformat(),),
        ).fetchall()

    for account, tweet_url, posted_at_text, claim_raw_text in rows:
        posted_at = _jst_datetime(posted_at_text)
        text = claim_raw_text or ""

        if not is_forecast(text):
            continue

        header = "\n".join(text.splitlines()[:2])
        n_halls_mentioned = sum(any(keyword in text for keyword in keywords) for keywords in HALL_KEYWORDS.values())
        target_text = target_date_of(text, posted_at.date()).strftime("%Y%m%d")

        for hall, keywords in HALL_KEYWORDS.items():
            strength = mention_strength(text, header, keywords, n_halls_mentioned)
            if strength <= 0:
                continue

            if hall not in db_max_cache:
                db_max_cache[hall] = db_max_date(hall)

            register_blocked = target_text <= db_max_cache[hall]
            registered = (hall, target_text) in registered_targets

            hall_output[hall]["announces"].append(
                {
                    "account": account,
                    "tweet_url": tweet_url,
                    "posted_at": posted_at.isoformat(),
                    "target_date": target_text,
                    "mention_strength": strength,
                    "claim_raw_text": text,
                    "account_track_record": _claim_stats(ledger_rows, account, hall),
                    "registered": registered,
                    "register_blocked": register_blocked,
                    "register_note": _register_note(registered, register_blocked),
                }
            )

    return {
        "date": run_date_text,
        "generated_at": generated.isoformat(),
        "halls": halls,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    watch = subparsers.add_parser("announce-watch", help="本日投稿された予告を過去実績と突き合わせる")
    watch.add_argument("--date", help="YYYYMMDD。省略時は実行時のJST日付")

    args = parser.parse_args(argv)

    run_date = _now_jst().date() if args.date is None else _parse_date(args.date)

    output = build_digest(run_date)

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    output_path = WATCH_DIR / f"{run_date:%Y%m%d}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    announce_count = sum(len(hall["announces"]) for hall in output["halls"])
    print(f"wrote {output_path} ({announce_count} announces)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
