"""ホール・機種別の設定事前をDBのRBから推定して保存する。

推定はRBだけを使う(BBは隣り合う設定を分けにくく、合算もしない)。2000G以上の台日を混合分布のEMで
分解し、設定ごとの台日あたり平均割合を求める。ホールが据え置きや稼働の偏りで見せる割合なので、
「その日の投入数」ではなく「その期間の平均」。回された台に限るため、低設定は実際より少なめに出る。
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.stats import poisson

from backtest.bonus_specs import find_spec, load_specs, normalize

ROOT = Path(__file__).resolve().parents[2]
PRIOR_PATH = ROOT / "scraper/realtime/output/hall_priors.json"
MIN_GAMES = 2000  # これ未満の台日はRB確率が不安定で、回されない台の偏りも強い
MIN_MACHINE_DAYS = 300  # 6設定機: これ未満は事前を作らず一様のまま(150台日台では窓を変えると5〜6割合が大きく動く)
MIN_MACHINE_DAYS_FEW_SETTINGS = (
    150  # 4設定機(1・2・5・6): 設定2と5の間隔が大きく、少ない台日でも安定。一様事前だと5以上が50%になり過大
)
FLOOR = 0.05  # 推定が0に張り付いた設定を完全に消さないための一様分布の混ぜ込み
EM_ITERATIONS = 300


def spec_key(model, specs=None):
    spec = find_spec(model, specs)
    return normalize((spec or {}).get("family_name") or model)


def _rb_settings(spec):
    return {s: float(v["rb_probability"]) for s, v in sorted(spec["settings"].items()) if v.get("rb_probability")}


def decompose(games, rb, rb_prob, iterations=EM_ITERATIONS):
    """台日ごとの(累計G, RB)から、設定の混合割合をEMで求める。"""
    probs = np.array(list(rb_prob.values()))
    likelihood = poisson.pmf(rb[:, None], games[:, None] * probs[None, :])
    weights = np.ones(len(probs)) / len(probs)
    for _ in range(iterations):
        post = likelihood * weights
        post /= post.sum(axis=1, keepdims=True)
        weights = post.mean(axis=0)
    return dict(zip(rb_prob, weights))


def smooth(weights, floor=FLOOR):
    n = len(weights)
    return {s: (1 - floor) * w + floor / n for s, w in weights.items()}


def estimate_hall(hall, *, db_dir=ROOT / "db", days=90, as_of=None, min_games=MIN_GAMES, min_days=MIN_MACHINE_DAYS):
    path = Path(db_dir) / f"{hall}.db"
    if not path.exists() or path.stat().st_size == 0:
        return {}
    con = sqlite3.connect(path)
    try:
        last = con.execute("select max(date) from machine_detailed_results").fetchone()[0]
        end = as_of or last
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
        rows = con.execute(
            "select machine_name, games_normalized, rb_count from machine_detailed_results "
            "where date>? and date<=? and games_normalized>=? and rb_count is not null",
            (start, end, min_games),
        ).fetchall()
    finally:
        con.close()
    specs = load_specs(hall=hall)
    grouped = {}
    for name, games, rb in rows:
        spec = find_spec(name, specs)
        if spec is None or not spec.get("judgeable"):
            continue
        grouped.setdefault(spec_key(name, specs), (spec, []))[1].append((games, rb))
    result = {}
    for key, (spec, values) in grouped.items():
        rb_prob = _rb_settings(spec)
        needed = min(min_days, MIN_MACHINE_DAYS_FEW_SETTINGS) if len(rb_prob) <= 4 else min_days
        if len(values) < needed or len(rb_prob) < 4 or not any(s >= 5 for s in rb_prob):
            continue
        arr = np.array(values, dtype=float)
        weights = smooth(decompose(arr[:, 0], arr[:, 1], rb_prob))
        result[key] = {
            "weights": {str(s): round(float(w), 4) for s, w in weights.items()},
            "machine_days": len(values),
            "window": [start, end],
        }
    return result


def build(halls, *, db_dir=ROOT / "db", days=90, path=PRIOR_PATH):
    data = {hall: estimate_hall(hall, db_dir=db_dir, days=days) for hall in halls}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def load_hall_priors(path=PRIOR_PATH):
    """estimate(hall_prior=...) に渡せる {ホール: {機種キー: {設定: 重み}}}。無ければNone。"""
    path = Path(path)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        hall: {key: {int(s): w for s, w in item["weights"].items()} for key, item in models.items()}
        for hall, models in raw.items()
        if models
    } or None


def main():
    from .run import HALLS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    data = build([value[0] for value in HALLS.values()], days=args.days)
    for hall, models in data.items():
        print(f"{hall}: {len(models)}機種" if models else f"{hall}: 事前なし(DBなしまたは台日不足。一様事前)")
        for key, item in models.items():
            high = sum(w for s, w in item["weights"].items() if int(s) >= 5)
            print(f"  {key}: 台日{item['machine_days']} 設定5以上{high:.1%}")


if __name__ == "__main__":
    main()
