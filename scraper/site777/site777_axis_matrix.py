# -*- coding: utf-8 -*-
"""区分 x 軸（機種・各台・末尾・角番・列）を毎回必ず出す軸別マトリクス。

毎回の指示を忘れないよう、必須の (区分, 軸) をコードで固定し、出力後に欠落を検査する。
欠落があるとブリーフ冒頭に警告を出し、site777_live_brief.py が非0で終了する。

指標の区分
  判別可能（ノーマル/BT/A+AT）: RB確率が主、BB確率も併記。機種内の期待値との比（機種効果を除去）。
  AT: 差枚（機種平均を引いた残差）。G数・G比を併記。
  どちらも総G・平均Gを併記する（1/200を400G回したのと9000G回したのでは重みが違う）。
"""

from __future__ import annotations

import math
import statistics as st
from collections import defaultdict

JUDGEABLE = ("ノーマル", "BT", "A+AT")
AXES = ("機種", "各台", "末尾", "角番", "列")
REQUIRED = [("判別可能", axis) for axis in AXES] + [("AT", axis) for axis in AXES]

MIN_GAMES_UNIT = 800
MIN_MODEL_UNITS = 3
ZENTAIKEI_THRESHOLD = 1800.0


def heading(segment, axis):
    return "### [%s x %s]" % (segment, axis)


def _z(obs, exp):
    return (obs - exp) / math.sqrt(exp) if exp >= 5 else None


def _fmt_z(z):
    return "-" if z is None else "%+.1f" % z


def _ratio(obs, exp):
    return "-" if exp <= 0 else "%.2f" % (obs / exp)


def _model_rates(units):
    """機種ごとの合算RB/BB率。自己基準が自分自身に寄らないよう3台以上の機種だけ。"""
    per_model = defaultdict(list)
    for m in units:
        per_model[m["model_name"]].append(m)
    rates = {}
    for name, members in per_model.items():
        if len(members) < MIN_MODEL_UNITS:
            continue
        games = sum(m["games"] for m in members)
        if games <= 0:
            continue
        rates[name] = (
            sum(m["rb_count"] or 0 for m in members) / games,
            sum(m["bb_count"] or 0 for m in members) / games,
        )
    return rates


def _axis_key(axis, m, layout_full):
    number = int(m["machine_number"])
    if axis == "末尾":
        return number % 10
    if axis == "角番":
        loc = layout_full.get(number)
        if not loc:
            return None
        return min(loc[1] or 99, loc[2] or 99)
    if axis == "列":
        loc = layout_full.get(number)
        return loc[0] if loc else None
    return None


def _normal_table(out, segment, axis, units, rates, layout_full, limit):
    out.append(heading(segment, axis))
    out.append("")
    groups = defaultdict(lambda: [0, 0, 0.0, 0.0, 0])
    for m in units:
        rate = rates.get(m["model_name"])
        if not rate or m["games"] < MIN_GAMES_UNIT:
            continue
        key = _axis_key(axis, m, layout_full) if axis != "機種" else m["model_name"]
        if key is None:
            continue
        g = groups[key]
        g[0] += m["rb_count"] or 0
        g[1] += m["bb_count"] or 0
        g[2] += m["games"] * rate[0]
        g[3] += m["games"] * rate[1]
        g[4] += m["games"]
    rows = []
    counts = defaultdict(int)
    for m in units:
        rate = rates.get(m["model_name"])
        if not rate or m["games"] < MIN_GAMES_UNIT:
            continue
        key = _axis_key(axis, m, layout_full) if axis != "機種" else m["model_name"]
        if key is not None:
            counts[key] += 1
    for key, (rb, bb, exp_rb, exp_bb, games) in groups.items():
        rows.append((_z(rb, exp_rb), key, counts[key], games, rb, exp_rb, bb, exp_bb))
    if not rows:
        out.append("- 台数不足で集計できない")
        out.append("")
        return
    rows.sort(key=lambda r: (r[0] is None, -(r[0] or 0)))
    shown = rows if axis == "末尾" else (rows[:limit] + [r for r in rows[-3:] if r not in rows[:limit]])
    out.append("| %s | 台数 | 総G | 平均G | RB比 | RB z | BB比 | BB z |" % axis)
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for z_rb, key, n, games, rb, exp_rb, bb, exp_bb in shown:
        out.append(
            "| %s | %d | %d | %.0f | %s | %s | %s | %s |"
            % (key, n, games, games / n, _ratio(rb, exp_rb), _fmt_z(z_rb), _ratio(bb, exp_bb), _fmt_z(_z(bb, exp_bb)))
        )
    out.append("")


