"""Generate a per-day announce watch digest from the Twitter monitor state.

使い方
------
    venv/Scripts/python.exe -X utf8 -m backtest.daily_digest announce-watch --date 20260924

`--date` は「予告が対象とする日（target_date）」であって、投稿日ではない。
前夜投稿・翌日対象の予告を拾うため、投稿日は [target_date-1, target_date] の窓で
スキャンする（2026-09-24 に判明した設計ミスの修正。詳細は build_digest() 参照）。
X監視(scraper/twitter_monitor/run_daily.py)は毎日03:00に実行されるので、
--date を省略して当日JST日付のまま03:00直後に回せば、前夜投稿の予告を
その日のうちに（朝の作業前に）拾える。

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

# 列軸: machine_layout_history.section（"2001-2010"のような台番号-台番号形式の
# 物理島の識別子）そのものを1単位として集計する。角番（section内の順位）・並び
# （section内の連番サブブロック）とは異なり、島全体を1つの塊として見る軸。
# section は x固定・y連続（縦列）だけでなく y固定・x連続（横列）の島も含む
# （2026-09-24 実測: 楽園蒲田で17 section が横列だった）。縦横を区別せず
# machine_layout_history の物理的な隣接単位をそのまま「列」と呼ぶ。
# 蒲田7の曜日別知見（火=角番/水=末尾/木=ニブイチ/金=列1台/土=3台並び/
# 月=列全体/日=機種1台）の「列」はこの意味（2026-09-24 ユーザー訂正）。
#
# 座標X値ベースの実装だった旧版は誤りだった（座標は蒲田1で合成の疑いがあり
# 使えないうえ、そもそも「列」の定義がsectionではなかった）。section は
# machine_layout_history から取得するため、座標の信頼性問題を回避でき、
# 3ホール全てで使える。
ROW_AXIS_MIN_SECTION_SIZE = 2
ROW_AXIS_TOP_N = 10
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


# 予告は「前夜投稿・翌営業日が対象」か「当日投稿・当日が対象」のどちらかにしかならない
# （run_daily.py の target_date_of() の仕様）。よって target_date の予告を漏らさず拾うには
# target_date 当日だけでなく前日投稿分もスキャンする必要がある。
ANNOUNCE_SCAN_LOOKBACK_DAYS = 1


def build_digest(target_date: date, generated_at: datetime | None = None) -> dict:
    """target_date を対象とする予告を集める。

    2026-09-24 に判明した設計ミスの修正: 当初は「run_date に投稿されたツイート」を
    検索してから対象日を計算していたため、03:00（Twitter収集直後）に前夜投稿・
    翌日対象の予告を拾おうとすると、前夜分の posted_at_jst が「昨日」の日付になり
    素通りしていた。target_date を軸にし、投稿日を [target_date-1, target_date] の
    窓でスキャンしてから target_date_of() で対象日を計算し直し、一致するものだけ残す。
    """
    target_text = target_date.strftime("%Y%m%d")
    generated = _now_jst(generated_at)
    scan_since = (target_date - timedelta(days=ANNOUNCE_SCAN_LOOKBACK_DAYS)).isoformat()
    scan_until = target_date.isoformat()

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
            WHERE substr(posted_at_jst, 1, 10) BETWEEN ? AND ?
            ORDER BY posted_at_jst, tweet_id
            """,
            (scan_since, scan_until),
        ).fetchall()

    for account, tweet_url, posted_at_text, claim_raw_text in rows:
        posted_at = _jst_datetime(posted_at_text)
        text = claim_raw_text or ""

        if not is_forecast(text):
            continue

        computed_target = target_date_of(text, posted_at.date()).strftime("%Y%m%d")
        if computed_target != target_text:
            continue

        header = "\n".join(text.splitlines()[:2])
        n_halls_mentioned = sum(any(keyword in text for keyword in keywords) for keywords in HALL_KEYWORDS.values())

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
        "target_date": target_text,
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
        "SELECT AVG(games_normalized) FROM machine_detailed_results WHERE date = ?",
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


def _today_mean_diff(connection: sqlite3.Connection, target_date: str) -> dict[str, dict]:
    """当日1日だけの機種別・生の平均差枚（台×台の単純平均）と勝率。

    `standing()` の edge（60日窓・対ホール平均）とは別物。当日の実績をそのまま
    見たいという要望のため、機種テーブルには両方を並べて出す。
    """
    rows = connection.execute(
        "SELECT machine_name, AVG(diff_coins_normalized), "
        "       AVG(CASE WHEN diff_coins_normalized > 0 THEN 1.0 ELSE 0.0 END), COUNT(*) "
        "FROM machine_detailed_results WHERE date = ? "
        "GROUP BY machine_name",
        (target_date,),
    ).fetchall()
    return {
        name: {"mean_diff": mean_diff, "win_rate": win_rate, "n": n}
        for name, mean_diff, win_rate, n in rows
        if mean_diff is not None
    }


