"""日中RB事後確率と同日の最終RB事後確率の対応を評価する。"""

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .estimate import ROOT, estimate, mark_new_machines
from .schema import SnapshotRow

MIN_FINAL_GAMES = 3000
MIN_BIN_N = 10
TOP_N = 10
CALIBRATION_BINS = 10
SNAPSHOTS = ROOT / "scraper/realtime/output/snapshots"


def _ranks(values):
    ordered = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for start in range(len(values)):
        if start and values[ordered[start]] == values[ordered[start - 1]]:
            continue
        end = start + 1
        while end < len(values) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        for pos in range(start, end):
            ranks[ordered[pos]] = (start + end - 1) / 2
    return ranks


def _spearman(x, y):
    a, b = _ranks(x), _ranks(y)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((u - ma) * (v - mb) for u, v in zip(a, b))
    da = sum((u - ma) ** 2 for u in a)
    db = sum((v - mb) ** 2 for v in b)
    return num / math.sqrt(da * db) if da and db else None


def _bin(stamp):
    return datetime.fromisoformat(stamp).strftime("%H:00")


def evaluate_rows(
    rows,
    final_rows,
    *,
    hall,
    db_dir=ROOT / "db",
    specs=None,
    audit=None,
    min_final_games=MIN_FINAL_GAMES,
    min_n=MIN_BIN_N,
    top_n=TOP_N,
):
    mark_new_machines(rows, db_dir)
    final = {}
    for item in final_rows:
        if item["games"] is None or item["games"] < min_final_games or item["rb"] is None:
            continue
        probe = SnapshotRow(
            hall=hall,
            observed_at=rows[0].observed_at,
            source_updated_at=None,
            unit=int(item["unit"]),
            model=item["model"],
            model_raw=item["model"],
            games=item["games"],
            rb=item["rb"],
        )
        value = estimate(probe, specs=specs, audit=audit)["p_high"]
        if value is not None:
            final[probe.unit] = value
    bins = defaultdict(dict)
    for row in rows:
        if row.is_new_machine or row.unit not in final:
            continue
        prediction = estimate(row, specs=specs, audit=audit)["p_high"]
        if prediction is not None:
            key = _bin(row.observed_at)
            previous = bins[key].get(row.unit)
            if previous is None or row.observed_at > previous[0]:
                bins[key][row.unit] = (row.observed_at, prediction, final[row.unit])
    result = {}
    for key, items in sorted(bins.items()):
        pairs = [(p, f) for _, p, f in items.values()]
        n = len(pairs)
        if n < min_n:
            result[key] = {
                "n": n,
                "status": "判定不能",
                "spearman": None,
                "top_mean": None,
                "all_mean": None,
                "calibration": [],
            }
            continue
        ordered = sorted(pairs, key=lambda pair: pair[0], reverse=True)
        count = min(top_n, n)
        calibration = []
        by_prediction = sorted(pairs)
        for q in range(CALIBRATION_BINS):
            chunk = by_prediction[q * n // CALIBRATION_BINS : (q + 1) * n // CALIBRATION_BINS]
            if chunk:
                calibration.append(
                    {
                        "decile": q + 1,
                        "n": len(chunk),
                        "predicted_mean": sum(p for p, _ in chunk) / len(chunk),
                        "final_mean": sum(f for _, f in chunk) / len(chunk),
                    }
                )
        correlation = _spearman([p for p, _ in pairs], [f for _, f in pairs])
        result[key] = {
            "n": n,
            "status": "判定不能" if correlation is None else "参考値",
            "spearman": correlation,
            "top_mean": sum(f for _, f in ordered[:count]) / count,
            "all_mean": sum(f for _, f in pairs) / n,
            "calibration": calibration,
        }
    return result


def load_final(db_path, date):
    with sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True) as con:
        return [
            {"unit": unit, "model": model, "games": games, "rb": rb}
            for unit, model, games, rb in con.execute(
                "SELECT machine_number, machine_name, games_normalized, rb_count "
                "FROM machine_detailed_results WHERE date=?",
                (date,),
            )
        ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--hall", required=True)
    args = parser.parse_args(argv)
    try:
        date = datetime.strptime(args.date, "%Y%m%d").date()
    except ValueError:
        parser.error("--date must be YYYYMMDD")
    db_path = ROOT / "db" / f"{args.hall}.db"
    if not db_path.is_file() or not db_path.stat().st_size:
        print(f"{args.hall}: 結果DBなし")
        return 0
    if "蒲田7" in args.hall and date.strftime("%m%d") == "0707":
        print("蒲田7の7/7は全設定6の特殊日: 評価対象から除外")
        return 0
    rows = []
    for path in SNAPSHOTS.glob("*.jsonl"):
        with path.open(encoding="utf-8-sig") as stream:
            rows.extend(
                SnapshotRow(**item)
                for line in stream
                if (item := json.loads(line)).get("hall") == args.hall
                and item.get("observed_at", "")[:10] == date.isoformat()
            )
    if not rows:
        print("当日スナップショットなし")
        return 0
    result = evaluate_rows(rows, load_final(db_path, args.date), hall=args.hall)
    for hour, values in result.items():
        print(
            f'{hour} n={values["n"]} {values["status"]} Spearman={values["spearman"]} 上位平均={values["top_mean"]} 全体平均={values["all_mean"]}'
        )
        for cell in values["calibration"]:
            print(
                f'  {cell["decile"]}分位 n={cell["n"]} 予測平均={cell["predicted_mean"]:.3f} 最終平均={cell["final_mean"]:.3f}'
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
