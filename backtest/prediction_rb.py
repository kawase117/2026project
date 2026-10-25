"""予測台帳のRB判別機種を、同一ホール・機種の過去RB率で採点する。"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from functools import lru_cache

from backtest import bonus_specs

MIN_GAMES = 3000
BASELINE_DAYS = 60
MIN_BASE_MACHINE_DAYS = 20
MIN_HISTORY_MACHINE_DAYS = 100
RANGE_MARGIN = 0.05
KINDS = ("models", "avoid_models", "units", "jug_units")


@lru_cache(maxsize=1)
def _specs() -> dict:
    return bonus_specs.load_specs()


def _judgeable(name: str, specs: dict) -> bool:
    spec = bonus_specs.find_spec(name, specs)
    return bool(spec and spec.get("judgeable"))


def _metric(rows: list[tuple[int, str, float, float, float]], day_ratio: float | None = None) -> dict | None:
    if not rows:
        return None
    games = sum(r[2] for r in rows)
    obs = sum(r[3] for r in rows)
    exp = sum(r[4] for r in rows)
    ratio = obs / exp if exp > 0 else None
    return {
        "n_machines": len(rows),
        "games": games,
        "rb_obs": obs,
        "rb_exp": exp,
        "rb_ratio": ratio,
        "z": (obs - exp) / math.sqrt(exp) if exp > 0 else None,
        "rb_edge": ratio - day_ratio if ratio is not None and day_ratio is not None else None,
    }


def rb_result(con: sqlite3.Connection, picks: dict, target_date: str) -> dict:
    """当日の有効な台日を、対象日前60日の機種別自己ベースラインと比べる。"""
    target = datetime.strptime(target_date, "%Y%m%d")
    start = (target - timedelta(days=BASELINE_DAYS)).strftime("%Y%m%d")
    end = (target - timedelta(days=1)).strftime("%Y%m%d")
    specs = _specs()
    base: dict[str, list[float]] = {}
    for name, games, rb in con.execute(
        "SELECT machine_name, games_normalized, rb_count FROM machine_detailed_results WHERE date >= ? AND date <= ?",
        (start, end),
    ):
        if not _judgeable(name, specs) or games is None or games < MIN_GAMES or rb is None:
            continue
        item = base.setdefault(name, [0, 0.0, 0.0])
        item[0] += 1
        item[1] += games
        item[2] += rb

    excluded_low = 0
    no_baseline: set[str] = set()
    not_judgeable: set[str] = set()
    day_rows: list[tuple[int, str, float, float, float]] = []
    for number, name, games, rb in con.execute(
        "SELECT machine_number, machine_name, games_normalized, rb_count FROM machine_detailed_results WHERE date = ?",
        (target_date,),
    ):
        if not _judgeable(name, specs):
            not_judgeable.add(name)
            continue
        if games is None or games < MIN_GAMES or rb is None:
            excluded_low += 1
            continue
        prior = base.get(name)
        if prior is None or prior[0] < MIN_BASE_MACHINE_DAYS or prior[1] <= 0:
            no_baseline.add(name)
            continue
        day_rows.append((int(number), name, float(games), float(rb), games * prior[2] / prior[1]))

    day_metric = _metric(day_rows)
    day_ratio = day_metric["rb_ratio"] if day_metric else None
    result = {
        "min_games": MIN_GAMES,
        "baseline_days": BASELINE_DAYS,
        "min_base_machine_days": MIN_BASE_MACHINE_DAYS,
        "day_rb_ratio": day_ratio,
    }
    for kind in KINDS:
        selected = set(picks.get(kind) or [])
        index = 1 if kind in ("models", "avoid_models") else 0
        result[kind] = _metric([r for r in day_rows if r[index] in selected], day_ratio)
    result["excluded"] = {
        "low_games": excluded_low,
        "no_baseline": sorted(no_baseline),
        "not_judgeable": sorted(not_judgeable),
    }
    return result


def _s1_metric(rows: list[tuple[int, str, float, float, float]]) -> dict | None:
    if not rows:
        return None
    games = sum(row[2] for row in rows)
    obs = sum(row[3] for row in rows)
    exp = sum(row[4] for row in rows)
    return {
        "n_machines": len(rows),
        "games": games,
        "rb_obs": obs,
        "rb_exp_s1": exp,
        "s1_ratio": obs / exp if exp > 0 else None,
        "z": (obs - exp) / math.sqrt(exp) if exp > 0 else None,
        "rb_s1_edge": None,
    }


def rb_s1_result(con: sqlite3.Connection, picks: dict, target_date: str) -> dict:
    """設定1比を採点する。機種丸ごとの名指しには同機種の非選択台がないため、
    models/avoid_models の edge は出さず、優劣は自己ベースライン比 result.rb で読む。
    """
    specs = _specs()
    history = {
        name: (count, games, rb)
        for name, count, games, rb in con.execute(
            "SELECT machine_name, COUNT(*), SUM(games_normalized), SUM(rb_count) "
            "FROM machine_detailed_results "
            "WHERE date < ? AND games_normalized >= ? AND rb_count IS NOT NULL "
            "GROUP BY machine_name",
            (target_date, MIN_GAMES),
        )
    }
    excluded = {
        "low_games": 0,
        "not_judgeable": set(),
        "no_rb_spec": set(),
        "history_short": set(),
        "out_of_range": set(),
    }
    day_rows: list[tuple[int, str, float, float, float]] = []
    probabilities: dict[str, tuple[float, float] | None] = {}
    eligible: dict[str, bool] = {}
    for number, name, games, rb in con.execute(
        "SELECT machine_number, machine_name, games_normalized, rb_count FROM machine_detailed_results WHERE date = ?",
        (target_date,),
    ):
        if games is None or games < MIN_GAMES or rb is None:
            excluded["low_games"] += 1
            continue
        if name not in eligible:
            spec = bonus_specs.find_spec(name, specs)
            if not spec or not spec.get("judgeable"):
                excluded["not_judgeable"].add(name)
                eligible[name] = False
                continue
            values = [
                float(setting["rb_probability"])
                for setting in (spec.get("settings") or {}).values()
                if setting.get("rb_probability") is not None
                and isinstance(setting.get("rb_probability"), (int, float))
                and math.isfinite(setting["rb_probability"])
                and 0 < setting["rb_probability"] <= 1
            ]
            if not values:
                excluded["no_rb_spec"].add(name)
                eligible[name] = False
                continue
            p_floor, p_max = min(values), max(values)
            prior = history.get(name)
            if prior is None or prior[0] < MIN_HISTORY_MACHINE_DAYS:
                excluded["history_short"].add(name)
                eligible[name] = False
                continue
            rate = prior[2] / prior[1]
            if not p_floor * (1 - RANGE_MARGIN) <= rate <= p_max * (1 + RANGE_MARGIN):
                excluded["out_of_range"].add(f"{name}(1/{round(1 / rate)})" if rate > 0 else f"{name}(1/∞)")
                eligible[name] = False
                continue
            probabilities[name] = (p_floor, p_max)
            eligible[name] = True
        if eligible[name]:
            day_rows.append((int(number), name, float(games), float(rb), games * probabilities[name][0]))

    result = {
        "min_games": MIN_GAMES,
        "min_history_machine_days": MIN_HISTORY_MACHINE_DAYS,
        "range_margin": RANGE_MARGIN,
    }
    for kind in KINDS:
        selected = set(picks.get(kind) or [])
        index = 1 if kind in ("models", "avoid_models") else 0
        picked = [row for row in day_rows if row[index] in selected]
        metric = _s1_metric(picked)
        if metric is not None and kind in ("units", "jug_units"):
            compared = []
            no_comparator = []
            for name in sorted({row[1] for row in picked}):
                chosen = [row for row in picked if row[1] == name]
                other = [row for row in day_rows if row[1] == name and row[0] not in selected]
                if not other:
                    no_comparator.append(name)
                    continue
                chosen_metric, other_metric = _s1_metric(chosen), _s1_metric(other)
                compared.append((chosen_metric["rb_exp_s1"], chosen_metric["s1_ratio"] - other_metric["s1_ratio"]))
            metric["rb_s1_edge"] = (
                sum(weight * difference for weight, difference in compared) / sum(weight for weight, _ in compared)
                if compared
                else None
            )
            metric["n_compared_machines"] = len(compared)
            metric["no_comparator"] = no_comparator
        result[kind] = metric
    result["excluded"] = {key: value if key == "low_games" else sorted(value) for key, value in excluded.items()}
    return result


@lru_cache(maxsize=4096)
def rb_family(name: str) -> tuple[str, float, float] | None:
    """判別可能な機種名を (family, 設定1相当RB率, 最大RB率) に写す。"""
    spec = bonus_specs.find_spec(name, _specs())
    if not spec or not spec.get("judgeable"):
        return None
    values = [
        float(v["rb_probability"])
        for v in (spec.get("settings") or {}).values()
        if isinstance(v.get("rb_probability"), (int, float))
        and math.isfinite(v["rb_probability"])
        and 0 < v["rb_probability"] <= 1
    ]
    if len(values) < 2 or max(values) <= min(values):
        return None
    return spec["family_name"], min(values), max(values)


def zval(rb: float, games: float, floor: float, maximum: float) -> float:
    return (rb / games - floor) / (maximum - floor)


def family_rows(con: sqlite3.Connection, before: str, start: str | None = None) -> list[tuple]:
    """対象日以前の採用可能な台日。family は呼び出し側で解決する。"""
    sql = (
        "SELECT date, machine_number, machine_name, games_normalized, rb_count "
        "FROM machine_detailed_results WHERE date < ? AND games_normalized >= ? "
        "AND rb_count IS NOT NULL"
    )
    params = [before, MIN_GAMES]
    if start is not None:
        sql += " AND date >= ?"
        params.append(start)
    return list(con.execute(sql, params))


def comparable_families(rows: list[tuple]) -> dict[str, tuple[int, float, float, float, float]]:
    """ホールごとに family を集計して比較可のものだけ返す。"""
    sums = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])
    for _, _, name, games, rb in rows:
        spec = rb_family(name)
        if spec is None:
            continue
        family, floor, maximum = spec
        item = sums[family]
        item[0] += 1
        item[1] += games
        item[2] += rb
        item[3], item[4] = floor, maximum
    return {
        f: tuple(v)
        for f, v in sums.items()
        if v[0] >= MIN_HISTORY_MACHINE_DAYS
        and v[1] > 0
        and v[3] * (1 - RANGE_MARGIN) <= v[2] / v[1] <= v[4] * (1 + RANGE_MARGIN)
    }


@lru_cache(maxsize=32)
def family_offsets(db_dir: Path, asof_exclusive: str) -> dict[str, float]:
    """各ホールで比較可能な family のみ全ホール合算し、RB率を共通尺度 z にする。"""
    totals = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for path in sorted(Path(db_dir).glob("*.db")):
        if "analysis" in path.name:
            continue
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
                if not con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_detailed_results'"
                ).fetchone():
                    continue
                for family, (_, games, rb, floor, maximum) in comparable_families(
                    family_rows(con, asof_exclusive)
                ).items():
                    item = totals[family]
                    item[0] += games
                    item[1] += rb
                    item[2], item[3] = floor, maximum
        except sqlite3.Error:
            continue
    return {f: zval(v[1], v[0], v[2], v[3]) for f, v in totals.items()}


def rb_machine_result(con: sqlite3.Connection, picks: dict, target_date: str, offsets: dict[str, float]) -> dict:
    """機種間の当日RB差。

    z=(ΣRB/ΣG-p_floor)/(p_max-p_floor)、adj=z-offset_f。
    重み w=ΣG×(p_max-p_floor)^2/p_floor とし、edge は選択群と他群の
    w 加重平均 adj の差。2026-01-01〜10-24、13ホールの検証では
    補正後上位20%−他が +0.06 z だった。
    """
    history = comparable_families(family_rows(con, target_date))
    day = defaultdict(lambda: [0, 0.0, 0.0])
    excluded = {"not_judgeable": set(), "no_offset": set(), "not_comparable": set()}
    for _, _, name, games, rb in con.execute(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count FROM machine_detailed_results "
        "WHERE date = ? AND games_normalized >= ? AND rb_count IS NOT NULL",
        (target_date, MIN_GAMES),
    ):
        spec = rb_family(name)
        if spec is None:
            excluded["not_judgeable"].add(name)
            continue
        family = spec[0]
        item = day[family]
        item[0] += 1
        item[1] += games
        item[2] += rb
    eligible = {}
    for family, (n, games, rb) in day.items():
        if family not in offsets:
            excluded["no_offset"].add(family)
        elif n < 3 or family not in history:
            excluded["not_comparable"].add(family)
        else:
            _, _, _, floor, maximum = history[family]
            eligible[family] = (
                zval(rb, games, floor, maximum) - offsets[family],
                games * (maximum - floor) ** 2 / floor,
            )

    def summary(names: list[str]) -> dict | None:
        selected = {rb_family(n)[0] for n in names if rb_family(n) is not None} & eligible.keys()
        other = eligible.keys() - selected
        if not selected or not other:
            return None

        def mean(group):
            return sum(eligible[f][0] * eligible[f][1] for f in group) / sum(eligible[f][1] for f in group)

        adj = mean(selected)
        return {"n_families": len(selected), "adj": adj, "edge": adj - mean(other)}

    return {
        "n_eligible": len(eligible),
        "top": summary(picks.get("models") or []),
        "bottom": summary(picks.get("avoid_models") or []),
        "excluded": {k: sorted(v) for k, v in excluded.items()},
    }
