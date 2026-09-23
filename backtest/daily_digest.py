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
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
MONITOR_DIR = BASE_DIR / "scraper" / "twitter_monitor"
DB_DIR = BASE_DIR / "db"

if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from run_daily import HALL_KEYWORDS, is_forecast, mention_strength, target_date_of  # noqa: E402

from backtest.announce import db_max_date  # noqa: E402
from backtest.bonus_specs import find_spec, load_specs, posterior, MIN_GAMES_FOR_JUDGEMENT  # noqa: E402
from backtest.event_days import active as event_days_active, load as event_days_load  # noqa: E402
from backtest.model_standing import standing  # noqa: E402
from backtest.narabi import find_blocks, load_day  # noqa: E402
from database import analysis_store  # noqa: E402


JST = ZoneInfo("Asia/Tokyo")
STATE_DB = MONITOR_DIR / "state.db"
LEDGER_PATH = BASE_DIR / "backtest" / "announce" / "LEDGER.jsonl"
ANNOUNCE_DIR = BASE_DIR / "backtest" / "announce"
WATCH_DIR = BASE_DIR / "backtest" / "daily_digest" / "watches"
REVIEW_DIR = BASE_DIR / "backtest" / "daily_digest" / "reviews"

# hall-review はフェーズ2として、machine_layout_history が整備されている
# 3ホールに限定する（database/CLAUDE.md: 雑色ほか5ホールは machine_layout 自体が
# 空。角番・並び軸がそもそも計算できない）。残り6ホールへの展開はフェーズ3。
HALL_REVIEW_HALLS = (
    "楽園蒲田店",
    "マルハンメガシティ2000-蒲田1",
    "マルハンメガシティ2000-蒲田7",
)
# 全台設定6の特殊日。この日は軸評価そのものが無意味なのでスキップする。
ALL_SETTING6_DATES = {
    "マルハンメガシティ2000-蒲田7": {"20260707"},
}
# 新台は設定不問で高回転するため、初出からこの日数未満は machine/rb_settings 軸から除外する
NEW_MACHINE_MIN_DAYS = 7
# 高稼働軸の層別に使う直近日数（当日を含む）
TRAFFIC_LOOKBACK_DAYS = 30
NORMAL_KEYWORDS = ("ジャグラー", "ハナハナ", "ハナビ")


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


def _shift(day_text: str, delta_days: int) -> str:
    return (datetime.strptime(day_text, "%Y%m%d") + timedelta(days=delta_days)).strftime("%Y%m%d")


def _ro_hall(hall: str) -> sqlite3.Connection:
    path = DB_DIR / f"{hall}.db"
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _hall_avg_games(connection: sqlite3.Connection, target_date: str) -> float | None:
    row = connection.execute(
        "SELECT AVG(games_normalized) FROM machine_detailed_results WHERE date = ? AND games_normalized > 0",
        (target_date,),
    ).fetchone()
    return row[0] if row and row[0] else None


def _traffic_stratum(connection: sqlite3.Connection, target_date: str) -> str | None:
    """直近 TRAFFIC_LOOKBACK_DAYS 日の avg_games_per_machine の中で target_date が
    上位/中位/下位のどこに入るかで層別する。他の全軸の解釈はこれを前提にする
    （層別なしで数値だけ出さない、という要件）。
    """
    since = _shift(target_date, -(TRAFFIC_LOOKBACK_DAYS - 1))
    rows = connection.execute(
        "SELECT date, avg_games_per_machine FROM daily_hall_summary "
        " WHERE date BETWEEN ? AND ? AND avg_games_per_machine IS NOT NULL ORDER BY avg_games_per_machine",
        (since, target_date),
    ).fetchall()
    if not rows:
        return None
    values = [r[1] for r in rows]
    target_row = next((r for r in rows if r[0] == target_date), None)
    if target_row is None:
        return None
    target_value = target_row[1]
    rank = sum(1 for v in values if v <= target_value) / len(values)
    if rank >= 2 / 3:
        return "高稼働"
    if rank <= 1 / 3:
        return "低稼働"
    return "中稼働"