def _normal_units_table(out, units, rates, layout, limit=12):
    out.append(heading("判別可能", "各台"))
    out.append("")
    rows = []
    for m in units:
        rate = rates.get(m["model_name"])
        if not rate or m["games"] < MIN_GAMES_UNIT:
            continue
        exp_rb = m["games"] * rate[0]
        exp_bb = m["games"] * rate[1]
        rows.append((_z(m["rb_count"] or 0, exp_rb), m, exp_rb, exp_bb))
    rows = [r for r in rows if r[0] is not None]
    if not rows:
        out.append("- 台数不足で集計できない")
        out.append("")
        return
    rows.sort(key=lambda r: -r[0])
    out.append("機種内の期待値に対するRB比。上位%d台と下位3台。RB z はポアソン近似。" % limit)
    out.append("")
    out.append("| 台 | 機種 | G | RB | RB確率 | RB比 | RB z | BB | BB確率 | BB比 | 差枚 | 列 |")
    out.append("|---|---|---:|---:|---|---:|---:|---:|---|---:|---:|---|")
    for z_rb, m, exp_rb, exp_bb in rows[:limit] + rows[-3:]:
        rb = m["rb_count"] or 0
        bb = m["bb_count"] or 0
        out.append(
            "| %s | %s | %d | %d | %s | %s | %s | %d | %s | %s | %s | %s |"
            % (
                m["machine_number"],
                m["model_name"],
                m["games"],
                rb,
                ("1/%.0f" % (m["games"] / rb)) if rb else "-",
                _ratio(rb, exp_rb),
                _fmt_z(z_rb),
                bb,
                ("1/%.0f" % (m["games"] / bb)) if bb else "-",
                _ratio(bb, exp_bb),
                m["latest_diff"] if m["latest_diff"] is not None else "-",
                layout.get(int(m["machine_number"]), "-"),
            )
        )
    out.append("")


def _at_tables(out, units, layout_full, hall_games, limit):
    diff_units = [m for m in units if m["latest_diff"] is not None]
    per_model = defaultdict(list)
    for m in diff_units:
        per_model[m["model_name"]].append(m["latest_diff"])
    model_mean = {k: st.mean(v) for k, v in per_model.items() if len(v) >= 2}
    residual = [
        (m, m["latest_diff"] - model_mean[m["model_name"]]) for m in diff_units if m["model_name"] in model_mean
    ]
    sd = st.pstdev([r for _m, r in residual]) if len(residual) >= 5 else None

    for axis in AXES:
        out.append(heading("AT", axis))
        out.append("")
        if axis == "各台":
            rows = sorted(diff_units, key=lambda m: -m["latest_diff"])
            if not rows:
                out.append("- 差枚が読めた台が無い")
                out.append("")
                continue
            out.append("差枚の上位%d台と下位3台。" % limit)
            out.append("")
            out.append("| 台 | 機種 | G | G比 | 差枚 | BB/RB | 列 |")
            out.append("|---|---|---:|---:|---:|---|---|")
            for m in rows[:limit] + rows[-3:]:
                sec = layout_full.get(int(m["machine_number"]))
                out.append(
                    "| %s | %s | %d | %.2f | %+d | %d/%d | %s |"
                    % (
                        m["machine_number"],
                        m["model_name"],
                        m["games"],
                        m["games"] / hall_games if hall_games else 0,
                        m["latest_diff"],
                        m["bb_count"] or 0,
                        m["rb_count"] or 0,
                        sec[0] if sec else "-",
                    )
                )
            out.append("")
            continue
        if axis == "機種":
            rows = []
            for name, members in per_model.items():
                if len(members) < 2:
                    continue
                unit_rows = [m for m in diff_units if m["model_name"] == name]
                games = sum(m["games"] for m in unit_rows)
                all_units = [m for m in units if m["model_name"] == name]
                ratio = st.mean(m["games"] for m in all_units) / hall_games if hall_games else 0
                mean_diff = st.mean(members)
                over = sum(1 for d in members if d >= ZENTAIKEI_THRESHOLD)
                rows.append((ratio * mean_diff, name, len(unit_rows), games, ratio, mean_diff, over))
            if not rows:
                out.append("- 差枚が読めたAT機が不足（機種内2台以上が必要）")
                out.append("")
                continue
            rows.sort(key=lambda r: -r[0])
            out.append(
                "スコア＝G比×平均差枚（全台系の閾値 %+.0f）。G比は機種の全台の平均G÷ホール平均G。"
                "総G・平均Gは差枚が読めた台（2,000G以上）だけの値。" % ZENTAIKEI_THRESHOLD
            )
            out.append("")
            out.append("| 機種 | 差枚台 | 総G | 平均G | G比 | 平均差枚 | スコア | +1800超え |")
            out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
            for score, name, n, games, ratio, mean_diff, over in rows[: limit + 4]:
                out.append(
                    "| %s | %d | %d | %.0f | %.2f | %+.0f | %+.0f | %d台 |"
                    % (name, n, games, games / n, ratio, mean_diff, score, over)
                )
            out.append("")
            continue
        model_keys = defaultdict(set)
        for m, _res in residual:
            key = _axis_key(axis, m, layout_full)
            if key is not None:
                model_keys[m["model_name"]].add(key)
        groups = defaultdict(list)
        excluded = 0
        for m, res in residual:
            key = _axis_key(axis, m, layout_full)
            if key is None:
                continue
            if len(model_keys[m["model_name"]]) < 2:
                excluded += 1
                continue
            groups[key].append((m, res))
        if not groups or sd is None or sd == 0:
            out.append("- 差枚が読めたAT機が不足（機種内2台以上が必要）")
            if excluded:
                out.append(
                    "- 機種の差枚台がすべて同じ%sに収まっている %d台は、残差が構造的に0になるため除いた。"
                    % (axis, excluded)
                )
            out.append("")
            continue
        rows = []
        for key, members in groups.items():
            if len(members) < 3:
                continue
            mean_res = st.mean(r for _m, r in members)
            games = sum(m["games"] for m, _r in members)
            over = sum(1 for m, _r in members if m["latest_diff"] >= ZENTAIKEI_THRESHOLD)
            rows.append((mean_res / (sd / math.sqrt(len(members))), key, len(members), games, mean_res, over))
        if not rows:
            out.append("- 台数不足で集計できない")
            out.append("")
            continue
        rows.sort(key=lambda r: -r[0])
        shown = rows if axis == "末尾" else (rows[:limit] + [r for r in rows[-3:] if r not in rows[:limit]])
        out.append("差枚残差＝台の差枚から機種の平均差枚を引いた値。z は残差平均÷(全体SD÷√n)。")
        if excluded:
            out.append(
                "機種の差枚台がすべて同じ%sに収まっている %d台は、残差が構造的に0になるため除いた。" % (axis, excluded)
            )
        out.append("")
        out.append("| %s | 差枚台 | 総G | 平均G | 残差平均 | z | +1800超え |" % axis)
        out.append("|---|---:|---:|---:|---:|---:|---:|")
        for z, key, n, games, mean_res, over in shown:
            out.append("| %s | %d | %d | %.0f | %+.0f | %+.1f | %d台 |" % (key, n, games, games / n, mean_res, z, over))
        out.append("")


