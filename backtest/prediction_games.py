"""予測台帳の名指しを、差枚・RB比とは別に回転数で採点する(2026-10 振り返り 作業5の2〜4)。

なぜ回転数か:
    AT機で7,000G以上回った台は、朝から期待され、途中の示唆(6,000〜7,000Gのトロフィーなど)を見て打ち続けられた
    可能性が高い。backtest.continuation_scan で、差枚マイナスの台に絞っても7,000G以上の台は結果ツイートに
    1.5〜4.6倍入ることを確かめた(蒲田1・蒲田7・楽園、2026-06〜10)。差枚だけで採点するとこの台を外れと数える。

出すもの(result のキー):
    games      : 名指しした台・機種の (a) 7,000G到達の割合(AT機)、(b) G比(台の回転数 ÷ 同じ日・同じ機種の中央値)。
                 台は同じ日・同じ機種の名指ししなかった台との差。機種は、機種丸ごとでは同機種の対照が無いので、
                 回転数をホールの当日中央値で割り、名指ししなかった機種の台との差にする。
    rb_stage   : RB自動候補(source=rb_auto)の2段採点の1段目。全候補について「打たれたか」(3,000G到達・G比)を数え、
                 打たれなかった候補も消さない。対照は同じ日・同じ機種の候補外の台。2段目(打たれた台のRB比)は
                 既存の rb_s1.units。候補が多すぎる日のために、台の偏差の上位5台の系列も出す(top5)。
    jug_model  : ジャグラー候補表の台の差枚 − 同じ日・同じ機種の候補外の台の差枚(蒲田7の持ち越し上位を外す仮説の判定用)。
"""

from __future__ import annotations

import sqlite3
from statistics import median

from backtest.prediction_rb import MIN_GAMES as PLAYED_GAMES, rb_s1_result

REACH_GAMES = 7000
AT_TYPES = ("AT", "ART", "A+AT", "A+ART")
TOP_N = 5


def _day_rows(con: sqlite3.Connection, target_date: str) -> list[tuple[int, str, float, float | None]]:
    return [
        (int(n), name, float(g), None if d is None else float(d))
        for n, name, g, d in con.execute(
            "SELECT machine_number, machine_name, games_normalized, diff_coins_normalized "
            "FROM machine_detailed_results WHERE date = ? AND games_normalized IS NOT NULL",
            (target_date,),
        )
    ]


def _at_models(con: sqlite3.Connection) -> set[str]:
    try:
        marks = ",".join("?" * len(AT_TYPES))
        sql = f"SELECT machine_name_normalized FROM machine_master WHERE game_type IN ({marks})"
        return {name for (name,) in con.execute(sql, AT_TYPES)}
    except sqlite3.Error:
        return set()


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _vs_same_model(picked: list[tuple], rows: list[tuple], selected: set[int], value) -> tuple[float | None, int]:
    """機種ごとに 名指しの平均 − 同機種の名指ししなかった台の平均 を、名指しの台数で重みづけして平均する。"""
    weighted, weight = 0.0, 0
    for name in sorted({r[1] for r in picked}):
        mine = [v for r in picked if r[1] == name and (v := value(r)) is not None]
        other = [v for r in rows if r[1] == name and r[0] not in selected and (v := value(r)) is not None]
        if mine and other:
            weighted += len(mine) * (_mean(mine) - _mean(other))
            weight += len(mine)
    return (weighted / weight if weight else None), weight