def _machine_axis(connection: sqlite3.Connection, hall: str, target_date: str, excluded_names: set[str]) -> dict:
    board = standing(hall, as_of=target_date)
    if board is None:
        return {"hot": [], "cold": [], "note": "データ不足（standing()がNoneを返した）"}
    board = board[~board.index.isin(excluded_names)]
    if board.empty:
        return {"hot": [], "cold": [], "note": "新台除外後にデータが残らなかった"}
    board = board.sort_values("edge", ascending=False)
    today_diff = _today_mean_diff(connection, target_date)

    def _rows(frame):
        return [
            {
                "name": str(name),
                "today_mean_diff": round(today_diff[str(name)]["mean_diff"], 1) if str(name) in today_diff else None,
                "today_win_rate": round(today_diff[str(name)]["win_rate"], 3) if str(name) in today_diff else None,
                "edge": round(float(row.edge), 1),
                "pct": round(float(row.pct), 3),
                "n_machines": int(row.machines),
                "mean_games": round(float(row.games), 1),
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

    # games_ratio・mean_games は kakuban_residual に保存されていないため、全館ベースで
    # 別途計算する（セグメント別の値は今回のフェーズでは未対応。全館の値を参考値として使う）
    games_by_rank: dict[str, tuple[float, float]] = {}
    if hall_avg_games:
        for rank, avg_games in connection.execute(
            "SELECT MIN(l.rank_from_min, l.rank_from_max) AS rk, AVG(m.games_normalized) "
            "FROM machine_detailed_results m JOIN machine_layout_history l "
            "  ON l.machine_number = m.machine_number "
            " AND m.date >= l.valid_from AND (l.valid_to IS NULL OR m.date <= l.valid_to) "
            "WHERE m.date = ? AND l.rank_from_min IS NOT NULL "
            "GROUP BY rk",
            (target_date,),
        ):
            if rank is not None and avg_games:
                games_by_rank[str(int(rank))] = (round(avg_games, 1), round(avg_games / hall_avg_games, 3))

    # 勝率も全館ベース（residual と同じくセグメント別未対応。参考値として使う）
    win_rate_by_rank: dict[str, float] = {}
    for rank, win_rate in connection.execute(
        "SELECT MIN(l.rank_from_min, l.rank_from_max) AS rk, "
        "       AVG(CASE WHEN m.diff_coins_normalized > 0 THEN 1.0 ELSE 0.0 END) "
        "FROM machine_detailed_results m JOIN machine_layout_history l "
        "  ON l.machine_number = m.machine_number "
        " AND m.date >= l.valid_from AND (l.valid_to IS NULL OR m.date <= l.valid_to) "
        "WHERE m.date = ? AND l.rank_from_min IS NOT NULL "
        "GROUP BY rk",
        (target_date,),
    ):
        if rank is not None and win_rate is not None:
            win_rate_by_rank[str(int(rank))] = round(win_rate, 3)

    segments: dict[str, dict] = {}
    for _date, _hall, _version, segment, item, value_num, n in rows:
        seg = segments.setdefault(segment, {"peak_rank": None, "rows": []})
        if item == "peak":
            seg["peak_rank"] = (value_num, n)  # 一時保持。下で角番表記に変換
            continue
        if item.startswith("角"):
            rank = item[1:]
            mean_games, games_ratio = games_by_rank.get(rank, (None, None))
            seg["rows"].append(
                {
                    "rank": rank,
                    "residual": value_num,
                    "mean_games": mean_games if mean_games is not None else "全館ベースの値が無い(参考値なし)",
                    "games_ratio": games_ratio if games_ratio is not None else "全館ベースの値が無い(参考値なし)",
                    "win_rate": win_rate_by_rank.get(rank),
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
        mean_games = (sum(block_games) / len(block_games)) if block_games else None
        games_ratio = (mean_games / hall_avg_games) if mean_games is not None and hall_avg_games else None
        wins = sum(1 for m in block["machines"] if m.get("diff") is not None and m["diff"] > 0)
        out.append(
            {
                "start": block["start"],
                "section": block["section"],
                "mean_diff": round(block["mean_diff"], 1),
                "mean_games": round(mean_games, 1) if mean_games is not None else None,
                "games_ratio": round(games_ratio, 3) if games_ratio is not None else None,
                "win_rate": round(wins / len(block["machines"]), 3) if block["machines"] else None,
                "segments": block["segments"],
                "names": block["names"],
            }
        )
    return {"blocks": out, "count": len(out)}


def _last_digit_axis(connection: sqlite3.Connection, target_date: str, hall_avg_games: float | None) -> dict:
    rows = connection.execute(
        "SELECT last_digit, AVG(diff_coins_normalized), AVG(games_normalized), "
        "       COUNT(DISTINCT machine_number), SUM(CASE WHEN is_zorome THEN 1 ELSE 0 END), "
        "       AVG(CASE WHEN diff_coins_normalized > 0 THEN 1.0 ELSE 0.0 END) "
        "FROM machine_detailed_results WHERE date = ? "
        "GROUP BY last_digit ORDER BY last_digit",
        (target_date,),
    ).fetchall()
    out = []
    for digit, mean_diff, mean_games, n, n_zorome, win_rate in rows:
        games_ratio = round(mean_games / hall_avg_games, 3) if hall_avg_games and mean_games else None
        out.append(
            {
                "digit": digit,
                "mean_diff": round(mean_diff, 1) if mean_diff is not None else None,
                "mean_games": round(mean_games, 1) if mean_games is not None else None,
                "games_ratio": games_ratio,
                "win_rate": round(win_rate, 3) if win_rate is not None else None,
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


def _machine_count_axis(connection: sqlite3.Connection, target_date: str, hall_avg_games: float | None) -> dict:
    """機種の当日設置台数でグルーピングした集計軸。

    少数台設置の機種ほど「全台系」の撒き餌になりやすい・予告の「まるごとは3〜5台設置」
    のような言及と対応するため、末尾・角番と同じ形式の軸として扱う。
    """
    rows = connection.execute(
        "SELECT machine_name, machine_number, diff_coins_normalized, games_normalized "
        "FROM machine_detailed_results WHERE date = ?",
        (target_date,),
    ).fetchall()
    by_name: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for name, number, diff, games in rows:
        by_name[name].append((number, diff, games))

    by_count: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for members in by_name.values():
        cnt = len({m[0] for m in members})
        for _number, diff, games in members:
            by_count[cnt].append((diff, games))

    out = []
    for cnt in sorted(by_count):
        values = by_count[cnt]
        n = len(values)
        diffs = [v[0] for v in values]
        games_list = [v[1] for v in values]
        mean_diff = sum(diffs) / n
        mean_games = sum(games_list) / n
        wins = sum(1 for d in diffs if d > 0)
        out.append(
            {
                "count": cnt,
                "mean_diff": round(mean_diff, 1),
                "mean_games": round(mean_games, 1),
                "games_ratio": round(mean_games / hall_avg_games, 3) if hall_avg_games else None,
                "win_rate": round(wins / n, 3),
                "n": n,
            }
        )
    return {"rows": out}


def _rb_settings_axis(connection: sqlite3.Connection, target_date: str, excluded_names: set[str]) -> dict:
    judgeable = {
        r[0]
        for r in connection.execute(
            "SELECT machine_name_normalized FROM machine_master "
            "WHERE spec_category IN ('ノーマル','BT','A+AT') AND bonus_judgeable = 1"
        )
    }
    rows = connection.execute(
        "SELECT machine_name, machine_number, games_normalized, bb_count, rb_count, diff_coins_normalized "
        "FROM machine_detailed_results WHERE date = ?",
        (target_date,),
    ).fetchall()
    total_machines = len({r[1] for r in rows})
    specs = load_specs()
    out = []
    for name, number, games, bb, rb, diff in rows:
        if name not in judgeable or name in excluded_names:
            continue
        spec = find_spec(name, specs)
        if spec is None or not spec.get("judgeable"):
            continue
        probs = posterior(spec, games, bb, rb)
        if not probs:
            continue
        best_setting, best_prob = max(probs.items(), key=lambda kv: kv[1])
        high_prob = sum(p for s, p in probs.items() if s >= 5)
        out.append(
            {
                "name": name,
                "number": number,
                "category": spec["category"],
                "games": games,
                "bb": bb,
                "rb": rb,
                "diff": diff,
                "win": bool(diff is not None and diff > 0),
                "posterior": {str(s): round(p, 4) for s, p in probs.items()},
                "best_setting": str(best_setting),
                "best_prob": round(best_prob, 4),
                "high_prob": round(high_prob, 4),
                "below_min_games": games < MIN_GAMES_FOR_JUDGEMENT,
            }
        )
    # 高設定(5+6)事後確率の降順。below_min_games（未判定水準）は最後にまとめる。
    out.sort(key=lambda m: (m["below_min_games"], -m["high_prob"]))
    coverage_pct = round(len(out) / total_machines, 3) if total_machines else None
    return {"coverage_pct": coverage_pct, "machines": out}


def _row_axis(connection: sqlite3.Connection, target_date: str, hall_avg_games: float | None) -> dict:
    rows = connection.execute(
        "SELECT l.section, m.diff_coins_normalized, m.games_normalized, m.machine_number "
        "FROM machine_detailed_results m JOIN machine_layout_history l "
        "  ON l.machine_number = m.machine_number "
        " AND m.date >= l.valid_from AND (l.valid_to IS NULL OR m.date <= l.valid_to) "
        "WHERE m.date = ? AND l.section IS NOT NULL",
        (target_date,),
    ).fetchall()
    if not rows:
        return {"applicable": False, "note": "レイアウトデータ不足、または対象日に十分な台数が無い"}

    groups: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for section, diff, games, number in rows:
        groups[section].append((diff, games, number))

    out = []
    for section, values in groups.items():
        if len(values) < ROW_AXIS_MIN_SECTION_SIZE:
            continue
        diffs = [v[0] for v in values]
        games_list = [v[1] for v in values]
        mean_diff = sum(diffs) / len(diffs)
        mean_games = sum(games_list) / len(games_list)
        top_diff = max(diffs)
        wins = sum(1 for d in diffs if d > 0)
        out.append(
            {
                "section": section,
                "n": len(values),
                "mean_diff": round(mean_diff, 1),
                "mean_games": round(mean_games, 1),
                "games_ratio": round(mean_games / hall_avg_games, 3) if hall_avg_games else None,
                "win_rate": round(wins / len(values), 3),
                # 1に近いほど列（島）全体が均等に高い（月=列全体型）、大きいほど1台だけが
                # 突出している（金=列1台型）。mean_diff<=0の列は比率が意味を持たないので出さない。
                "top_single_ratio": round(top_diff / mean_diff, 2) if mean_diff > 0 else None,
                "first_machine_number": min(v[2] for v in values),
            }
        )
    out.sort(key=lambda r: -r["mean_diff"])
    return {
        "applicable": True,
        "columns": out[:ROW_AXIS_TOP_N],
        "note": (
            "「列」はmachine_layout_history.sectionの島単位。角番（島内の順位）・並び"
            "（島内の連番サブブロック）とは異なり島全体を1塊として見る。top_single_ratioが"
            "1に近いほど列全体型（蒲田7曜日知見の月）、大きいほど列1台型（同・金）に近い。"
        ),
    }


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
                "machine": _machine_axis(connection, hall, target_date, set(excluded_new_machines)),
                "kakuban": _kakuban_axis(connection, hall, target_date, hall_avg_games),
                "last_digit": _last_digit_axis(connection, target_date, hall_avg_games),
                "machine_count": _machine_count_axis(connection, target_date, hall_avg_games),
                "row": _row_axis(connection, target_date, hall_avg_games),
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


_HTML_STYLE = """
<style>
  body { font-family: -apple-system, "Hiragino Sans", "Meiryo", sans-serif; margin: 0; padding: 24px;
         background: #0f1115; color: #e6e6e6; }
  h1 { font-size: 1.4rem; margin-bottom: 4px; }
  .meta { color: #9aa0a6; font-size: 0.9rem; margin-bottom: 20px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-right: 6px; }
  .badge-hot { background: #1e3a2f; color: #7ee0a8; }
  .badge-warn { background: #3a2f1e; color: #e0b87e; }
  .badge-info { background: #1e2a3a; color: #7eb8e0; }
  section { background: #1a1d24; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; }
  h2 { font-size: 1.05rem; margin: 0 0 10px; border-left: 4px solid #4a90d9; padding-left: 8px; }
  table { border-collapse: collapse; width: 100%; font-size: 0.88rem; margin-top: 6px; }
  th, td { text-align: right; padding: 4px 8px; border-bottom: 1px solid #2a2e37; }
  th:first-child, td:first-child { text-align: left; }
  .pos { color: #7ee0a8; } .neg { color: #e07e7e; }
  .note { color: #9aa0a6; font-size: 0.85rem; margin-top: 8px; }
  .warn { color: #e0b87e; font-size: 0.85rem; }
  a { color: #7eb8e0; }
  tr.below-min { opacity: 0.55; }
  .table-search { display: block; width: 100%; max-width: 320px; margin: 8px 0 4px;
    padding: 6px 10px; border-radius: 4px; border: 1px solid #2a2e37;
    background: #0f1115; color: #e6e6e6; font-size: 0.88rem; box-sizing: border-box; }
  .table-search::placeholder { color: #6a7078; }
</style>
"""

_TABLE_SEARCH_SCRIPT = """
<script>
document.querySelectorAll('.table-search').forEach(function (input) {
  var table = document.getElementById(input.dataset.target);
  if (!table) return;
  var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr, tr'));
  input.addEventListener('input', function () {
    var q = input.value.trim().toLowerCase();
    rows.forEach(function (row) {
      if (row.querySelector('th')) return;
      row.style.display = !q || row.textContent.toLowerCase().indexOf(q) !== -1 ? '' : 'none';
    });
  });
});
</script>
"""


def _html_escape(value) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _fmt_num(value, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:+,.{digits}f}" if isinstance(value, (int, float)) else _html_escape(value)


def _num_class(value) -> str:
    if isinstance(value, (int, float)):
        return "pos" if value >= 0 else "neg"
    return ""


def _fmt_pct(value) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%"


def _detail_filename(hall: str, target_date: str) -> str:
    return f"{hall}__{target_date}_detail.html"


def _detail_link(hall: str, target_date: str, anchor: str = "") -> str:
    filename = _detail_filename(hall, target_date)
    return f"{filename}#{anchor}" if anchor else filename


def _digit_anchor(digit) -> str:
    return "last_digit_section10" if digit == "ゾロ目" else f"last_digit_section{digit}"


def _kakuban_anchor(rank) -> str:
    return f"kakuban_section{rank}"


def _machine_count_anchor(count) -> str:
    return f"machine_count_section{count}"


def fetch_detail_rows(hall: str, target_date: str) -> list[dict]:
    """ana-sloがその日に出す情報を台単位で全部並べるための生データ。

    集計軸（機種/角番/末尾/並び/列）を経由しない生データなので、集計ロジックの
    検証にも使える。表示専用で、hall-reviewの軸計算はこの関数を経由しない
    （経由すると集計とは違うJOIN条件・除外条件が紛れ込むリスクがあるため）。

    ⚠️ ART列は出さない: ana-sloはBB/RB/ARTを別々の列で表示するが、
    machine_detailed_resultsにはbb_count/rb_countしか無く、ART単体の
    カウントは元々収集していない（2026-09-24確認）。合成確率
    （total_probability_fraction）はana-sloの値をそのまま保存しており、
    ART込みの計算として正しいが、ART単体には分解できない。
    """
    with _ro_hall(hall) as connection:
        rows = connection.execute(
            "SELECT m.machine_number, m.machine_name, m.last_digit, m.is_zorome, "
            "       m.games_normalized, m.diff_coins_normalized, m.bb_count, m.rb_count, "
            "       m.total_probability_fraction, m.bb_probability_fraction, m.rb_probability_fraction, "
            "       l.section, MIN(l.rank_from_min, l.rank_from_max) AS kakuban_rank "
            "FROM machine_detailed_results m "
            "LEFT JOIN machine_layout_history l "
            "  ON l.machine_number = m.machine_number "
            " AND m.date >= l.valid_from AND (l.valid_to IS NULL OR m.date <= l.valid_to) "
            "WHERE m.date = ? "
            "ORDER BY m.machine_number",
            (target_date,),
        ).fetchall()
    return [
        {
            "machine_number": r[0],
            "machine_name": r[1],
            "last_digit": r[2],
            "is_zorome": bool(r[3]),
            "games": r[4],
            "diff": r[5],
            "bb": r[6],
            "rb": r[7],
            "total_prob": r[8],
            "bb_prob": r[9],
            "rb_prob": r[10],
            "section": r[11],
            "kakuban_rank": r[12],
        }
        for r in rows
    ]


def build_machine_anchor_map(rows: list[dict]) -> dict[str, str]:
    """機種名 -> 詳細ページの#sectionN アンカー。設置機種一覧の並び順（初出台番号の昇順）を基準にする。"""
    first_seen: dict[str, int] = {}
    for r in rows:
        first_seen.setdefault(r["machine_name"], r["machine_number"])
    ordered = sorted(first_seen, key=lambda name: first_seen[name])
    return {name: f"section{i}" for i, name in enumerate(ordered)}


def _prob_text(games: float, count: float) -> str:
    if not count:
        return "1/0.0"
    return f"1/{games / count:.1f}"


def render_hall_detail_html(hall: str, target_date: str, rows: list[dict]) -> str:
    hall_e = _html_escape(hall)
    target_date_e = _html_escape(target_date)
    summary_link = f"{hall}__{target_date}.html"

    if not rows:
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{hall_e} {target_date_e} 詳細</title>"
            f"{_HTML_STYLE}</head><body><h1>{hall_e}　{target_date_e}　詳細</h1>"
            f"<p class='warn'>対象日のデータがありません。</p>"
            f"<p class='meta'><a href='{summary_link}'>← 概略に戻る</a></p></body></html>"
        )

    total_diff = sum(r["diff"] for r in rows)
    total_games = len(rows)
    wins = sum(1 for r in rows if r["diff"] > 0)
    mean_diff = total_diff / total_games
    mean_games = sum(r["games"] for r in rows) / total_games

    # 全体データ
    overall_html = (
        "<table><tr><th>総差枚</th><th>平均差枚</th><th>平均G数</th><th>勝率</th></tr>"
        f"<tr><td>{_fmt_num(total_diff, 0)}</td><td>{_fmt_num(mean_diff, 0)}</td>"
        f"<td>{mean_games:,.0f}</td><td>{wins / total_games * 100:.1f}%({wins}/{total_games})</td></tr></table>"
    )

    # 機種別グルーピング（設置機種一覧・機種別ピックアップ・機種別詳細の3か所で共用）
    by_machine: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_machine[r["machine_name"]].append(r)
    machine_anchor = build_machine_anchor_map(rows)
    machine_order = sorted(by_machine, key=lambda name: machine_anchor[name])

    def machine_stats(name: str) -> dict:
        members = by_machine[name]
        n = len(members)
        total = sum(m["diff"] for m in members)
        w = sum(1 for m in members if m["diff"] > 0)
        return {
            "name": name,
            "total_diff": total,
            "mean_diff": total / n,
            "mean_games": sum(m["games"] for m in members) / n,
            "win_rate": w / n,
            "wins": w,
            "n": n,
        }

    # 機種別データピックアップ（機種別差枚の上位20）
    picks = sorted((machine_stats(name) for name in by_machine), key=lambda s: -s["total_diff"])[:20]
    pick_rows = "".join(
        f"<tr><td>{i + 1}位: <a href='#{machine_anchor[s['name']]}'>{_html_escape(s['name'])}</a></td>"
        f"<td class='{_num_class(s['total_diff'])}'>{_fmt_num(s['total_diff'], 0)}</td>"
        f"<td class='{_num_class(s['mean_diff'])}'>{_fmt_num(s['mean_diff'], 0)}</td>"
        f"<td>{s['mean_games']:,.0f}</td>"
        f"<td>{s['win_rate'] * 100:.1f}%({s['wins']}/{s['n']})</td></tr>"
        for i, s in enumerate(picks)
    )
    picks_html = (
        "<table><tr><th>順位</th><th>機種別差枚</th><th>平均差枚</th><th>平均G数</th><th>勝率</th></tr>"
        f"{pick_rows}</table>"
    )

    # 末尾別データ
    by_digit: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_digit[r["last_digit"]].append(r)
        if r["is_zorome"]:
            by_digit["ゾロ目"].append(r)
    digit_order = [str(d) for d in range(10)] + ["ゾロ目"]
    digit_rows = []
    for digit in digit_order:
        members = by_digit.get(digit)
        if not members:
            digit_rows.append(
                f"<tr><td><a href='#{_digit_anchor(digit)}'>{_html_escape(digit)}</a></td>"
                f"<td>-</td><td>-</td><td>{'-'}</td><td>-</td></tr>"
            )
            continue
        n = len(members)
        total = sum(m["diff"] for m in members)
        w = sum(1 for m in members if m["diff"] > 0)
        digit_rows.append(
            f"<tr><td><a href='#{_digit_anchor(digit)}'>{_html_escape(digit)}</a></td>"
            f"<td class='{_num_class(total)}'>{_fmt_num(total, 0)}</td>"
            f"<td class='{_num_class(total / n)}'>{_fmt_num(total / n, 0)}</td>"
            f"<td>{sum(m['games'] for m in members) / n:,.0f}</td>"
            f"<td>{w / n * 100:.1f}%({w}/{n})</td></tr>"
        )
    digit_html = (
        "<table id='last_digit_list'><tr><th>末尾</th><th>末尾別差枚</th><th>平均差枚</th>"
        f"<th>平均G数</th><th>勝率</th></tr>{''.join(digit_rows)}</table>"
    )

    # 角番別データ（末尾別データと同形式で集計する、という要望に対応）
    by_kakuban: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("kakuban_rank") is not None:
            by_kakuban[int(r["kakuban_rank"])].append(r)
    kakuban_order = sorted(by_kakuban)
    kakuban_rows = []
    for rank in kakuban_order:
        members = by_kakuban[rank]
        n = len(members)
        total = sum(m["diff"] for m in members)
        w = sum(1 for m in members if m["diff"] > 0)
        kakuban_rows.append(
            f"<tr><td><a href='#{_kakuban_anchor(rank)}'>角{rank}</a></td>"
            f"<td class='{_num_class(total)}'>{_fmt_num(total, 0)}</td>"
            f"<td class='{_num_class(total / n)}'>{_fmt_num(total / n, 0)}</td>"
            f"<td>{sum(m['games'] for m in members) / n:,.0f}</td>"
            f"<td>{w / n * 100:.1f}%({w}/{n})</td>"
            f"<td>{n}台</td></tr>"
        )
    kakuban_html = (
        "<table id='kakuban_list'><tr><th>角番</th><th>角番別差枚</th><th>平均差枚</th>"
        f"<th>平均G数</th><th>勝率</th><th>台数</th></tr>{''.join(kakuban_rows)}</table>"
        if kakuban_rows
        else "<p class='warn'>レイアウトデータ不足のため角番を集計できません。</p>"
    )

    # 台数別データ（機種の当日設置台数でグルーピング。末尾・角番と同形式）
    machine_count_of = {name: len({m["machine_number"] for m in members}) for name, members in by_machine.items()}
    by_machine_count: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_machine_count[machine_count_of[r["machine_name"]]].append(r)
    machine_count_order = sorted(by_machine_count)
    machine_count_rows = []
    for cnt in machine_count_order:
        members = by_machine_count[cnt]
        n = len(members)
        total = sum(m["diff"] for m in members)
        w = sum(1 for m in members if m["diff"] > 0)
        machine_count_rows.append(
            f"<tr><td><a href='#{_machine_count_anchor(cnt)}'>{cnt}台設置</a></td>"
            f"<td class='{_num_class(total)}'>{_fmt_num(total, 0)}</td>"
            f"<td class='{_num_class(total / n)}'>{_fmt_num(total / n, 0)}</td>"
            f"<td>{sum(m['games'] for m in members) / n:,.0f}</td>"
            f"<td>{w / n * 100:.1f}%({w}/{n})</td>"
            f"<td>{n}台</td></tr>"
        )
    machine_count_html = (
        "<table id='machine_count_list'><tr><th>設置台数</th><th>台数別差枚</th><th>平均差枚</th>"
        f"<th>平均G数</th><th>勝率</th><th>台数</th></tr>{''.join(machine_count_rows)}</table>"
        if machine_count_rows
        else "<p class='warn'>データがありません。</p>"
    )

    # 機種別詳細データ
    def machine_row_html(r: dict) -> str:
        return (
            f"<tr><td>{r['machine_number']}</td><td>{r['games']:,}</td>"
            f"<td class='{_num_class(r['diff'])}'>{_fmt_num(r['diff'], 0)}</td>"
            f"<td>{r['bb']}</td><td>{r['rb']}</td>"
            f"<td>{_html_escape(r['total_prob'])}</td><td>{_html_escape(r['bb_prob'])}</td>"
            f"<td>{_html_escape(r['rb_prob'])}</td></tr>"
        )

    machine_sections = []
    for name in machine_order:
        members = sorted(by_machine[name], key=lambda r: r["machine_number"])
        n = len(members)
        avg_games = sum(m["games"] for m in members) / n
        avg_diff = sum(m["diff"] for m in members) / n
        avg_bb = sum(m["bb"] for m in members) / n
        avg_rb = sum(m["rb"] for m in members) / n
        avg_row = (
            f"<tr><td>平均</td><td>{avg_games:,.0f}</td>"
            f"<td class='{_num_class(avg_diff)}'>{_fmt_num(avg_diff, 0)}</td>"
            f"<td>{avg_bb:.0f}</td><td>{avg_rb:.0f}</td>"
            f"<td>{_prob_text(avg_games, avg_bb + avg_rb)}</td>"
            f"<td>{_prob_text(avg_games, avg_bb)}</td><td>{_prob_text(avg_games, avg_rb)}</td></tr>"
        )
        body = "".join(machine_row_html(r) for r in members) + avg_row
        machine_sections.append(
            f"<h3 id='{machine_anchor[name]}'>{_html_escape(name)}</h3>"
            "<table><tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th>"
            f"<th>合成確率</th><th>BB確率</th><th>RB確率</th></tr>{body}</table>"
        )
    machine_sections_html = "".join(machine_sections)

    # 末尾毎詳細データ
    digit_sections = []
    for digit in digit_order:
        members = by_digit.get(digit)
        if not members:
            continue
        members = sorted(members, key=lambda r: r["machine_number"])
        body = "".join(
            f"<tr><td>{_html_escape(r['machine_name'])}</td><td>{r['machine_number']}</td>"
            f"<td>{r['games']:,}</td><td class='{_num_class(r['diff'])}'>{_fmt_num(r['diff'], 0)}</td>"
            f"<td>{r['bb']}</td><td>{r['rb']}</td>"
            f"<td>{_html_escape(r['total_prob'])}</td><td>{_html_escape(r['bb_prob'])}</td>"
            f"<td>{_html_escape(r['rb_prob'])}</td></tr>"
            for r in members
        )
        digit_sections.append(
            f"<h3 id='{_digit_anchor(digit)}'>末尾{_html_escape(digit)}</h3>"
            "<table><tr><th>機種名</th><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th>"
            f"<th>合成確率</th><th>BB確率</th><th>RB確率</th></tr>{body}</table>"
            "<p class='meta'><a href='#last_digit_list'>末尾別データ一覧へ戻る</a></p>"
        )
    digit_sections_html = "".join(digit_sections)

    # 角番毎詳細データ（その角番に属する機種を台単位で一覧できるようにする）
    kakuban_sections = []
    for rank in kakuban_order:
        members = sorted(by_kakuban[rank], key=lambda r: r["machine_number"])
        body = "".join(
            f"<tr><td>{_html_escape(r['machine_name'])}</td><td>{r['machine_number']}</td>"
            f"<td>{r['games']:,}</td><td class='{_num_class(r['diff'])}'>{_fmt_num(r['diff'], 0)}</td>"
            f"<td>{r['bb']}</td><td>{r['rb']}</td>"
            f"<td>{_html_escape(r['total_prob'])}</td><td>{_html_escape(r['bb_prob'])}</td>"
            f"<td>{_html_escape(r['rb_prob'])}</td></tr>"
            for r in members
        )
        kakuban_sections.append(
            f"<h3 id='{_kakuban_anchor(rank)}'>角{rank}</h3>"
            "<table><tr><th>機種名</th><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th>"
            f"<th>合成確率</th><th>BB確率</th><th>RB確率</th></tr>{body}</table>"
            "<p class='meta'><a href='#kakuban_list'>角番別データ一覧へ戻る</a></p>"
        )
    kakuban_sections_html = "".join(kakuban_sections)

    # 台数毎詳細データ（その設置台数に属する機種を台単位で一覧できるようにする）
    machine_count_sections = []
    for cnt in machine_count_order:
        members = sorted(by_machine_count[cnt], key=lambda r: r["machine_number"])
        body = "".join(
            f"<tr><td>{_html_escape(r['machine_name'])}</td><td>{r['machine_number']}</td>"
            f"<td>{r['games']:,}</td><td class='{_num_class(r['diff'])}'>{_fmt_num(r['diff'], 0)}</td>"
            f"<td>{r['bb']}</td><td>{r['rb']}</td>"
            f"<td>{_html_escape(r['total_prob'])}</td><td>{_html_escape(r['bb_prob'])}</td>"
            f"<td>{_html_escape(r['rb_prob'])}</td></tr>"
            for r in members
        )
        machine_count_sections.append(
            f"<h3 id='{_machine_count_anchor(cnt)}'>{cnt}台設置</h3>"
            "<table><tr><th>機種名</th><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th>"
            f"<th>合成確率</th><th>BB確率</th><th>RB確率</th></tr>{body}</table>"
            "<p class='meta'><a href='#machine_count_list'>台数別データ一覧へ戻る</a></p>"
        )
    machine_count_sections_html = "".join(machine_count_sections)

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{hall_e} {target_date_e} 詳細</title>{_HTML_STYLE}</head>
<body>
<h1>{hall_e}　{target_date_e}　詳細（全{total_games}台）</h1>
<p class="meta"><a href="{summary_link}">← 概略に戻る</a></p>
<p class="warn">⚠️ ART（AT機の疑似ボーナス）単体のカウントは未収集のため列を出していません。合成確率はART込みでana-sloの値をそのまま保存しているため正しい値です。</p>
<section><h2>全体データ</h2>{overall_html}</section>
<section><h2>機種別データピックアップ（上位20）</h2>{picks_html}</section>
<section><h2>末尾別データ</h2>{digit_html}</section>
<section><h2>角番別データ</h2>{kakuban_html}</section>
<section><h2>台数別データ</h2>{machine_count_html}</section>
<section><h2>機種別詳細データ</h2>{machine_sections_html}</section>
<section><h2>末尾毎詳細データ</h2>{digit_sections_html}</section>
<section><h2>角番毎詳細データ</h2>{kakuban_sections_html}</section>
<section><h2>台数毎詳細データ</h2>{machine_count_sections_html}</section>
</body></html>"""


_EVENT_KIND_LABELS = {
    "collab": "合同企画",
    "recording": "収録来店",
    "coverage": "取材",
    "anniversary": "周年",
    "renovation": "改装",
    "ip": "版権イベント",
    "manager": "店長絡み",
    "visit": "来店",
    "other": "その他",
}


def _render_event_detail(event: dict) -> str:
    """イベント日バッジ。kind の日本語訳・演者・注記まで出す（kind だけでは
    「coverage」としか分からず取材の中身が見えないという指摘への対応）。
    """
    kind_raw = event.get("kind")
    kind_label = _EVENT_KIND_LABELS.get(kind_raw, kind_raw)
    name = _html_escape(event.get("event_name"))
    badge = f"<span class='badge badge-hot'>イベント: {name}（{_html_escape(kind_label)}）</span>"

    performers = event.get("performers") or []
    performer_text = "; ".join(
        f"{_html_escape(p.get('name'))}"
        + (f"（{_html_escape(p.get('handle'))}）" if p.get("handle") else "")
        + (f" — {_html_escape(p.get('note'))}" if p.get("note") else "")
        for p in performers
    )
    performer_html = f"<br><span class='note'>演者: {performer_text}</span>" if performer_text else ""

    related_halls = event.get("related_halls") or []
    related_html = (
        f"<br><span class='note'>同日開催: {_html_escape('、'.join(related_halls))}</span>" if related_halls else ""
    )

    note = event.get("note")
    note_html = f"<br><span class='note'>{_html_escape(note)}</span>" if note else ""

    return badge + performer_html + related_html + note_html


def render_hall_review_html(review: dict, detail_rows: list[dict] | None = None) -> str:
    raw_hall = review.get("hall")
    raw_target_date = review.get("target_date")
    hall = _html_escape(raw_hall)
    target_date = _html_escape(raw_target_date)
    detail_href = _html_escape(_detail_filename(raw_hall, raw_target_date))

    detail_rows = detail_rows or []
    machine_anchor = build_machine_anchor_map(detail_rows) if detail_rows else {}
    number_anchor = {r["machine_number"]: machine_anchor[r["machine_name"]] for r in detail_rows}

    def detail_link(text: str, anchor: str) -> str:
        href = _html_escape(_detail_link(raw_hall, raw_target_date, anchor)) if anchor else detail_href
        return f"<a href='{href}'>{_html_escape(text)}</a>"

    def machine_anchor_link(text: str, name: str) -> str:
        return detail_link(text, machine_anchor.get(name, ""))

    def number_anchor_link(text: str, number: int) -> str:
        return detail_link(text, number_anchor.get(number, ""))

    if review.get("skipped") or (review.get("note") and "axes" not in review):
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{hall} {target_date}</title>"
            f"{_HTML_STYLE}</head><body><h1>{hall}　{target_date}</h1>"
            f"<section><p class='warn'>{_html_escape(review.get('note'))}</p>"
            f"<p class='meta'>data_asof: {_html_escape(review.get('data_asof'))}</p></section></body></html>"
        )

    axes = review.get("axes", {})

    def machine_table(rows, cls):
        if not rows:
            return "<p class='note'>（なし）</p>"
        body = "".join(
            f"<tr><td>{machine_anchor_link(r['name'], r['name'])}</td>"
            f"<td class='{_num_class(r['today_mean_diff'])}'>{_fmt_num(r['today_mean_diff'])}枚</td>"
            f"<td>{_fmt_pct(r['today_win_rate'])}</td>"
            f"<td class='{_num_class(r['edge'])}'>{_fmt_num(r['edge'])}枚</td>"
            f"<td>{r['n_machines']}台</td><td>{r['mean_games']}G</td><td>{r['games_ratio']}</td></tr>"
            for r in rows
        )
        return (
            "<table><tr><th>機種</th><th>当日平均差枚</th><th>当日勝率</th><th>エッジ(60日・対ホール平均)</th>"
            f"<th>台数</th><th>平均G数</th><th>回転数比</th></tr>{body}</table>"
        )

    machine = axes.get("machine", {})
    machine_html = (
        f"<h3>好調</h3>{machine_table(machine.get('hot'), 'pos')}"
        f"<h3>不調</h3>{machine_table(machine.get('cold'), 'neg')}"
        if "hot" in machine
        else f"<p class='warn'>{_html_escape(machine.get('note'))}</p>"
    )

    kakuban = axes.get("kakuban", {})
    if kakuban.get("applicable"):
        seg_blocks = []
        for seg_name, seg in kakuban.get("segments", {}).items():
            rows = "".join(
                f"<tr><td>{detail_link('角' + str(r['rank']), _kakuban_anchor(r['rank']))}</td>"
                f"<td class='{_num_class(r['residual'])}'>{_fmt_num(r['residual'])}枚</td>"
                f"<td>{_html_escape(r['mean_games'])}</td><td>{_html_escape(r['games_ratio'])}</td>"
                f"<td>{_fmt_pct(r.get('win_rate'))}</td><td>{r['n']}台</td></tr>"
                for r in seg.get("rows", [])
            )
            seg_blocks.append(
                f"<h3>{_html_escape(seg_name)}（ピーク: 角{_html_escape(seg.get('peak_rank'))}）</h3>"
                "<table><tr><th>角番</th><th>残差</th><th>平均G数</th><th>回転数比</th><th>勝率</th>"
                f"<th>台数</th></tr>{rows}</table>"
            )
        kakuban_html = "".join(seg_blocks) + f"<p class='note'>{_html_escape(kakuban.get('games_ratio_basis'))}</p>"
    else:
        kakuban_html = f"<p class='warn'>{_html_escape(kakuban.get('note'))}</p>"

    last_digit = axes.get("last_digit", {})
    ld_rows = "".join(
        f"<tr><td>{detail_link('末尾' + str(r['digit']), _digit_anchor(r['digit']))}</td>"
        f"<td class='{_num_class(r['mean_diff'])}'>{_fmt_num(r['mean_diff'])}枚</td>"
        f"<td>{r['mean_games']}G</td><td>{r['games_ratio']}</td><td>{_fmt_pct(r.get('win_rate'))}</td>"
        f"<td>{r['n']}台</td><td>{r['n_zorome']}</td></tr>"
        for r in last_digit.get("rows", [])
    )
    last_digit_html = (
        "<table><tr><th>末尾</th><th>平均差枚</th><th>平均G数</th><th>回転数比</th><th>勝率</th>"
        f"<th>台数</th><th>ゾロ目台数</th></tr>{ld_rows}</table>"
        f"<p class='warn'>⚠️ {_html_escape(last_digit.get('decoy_warning'))}</p>"
    )

    machine_count = axes.get("machine_count", {})
    mc_rows = "".join(
        f"<tr><td>{detail_link(str(r['count']) + '台設置', _machine_count_anchor(r['count']))}</td>"
        f"<td class='{_num_class(r['mean_diff'])}'>{_fmt_num(r['mean_diff'])}枚</td>"
        f"<td>{r['mean_games']}G</td><td>{r['games_ratio']}</td><td>{_fmt_pct(r.get('win_rate'))}</td>"
        f"<td>{r['n']}台</td></tr>"
        for r in machine_count.get("rows", [])
    )
    machine_count_html = (
        "<table><tr><th>設置台数</th><th>平均差枚</th><th>平均G数</th><th>回転数比</th><th>勝率</th>"
        f"<th>台数</th></tr>{mc_rows}</table>"
        if mc_rows
        else "<p class='note'>（データなし）</p>"
    )

    narabi = axes.get("narabi", {})
    narabi_rows = "".join(
        f"<tr><td>{number_anchor_link(str(b['start']) + '〜', b['start'])}（{_html_escape(b['section'])}）</td>"
        f"<td class='{_num_class(b['mean_diff'])}'>{_fmt_num(b['mean_diff'])}枚</td>"
        f"<td>{b['mean_games']}G</td><td>{b['games_ratio']}</td><td>{_fmt_pct(b.get('win_rate'))}</td>"
        f"<td>{_html_escape('/'.join(b['names']))}</td></tr>"
        for b in narabi.get("blocks", [])
    )
    narabi_html = (
        f"<p class='meta'>成立 {narabi.get('count', 0)} 件</p>"
        "<table><tr><th>開始台</th><th>平均差枚</th><th>平均G数</th><th>回転数比</th><th>勝率</th>"
        f"<th>機種</th></tr>{narabi_rows}</table>"
        if narabi.get("blocks")
        else "<p class='note'>（成立ブロックなし）</p>"
    )

    rb = axes.get("rb_settings", {})
    rb_machines = rb.get("machines", [])
    rb_rows = "".join(
        f"<tr class='{'below-min' if m['below_min_games'] else ''}'>"
        f"<td>{machine_anchor_link(m['name'], m['name'])} #{m['number']}</td><td>{_html_escape(m['category'])}</td>"
        f"<td>{m['games']}G{'<span class="warn"> (規定G未満)</span>' if m['below_min_games'] else ''}</td>"
        f"<td>BB{m['bb']}/RB{m['rb']}</td>"
        f"<td class='{_num_class(m.get('diff'))}'>{_fmt_num(m.get('diff'), 0)}枚（{'勝ち' if m['win'] else '負け'}）</td>"
        f"<td>設定{_html_escape(m['best_setting'])}: {m['best_prob'] * 100:.0f}%</td>"
        f"<td>{m['high_prob'] * 100:.0f}%</td></tr>"
        for m in rb_machines
    )
    rb_html = (
        f"<p class='meta'>判別可能率 {(rb.get('coverage_pct') or 0) * 100:.1f}%"
        f"（全{len(rb_machines)}台、高設定(5+6)事後確率の降順。規定G未満は末尾に参考掲載）</p>"
        "<input type='text' class='table-search' data-target='rb-table' "
        "placeholder='機種名・台番号で検索' />"
        "<table id='rb-table'><tr><th>機種/台番号</th><th>区分</th><th>G数</th><th>BB/RB</th><th>差枚</th>"
        f"<th>最尤設定</th><th>高設定(5+6)確率</th></tr>{rb_rows}</table>"
    )

    row_axis = axes.get("row", {})
    if row_axis.get("applicable"):
        row_rows = "".join(
            f"<tr><td>{number_anchor_link(c['section'], c.get('first_machine_number'))}</td>"
            f"<td class='{_num_class(c['mean_diff'])}'>{_fmt_num(c['mean_diff'])}枚</td>"
            f"<td>{c['mean_games']}G</td><td>{c['games_ratio']}</td><td>{_fmt_pct(c.get('win_rate'))}</td>"
            f"<td>{c['n']}台</td>"
            f"<td>{c['top_single_ratio'] if c['top_single_ratio'] is not None else '-'}</td></tr>"
            for c in row_axis.get("columns", [])
        )
        row_html = (
            "<table><tr><th>列（section）</th><th>平均差枚</th><th>平均G数</th><th>回転数比</th><th>勝率</th>"
            f"<th>台数</th><th>突出比(1=列全体型/高いほど列1台型)</th></tr>{row_rows}</table>"
            f"<p class='note'>{_html_escape(row_axis.get('note'))}</p>"
        )
    else:
        row_html = f"<p class='warn'>{_html_escape(row_axis.get('note'))}</p>"

    event = review.get("event")
    event_html = (
        _render_event_detail(event)
        if review.get("is_event_day") and event
        else "<span class='badge badge-info'>通常日</span>"
    )

    excluded = review.get("excluded_new_machines") or []
    excluded_html = f"<p class='note'>新台除外: {_html_escape(', '.join(excluded))}</p>" if excluded else ""

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{hall} {target_date}</title>{_HTML_STYLE}</head>
<body>
<h1>{hall}　{target_date}</h1>
<div class="meta">
  data_asof: {_html_escape(review.get('data_asof'))} / lag: {review.get('data_lag_days')}日 /
  <span class="badge badge-info">{_html_escape(review.get('traffic_stratum'))}</span>
  {event_html}
  ／ <a href="{detail_href}">全台の詳細データを見る →</a>
</div>
{excluded_html}
<section><h2>機種（好調/不調）</h2>{machine_html}</section>
<section><h2>角番</h2>{kakuban_html}</section>
<section><h2>末尾</h2>{last_digit_html}</section>
<section><h2>台数別</h2>{machine_count_html}</section>
<section><h2>並び</h2>{narabi_html}</section>
<section><h2>列</h2>{row_html}</section>
<section><h2>RB設定判別</h2>{rb_html}</section>
{_TABLE_SEARCH_SCRIPT}
</body></html>"""


def render_announce_watch_html(digest: dict) -> str:
    target_date = _html_escape(digest.get("target_date"))
    blocks = []
    for hall in digest.get("halls", []):
        if not hall["announces"]:
            continue
        rows = []
        for a in hall["announces"]:
            track = a.get("account_track_record")
            if track is None:
                track_text = "実績データなし"
            else:
                rate = track.get("hit_rate_known")
                rate_text = f"{rate * 100:.0f}%" if rate is not None else "判定不能のみ"
                track_text = (
                    f"{track['n_hit']}的中/{track['n_miss']}外れ/{track['n_unknown']}判定不能（既知的中率 {rate_text}）"
                )
            reg_badge = (
                "<span class='badge badge-hot'>登録済み</span>"
                if a["registered"]
                else "<span class='badge badge-warn'>未登録</span>"
            )
            rows.append(
                f"<tr><td>{_html_escape(a['account'])}</td><td>{_html_escape(a['target_date'])}</td>"
                f"<td>{a['mention_strength']}</td><td>{reg_badge}<br><span class='note'>{_html_escape(a['register_note'])}</span></td>"
                f"<td>{_html_escape(track_text)}</td>"
                f"<td><a href='{_html_escape(a['tweet_url'])}'>本文</a>: {_html_escape(a['claim_raw_text'][:60])}...</td></tr>"
            )
        blocks.append(
            f"<section><h2>{_html_escape(hall['hall'])}</h2>"
            f"<table><tr><th>アカウント</th><th>対象日</th><th>言及強度</th><th>登録状況</th><th>過去実績</th><th>本文</th></tr>"
            f"{''.join(rows)}</table></section>"
        )
    body = "".join(blocks) if blocks else "<section><p class='note'>該当する予告はありません</p></section>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>予告ウォッチ {target_date}</title>{_HTML_STYLE}</head>
<body><h1>予告ウォッチ　{target_date}</h1>{body}</body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    watch = subparsers.add_parser("announce-watch", help="本日投稿された予告を過去実績と突き合わせる")
    watch.add_argument("--date", help="YYYYMMDD（予告の対象日=target_date。投稿日ではない）。省略時は実行時のJST日付")

    review = subparsers.add_parser("hall-review", help="昨日のホール実績を軸別に振り返る（フェーズ2: 3ホール限定）")
    review.add_argument("--hall", help="対象ホール名（HALL_REVIEW_HALLSのいずれか）")
    review.add_argument("--all-halls", action="store_true", help="HALL_REVIEW_HALLS全件をループする")
    review.add_argument("--date", help="YYYYMMDD（target_date）。省略時は実行時JSTの前日")

    args = parser.parse_args(argv)

    if args.command == "announce-watch":
        target_date = _now_jst().date() if args.date is None else _parse_date(args.date)

        output = build_digest(target_date)

        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        output_path = WATCH_DIR / f"{target_date:%Y%m%d}.json"
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        html_path = WATCH_DIR / f"{target_date:%Y%m%d}.html"
        html_path.write_text(render_announce_watch_html(output), encoding="utf-8")

        announce_count = sum(len(hall["announces"]) for hall in output["halls"])
        print(f"wrote {output_path} / {html_path} ({announce_count} announces)")
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

            detail_rows = fetch_detail_rows(hall, target_date)
            detail_path = REVIEW_DIR / _detail_filename(hall, target_date)
            detail_path.write_text(render_hall_detail_html(hall, target_date, detail_rows), encoding="utf-8")

            html_path = REVIEW_DIR / f"{hall}__{target_date}.html"
            html_path.write_text(render_hall_review_html(output, detail_rows), encoding="utf-8")

            note = output.get("note", "")
            print(
                f"wrote {output_path} / {html_path} / {detail_path} ({len(detail_rows)}台)"
                f"{'  (' + note + ')' if note else ''}"
            )
        return 0

    parser.error(f"未知のコマンド: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
