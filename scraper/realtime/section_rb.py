"""列・島ごとの合算RB: RB判別できる台だけを列単位で合算し、偶然に起きる確率を出す。

2026-10-18の東口で、同じ列のRB判別できる5台がそろって設定6のスペック値より良いRB確率だったのに、
台ごとの確率(一様事前では0.5前後)と、機種混在の列全体の合算では薄まって見落とした。
台ごとの事後確率ではなく、列単位でRBを合算してポアソンで偶然の確率を出す。BBとRBは合算しない(RBのみ)。
"""

import sqlite3
from collections import defaultdict
from pathlib import Path

from scipy.stats import poisson

from backtest.bonus_specs import find_spec

from .estimate import ROOT, _hall_specs, _model, estimate
from .quick_filter import load_audit

MIN_RB_SETTINGS = 4  # rb_probabilityのある設定がこれ以上の機種だけ(4設定機・6設定機)


def _layout(db_dir, hall):
    """{台番号: section}。DBなし・サイズ0・machine_layoutなし・section NULLは空/除外。"""
    path = Path(db_dir) / f"{hall}.db"
    if not path.is_file() or not path.stat().st_size:
        return {}
    try:
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            found = con.execute(
                "SELECT machine_number, section FROM machine_layout WHERE section IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    return {int(unit): section for unit, section in found if section}


def _rb_probabilities(row, specs, audit):
    """RB判別できる台なら設定別のRB確率のリスト、そうでなければNone(estimateと同じ基準)。"""
    if row.is_new_machine or row.games is None or row.rb is None:
        return None
    if row.games <= 0 or not 0 <= row.rb <= row.games:
        return None
    result = estimate(row, specs=specs, audit=audit, hall_prior=None)
    if result["kind"] != "rb_posterior" or result["discriminability"] != "high":
        return None
    spec = find_spec(_model(row), specs) or {}
    probs = [float(v["rb_probability"]) for v in spec.get("settings", {}).values() if v.get("rb_probability")]
    return probs if len(probs) >= MIN_RB_SETTINGS else None


def _p_value(rb, expected):
    return float(poisson.sf(rb - 1, expected)) if expected > 0 else None


def _entry(hall, kind, section, units, eligible):
    members = [eligible[u] for u in units]
    games = sum(row.games for row, _ in members)
    rb = sum(row.rb for row, _ in members)
    expected_low = sum(row.games * min(probs) for row, probs in members)
    expected_avg = sum(row.games * sum(probs) / len(probs) for row, probs in members)
    return {
        "hall": hall,
        "kind": kind,
        "section": section,
        "unit_from": min(units),
        "unit_to": max(units),
        "units": sorted(units),
        "n": len(units),
        "models": list(dict.fromkeys(eligible[u][0].model for u in sorted(units))),
        "total_games": games,
        "total_rb": rb,
        "rb_one_in": games / rb if rb else None,
        "better_than_high": sum(1 for row, probs in members if row.rb > 0 and row.rb / row.games > max(probs)),
        "p_low": _p_value(rb, expected_low),
        "p_avg": _p_value(rb, expected_avg),
    }


def _select(entries, top):
    """p(設定平均)が小さい順に貪欲に選ぶ。すでに選んだ候補と台集合が包含関係にあるものは飛ばす。"""
    entries = sorted(entries, key=lambda e: (e["p_avg"] is None, e["p_avg"] or 0.0, -e["total_games"]))
    chosen = []
    for entry in entries:
        units = set(entry["units"])
        if any(units <= set(c["units"]) or units >= set(c["units"]) for c in chosen):
            continue
        chosen.append(entry)
        if len(chosen) >= top:
            break
    return chosen


def section_rb(rows, *, db_dir=ROOT / "db", specs_by_hall=None, audit=None, top=5, min_units=3, window=6):
    """{ホール: [エントリー...]}。判別できる台がmin_units未満の列・窓は出さない。"""
    audit = load_audit() if audit is None else audit
    latest = {}
    for row in rows:
        latest[row.hall] = max(latest.get(row.hall, ""), row.observed_at)
    by_hall = defaultdict(list)
    for row in rows:
        if row.observed_at == latest[row.hall]:
            by_hall[row.hall].append(row)
    result = {}
    for hall, items in by_hall.items():
        layout = _layout(db_dir, hall)
        if not layout:
            result[hall] = []
            continue
        specs = (specs_by_hall or {}).get(hall)
        if specs is None:
            specs = _hall_specs(hall)
        eligible = {}
        for row in items:
            probs = _rb_probabilities(row, specs, audit)
            if probs and row.unit in layout:
                eligible[row.unit] = (row, probs)
        sections = defaultdict(list)
        for unit, section in layout.items():
            sections[section].append(unit)
        entries = []
        for section, units in sections.items():
            units.sort()
            whole = [u for u in units if u in eligible]
            if len(whole) >= min_units:
                entries.append(_entry(hall, "section", section, whole, eligible))
            seen = {tuple(whole)}
            starts = range(len(units) - window + 1) if len(units) > window else range(0)  # 窓より多い列だけ
            for i in starts:
                part = tuple(u for u in units[i : i + window] if u in eligible)
                if len(part) >= min_units and part not in seen:
                    seen.add(part)
                    entries.append(_entry(hall, "window", section, list(part), eligible))
        result[hall] = _select(entries, top)
    return result