def _new_machine_names(connection: sqlite3.Connection, target_date: str) -> set[str]:
    """target_date時点で初出からNEW_MACHINE_MIN_DAYS日未満の機種名。"""
    names = [
        r[0]
        for r in connection.execute(
            "SELECT DISTINCT machine_name FROM machine_detailed_results WHERE date = ?", (target_date,)
        )
    ]
    if not names:
        return set()
    placeholders = ",".join("?" * len(names))
    rows = connection.execute(
        f"SELECT machine_name, MIN(date) FROM machine_detailed_results "
        f"WHERE machine_name IN ({placeholders}) GROUP BY machine_name",
        names,
    ).fetchall()
    target = datetime.strptime(target_date, "%Y%m%d")
    excluded = set()
    for name, min_date in rows:
        if not min_date:
            continue
        age_days = (target - datetime.strptime(min_date, "%Y%m%d")).days
        if age_days < NEW_MACHINE_MIN_DAYS:
            excluded.add(name)
    return excluded


def _machine_axis(hall: str, target_date: str, excluded_names: set[str]) -> dict:
    board = standing(hall, as_of=target_date)
    if board is None:
        return {"hot": [], "cold": [], "note": "データ不足（standing()がNoneを返した）"}
    board = board[~board.index.isin(excluded_names)]
    if board.empty:
        return {"hot": [], "cold": [], "note": "新台除外後にデータが残らなかった"}
    board = board.sort_values("edge", ascending=False)

    def _rows(frame):
        return [
            {
                "name": str(name),
                "edge": round(float(row.edge), 1),
                "pct": round(float(row.pct), 3),
                "n_machines": int(row.machines),
                "games_ratio": round(float(row.games_ratio), 3),
            }
            for name, row in frame.iterrows()
        ]

    return {"hot": _rows(board.head(5)), "cold": _rows(board.tail(5).iloc[::-1])}


def _kakuban_axis(connection: sqlite3.Connection, hall: str, target_date: str, hall_avg_games: float | None) -> dict:
    store_con = analysis_store.connect()
    try:
        rows = analysis_store.daily(store_con, "kakuban_residual", hall=hall, since=target_date)
    finally:
        store_con.close()
    rows = [r for r in rows if r[0] == target_date]
    if not rows:
        return {"applicable": False, "note": "レイアウトデータ不足、または対象日に十分な台数が無い"}

    # games_ratio は kakuban_residual に保存されていないため、全館ベースで別途計算する
    # （セグメント別のgames_ratioは今回のフェーズでは未対応。全館の値を参考値として使う）
    games_by_rank: dict[str, float] = {}
    if hall_avg_games:
        for rank, avg_games in connection.execute(
            "SELECT MIN(l.rank_from_min, l.rank_from_max) AS rk, AVG(m.games_normalized) "
            "FROM machine_detailed_results m JOIN machine_layout_history l "
            "  ON l.machine_number = m.machine_number "
            " AND m.date >= l.valid_from AND (l.valid_to IS NULL OR m.date <= l.valid_to) "
            "WHERE m.date = ? AND m.games_normalized > 0 AND l.rank_from_min IS NOT NULL "
            "GROUP BY rk",
            (target_date,),
        ):
            if rank is not None and avg_games:
                games_by_rank[str(int(rank))] = round(avg_games / hall_avg_games, 3)

    segments: dict[str, dict] = {}
    for _date, _hall, _version, segment, item, value_num, n in rows:
        seg = segments.setdefault(segment, {"peak_rank": None, "rows": []})
        if item == "peak":
            seg["peak_rank"] = (value_num, n)  # 一時保持。下で角番表記に変換
            continue
        if item.startswith("角"):
            rank = item[1:]
            seg["rows"].append(
                {
                    "rank": rank,
                    "residual": value_num,
                    "games_ratio": games_by_rank.get(rank, "全館ベースの値が無い(参考値なし)"),
                    "n": n,
                }
            )
    for segment, seg in segments.items():
        if seg["peak_rank"] is not None:
            value_num, n = seg["peak_rank"]
            match = next((r for r in seg["rows"] if r["residual"] == value_num), None)
            seg["peak_rank"] = match["rank"] if match else None
    return {"applicable": True, "games_ratio_basis": "全館ベース(セグメント別未対応)", "segments": segments}


