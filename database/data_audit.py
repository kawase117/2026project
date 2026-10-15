#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ana-slo 取り込み後のデータ品質監査（ホール別 SQLite DB が対象）。

なぜ作ったか:
  分析の土台になる DB で、後から発覚したデータ事故が何度もあった。
    - daily_hall_summary の日付フラグが一部期間で 0/NULL、is_holiday は全期間誤り
      （2026-09-14 に発覚・修正。jpholiday が venv に無かった）
    - anaslo_scraper_auto.py が楽園蒲田を金時京急蒲田店に無言で差し替える
      （EXIT=0・成功1件と表示される）
    - anaslo_scraper_auto_multi.py が cp932 で ABORT し success=0 と嘘をつく
  どれも「成功」と表示されたまま見逃された。ここでは取り込み結果を DB と JSON の
  実物から検査し、1ホール1日1行で document/registry/DATA_AUDIT.jsonl に残す。
  **異常を見つけても直さない**（報告のみ）。

検査項目（ホール×日付ごと）:
  presence      当日分が DB に無い（INFO: 未掲載・未取得。朝の実行を失敗にしない）。
                DB ファイル自体が無い・空は ERROR。
  json          JSON の hall_name・date がフォルダ・ファイル名と一致するか。
                all_data が0件（成功扱いの空振り）、JSON はあるのに DB に0行、
                JSON の台数と DB の行数の不一致（部分投入）は ERROR。
  continuity    前回の収録日との間に欠けた日がないか。JSON があるのに DB に無い日は
                取り込み失敗（ERROR）、JSON も無い日は ana-slo 未掲載の可能性（WARN）。
                data/failed_dates_report確認済み.csv にある日は確認済みとして INFO。
  machine_count 当日の台数が直近28収録日の中央値から ±10% 以上ずれたら WARN、
                半分未満なら ERROR（取り込み途中で切れた等）。前日と同じ台数なら INFO。
  avg_games     台平均G数が 7,500G 超なら WARN（合算・二重取り込み）。比率で見ると小規模ホールの
                イベント日（中央値の2〜3倍）で誤検知が多すぎたので、物理的な上限側で切る。
  hall_identity 当日の台番号が直近7収録日に見えていた台番号とどれだけ重なるか。
                50% 未満は ERROR（別ホールの中身）、80% 未満は WARN（大規模入替）。
                さらに同じ日の他ホールと (台番号, G数, 差枚) が 90% 以上一致したら ERROR。
  date_flags    daily_hall_summary の行が存在し、日付フラグ13列が
                DateInfoCalculator.calculate_date_info（取り込み時と同じ計算）の
                再計算値と一致するか。total_machines が実行数と一致するか。
  values        games/差枚/BB/RB の NULL・負値（ERROR）、同日同台番号の重複（ERROR）、
                全台 G数0（ERROR）、極端値（WARN）。

終了コード: ERROR が1件でもあれば 1。WARN/INFO だけなら 0。

使い方:
  venv\\Scripts\\python.exe -m database.data_audit --date 2026-10-15
  venv\\Scripts\\python.exe -m database.data_audit --date 2026-10-15 --hall 楽園蒲田店
  venv\\Scripts\\python.exe -m database.data_audit --all-days            # 全期間（--date 不要）
  venv\\Scripts\\python.exe -m database.data_audit --all-days --no-write --summary
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import os
import sqlite3
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_DIR = PROJECT_ROOT / "db"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "hall_config.json"
DEFAULT_OUT = PROJECT_ROOT / "document" / "registry" / "DATA_AUDIT.jsonl"
KNOWN_MISSING_CSV = "failed_dates_report確認済み.csv"  # 人のメモ(CSV行+自由記述)。CSV行だけ読む
# 人が確認した休業日・未掲載日の機械可読な台帳（hall_name,date,reason,source）
KNOWN_CLOSED_DAYS = PROJECT_ROOT / "document" / "registry" / "KNOWN_CLOSED_DAYS.csv"

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

COUNT_WINDOW = 28
COUNT_WARN_RATIO = 0.10
COUNT_ERROR_RATIO = 0.50
IDENTITY_WINDOW = 7
IDENTITY_WARN = 0.80
IDENTITY_ERROR = 0.50
CROSS_HALL_ERROR = 0.90
AVG_GAMES_EXTREME = 7500  # backfill で周年・強イベント日の最大が 7,437G（ARROW 8/8・平和島 9/19）
GAMES_EXTREME = 12000  # 営業時間で回せる上限の目安（約800G/h × 13h ≒ 10,400G）
DIFF_EXTREME = 30000

