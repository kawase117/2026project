"""同じJST日の各ホール最新観測を横断順位にする。"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from .estimate import ROOT, at_scores, estimate, mark_new_machines
from .schema import JST, SnapshotRow

OUTPUT = ROOT / "scraper/realtime/output/rankings"


def read_snapshots(paths, latest_per_hall=True):
    files = [f for p in paths for f in (sorted(p.rglob("*.jsonl")) if p.is_dir() else [p])]
    rows = []
    for path in files:
        with path.open(encoding="utf-8-sig") as stream:
            rows.extend(SnapshotRow(**json.loads(line)) for line in stream if line.strip())
    if not rows:
        return []
    day = max(r.observed_at[:10] for r in rows)
    rows = [r for r in rows if r.observed_at[:10] == day]
    if latest_per_hall:
        latest = {}
        for r in rows:
            latest[r.hall] = max(latest.get(r.hall, ""), r.observed_at)
        rows = [r for r in rows if r.observed_at == latest[r.hall]]
    return list({(r.hall, r.observed_at, r.unit): r for r in rows}.values())


def build_ranking(
    rows, *, top=30, min_confidence=0.0, db_dir=ROOT / "db", hall_prior=None, specs_by_hall=None, audit=None
):
    if top < 1 or not 0 <= min_confidence <= 1:
        raise ValueError("top and min_confidence out of range")
    mark_new_machines(rows, db_dir)
    context = at_scores(rows)
    buckets = {"ranked": [], "at_scores": [], "uncertain": [], "new_machines": []}
    for row in rows:
        result = estimate(
            row, specs=(specs_by_hall or {}).get(row.hall), audit=audit, hall_prior=hall_prior, at_context=context
        )
        item = {
            "hall": row.hall,
            "unit": row.unit,
            "model": row.model,
            "games": row.games,
            "rb": row.rb,
            "p_high": result["p_high"],
            "confidence": result["confidence"],
            "discriminability": result["discriminability"],
            "kind": result["kind"],
            "score": result["score"],
            "flags": list(row.quality_flags),
            "notes": result["notes"],
            "is_new_machine": row.is_new_machine,
            "observed_at": row.observed_at,
        }
        if row.is_new_machine:
            item["notes"].append("導入後7日以内（DB初出日を代用）: 順位から除外")
            bucket = "new_machines"
        elif result["kind"] == "at_gratio_diff":
            bucket = "at_scores"
        elif result["discriminability"] != "high" or result["confidence"] < min_confidence:
            bucket = "uncertain"
        else:
            bucket = "ranked"
        buckets[bucket].append(item)
    buckets["ranked"].sort(key=lambda x: x["p_high"], reverse=True)
    buckets["at_scores"].sort(key=lambda x: x["score"], reverse=True)
    buckets["uncertain"].sort(key=lambda x: (x["p_high"] is not None, x["p_high"] or -1), reverse=True)
    buckets["ranked"] = buckets["ranked"][:top]
    buckets["at_scores"] = buckets["at_scores"][:top]
    return buckets


def format_ranking(data):
    titles = {
        "ranked": "RB事後確率順位",
        "at_scores": "AT参考スコア（G比×平均差枚）",
        "uncertain": "判別不能に近い・判別不能",
        "new_machines": "新台（順位から除外）",
    }
    lines = []
    for key, title in titles.items():
        lines += [f"\n{title}", "ホール | 台 | 機種 | G | RB | p_high | AT score | confidence | 判別力 | flags"]
        for r in data[key]:
            p = "-" if r["p_high"] is None else f'{r["p_high"]:.3f}'
            score = "-" if r["score"] is None else f'{r["score"]:.1f}'
            flags = ",".join(r["flags"] + r["notes"])
            lines.append(
                f'{r["hall"]} | {r["unit"]} | {r["model"]} | {r["games"]} | {r["rb"]} | {p} | {score} | {r["confidence"]:.3f} | {r["discriminability"]} | {flags}'
            )
    return "\n".join(lines)


def format_hall_report(hall, rows, top=8):
    """1ホール分の即時報告。RB事後確率の高い順(判別可能機種のみ)。"""
    data = build_ranking(rows, top=10000)
    ranked = data["ranked"]
    stamp = max((r.observed_at for r in rows), default="")[11:16]
    estimable = sum(1 for r in ranked + data["uncertain"] if r["p_high"] is not None)
    lines = [f"\n=== {hall} (観測{stamp} / 取得{len(rows)}台 / RBで推定できた台{estimable}) ==="]
    if not ranked:
        lines.append("  推定できる台がありません")
    for r in ranked[:top]:
        lines.append(
            f'  {r["unit"]} {r["model"]} {r["games"]}G RB{r["rb"]} 設定5以上={r["p_high"]:.2f} (確度{r["confidence"]:.2f})'
        )
    return "\n".join(lines)


def format_final(data):
    """全ホール完了後の総合ランキング(設定5以上の確率が高い順)。"""
    lines = [
        "\n##### 総合ランキング(設定5以上の確率が高い順・RB判別可能機種) #####",
        "順位 | ホール | 台 | 機種 | G | RB | 設定5以上 | 確度",
    ]
    for i, r in enumerate(data["ranked"], 1):
        lines.append(
            f'{i} | {r["hall"]} | {r["unit"]} | {r["model"]} | {r["games"]} | {r["rb"]} | {r["p_high"]:.2f} | {r["confidence"]:.2f}'
        )
    lines.append("※途中の高RBは最終で平均に回帰しうる。判別不能に近い機種・AT機・新台は含まない。")
    return "\n".join(lines)


def write_ranking(data, out_dir=OUTPUT, now=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(JST)).astimezone(JST).strftime("%Y%m%d_%H%M%S")
    for i in range(10000):
        path = out_dir / f'ranking_{stamp}{"" if i == 0 else f"_{i}"}.json'
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            return path
        except FileExistsError:
            continue
    raise FileExistsError("ranking sequence exhausted")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", nargs="+", type=Path, required=True)
    parser.add_argument("--latest-per-hall", action="store_true")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    args = parser.parse_args(argv)
    rows = read_snapshots(args.snapshots, latest_per_hall=True)
    data = build_ranking(rows, top=args.top, min_confidence=args.min_confidence)
    print(format_ranking(data))
    print(f"JSON: {write_ranking(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