def _narabi_axis(hall: str, target_date: str, hall_avg_games: float | None) -> dict:
    with _ro_hall(hall) as connection:
        machines = load_day(connection, target_date)
    blocks = find_blocks(machines)
    out = []
    for block in blocks:
        block_games = [m["games"] for m in block["machines"] if m.get("games")]
        games_ratio = (sum(block_games) / len(block_games) / hall_avg_games) if block_games and hall_avg_games else None
        out.append(
            {
                "start": block["start"],
                "section": block["section"],
                "mean_diff": round(block["mean_diff"], 1),
                "games_ratio": round(games_ratio, 3) if games_ratio is not None else None,
                "segments": block["segments"],
                "names": block["names"],
            }
        )
    return {"blocks": out, "count": len(out)}


def _last_digit_axis(connection: sqlite3.Connection, target_date: str, hall_avg_games: float | None) -> dict:
    rows = connection.execute(
        "SELECT last_digit, AVG(diff_coins_normalized), AVG(games_normalized), "
        "       COUNT(DISTINCT machine_number), SUM(CASE WHEN is_zorome THEN 1 ELSE 0 END) "
        "FROM machine_detailed_results WHERE date = ? AND games_normalized > 0 "
        "GROUP BY last_digit ORDER BY last_digit",
        (target_date,),
    ).fetchall()
    out = []
    for digit, mean_diff, mean_games, n, n_zorome in rows:
        games_ratio = round(mean_games / hall_avg_games, 3) if hall_avg_games and mean_games else None
        out.append(
            {
                "digit": digit,
                "mean_diff": round(mean_diff, 1) if mean_diff is not None else None,
                "games_ratio": games_ratio,
                "n": n,
                "n_zorome": n_zorome,
            }
        )
    return {
        "rows": out,
        "decoy_warning": (
            "二値flag台数だけで順位付けしない。ホールは本命末尾を隠すため別末尾に"
            "少数の高設定を混ぜる撒き餌のリスクがある（フェイク末尾）。"
        ),
    }


def _rb_settings_axis(connection: sqlite3.Connection, target_date: str, excluded_names: set[str]) -> dict:
    judgeable = {
        r[0]
        for r in connection.execute(
            "SELECT machine_name_normalized FROM machine_master "
            "WHERE spec_category IN ('ノーマル','BT','A+AT') AND bonus_judgeable = 1"
        )
    }
    rows = connection.execute(
        "SELECT machine_name, machine_number, games_normalized, bb_count, rb_count "
        "FROM machine_detailed_results WHERE date = ? AND games_normalized > 0",
        (target_date,),
    ).fetchall()
    total_machines = len({r[1] for r in rows})
    specs = load_specs()
    out = []
    for name, number, games, bb, rb in rows:
        if name not in judgeable or name in excluded_names:
            continue
        spec = find_spec(name, specs)
        if spec is None or not spec.get("judgeable"):
            continue
        probs = posterior(spec, games, bb, rb)
        out.append(
            {
                "name": name,
                "number": number,
                "category": spec["category"],
                "games": games,
                "bb": bb,
                "rb": rb,
                "posterior": {str(s): round(p, 4) for s, p in probs.items()},
                "below_min_games": games < MIN_GAMES_FOR_JUDGEMENT,
            }
        )
    coverage_pct = round(len(out) / total_machines, 3) if total_machines else None
    return {"coverage_pct": coverage_pct, "machines": out}


def _event_for(hall: str, target_date: str) -> dict | None:
    for record in event_days_active(event_days_load()):
        if record.get("hall") == hall and record.get("date") == target_date:
            return record
    return None