def games_result(con: sqlite3.Connection, picks: dict, target_date: str) -> dict:
    rows = _day_rows(con, target_date)
    at = _at_models(con)
    medians = {name: median(r[2] for r in rows if r[1] == name) for name in {r[1] for r in rows}}
    hall_median = median(r[2] for r in rows) if rows else None

    def g_ratio(r):
        return r[2] / medians[r[1]] if medians[r[1]] > 0 else None

    def reach(r):
        return (100.0 if r[2] >= REACH_GAMES else 0.0) if r[1] in at else None

    out: dict = {"reach_games": REACH_GAMES, "hall_median_games": hall_median}
    for kind in ("units", "jug_units"):
        selected = set(picks.get(kind) or [])
        picked = [r for r in rows if r[0] in selected]
        if not picked:
            out[kind] = None
            continue
        g_edge, n_g = _vs_same_model(picked, rows, selected, g_ratio)
        r_edge, n_r = _vs_same_model(picked, rows, selected, reach)
        out[kind] = {
            "n_machines": len(picked),
            "g_ratio": _mean(g_ratio(r) for r in picked),
            "g_edge": g_edge,
            "n_g_compared": n_g,
            "n_at": sum(r[1] in at for r in picked),
            "reach_share": _mean(reach(r) for r in picked),
            "reach_edge": r_edge,
            "n_reach_compared": n_r,
        }
    names = set(picks.get("models") or [])
    named = [r for r in rows if r[1] in names]
    out["models"] = None
    if named and hall_median:
        others = [r for r in rows if r[1] not in names]
        g_mine, g_other = _mean(r[2] / hall_median for r in named), _mean(r[2] / hall_median for r in others)
        r_mine, r_other = _mean(reach(r) for r in named), _mean(reach(r) for r in others)
        out["models"] = {
            "n_machines": len(named),
            "g_ratio": g_mine,
            "g_edge": None if g_other is None else g_mine - g_other,
            "n_at": sum(r[1] in at for r in named),
            "reach_share": r_mine,
            "reach_edge": None if r_mine is None or r_other is None else r_mine - r_other,
        }
    return out


def _stage1(rows: list[tuple], units: list[int]) -> dict | None:
    if not units:
        return None
    selected = set(units)
    present = [r for r in rows if r[0] in selected]
    medians = {name: median(r[2] for r in rows if r[1] == name) for name in {r[1] for r in present}}

    def g_ratio(r):
        return r[2] / medians[r[1]] if medians.get(r[1]) else None

    def played(r):
        return 100.0 if r[2] >= PLAYED_GAMES else 0.0

    played_edge, n_played = _vs_same_model(present, rows, selected, played)
    g_edge, n_g = _vs_same_model(present, rows, selected, g_ratio)
    return {
        "n_candidates": len(selected),
        "n_present": len(present),
        "n_played": sum(r[2] >= PLAYED_GAMES for r in present),
        "played_share": _mean(played(r) for r in present),
        "played_edge": played_edge,
        "n_played_compared": n_played,
        "g_ratio": _mean(g_ratio(r) for r in present),
        "g_edge": g_edge,
        "n_g_compared": n_g,
    }


def top_units(rb_auto: dict | None, n: int = TOP_N) -> list[int]:
    """凍結した候補台のうち、機種内の偏差(dev)の大きい上位 n 台。"""
    units = [u for group in ((rb_auto or {}).get("units") or {}).values() for u in group]
    units.sort(key=lambda u: (-(u.get("dev") or 0.0), u["machine_number"]))
    return [u["machine_number"] for u in units[:n]]


def rb_stage_result(con: sqlite3.Connection, picks: dict, target_date: str, rb_auto: dict | None) -> dict:
    rows = _day_rows(con, target_date)
    top = top_units(rb_auto)
    out = {
        "played_games": PLAYED_GAMES,
        "all": _stage1(rows, list(picks.get("units") or [])),
        "top5_units": top,
        "top5": _stage1(rows, top),
        "top5_rb_s1": None,
    }
    if top:
        part = rb_s1_result(con, {"models": [], "avoid_models": [], "units": top, "jug_units": []}, target_date)
        out["top5_rb_s1"] = part.get("units")
    return out


def jug_model_result(con: sqlite3.Connection, picks: dict, target_date: str) -> dict | None:
    selected = set(picks.get("jug_units") or [])
    if not selected:
        return None
    rows = _day_rows(con, target_date)
    picked = [r for r in rows if r[0] in selected and r[3] is not None]
    edge, n = _vs_same_model(picked, rows, selected, lambda r: r[3])
    return {"n_machines": len(picked), "mean_diff": _mean(r[3] for r in picked), "edge": edge, "n_compared": n}
