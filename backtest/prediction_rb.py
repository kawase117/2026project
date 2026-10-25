"""予測台帳のRB判別機種を、同一ホール・機種の過去RB率で採点する。"""

from __future__ import annotations

import math
import sqlite3
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