def build_hall_review(hall: str, target_date: str, generated_at: datetime | None = None) -> dict:
    generated = _now_jst(generated_at)

    if hall not in HALL_REVIEW_HALLS:
        raise ValueError(f"hall-review はフェーズ2として次の3ホールのみ対象: {HALL_REVIEW_HALLS}")

    with _ro_hall(hall) as connection:
        data_asof = connection.execute("SELECT MAX(date) FROM machine_detailed_results").fetchone()[0]
        if not data_asof or target_date > data_asof:
            return {
                "hall": hall,
                "target_date": target_date,
                "generated_at": generated.isoformat(),
                "data_asof": data_asof,
                "skipped": True,
                "note": "target_date のデータがまだ無い（ana-slo未公開、または取り込み未完了）",
            }

        if target_date in ALL_SETTING6_DATES.get(hall, set()):
            return {
                "hall": hall,
                "target_date": target_date,
                "generated_at": generated.isoformat(),
                "data_asof": data_asof,
                "note": "全台設定6の特殊日のため軸評価をスキップ",
            }

        traffic_stratum = _traffic_stratum(connection, target_date)
        excluded_new_machines = sorted(_new_machine_names(connection, target_date))
        hall_avg_games = _hall_avg_games(connection, target_date)

        result = {
            "hall": hall,
            "target_date": target_date,
            "generated_at": generated.isoformat(),
            "data_asof": data_asof,
            "data_lag_days": (datetime.strptime(target_date, "%Y%m%d") - datetime.strptime(data_asof, "%Y%m%d")).days,
            "traffic_stratum": traffic_stratum,
            "excluded_new_machines": excluded_new_machines,
            "axes": {
                "machine": _machine_axis(hall, target_date, set(excluded_new_machines)),
                "kakuban": _kakuban_axis(connection, hall, target_date, hall_avg_games),
                "last_digit": _last_digit_axis(connection, target_date, hall_avg_games),
                "row": {"applicable": False, "note": "列軸はフェーズ3で設計予定。未実装"},
                "rb_settings": _rb_settings_axis(connection, target_date, set(excluded_new_machines)),
            },
        }

    result["axes"]["narabi"] = _narabi_axis(hall, target_date, hall_avg_games)

    event = _event_for(hall, target_date)
    result["is_event_day"] = event is not None
    result["event"] = event
    return result


def _default_target_date() -> str:
    return _shift(_now_jst().date().strftime("%Y%m%d"), -1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    watch = subparsers.add_parser("announce-watch", help="本日投稿された予告を過去実績と突き合わせる")
    watch.add_argument("--date", help="YYYYMMDD。省略時は実行時のJST日付")

    review = subparsers.add_parser("hall-review", help="昨日のホール実績を軸別に振り返る（フェーズ2: 3ホール限定）")
    review.add_argument("--hall", help="対象ホール名（HALL_REVIEW_HALLSのいずれか）")
    review.add_argument("--all-halls", action="store_true", help="HALL_REVIEW_HALLS全件をループする")
    review.add_argument("--date", help="YYYYMMDD（target_date）。省略時は実行時JSTの前日")

    args = parser.parse_args(argv)

    if args.command == "announce-watch":
        run_date = _now_jst().date() if args.date is None else _parse_date(args.date)

        output = build_digest(run_date)

        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        output_path = WATCH_DIR / f"{run_date:%Y%m%d}.json"
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        announce_count = sum(len(hall["announces"]) for hall in output["halls"])
        print(f"wrote {output_path} ({announce_count} announces)")
        return 0

    if args.command == "hall-review":
        if not args.all_halls and not args.hall:
            parser.error("--hall か --all-halls のどちらかを指定すること")
        target_date = args.date if args.date else _default_target_date()
        target_halls = list(HALL_REVIEW_HALLS) if args.all_halls else [args.hall]

        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        for hall in target_halls:
            output = build_hall_review(hall, target_date)
            output_path = REVIEW_DIR / f"{hall}__{target_date}.json"
            output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            note = output.get("note", "")
            print(f"wrote {output_path}{'  (' + note + ')' if note else ''}")
        return 0

    parser.error(f"未知のコマンド: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