DATE_FLAG_COLUMNS = (
    "day_of_week",
    "last_digit",
    "weekday_nth",
    "is_strong_zorome",
    "is_zorome",
    "is_month_start",
    "is_month_end",
    "is_weekend",
    "is_holiday",
    "hall_anniversary",
    "is_x_day",
    "week_of_month",
    "is_any_event",
)


@dataclass
class Issue:
    check: str
    severity: str
    message: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {"check": self.check, "severity": self.severity, "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass
class HallData:
    """1ホール分の DB の中身（監査に要る列だけ）をメモリに載せたもの。"""

    hall: str
    db_path: Path
    rows: dict[str, list[tuple]]  # date -> [(machine_number, machine_name, games, diff, bb, rb)]
    summary: dict[str, dict]  # date -> daily_hall_summary の行
    summary_columns: set[str]
    dates: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.dates = sorted(self.rows)


# --------------------------------------------------------------------------- 読み込み


def safe_hall_filename(hall: str) -> str:
    """incremental_db_updater と同じ規則で DB ファイル名を作る。"""
    return hall.replace(" ", "_").replace("（", "(").replace("）", ")")


def load_halls(config_path: Path) -> list[dict]:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return [h for h in config.get("halls", []) if h.get("active", True)]


def load_hall_data(hall: str, db_path: Path) -> HallData | None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "machine_detailed_results" not in tables:
            return None
        rows: dict[str, list[tuple]] = {}
        for r in conn.execute(
            "SELECT date, machine_number, machine_name, games_normalized, "
            "diff_coins_normalized, bb_count, rb_count FROM machine_detailed_results"
        ):
            rows.setdefault(r[0], []).append(tuple(r[1:]))
        summary: dict[str, dict] = {}
        summary_columns: set[str] = set()
        if "daily_hall_summary" in tables:
            cur = conn.execute("SELECT * FROM daily_hall_summary")
            names = [d[0] for d in cur.description]
            summary_columns = set(names)
            for r in cur:
                rec = dict(zip(names, r))
                summary[rec["date"]] = rec
        return HallData(hall, db_path, rows, summary, summary_columns)
    finally:
        conn.close()


def load_known_missing(data_dir: Path, registry: Path = KNOWN_CLOSED_DAYS) -> set[tuple[str, str]]:
    """休業日・未掲載として人が確認済みの (ホール名小文字, YYYYMMDD)。"""
    out: set[tuple[str, str]] = set()
    for path in (Path(data_dir) / KNOWN_MISSING_CSV, Path(registry)):
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as f:
            for rec in csv.DictReader(f):
                hall, day = (rec.get("hall_name") or "").strip(), (rec.get("date") or "").strip()
                day = day.replace("-", "")
                if hall and len(day) == 8 and day.isdigit():
                    out.add((hall.lower(), day))
    return out


_json_index: dict[Path, dict[str, Path]] = {}


def json_path_for(data_dir: Path, hall: str, day: str) -> Path | None:
    """data/<ホール>/<YYYYMMDD>_<ホール>_data.json。

    ARROW は hall_config が小文字 arrow、ファイル名は大小が混在しているので小文字で照合する。
    """
    folder = data_dir / hall
    if folder not in _json_index:
        index: dict[str, Path] = {}
        if folder.is_dir():
            for name in os.listdir(folder):
                index[name.lower()] = folder / name
        _json_index[folder] = index
    return _json_index[folder].get(("%s_%s_data.json" % (day, hall)).lower())


# --------------------------------------------------------------------------- 個別検査


def _prev_dates(dates: list[str], day: str, n: int) -> list[str]:
    i = bisect.bisect_left(dates, day)
    return dates[max(0, i - n) : i]


def _baseline_dates(dates: list[str], day: str, n: int) -> list[str]:
    """比較の基準にする日。原則は直前 n 収録日。

    収録の最初の数日は直前が足りないので、後ろの日で n 日まで補う（全期間監査で効く）。
    平和島 2025-03-24 は収録5日目で418台中100台しか入っていなかったが、直前4日では
    基準不足で検査が素通りしていた。
    """
    prev = _prev_dates(dates, day, n)
    if len(prev) >= 7:
        return prev
    i = bisect.bisect_right(dates, day)
    return prev + dates[i : i + n - len(prev)]


def _calendar_days_between(a: str, b: str) -> list[str]:
    """a と b の間（両端を含まない）の暦日。"""
    d, end = datetime.strptime(a, "%Y%m%d") + timedelta(days=1), datetime.strptime(b, "%Y%m%d")
    out = []
    while d < end:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def check_continuity(hd: HallData, day: str, data_dir: Path, known_missing: set) -> list[Issue]:
    prev = _prev_dates(hd.dates, day, 1)
    if not prev:
        return []
    missing = _calendar_days_between(prev[0], day)
    if not missing:
        return []
    ingest_failed = [d for d in missing if json_path_for(data_dir, hd.hall, d)]
    confirmed = [d for d in missing if (hd.hall.lower(), d) in known_missing and d not in ingest_failed]
    unknown = [d for d in missing if d not in ingest_failed and d not in confirmed]
    issues = []
    if ingest_failed:
        issues.append(
            Issue("continuity", ERROR, "JSONがあるのにDBに無い日がある（取り込み失敗）", {"dates": ingest_failed})
        )
    if unknown:
        issues.append(Issue("continuity", WARN, "前回収録日との間に欠けた日がある（JSONも無い）", {"dates": unknown}))
    if confirmed:
        issues.append(Issue("continuity", INFO, "確認済みの未掲載日", {"dates": confirmed}))
    return issues


def check_json(hd: HallData, day: str, data_dir: Path) -> list[Issue]:
    path = json_path_for(data_dir, hd.hall, day)
    db_rows = hd.rows.get(day, [])
    if path is None:
        if db_rows:
            return [Issue("json", WARN, "DBにはあるが元のJSONが見つからない", {"folder": str(data_dir / hd.hall)})]
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [Issue("json", ERROR, "JSONを読めない", {"path": path.name, "error": str(error)})]
    issues = []
    json_hall = str(obj.get("hall_name", ""))
    if json_hall.lower() != hd.hall.lower():
        issues.append(
            Issue(
                "json", ERROR, "JSONのhall_nameがフォルダ/ホール名と違う", {"json_hall": json_hall, "path": path.name}
            )
        )
    if str(obj.get("date", "")) != day:
        issues.append(
            Issue("json", ERROR, "JSONのdateがファイル名と違う", {"json_date": obj.get("date"), "path": path.name})
        )
    records = obj.get("all_data") or []
    if not records and db_rows:
        # 2026-08-01 楽園: DB は正常、JSON だけ後日の再取得で空ページに上書きされていた
        issues.append(
            Issue("json", WARN, "JSONが空だがDBは入っている（元JSONが後から空で上書きされた疑い）", {"path": path.name})
        )
    elif not records:
        issues.append(Issue("json", ERROR, "JSONのall_dataが0件（成功扱いの空振り）", {"path": path.name}))
    elif not db_rows:
        issues.append(Issue("json", ERROR, "JSONはあるのにDBに0行（取り込み失敗）", {"json_rows": len(records)}))
    elif len(records) != len(db_rows):
        issues.append(
            Issue(
                "json",
                ERROR,
                "JSONの台数とDBの行数が違う（部分投入）",
                {"json_rows": len(records), "db_rows": len(db_rows)},
            )
        )
    return issues


def check_machine_count(hd: HallData, day: str) -> list[Issue]:
    base = _baseline_dates(hd.dates, day, COUNT_WINDOW)
    prev = _prev_dates(hd.dates, day, 1)
    n = len(hd.rows.get(day, []))
    if len(base) < 7 or n == 0:
        return []
    median = statistics.median(len(hd.rows[d]) for d in base)
    if median <= 0:
        return []
    ratio = n / median
    detail = {"machines": n, "median_28": median, "ratio": round(ratio, 3)}
    if ratio < COUNT_ERROR_RATIO:
        return [Issue("machine_count", ERROR, "台数が直近中央値の半分未満（取り込み途中切れの疑い）", detail)]
    if abs(ratio - 1) >= COUNT_WARN_RATIO:
        # 増台・減台の翌日以降は中央値が追いつくまで（最大2週間）同じずれが続く。
        # 前日と同じ台数なら変化は既に報告済みなので INFO に落とす。
        if prev and len(hd.rows[prev[-1]]) == n:
            return [Issue("machine_count", INFO, "台数のずれが継続中（変化は報告済み）", detail)]
        return [Issue("machine_count", WARN, "台数が直近中央値から±10%以上ずれた（改装・入替・事故）", detail)]
    return []


def check_avg_games(hd: HallData, day: str) -> list[Issue]:
    """台平均G数の跳ね。2日分の合算や二重取り込みを疑う（2025-04-13 戸越は 8,245G・近傍の3.6倍）。"""
    rows = hd.rows.get(day, [])
    if not rows:
        return []

    def mean_games(rs: list[tuple]) -> float:
        return sum(r[2] or 0 for r in rs) / len(rs)

    avg = mean_games(rows)
    if avg <= AVG_GAMES_EXTREME:
        return []
    prev = _prev_dates(hd.dates, day, COUNT_WINDOW)
    median = statistics.median(mean_games(hd.rows[d]) for d in prev) if prev else None
    return [
        Issue(
            "avg_games",
            WARN,
            "台平均G数が%dG超（合算・二重取り込みの疑い）" % AVG_GAMES_EXTREME,
            {"avg_games": round(avg), "median_28": round(median) if median else None},
        )
    ]


def check_hall_identity(hd: HallData, day: str, others: dict[str, HallData]) -> list[Issue]:
    today = hd.rows.get(day, [])
    if not today:
        return []
    issues = []
    numbers = {r[0] for r in today}
    prev = _prev_dates(hd.dates, day, IDENTITY_WINDOW)
    if len(prev) >= 3:
        seen: set = set()
        for d in prev:
            seen.update(r[0] for r in hd.rows[d])
        overlap = len(numbers & seen) / len(numbers)
        detail = {
            "overlap_with_prev7": round(overlap, 3),
            "range": [min(numbers), max(numbers)],
            "prev_range": [min(seen), max(seen)],
        }
        if overlap < IDENTITY_ERROR:
            issues.append(
                Issue("hall_identity", ERROR, "台番号が直近7日とほとんど重ならない（別ホールの中身の疑い）", detail)
            )
        elif overlap < IDENTITY_WARN:
            issues.append(Issue("hall_identity", WARN, "台番号の2割以上が直近7日に無い（大規模入替？）", detail))
    fingerprint = {(r[0], r[2], r[3]) for r in today}
    for name, other in others.items():
        if name == hd.hall:
            continue
        other_rows = other.rows.get(day)
        if not other_rows:
            continue
        share = len(fingerprint & {(r[0], r[2], r[3]) for r in other_rows}) / len(fingerprint)
        if share >= CROSS_HALL_ERROR:
            issues.append(
                Issue(
                    "hall_identity",
                    ERROR,
                    "同じ日の他ホールと中身がほぼ同一（ホール取り違え）",
                    {"other_hall": name, "share": round(share, 3)},
                )
            )
    return issues


_date_calc_cache: dict[str, object] = {}


def _date_calculator(hall: str, config_path: Path):
    from database.date_info_calculator import DateInfoCalculator

    key = "%s|%s" % (hall, config_path)
    if key not in _date_calc_cache:
        # db_path を渡すと DB ディレクトリを作りに行かない（計算だけ使う）
        _date_calc_cache[key] = DateInfoCalculator(hall, db_path=os.devnull, config_path=str(config_path))
    return _date_calc_cache[key]


def jpholiday_available() -> bool:
    try:
        import jpholiday  # noqa: F401
    except ImportError:
        return False
    return True


def check_date_flags(hd: HallData, day: str, config_path: Path) -> list[Issue]:
    n = len(hd.rows.get(day, []))
    rec = hd.summary.get(day)
    if rec is None:
        return [Issue("date_flags", ERROR, "daily_hall_summary に当日の行が無い")] if n else []
    issues = []
    total = rec.get("total_machines")
    if total is not None and n and int(total) != n:
        issues.append(
            Issue(
                "date_flags", ERROR, "daily_hall_summary.total_machines が実行数と違う", {"summary": total, "rows": n}
            )
        )
    missing_cols = [c for c in DATE_FLAG_COLUMNS if c not in hd.summary_columns]
    if missing_cols:
        issues.append(Issue("date_flags", ERROR, "日付フラグ列が無い", {"columns": missing_cols}))
    # jpholiday が無いと DateInfoCalculator は固定10日で祝日を判定する（2026-09-14 の事故の原因）。
    # その状態の再計算値を正解として比べると誤りを見逃すので、祝日系は検査しない。
    holiday_ok = jpholiday_available()
    expected = _date_calculator(hd.hall, config_path).calculate_date_info(day)
    wrong = {}
    for col in DATE_FLAG_COLUMNS:
        if col in missing_cols or (col in ("is_holiday", "is_any_event") and not holiday_ok):
            continue
        got, want = rec.get(col), expected[col]
        if got is None or str(got) != str(want):
            wrong[col] = {"db": got, "expected": want}
    if wrong:
        issues.append(Issue("date_flags", ERROR, "日付フラグが日付からの再計算と違う", wrong))
    if not holiday_ok:
        issues.append(Issue("date_flags", WARN, "jpholiday が無いので is_holiday/is_any_event を検査していない"))
    return issues


def check_values(hd: HallData, day: str) -> list[Issue]:
    rows = hd.rows.get(day, [])
    if not rows:
        return []
    issues = []
    nulls: Counter = Counter()
    negatives: Counter = Counter()
    for _no, _name, games, diff, bb, rb in rows:
        for col, v in (("games", games), ("diff", diff), ("bb", bb), ("rb", rb)):
            if v is None:
                nulls[col] += 1
            elif col != "diff" and v < 0:
                negatives[col] += 1
    if nulls:
        issues.append(Issue("values", ERROR, "NULL がある", dict(nulls)))
    if negatives:
        issues.append(Issue("values", ERROR, "負値がある（G数/BB/RB）", dict(negatives)))
    dup = sorted(no for no, c in Counter(r[0] for r in rows).items() if c > 1)
    if dup:
        issues.append(Issue("values", ERROR, "同じ台番号が同日に重複", {"machine_numbers": dup[:20], "n": len(dup)}))
    if all((r[2] or 0) == 0 for r in rows):
        issues.append(Issue("values", ERROR, "全台のG数が0（空のページを取り込んだ疑い）"))
    # 2025-04-21・2026-07-06 楽園（入替・改装の休業日）は全台が 差枚 -6,142・G数なしのページだった
    diff_value, diff_count = Counter(r[3] for r in rows).most_common(1)[0]
    if len(rows) >= 10 and diff_value not in (None, 0) and diff_count / len(rows) >= 0.9:
        issues.append(
            Issue(
                "values",
                ERROR,
                "9割以上の台で差枚が同じ値（休業日・壊れたページの疑い）",
                {"diff": diff_value, "n": diff_count},
            )
        )
    big_games = [r[0] for r in rows if r[2] is not None and r[2] > GAMES_EXTREME]
    big_diff = [r[0] for r in rows if r[3] is not None and abs(r[3]) > DIFF_EXTREME]
    if big_games:
        issues.append(Issue("values", WARN, "G数が極端（>%d）" % GAMES_EXTREME, {"machine_numbers": big_games[:20]}))
    if big_diff:
        issues.append(Issue("values", WARN, "差枚が極端（|x|>%d）" % DIFF_EXTREME, {"machine_numbers": big_diff[:20]}))
    return issues


# --------------------------------------------------------------------------- 実行


def _record(hall: str, day: str, n: int, issues: list[Issue]) -> dict:
    severities = {i.severity for i in issues}
    return {
        "audited_at": datetime.now().isoformat(timespec="seconds"),
        "hall": hall,
        "date": day,
        "status": ERROR if ERROR in severities else WARN if WARN in severities else "OK",
        "machines": n,
        "n_error": sum(i.severity == ERROR for i in issues),
        "n_warn": sum(i.severity == WARN for i in issues),
        "issues": [i.to_dict() for i in issues],
    }


def audit_hall_day(
    hd: HallData,
    day: str,
    others: dict[str, HallData],
    data_dir: Path,
    config_path: Path,
    known_missing: set,
) -> dict:
    issues: list[Issue] = []
    n = len(hd.rows.get(day, []))
    if n == 0:
        issues.append(Issue("presence", INFO, "当日分がDBに無い（未掲載・未取得）"))
    issues += check_json(hd, day, data_dir)
    if n:
        issues += check_continuity(hd, day, data_dir, known_missing)
        issues += check_machine_count(hd, day)
        issues += check_avg_games(hd, day)
        issues += check_hall_identity(hd, day, others)
        issues += check_values(hd, day)
    issues += check_date_flags(hd, day, config_path)
    return _record(hd.hall, day, n, issues)


def run_audit(
    days: Iterable[str] | None,
    halls: list[str] | None,
    db_dir: Path,
    data_dir: Path,
    config_path: Path,
    all_days: bool = False,
) -> list[dict]:
    hall_names = [h["hall_name"] for h in load_halls(config_path)]
    loaded: dict[str, HallData] = {}
    for name in hall_names:
        hd = load_hall_data(name, Path(db_dir) / ("%s.db" % safe_hall_filename(name)))
        if hd is not None:
            loaded[name] = hd
    wanted = {x.lower() for x in halls or []}
    unknown = wanted - {h.lower() for h in hall_names}
    if unknown:
        raise SystemExit("hall_config に無いホール名: %s" % ", ".join(sorted(unknown)))
    targets = [h for h in hall_names if not wanted or h.lower() in wanted]
    known_missing = load_known_missing(Path(data_dir))
    results = []
    for name in targets:
        if name not in loaded:
            for day in list(days or []) or ["-"]:
                results.append(_record(name, day, 0, [Issue("presence", ERROR, "DBが無い・空・テーブル無し")]))
            continue
        hd = loaded[name]
        for day in hd.dates if all_days else list(days or []):
            results.append(audit_hall_day(hd, day, loaded, Path(data_dir), Path(config_path), known_missing))
    return results


def append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def print_report(results: list[dict], summary_only: bool = False) -> None:
    by_status = Counter(r["status"] for r in results)
    print("監査 %d件: ERROR %d / WARN %d / OK %d" % (len(results), by_status[ERROR], by_status[WARN], by_status["OK"]))
    if summary_only:
        counter: Counter = Counter()
        for r in results:
            for i in r["issues"]:
                counter[(r["hall"], i["severity"], i["check"], i["message"])] += 1
        for (hall, sev, check, msg), c in sorted(counter.items()):
            print("  %-5s %-28s %-13s %4d日  %s" % (sev, hall, check, c, msg))
        return
    for r in results:
        print("  %-5s %s %s (%d台)" % (r["status"], r["date"], r["hall"], r["machines"]))
        for i in r["issues"]:
            detail = json.dumps(i.get("detail", {}), ensure_ascii=False) if i.get("detail") else ""
            if len(detail) > 200:
                detail = detail[:200] + "…"
            print("      [%s] %s: %s %s" % (i["severity"], i["check"], i["message"], detail))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ana-slo 取り込みDBのデータ品質監査")
    parser.add_argument(
        "--date",
        action="append",
        help="監査する日 YYYY-MM-DD または YYYYMMDD（複数可。朝の実行は遡って取り込んだ日もまとめて渡す）",
    )
    parser.add_argument("--hall", action="append", help="ホール名（複数可）。省略時は hall_config の active 全ホール")
    parser.add_argument("--all-days", action="store_true", help="DBにある全日付を監査する")
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="追記先 JSONL")
    parser.add_argument("--no-write", action="store_true", help="JSONL に追記しない")
    parser.add_argument("--summary", action="store_true", help="ホール×検査ごとの件数だけ表示する")
    args = parser.parse_args(argv)

    if not args.all_days and not args.date:
        parser.error("--date か --all-days のどちらかが必要")
    days = None
    if args.date:
        days = []
        for value in args.date:
            try:
                day = datetime.strptime(value.replace("-", ""), "%Y%m%d").strftime("%Y%m%d")
            except ValueError:
                parser.error("--date は YYYY-MM-DD か YYYYMMDD: %s" % value)
            if day not in days:
                days.append(day)

    results = run_audit(days, args.hall, args.db_dir, args.data_dir, args.config, all_days=args.all_days)
    if not args.no_write:
        append_jsonl(args.out, results)
    print_report(results, summary_only=args.summary)
    return 1 if any(r["status"] == ERROR for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
