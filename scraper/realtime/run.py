"""5ホールの収集系統を並行実行し、共通JSONLへ変換する。"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .adapters import daidata, dmm, site777
from .store import write_snapshot

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
JST = ZoneInfo("Asia/Tokyo")
HALLS = {
    "hiroki_west": ("ヒロキ西口店", "dmm", "nishiguchi"),
    "hiroki_max": ("ヒロキMAX蒲田店", "dmm", "max"),
    "hiroki_east": ("ヒロキ東口店", "dmm", "higashiguchi"),
    "mitoya": ("みとや大森町店", "daidata", None),
    "rakuen": ("楽園蒲田店", "site777", None),
}


_PRINT_LOCK = threading.Lock()
_ROWS: dict[str, list] = {}  # ホール名 -> 今回の収集で保存した行(最後の総合ランキング用)
REPORT = {"each": True, "top": 8}


def _publish(rows, hall: str, mode: str) -> None:
    """スナップショットを保存し、そのホールの上位を即座に出す(全体の完了を待たない)。"""
    write_snapshot(rows, HERE / "output", hall, mode, datetime.now(JST))
    _ROWS[hall] = rows
    if REPORT["each"]:
        from .rank import format_hall_report

        text = format_hall_report(hall, rows, top=REPORT["top"])
        with _PRINT_LOCK:
            print(text, flush=True)


def _without(command: list[str], *flags: str) -> list[str]:
    """コマンドから「--flag 値」の組を取り除く。"""
    result, skip = [], False
    for part in command:
        if skip:
            skip = False
        elif part in flags:
            skip = True
        else:
            result.append(part)
    return result


def _failed_units(document: dict) -> set[str]:
    return {str(f["machine_number"]) for f in document.get("failures") or [] if f.get("machine_number")}


def _top_up(path: Path, hall: str, base_command: list[str], audit, flags, process):
    """一覧で当たり(BB+RB>=1)があるRB判別可能機種のうち、詳細が無い台を取りこぼしなく取る。

    collectorのquickは今回の対象台の詳細しか出力に残さないので、1回目の詳細を統合して書き戻す。
    台単位の失敗(45秒タイムアウトなど)があっても取得できた詳細は捨てず、失敗した台は1回だけ再試行する。
    """
    from .quick_filter import select_first_pass

    first = json.loads(path.read_text(encoding="utf-8-sig"))
    missing = [r for r in dmm.adapt(path, hall) if r.games is None]
    units = select_first_pass(missing, audit, flags)
    if not units and not _failed_units(first):
        return process
    # 追加取得は選別済みの台だけ。collector側の判定(--rb-quick-min-games)を外し、1回目と二重に取らない。
    plain = _without(base_command, "--rb-quick-min-games", "--snapshot-hall")
    details = dict(first.get("details", {}))
    failures = list(first.get("failures") or [])
    document = first
    wanted = sorted(set(map(str, units)) | _failed_units(first))
    for _ in range(2):  # 追加取得1回 + 失敗台の再試行1回
        if not wanted:
            break
        before = path.stat().st_mtime_ns
        process = _run_command(plain + ["--units", *wanted])
        if path.stat().st_mtime_ns == before:
            break  # 出力が更新されなかった
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        details.update(document.get("details", {}))
        failures += list(document.get("failures") or [])
        failures = [f for f in failures if str(f.get("machine_number")) not in details]
        wanted = sorted(_failed_units({"failures": failures}))
    document["details"] = details
    document["detail_count"] = len(details)
    document["failures"] = failures
    document["complete"] = not failures
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return process


@dataclass
class Result:
    hall: str
    source: str
    count: int = 0
    failures: int = 0
    seconds: float = 0
    data_time: str = "-"
    status: str = "FAIL"
    error: str = ""


def first_line(error: BaseException | str) -> str:
    return str(error).splitlines()[0] if str(error) else ""


def commands(halls: list[str], mode: str, quick_min_games: int) -> dict[str, list[list[str]]]:
    result = {"dmm": [], "site777": [], "daidata": []}
    for key in halls:
        _, source, code = HALLS[key]
        if source == "dmm":
            command = [
                str(ROOT / "venv/Scripts/python.exe"),
                str(ROOT / "scraper/dmm_goraggio/collector.py"),
                "--hall",
                code,
                "--mode",
                mode,
            ]
            if mode == "quick":
                command += ["--rb-quick-min-games", str(quick_min_games), "--snapshot-hall", HALLS[key][0]]
            result[source].append(command)
        elif source == "site777":
            if mode == "quick":
                # RB台表のみ取得し、最高出玉とグラフは省く。機種の絞り込み(-ModelNamesFile)は _site が付け足す。
                result[source].append(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(ROOT / "scraper/site777/run_site777_full_collect_parallel.ps1"),
                        "-SkipHighest",
                    ]
                )
            else:
                result[source].append([str(ROOT / "scraper/site777/run_site777_complete.cmd")])
        else:
            # TODO: daidata は収集元が全21.3円台を返すため、取得前の詳細対象絞り込み未対応。
            result[source].append([str(ROOT / "venv/Scripts/python.exe"), str(ROOT / "scraper/daidata/collect.py")])
    return result


def format_table(results: list[Result]) -> str:
    lines = [
        "hall | 系統 | 取得台数 | 失敗数 | 所要秒 | データ時刻 | 状態",
        "--- | --- | ---: | ---: | ---: | --- | ---",
    ]
    for r in results:
        lines.append(f"{r.hall} | {r.source} | {r.count} | {r.failures} | {r.seconds:.1f} | {r.data_time} | {r.status}")
    return "\n".join(lines)


def _run_command(command: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    # 収集先が返したヘッダ等は保存・表示しない。
    return subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )


def _dmm(keys: list[str], mode: str, quick_min_games: int) -> list[Result]:
    result = []
    for key in keys:  # DMM内は必ず直列
        hall, source, code = HALLS[key]
        start = time.monotonic()
        item = Result(hall, source)
        path = ROOT / "scraper/dmm_goraggio" / ("output" if code == "max" else f"output_{code}") / f"latest_{mode}.json"
        try:
            command = commands([key], mode, quick_min_games)["dmm"][0]
            base_command = list(command)
            audit = flags = None
            if mode == "quick":
                # 既存collectorの変化台取得を維持。前回のスナップショットにある台は強制で再取得する。
                from .quick_filter import (
                    audit_for_hall,
                    load_audit,
                    load_master_flags,
                    load_master_flags_any,
                    load_previous,
                    select_units,
                )

                previous = load_previous(HERE / "output/snapshots", hall, datetime.now(JST))
                flags = load_master_flags(ROOT / "db" / f"{hall}.db") or load_master_flags_any(ROOT / "db")
                audit = audit_for_hall(load_audit(), hall)
                if previous:
                    units = select_units(previous, [], audit, flags, quick_min_games)
                    if units:
                        command += ["--units", *map(str, units)]
            before = path.stat().st_mtime_ns if path.exists() else -1
            process = _run_command(command)
            if not path.exists() or path.stat().st_mtime_ns == before:
                raise RuntimeError("DMM output was not refreshed")
            if mode == "quick":
                process = _top_up(path, hall, base_command, audit, flags, process)
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            rows = dmm.adapt(path, hall)
            _publish(rows, hall, mode)
            item.count = len(rows)
            item.failures = len(document.get("failures") or [])
            item.data_time = max((r.source_updated_at for r in rows if r.source_updated_at), default="-")
            item.status = "OK" if document.get("complete") else "INCOMPLETE"
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            item.error = first_line(exc)
        item.seconds = time.monotonic() - start
        result.append(item)
    return result


def _site(keys: list[str], mode: str, quick_min_games: int) -> list[Result]:
    hall = HALLS[keys[0]][0]
    item = Result(hall, "site777")
    start = time.monotonic()
    output = ROOT / "scraper/site777/output"
    summary_path = output / ("site777_quick_summary.json" if mode == "quick" else "site777_graph_summary_filtered.json")
    try:
        before = summary_path.stat().st_mtime_ns if summary_path.exists() else -1
        command = commands(keys, mode, quick_min_games)["site777"][0]
        if mode == "quick":
            from .adapters.common import model_name
            from .quick_filter import (
                audit_for_hall,
                load_audit,
                load_master_flags,
                load_master_flags_any,
                site_model_allowlist,
            )

            flags = load_master_flags(ROOT / "db" / f"{hall}.db") or load_master_flags_any(ROOT / "db")
            allowed = site_model_allowlist(
                output / "site777_full_data.json", hall, audit_for_hall(load_audit(), hall), flags, model_name
            )
            if allowed:  # 前回フル収集が無ければ絞らず全機種を取る
                names_path = HERE / "output" / "site777_quick_models.json"
                names_path.parent.mkdir(parents=True, exist_ok=True)
                names_path.write_text(
                    json.dumps(allowed), encoding="utf-8"
                )  # ASCIIエスケープ(PowerShell 5の文字コード対策)
                command += ["-ModelNamesFile", str(names_path)]
        _run_command(command)
        if not summary_path.exists() or summary_path.stat().st_mtime_ns == before:
            raise RuntimeError("site777 summary was not refreshed")
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        rows = site777.adapt(output, hall, quick=mode == "quick")
        _publish(rows, hall, mode)
        item.count = len(rows)
        item.failures = int(summary.get("failures") or 0)
        item.data_time = max((r.source_updated_at for r in rows if r.source_updated_at), default="-")
        item.status = "OK" if summary.get("ok") and summary.get("complete") and not item.failures else "INCOMPLETE"
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        item.error = first_line(exc)
    item.seconds = time.monotonic() - start
    return [item]


def _daidata(keys: list[str], mode: str, quick_min_games: int) -> list[Result]:
    hall = HALLS[keys[0]][0]
    item = Result(hall, "daidata")
    start = time.monotonic()
    output = ROOT / "scraper/daidata/output"
    try:
        before = {p: p.stat().st_mtime_ns for p in output.glob("mitoya_omorimachi_slots_21.3yen_*.csv")}
        process = _run_command(commands(keys, mode, quick_min_games)["daidata"][0])
        fresh = [
            p for p in output.glob("mitoya_omorimachi_slots_21.3yen_*.csv") if p.stat().st_mtime_ns != before.get(p)
        ]
        if not fresh:
            raise RuntimeError("daidata CSV was not refreshed")
        rows = daidata.adapt(max(fresh, key=lambda p: p.stat().st_mtime_ns), hall)
        _publish(rows, hall, mode)
        item.count = len(rows)
        item.data_time = max((r.observed_at for r in rows), default="-")
        item.status = "OK" if process.returncode == 0 else "INCOMPLETE"
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        item.error = first_line(exc)
    item.seconds = time.monotonic() - start
    return [item]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--halls", default="all")
    parser.add_argument("--mode", choices=("full", "quick"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quick-min-games", type=int, default=1000)
    parser.add_argument("--no-report", action="store_true", help="ホールごとの即時報告と最後の総合ランキングを出さない")
    parser.add_argument("--report-top", type=int, default=8, help="ホールごとの即時報告に出す台数")
    parser.add_argument("--final-top", type=int, default=50, help="最後の総合ランキングに出す台数")
    args = parser.parse_args(argv)
    keys = list(HALLS) if args.halls == "all" else args.halls.split(",")
    if not keys or any(key not in HALLS for key in keys) or len(set(keys)) != len(keys):
        parser.error("--halls must be all or comma-separated known hall keys")
    if args.quick_min_games < 0:
        parser.error("--quick-min-games must be nonnegative")
    grouped = {source: [key for key in keys if HALLS[key][1] == source] for source in ("dmm", "site777", "daidata")}
    if args.dry_run:
        for source, command_list in commands(keys, args.mode, args.quick_min_games).items():
            for command in command_list:
                print(source, subprocess.list2cmdline(command))
        if args.mode == "quick":
            print(
                f"quick: RB eligible (audit A or master normal/BT/A+AT; X excluded); "
                f"games >= {args.quick_min_games} or same-day BB/RB/G changed"
            )
            print("site777: RB table only; graph skipped. daidata: prefetch filtering TODO")
        return 0
    REPORT.update(each=not args.no_report, top=args.report_top)
    workers = {"dmm": _dmm, "site777": _site, "daidata": _daidata}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            source: pool.submit(workers[source], selected, args.mode, args.quick_min_games)
            for source, selected in grouped.items()
            if selected
        }
        results = [item for future in futures.values() for item in future.result()]
    print(format_table(results))
    if not args.no_report and _ROWS:
        from .rank import build_ranking, format_final, write_ranking

        data = build_ranking([r for rows in _ROWS.values() for r in rows], top=args.final_top)
        print(format_final(data))
        print(f"JSON: {write_ranking(data)}")
    for item in results:
        if item.error:
            print(f"{item.hall}: {item.error}", file=sys.stderr)
    return 0 if all(item.status == "OK" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
