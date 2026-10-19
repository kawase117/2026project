"""同じJST日の各ホール最新観測を横断順位にする。"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from .estimate import ROOT, at_scores, estimate, mark_new_machines
from .schema import JST, SnapshotRow
from .section_rb import section_rb as compute_section_rb

OUTPUT = ROOT / "scraper/realtime/output/rankings"
FINAL_NO_PRIOR_TOP = 20  # 総合ランキング末尾の「事前なし」参考表の行数


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
    rows,
    *,
    top=50,
    min_confidence=0.0,
    db_dir=ROOT / "db",
    hall_prior=None,
    specs_by_hall=None,
    audit=None,
    section_rb=True,
):
    if top < 1 or not 0 <= min_confidence <= 1:
        raise ValueError("top and min_confidence out of range")
    mark_new_machines(rows, db_dir)
    context = at_scores(rows)
    buckets = {"ranked": [], "no_prior": [], "at_scores": [], "uncertain": [], "new_machines": []}
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
            "setting_probabilities": {str(s): p for s, p in (result.get("setting_probabilities") or {}).items()},
            "confidence": result["confidence"],
            "discriminability": result["discriminability"],
            "kind": result["kind"],
            "score": result["score"],
            "prior_applied": result.get("prior_applied"),
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
        elif result.get("prior_applied") is False:
            # ホール別事前の無い台(DBなし・台日不足)は一様事前のままで、事前のある台と同じ表に混ぜない
            bucket = "no_prior"
        else:
            bucket = "ranked"
        buckets[bucket].append(item)
    buckets["ranked"].sort(key=lambda x: x["p_high"], reverse=True)
    buckets["no_prior"].sort(key=lambda x: x["p_high"], reverse=True)
    buckets["at_scores"].sort(key=lambda x: x["score"], reverse=True)
    buckets["uncertain"].sort(key=lambda x: (x["p_high"] is not None, x["p_high"] or -1), reverse=True)
    buckets["ranked"] = buckets["ranked"][:top]
    buckets["no_prior"] = buckets["no_prior"][:top]
    buckets["at_scores"] = buckets["at_scores"][:top]
    # 列・島ごとのRB合算(台ごとの確率では薄まる列単位の偏りを拾う)。順位の本表には混ぜない
    buckets["section_rb"] = (
        compute_section_rb(rows, db_dir=db_dir, specs_by_hall=specs_by_hall, audit=audit) if section_rb else {}
    )
    return buckets


def format_section_rb(data):
    """列・島ごとの合算RB。データが空なら何も出さない(空文字)。"""
    section = data.get("section_rb") or {}
    if not any(section.values()):
        return ""
    lines = [
        "\n##### 列・島ごとの合算RB(RB判別できる台のみ・設定平均のp値が小さい順) #####",
        "※偶然の確率が小さいほど、列全体で高設定寄りに偏っている。途中経過の偏りは最終で薄まりうる。",
    ]
    for hall, entries in section.items():
        if not entries:
            continue
        lines += [
            f"【{hall}】",
            "台番号範囲 | 台数 | 機種 | 合算G | 合算RB | 1/x | 最高設定超 | p(最低設定) | p(設定平均)",
        ]
        for e in entries:
            one_in = "-" if e["rb_one_in"] is None else f'1/{e["rb_one_in"]:.0f}'
            p_low = "-" if e["p_low"] is None else f'{e["p_low"]:.2g}'
            p_avg = "-" if e["p_avg"] is None else f'{e["p_avg"]:.2g}'
            lines.append(
                f'{e["unit_from"]}〜{e["unit_to"]} | {e["n"]} | {"・".join(e["models"])} | {e["total_games"]} | '
                f'{e["total_rb"]} | {one_in} | {e["better_than_high"]}/{e["n"]} | {p_low} | {p_avg}'
            )
    return "\n".join(lines)


def format_ranking(data):
    titles = {
        "ranked": "RB事後確率順位",
        "no_prior": "ホール別事前なし（一様事前のため高めに出る。順位に混ぜない）",
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
    return "\n".join(lines) + format_section_rb(data)


def format_hall_report(hall, rows, top=8, hall_prior=None):
    """1ホール分の即時報告。RB事後確率の高い順(判別可能機種のみ)。事前なしの台は(補正なし)を付けて同じ表に並べる。"""
    data = build_ranking(rows, top=10000, hall_prior=hall_prior, section_rb=False)
    ranked = sorted(
        (r for r in data["ranked"] + data["no_prior"] if r["rb"]),  # RB0は情報なしなので表示しない
        key=lambda r: r["p_high"],
        reverse=True,
    )
    stamp = max((r.observed_at for r in rows), default="")[11:16]
    estimable = sum(1 for r in ranked + data["uncertain"] if r["p_high"] is not None)
    lines = [f"\n=== {hall} (観測{stamp} / 取得{len(rows)}台 / RBで推定できた台{estimable}) ==="]
    if not ranked:
        lines.append("  推定できる台がありません")
    for r in ranked[:top]:
        mark = " (補正なし)" if r.get("prior_applied") is False else ""
        lines.append(
            f'  {r["unit"]} {r["model"]} {r["games"]}G RB{r["rb"]} 設定5以上={r["p_high"]:.2f} (確度{r["confidence"]:.2f}){mark}'
        )
    return "\n".join(lines)


def format_final(data):
    """全ホール完了後の総合ランキング(設定5以上の確率が高い順)。"""
    lines = [
        "\n##### 総合ランキング(設定5以上の確率が高い順・RB判別可能機種) #####",
        "順位 | ホール | 台 | 機種 | G | RB | 設定5以上 | 確度",
    ]
    for i, r in enumerate((r for r in data["ranked"] if r["rb"]), 1):
        lines.append(
            f'{i} | {r["hall"]} | {r["unit"]} | {r["model"]} | {r["games"]} | {r["rb"]} | {r["p_high"]:.2f} | {r["confidence"]:.2f}'
        )
    lines.append("※途中の高RBは最終で平均に回帰しうる。判別不能に近い機種・AT機・新台は含まない。")
    no_prior = [r for r in data.get("no_prior", []) if r["rb"]][:FINAL_NO_PRIOR_TOP]
    if no_prior:
        lines += [
            "\n##### ホール別事前なし(補正なし・順位に混ぜない参考表) #####",
            "※DBがない、または台日不足で一様事前のまま。4設定機は5以上が50%から始まるため、上の表より高く出る。",
            "ホール | 台 | 機種 | G | RB | 設定5以上 | 確度",
        ]
        for r in no_prior:
            lines.append(
                f'{r["hall"]} | {r["unit"]} | {r["model"]} | {r["games"]} | {r["rb"]} | {r["p_high"]:.2f} | {r["confidence"]:.2f}'
            )
    return "\n".join(lines) + format_section_rb(data)


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
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--uniform-prior", action="store_true", help="ホール別の設定事前を使わず一様事前にする")
    args = parser.parse_args(argv)
    rows = read_snapshots(args.snapshots, latest_per_hall=True)
    from .hall_prior import load_hall_priors

    data = build_ranking(
        rows,
        top=args.top,
        min_confidence=args.min_confidence,
        hall_prior=None if args.uniform_prior else load_hall_priors(),
    )
    print(format_ranking(data))
    print(f"JSON: {write_ranking(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