def build(machines, layout, layout_full, by_norm, norm, hall_games, limit=8):
    """(markdown行のリスト, 出力済み (区分,軸) の集合)。"""
    judgeable, at_units, unknown = [], [], 0
    for m in machines:
        ent = by_norm.get(norm(m["model_name"]))
        if not ent:
            unknown += 1
        elif ent[1] in JUDGEABLE:
            judgeable.append(m)
        elif ent[1] == "AT":
            at_units.append(m)
        else:
            unknown += 1

    out = []
    out.append("## 区分 x 軸の必須マトリクス")
    out.append("")
    out.append(
        "判別可能機種は RB確率が主・BB確率を併記（機種内の期待値との比で機種差を除去）。AT機は差枚残差が主。"
        "どちらも総G・平均Gを併記する。判別可能 %d台 / AT %d台 / 区分不明 %d台。"
        % (len(judgeable), len(at_units), unknown)
    )
    out.append("")
    out.append(
        "⚠️ 末尾は10行、角番・列は上位%d行と下位3行。RB比・BB比は観測÷期待（1.00が機種平均）。"
        "z は近似で、軸の数だけ多重比較になる。|z|>3 でも他の軸と合わせて見る。" % limit
    )
    out.append("")

    rates = _model_rates(judgeable)
    out.append(heading("判別可能", "機種"))
    out.append("")
    out.append("機種の値は上の「判別可能機種」表（RB確率・自己ベースライン・BB確率・総G）。")
    out.append("")
    _normal_units_table(out, judgeable, rates, layout)
    for axis in ("末尾", "角番", "列"):
        _normal_table(out, "判別可能", axis, judgeable, rates, layout_full, limit)
    _at_tables(out, at_units, layout_full, hall_games, limit)

    text = "\n".join(out)
    produced = {(seg, axis) for seg, axis in REQUIRED if heading(seg, axis) in text}
    return out, produced


def missing(produced):
    return [pair for pair in REQUIRED if pair not in produced]
