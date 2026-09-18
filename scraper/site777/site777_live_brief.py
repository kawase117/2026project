# -*- coding: utf-8 -*-
"""収集のたびに「言われなくても出す」当日ブリーフ。

なぜ要るか
----------
2026-09-16 の楽園蒲田で、以下はすべてユーザーに指摘されて初めて出した。
毎回の収集で自動的に出すべき内容なので、レポートに固定する。

  1. 区分で指標を分ける（判別可能=RB単独 / AT=G比×平均差枚）
     RB順位と差枚残差の相関は AT機 -0.088、判別可能機種 -0.292（楽園 20260601以降）。
     合算(BB+RB)はBB差が7〜13%しかなくノイズになる（memory: feedback-rb-only-not-combined）。
  2. 機種の自己ベースライン比較（当日のボーナス確率が過去45日のどこか）。
     差枚で全台系スコアに届かない「打たれずに終わった高設定」を取り逃がすため
     （2026-09-15 のスマスロハナビを機種平均+504で見落とした）。
  3. 機種×列（section）の分解。同じ機種でも列で扱いが逆になる
     （9/16 東京喰種 2058-2070 +4083 / 2083-2090 -1687）。
  4. 当月の列別（ただし予測力は無い。2026-09-16 実測: 列の持続性は機種効果を除くと
     月→翌月 r=0.111・前日→当日 r=-0.032、翌月の実効幅は +54/-34枚。列で狙うルールは作れない。
     当日の機種×列の分解だけが当日の席選びに効く）。
  5. 空き台候補（RBは高いのに差枚マイナス＝差枚で切られて空いている台）。
  6. 登録済み予告との突合。

出力
----
    scraper/site777/output/site777_live_brief.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import statistics as st
import sys

import numpy as np
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

sys.path.insert(0, HERE)
from backtest import bonus_specs as bs  # noqa: E402
import site777_axis_matrix as axis_matrix  # noqa: E402

JUDGEABLE = ("ノーマル", "BT", "A+AT")
ZENTAIKEI_THRESHOLD = 1800.0
BASELINE_FROM = "20260801"
MIN_GAMES_UNIT = 800
MIN_GAMES_MODEL = 1000
HIGH_CUT = 0.55
STRIP_WORDS = (
    "スマスロ",
    "Lパチスロ",
    "パチスロ",
    "スロット",
    "A-SLOT+",
    "A‐SLOT+",
    "L ",
    "LB",
    "L",
    "　",
    " ",
    "‐",
    "-",
)


def norm(name):
    for word in STRIP_WORDS:
        name = name.replace(word, "")
    return name


def rb_posterior(spec, games, rb):
    """RB単独の設定事後。AT機・RBスペック無しは None を返す。"""
    if not spec or not spec.get("settings"):
        return None
    logs = {}
    for setting, values in spec["settings"].items():
        p = values.get("rb_probability")
        if not p:
            return None
        logs[setting] = rb * math.log(p) + (games - rb) * math.log(1 - p)
    top = max(logs.values())
    exp = {k: math.exp(v - top) for k, v in logs.items()}
    total = sum(exp.values())
    return {k: v / total for k, v in exp.items()}


def high_prob(post):
    return sum(v for k, v in post.items() if int(k) >= 5) if post else None


def pct_rank(pool, value):
    """poolのうち value より良い(小さい)割合。小さいほど当日が良い。"""
    if not pool:
        return None
    return 100.0 * sum(1 for p in pool if p < value) / len(pool)


def daily_rb_pool(conn, db_name):
    rows = conn.execute(
        "select sum(games_normalized), sum(rb_count) from machine_detailed_results "
        "where machine_name like ? and date >= ? group by date",
        ("%" + db_name + "%", BASELINE_FROM),
    ).fetchall()
    return sorted(r[0] / r[1] for r in rows if r[1])


AXES = (
    ("機種", lambda r: r["name"]),
    ("列", lambda r: r["sec"]),
    ("末尾", lambda r: r["tail"]),
    ("角番", lambda r: r["kaku"]),
    ("フロア", lambda r: r["floor"]),
    ("機種×列", lambda r: (r["name"][:10], r["sec"])),
    ("機種×末尾", lambda r: (r["name"][:10], r["tail"])),
    ("機種×角番", lambda r: (r["name"][:10], r["kaku"])),
)
SWEEP_ITERS = 400

# 軸スイープの★の平常発生率（楽園蒲田 20260617-20260915 の88日、
# backtest/axis_sweep_baserate.py で実測。★率が高い軸は帰無が不完全で、出ても情報が薄い）
STAR_BASE_RATE = {
    ("回転数残差（機種効果を除去・全台）", "末尾"): 24,
    ("回転数残差（機種効果を除去・全台）", "機種×末尾"): 15,
    ("回転数残差（機種効果を除去・全台）", "機種×角番"): 9,
    ("回転数残差（機種効果を除去・全台）", "列"): 8,
    ("回転数残差（機種効果を除去・全台）", "機種×列"): 8,
    ("回転数残差（機種効果を除去・全台）", "角番"): 3,
    ("回転数残差（機種効果を除去・全台）", "フロア"): 1,
    ("差枚（ホール中央値比・機種軸用）", "列"): 12,
    ("差枚（ホール中央値比・機種軸用）", "機種"): 11,
    ("差枚（ホール中央値比・機種軸用）", "末尾"): 6,
    ("差枚（ホール中央値比・機種軸用）", "角番"): 6,
    ("差枚（ホール中央値比・機種軸用）", "フロア"): 3,
    ("差枚残差（機種効果を除去）", "末尾"): 8,
    ("差枚残差（機種効果を除去）", "角番"): 8,
    ("差枚残差（機種効果を除去）", "機種×末尾"): 8,
    ("差枚残差（機種効果を除去）", "列"): 6,
    ("差枚残差（機種効果を除去）", "機種×角番"): 5,
    ("差枚残差（機種効果を除去）", "機種×列"): 2,
    ("差枚残差（機種効果を除去）", "フロア"): 1,
}


def axis_sweep(records, metric_name, valfn, within_model, min_n, rng, iters=SWEEP_ITERS):
    """軸ごとに最も外れているグループを出し、並べ替え検定で偶然と比べる。

    within_model=True は機種内でラベルを入れ替える帰無（機種効果の混入を防ぐ）。
    機種軸そのものを測るときは within_model=False（ホール全体でシャッフル）。
    最大統計量で検定しているので同一軸内の多重比較は補正済み。軸×指標をまたぐ補正は報告側で行う。
    """
    data = [r for r in records if valfn(r) is not None]
    if len(data) < 20:
        return metric_name, len(data), []
    results = []
    for label, keyfn in AXES:
        if within_model and label == "機種":
            continue
        if not within_model and label.startswith("機種×"):
            continue
        groups = defaultdict(list)
        for r in data:
            groups[keyfn(r)].append(valfn(r))
        cand = {k: v for k, v in groups.items() if len(v) >= min_n}
        if len(cand) < 2:
            continue
        obs = {k: st.mean(v) for k, v in cand.items()}
        best = max(obs, key=obs.get)
        maxima = []
        if within_model:
            by_model = defaultdict(list)
            for r in data:
                by_model[r["name"]].append(r)
            for _ in range(iters):
                shuffled = defaultdict(list)
                for _name, rs in by_model.items():
                    labels = [keyfn(r) for r in rs]
                    rng.shuffle(labels)
                    for r, lab in zip(rs, labels):
                        shuffled[lab].append(valfn(r))
                means = [st.mean(v) for v in shuffled.values() if len(v) >= min_n]
                maxima.append(max(means) if means else 0.0)
        else:
            labels = [keyfn(r) for r in data]
            values = [valfn(r) for r in data]
            for _ in range(iters):
                shuffled_labels = list(labels)
                rng.shuffle(shuffled_labels)
                shuffled = defaultdict(list)
                for lab, val in zip(shuffled_labels, values):
                    shuffled[lab].append(val)
                means = [st.mean(v) for v in shuffled.values() if len(v) >= min_n]
                maxima.append(max(means) if means else 0.0)
        pval = float(np.mean(np.asarray(maxima) >= obs[best]))
        runner_up = sorted(obs.items(), key=lambda kv: -kv[1])[1:3]
        results.append((pval, label, best, len(cand[best]), obs[best], len(cand), runner_up))
    results.sort()
    return metric_name, len(data), results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hall", default="楽園蒲田店")
    parser.add_argument("--input", default=os.path.join(HERE, "output", "site777_analysis_filtered.json"))
    parser.add_argument("--output", default=os.path.join(HERE, "output", "site777_live_brief.md"))
    parser.add_argument("--month", default=None, help="YYYYMM。既定はデータ時刻の月")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as handle:
        analysis = json.load(handle)
    machines = analysis["machines"]
    path = os.path.join(ROOT, "db", args.hall + ".db")
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)

    spec_category = {
        row[0]: row[1]
        for row in conn.execute(
            "select official_name, spec_category from machine_master where spec_category is not null"
        )
    }
    by_norm = {norm(k): (k, v) for k, v in spec_category.items()}
    layout = {}
    layout_full = {}
    for n, sec, rank_min, rank_max, y in conn.execute(
        "select machine_number, section, rank_from_min, rank_from_max, y "
        "from machine_layout_history where valid_to is null"
    ):
        layout[int(n)] = sec
        layout_full[int(n)] = (sec, rank_min, rank_max, y)

    update_time = machines[0].get("jackpot_update_time") if machines else ""
    diff_ok = [m for m in machines if m["latest_diff"] is not None]
    hall_games = st.mean(m["games"] for m in machines)
    hall_diff = st.mean(m["latest_diff"] for m in diff_ok) if diff_ok else 0.0

    out = []
    out.append("# 当日ブリーフ %s（%s）" % (args.hall, update_time))
    out.append("")
    out.append(
        "稼働 %d台 / 差枚が読めた %d台 / ホール平均 %.0fG・%+.0f枚 / 勝率 %.0f%%"
        % (
            len(machines),
            len(diff_ok),
            hall_games,
            hall_diff,
            100.0 * sum(1 for m in diff_ok if m["latest_diff"] > 0) / len(diff_ok) if diff_ok else 0,
        )
    )
    out.append("")
    out.append(
        "⚠️ 途中データでは打たれていない台を判定できない。差枚は勝ち台選抜が入るので、"
        "機種・並びの**否定**には使わない（memory: feedback-midday-rb-cannot-veto-narabi）。"
    )
    out.append("")

    cur_models = defaultdict(list)
    for m in machines:
        cur_models[m["model_name"]].append(m)

    # 1) 判別可能機種: RB単独
    out.append("## 判別可能機種（ノーマル / BT / A+AT）｜RB単独")
    out.append("")
    out.append("RB確率が主指標、BB確率と総G・平均Gを併記（回転数が少ない確率は重みが小さい）。")
    out.append("")
    out.append("| 機種 | 区分 | 設置/稼働 | 総G | 平均G | RB | BB | 自己ベースライン | 設定5以上 | 平均差枚 |")
    out.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    judge_rows = []
    for name, units in cur_models.items():
        ent = by_norm.get(norm(name))
        if not ent or ent[1] not in JUDGEABLE:
            continue
        db_name, category = ent
        live = [m for m in units if m["games"] >= MIN_GAMES_MODEL]
        games = sum(m["games"] for m in live)
        rb = sum(m["rb_count"] for m in live)
        bb = sum(m["bb_count"] or 0 for m in live)
        if not rb:
            continue
        pool = daily_rb_pool(conn, db_name)
        post = rb_posterior(bs.find_spec(db_name), games, rb)
        diffs = [m["latest_diff"] for m in live if m["latest_diff"] is not None]
        rank = pct_rank(pool, games / rb)
        judge_rows.append(
            (
                rank if rank is not None else 999.0,
                name,
                category,
                len(units),
                len(live),
                games / rb,
                high_prob(post),
                st.mean(diffs) if diffs else None,
                len(pool),
                games,
                (games / bb) if bb else None,
            )
        )
    for rank, name, category, n_all, n_live, rate, high, diff, n_pool, games, bb_rate in sorted(judge_rows):
        out.append(
            "| %s | %s | %d/%d | %d | %.0f | 1/%.0f | %s | %s | %s | %s |"
            % (
                name,
                category,
                n_all,
                n_live,
                games,
                games / max(n_live, 1),
                rate,
                ("1/%.0f" % bb_rate) if bb_rate else "-",
                ("上位%.0f%%（%d日）" % (rank, n_pool)) if rank != 999.0 else "基準不足",
                ("%.0f%%" % (100 * high)) if high is not None else "-",
                ("%+.0f" % diff) if diff is not None else "-",
            )
        )
    out.append("")
    out.append(
        "⚠️ ニューキングハナハナV-30 は設定1〜4しかなく「設定5以上」は常に0%。"
        "ネオアイムジャグラーEX は設定5と6のRB確率が同一で6と断定できない。"
    )
    out.append("")

    # 2) 台別（RB単独）
    unit_rows = []
    for m in machines:
        ent = by_norm.get(norm(m["model_name"]))
        if not ent or ent[1] not in JUDGEABLE or m["games"] < MIN_GAMES_UNIT or not m["rb_count"]:
            continue
        high = high_prob(rb_posterior(bs.find_spec(ent[0]), m["games"], m["rb_count"]))
        if high and high >= HIGH_CUT:
            unit_rows.append((high, m))
    out.append("## 高設定寄りの台（RB単独 %.0f%%以上）" % (100 * HIGH_CUT))
    out.append("")
    out.append("| 台 | 機種 | G | RB | RB確率 | BB確率 | 設定5以上 | 差枚 | 列 |")
    out.append("|---|---|---:|---:|---|---|---:|---:|---|")
    for high, m in sorted(unit_rows, key=lambda r: -r[0]):
        out.append(
            "| %s | %s | %d | %d | 1/%.0f | %s | %.0f%% | %s | %s |"
            % (
                m["machine_number"],
                m["model_name"],
                m["games"],
                m["rb_count"],
                m["games"] / m["rb_count"],
                ("1/%.0f" % (m["games"] / m["bb_count"])) if m.get("bb_count") else "-",
                100 * high,
                m["latest_diff"] if m["latest_diff"] is not None else "-",
                layout.get(int(m["machine_number"]), "-"),
            )
        )
    out.append("")

    # 3) 空き台候補
    out.append("## 空き台候補（RBは高いのに差枚マイナス＝差枚で切られて空いている可能性）")
    out.append("")
    empty = [(h, m) for h, m in unit_rows if m["latest_diff"] is not None and m["latest_diff"] < 0]
    thin = [(h, m) for h, m in unit_rows if m["latest_diff"] is None]
    if empty:
        for high, m in sorted(empty, key=lambda r: -r[0]):
            out.append(
                "- **%s %s** 設定5以上%.0f%% / 差枚%+d / %dG"
                % (m["machine_number"], m["model_name"], 100 * high, m["latest_diff"], m["games"])
            )
    else:
        out.append("- 該当なし")
    if thin:
        out.append("")
        out.append("差枚未計測（2,000G未満＝ほぼ打たれていない）の高設定寄り台:")
        for high, m in sorted(thin, key=lambda r: -r[0]):
            out.append("- %s %s 設定5以上%.0f%% / %dG" % (m["machine_number"], m["model_name"], 100 * high, m["games"]))
    out.append("")

    # 4) AT機: G比×平均差枚
    out.append("## AT機｜G比×平均差枚（全台系の閾値 %+.0f）" % ZENTAIKEI_THRESHOLD)
    out.append("")
    out.append(
        "⚠️ AT機はRBの設定差が小さく、RB順位と差枚残差の相関は -0.088（判別可能機種は -0.292）。"
        "差枚を主指標にし、RBは補助。"
    )
    out.append("")
    out.append("| 機種 | 設置/差枚台 | G比 | 平均差枚 | スコア | +1800超え | RB自己ベースライン |")
    out.append("|---|---|---:|---:|---:|---:|---:|")
    at_rows = []
    for name, units in cur_models.items():
        ent = by_norm.get(norm(name))
        if not ent or ent[1] != "AT" or len(units) < 3:
            continue
        diffs = [m["latest_diff"] for m in units if m["latest_diff"] is not None]
        if len(diffs) < 2:
            continue
        gratio = st.mean(m["games"] for m in units) / hall_games
        live = [m for m in units if m["games"] >= MIN_GAMES_MODEL]
        games = sum(m["games"] for m in live)
        rb = sum(m["rb_count"] for m in live)
        pool = daily_rb_pool(conn, ent[0])
        rb_rank = pct_rank(pool, games / rb) if (rb and pool) else None
        at_rows.append(
            (
                gratio * st.mean(diffs),
                name,
                len(units),
                len(diffs),
                gratio,
                st.mean(diffs),
                sum(1 for d in diffs if d >= ZENTAIKEI_THRESHOLD),
                rb_rank,
            )
        )
    for score, name, n_all, n_diff, gratio, mean_diff, over, rb_rank in sorted(at_rows, reverse=True):
        out.append(
            "| %s | %d/%d | %.2f | %+.0f | %+.0f | %d台 | %s |"
            % (
                name,
                n_all,
                n_diff,
                gratio,
                mean_diff,
                score,
                over,
                ("上位%.0f%%" % rb_rank) if rb_rank is not None else "-",
            )
        )
    out.append("")

    # 4.5) 区分 x 軸の必須マトリクス（欠落はコードで検出して失敗にする）
    matrix_lines, produced = axis_matrix.build(machines, layout, layout_full, by_norm, norm, hall_games)
    absent = axis_matrix.missing(produced)
    if absent:
        checklist = "⚠️ 必須マトリクスが欠落: " + " / ".join("%s x %s" % pair for pair in absent)
    else:
        checklist = "✅ 必須マトリクス %d 枚（区分2 x 軸5）を出力済み" % len(axis_matrix.REQUIRED)
    out.extend(matrix_lines)

    # 5) 列（section）別
    out.append("## 列（島）別")
    out.append("")
    out.append("列 = machine_layout_history の section（x固定・y連続の1列）。")
    out.append("")
    sec_today = defaultdict(list)
    for m in machines:
        sec = layout.get(int(m["machine_number"]))
        if sec:
            sec_today[sec].append(m)
    rows = []
    for sec, units in sec_today.items():
        diffs = [m["latest_diff"] for m in units if m["latest_diff"] is not None]
        if len(diffs) < 3:
            continue
        names = sorted({m["model_name"] for m in units})
        rows.append(
            (
                st.mean(diffs),
                sec,
                len(units),
                len(diffs),
                st.mean(m["games"] for m in units) / hall_games,
                sum(1 for d in diffs if d >= ZENTAIKEI_THRESHOLD),
                "/".join(names[:2]),
            )
        )
    rows.sort(reverse=True)
    out.append("### 当日（差枚が読めた3台以上の列）")
    out.append("")
    out.append("| 列 | 台数/差枚台 | G比 | 平均差枚 | +1800超え | 機種 |")
    out.append("|---|---|---:|---:|---:|---|")
    for mean_diff, sec, n_all, n_diff, gratio, over, names in rows[:10] + rows[-5:]:
        out.append("| %s | %d/%d | %.2f | %+.0f | %d台 | %s |" % (sec, n_all, n_diff, gratio, mean_diff, over, names))
    out.append("")

    month = args.month or (update_time[:7].replace("/", "") if update_time else None)
    if month:
        mrows = conn.execute(
            "select machine_number, machine_name, diff_coins_normalized from machine_detailed_results "
            "where date between ? and ? and games_normalized > 0",
            (month + "01", month + "31"),
        ).fetchall()
        per_sec = defaultdict(list)
        per_model_sec = defaultdict(lambda: defaultdict(list))
        for number, name, diff in mrows:
            sec = layout.get(int(number))
            if sec:
                per_sec[sec].append(diff)
                per_model_sec[name][sec].append(diff)
        msorted = sorted(((st.mean(v), s, len(v)) for s, v in per_sec.items() if len(v) >= 40), reverse=True)
        out.append("### 当月（%s）の列別 台日平均差枚" % month)
        out.append("")
        out.append("| 列 | 台日 | 台日平均 |")
        out.append("|---|---:|---:|")
        for mean_diff, sec, n in msorted[:8] + msorted[-4:]:
            out.append("| %s | %d | %+.0f |" % (sec, n, mean_diff))
        out.append("")
        out.append("### 同じ機種で列が割れている例（当月、列間の差600枚以上）")
        out.append("")
        split = []
        for name, secs in per_model_sec.items():
            vals = sorted(((st.mean(v), s, len(v)) for s, v in secs.items() if len(v) >= 20), reverse=True)
            if len(vals) >= 2 and vals[0][0] - vals[-1][0] >= 600:
                split.append((vals[0][0] - vals[-1][0], name, vals))
        for gap, name, vals in sorted(split, reverse=True)[:8]:
            out.append("- **%s**：%s" % (name, " / ".join("%s %+.0f(n%d)" % (s, d, n) for d, s, n in vals)))
        if not split:
            out.append("- 該当なし")
        out.append("")
        out.append(
            "⚠️ 当月の列順位に予測力は無い（2026-09-16 実測）。列の持続性は機種効果を除くと "
            "月→翌月 r=0.111、前日→当日 r=-0.032、翌月の実効幅は上位25%で+54枚・下位25%で-34枚。"
            "列で狙うルールは作らない。**当日の機種×列の分解だけを席選びに使う**（当日は同じ機種でも列で逆になる）。"
        )
        out.append("")

    # 5.5) 軸スイープ（どの切り口に構造が出ているかを毎回探す）
    out.append("## 軸スイープ（今日どの切り口に構造が出ているか）")
    out.append("")
    out.append(
        "機種 / 列 / 末尾 / 角番 / フロア と、機種×列・機種×末尾・機種×角番 を総なめにして、"
        "各軸で最も外れているグループを並べ替え検定（%d回）で評価する。"
        "機種以外の軸は機種内でラベルを入れ替える帰無を使い、機種効果の混入を防ぐ。" % SWEEP_ITERS
    )
    out.append("")
    out.append(
        "⚠️ 指標4本 × 軸7本 = 28検定なので Bonferroni 基準は p<0.002。"
        "★(p<0.05) は「見る価値あり」であって確定ではない。n=3〜4の★は1台の大勝ちで立つことがある。"
    )
    out.append("")
    out.append(
        "⚠️ **★は当日限定**（2026-09-17 実測、楽園88日）。前日の最強グループが翌日も最強な率は "
        "列 7%(偶然2%)・角番 23%(偶然14%) で偶然を超えるが、そのグループの30日平均で統制すると "
        "列 -195枚・機種 -153枚・角番 +63枚（いずれも有意でない）。再現しているのは"
        "『もともと強い機種』だけで、★であること自体の上乗せは無い。翌日の予測には使わない。"
    )
    out.append("")
    out.append(
        "各行の「平常★率」は同じスイープを88日に当てたときに★が立った割合。"
        "24%の軸（回転数残差×末尾）で★が出ても日常であって情報は薄い。"
        "相対的に珍しいのは 差枚残差の 機種×列(2%)・フロア(1%)・機種×角番(5%)。"
    )
    out.append("")
    rng = np.random.default_rng(0)
    records = []
    for m in machines:
        number = int(m["machine_number"])
        loc = layout_full.get(number)
        if not loc:
            continue
        sec, rank_min, rank_max, _y = loc
        ent = by_norm.get(norm(m["model_name"]))
        high = None
        if ent and ent[1] in JUDGEABLE and m["games"] >= MIN_GAMES_UNIT and m["rb_count"]:
            high = high_prob(rb_posterior(bs.find_spec(ent[0]), m["games"], m["rb_count"]))
        records.append(
            dict(
                n=number,
                name=m["model_name"],
                d=m["latest_diff"],
                g=m["games"],
                sec=sec,
                tail=number % 10,
                kaku=min(rank_min or 99, rank_max or 99),
                floor=str(number)[0] + "F",
                hi=high,
            )
        )
    model_diff = defaultdict(list)
    model_games = defaultdict(list)
    for r in records:
        if r["d"] is not None:
            model_diff[r["name"]].append(r["d"])
        model_games[r["name"]].append(r["g"])
    diff_mean = {k: st.mean(v) for k, v in model_diff.items()}
    games_mean = {k: st.mean(v) for k, v in model_games.items()}
    diffs_all = [r["d"] for r in records if r["d"] is not None]
    median_diff = st.median(diffs_all) if diffs_all else 0.0
    for r in records:
        r["dres"] = None if r["d"] is None else r["d"] - diff_mean[r["name"]]
        r["dhall"] = None if r["d"] is None else r["d"] - median_diff
        r["gres"] = r["g"] - games_mean[r["name"]]
    plans = (
        ("差枚残差（機種効果を除去）", lambda r: r["dres"], True, 3),
        ("差枚（ホール中央値比・機種軸用）", lambda r: r["dhall"], False, 3),
        ("回転数残差（機種効果を除去・全台）", lambda r: r["gres"], True, 4),
        ("RB設定5以上%（判別可能機種のみ）", lambda r: None if r["hi"] is None else 100 * r["hi"], True, 3),
    )
    for metric_name, valfn, within, min_n in plans:
        name, n_used, results = axis_sweep(records, metric_name, valfn, within, min_n, rng)
        out.append("### %s（%d台）" % (name, n_used))
        out.append("")
        if not results:
            out.append("- 台数不足で検定できない")
            out.append("")
            continue
        out.append("| | 軸 | 最も外れているグループ | n | 平均 | p | 平常★率 | 候補数 | 2・3位 |")
        out.append("|---|---|---|---:|---:|---:|---:|---:|---|")
        for pval, label, best, n_best, val, n_cand, runner in results:
            mark = "★" if pval < 0.05 else ("◯" if pval < 0.15 else "")
            base = STAR_BASE_RATE.get((name, label))
            out.append(
                "| %s | %s | %s | %d | %+.1f | %.3f | %s | %d | %s |"
                % (
                    mark,
                    label,
                    str(best),
                    n_best,
                    val,
                    pval,
                    ("%d%%" % base) if base is not None else "-",
                    n_cand,
                    " / ".join("%s %+.0f" % (str(k), v) for k, v in runner),
                )
            )
        out.append("")

    # 6) 予告突合
    out.append("## 登録済み予告との突合")
    out.append("")
    date_key = update_time[:10].replace("/", "") if update_time else ""
    ann_dir = os.path.join(ROOT, "backtest", "announce")
    found = []
    if date_key and os.path.isdir(ann_dir):
        for fname in sorted(os.listdir(ann_dir)):
            if date_key in fname and fname.endswith(".json") and "scoring" not in fname:
                with open(os.path.join(ann_dir, fname), encoding="utf-8") as handle:
                    ann = json.load(handle)
                if ann.get("hall") == args.hall:
                    found.append((fname, ann))
    if not found:
        out.append("- 当日（%s）の登録済み予告は無し。" % date_key)
    for fname, ann in found:
        out.append("### %s" % ann.get("announce_id", fname))
        named = [c.get("machine_name") for c in ann.get("claims", []) if c.get("type") == "model_named"]
        for machine_name in named:
            key = norm(machine_name)[:6]
            units = [m for m in machines if key in norm(m["model_name"])]
            if not units:
                out.append("- %s：当日データに一致する機種名が無い（表記ゆれを確認）" % machine_name)
                continue
            diffs = [m["latest_diff"] for m in units if m["latest_diff"] is not None]
            out.append(
                "- **%s**：%d台 / G比%.2f / 平均差枚%s / +1800超え%d台"
                % (
                    machine_name,
                    len(units),
                    st.mean(m["games"] for m in units) / hall_games,
                    ("%+.0f" % st.mean(diffs)) if diffs else "未計測",
                    sum(1 for d in diffs if d >= ZENTAIKEI_THRESHOLD),
                )
            )
        out.append("")

    out.insert(2, checklist)
    out.insert(3, "")
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    print("[OK] live brief -> %s (%d lines)" % (args.output, len(out)))
    if absent:
        print("[FAIL] " + checklist)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
