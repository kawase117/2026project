# -*- coding: utf-8 -*-
"""楽園蒲田 月初レポート 層2（イベント実績）。

- イベント種別(kind)ごとに、イベント日が「同曜日の通常日」からどれだけずれるかを層別並べ替え検定で測る。
  t検定は使わない。n<5 の kind は効果量もpも出さず、日付と生の値を並べるだけ。
- 結果発表（analysis_results.db）はこのモジュール内にだけ隔離する。層1・層3の入力には混ぜない。
  使い道は ①記述（発表で名指しされた機種の当日実績を、同機種の通常日分布と並べる）のみ。
  公表は店に都合のよい選択でもあるので、「公表された=入っていた」「未公表=入っていない」とは書かない。
仕様: document/plans/monthly_report_rakuen_kamata_spec.md §3
"""

from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

from scipy import stats

from backtest.bonus_specs import JUDGEABLE_CATEGORIES, MIN_GAMES_FOR_JUDGEMENT, find_spec, load_specs
from backtest.event_days import RESULT_DB, RESULT_LINKS_LEDGER, _latest_link_rows
from backtest.monthly_report import (
    DEFAULT_HALL,
    REGIME_NOTE,
    hall_db_path,
    hall_event_records,
    load_machine_days,
    load_weekdays,
    md_table,
    rb_posterior,
    wilson,
)

MIN_EVENT_DAYS = 5
BOOTSTRAP_B = 2000
# 回転数帯（G/台日）。大量の差枚でも回転数が少ない台日は、低設定のマグレの可能性が高いので帯を分けて見る
G_BINS = (2000, 4000)
G_BIN_LABELS = ("G<2000", "2000<=G<4000", "G>=4000")
POWER_Z = 0.8416  # 検出力80%
# (表示名, metricsの列名)。検定対象はこの3本。avg_games は交絡の併記のみで検定しない。
TESTED_METRICS = (("台日勝率", "win_rate"), ("機械割pp", "payout_pp"), ("RB/1000G(判別可機種)", "rb_per_1000g"))
COVARIATE = ("平均G/台日", "avg_games")


def hall_day_metrics(frame, specs, min_games=500):
    """ホール×日の指標。min_games 未満の台日は除外し、除外件数を attrs に残す。"""
    d = frame[frame["games_normalized"] >= min_games].copy()
    judge = {}
    for name in frame["machine_name"].unique():
        spec = find_spec(name, specs)
        judge[name] = bool(spec and spec.get("judgeable") and spec.get("category") in JUDGEABLE_CATEGORIES)
    d["win"] = (d["diff_coins_normalized"] > 0).astype(float)
    d["is_j"] = d["machine_name"].map(judge)
    d["j_games"] = np.where(d["is_j"], d["games_normalized"], 0.0)
    d["j_rb"] = np.where(d["is_j"], d["rb_count"], 0.0)
    g = d.groupby("ds").agg(
        win_rate=("win", "mean"),
        diff=("diff_coins_normalized", "sum"),
        games=("games_normalized", "sum"),
        avg_games=("games_normalized", "mean"),
        n_md=("win", "size"),
        j_games=("j_games", "sum"),
        j_rb=("j_rb", "sum"),
    )
    out = pd.DataFrame(
        {
            "win_rate": g["win_rate"],
            "payout_pp": 100.0 * g["diff"] / (3.0 * g["games"]),
            "rb_per_1000g": np.where(
                g["j_games"] > 0, 1000.0 * g["j_rb"] / g["j_games"].where(g["j_games"] > 0), np.nan
            ),
            "avg_games": g["avg_games"],
            "n_md": g["n_md"],
        }
    )
    out.attrs["excluded_below_min_games"] = int(len(frame) - len(d))
    return out


def stratified_perm_test(strata, B=10000, seed=20261001):
    """曜日で層別した並べ替え検定。

    strata: [(イベント日の値, 同曜日通常日の値), ...]（両方1件以上）。
    イベント日と通常日を曜日ごとに混ぜ、イベント日ラベルを同数だけ引き直す（非復元）。
    統計量 = Σ_w (k_w/n)·(イベント平均_w − 通常平均_w)。経験p（両側）=(1+#{|T*|>=|T|})/(1+B)。
    """
    rng = np.random.default_rng(seed)
    n = sum(len(ev) for ev, _ in strata)
    t_obs = sum(len(ev) / n * (ev.mean() - nm.mean()) for ev, nm in strata)
    null = np.zeros(int(B))
    for ev, nm in strata:
        pool = np.concatenate([ev, nm])
        k, size = len(ev), len(pool)
        pick = rng.random((int(B), size)).argsort(axis=1)[:, :k]
        picked = pool[pick]
        null += k / n * (picked.mean(axis=1) - (pool.sum() - picked.sum(axis=1)) / (size - k))
    p = (1 + int(np.sum(np.abs(null) >= abs(t_obs) - 1e-12))) / (1 + int(B))
    return float(t_obs), float(p)


def stratified_effect_ci(strata, B=BOOTSTRAP_B, seed=20261001):
    """イベント日・通常日をそれぞれ曜日内で復元抽出する効果量の95%CI。"""
    rng = np.random.default_rng(seed)
    n = sum(len(ev) for ev, _ in strata)
    boot = np.zeros(int(B))
    for ev, nm in strata:
        e = ev[rng.integers(0, len(ev), size=(int(B), len(ev)))].mean(axis=1)
        m = nm[rng.integers(0, len(nm), size=(int(B), len(nm)))].mean(axis=1)
        boot += len(ev) / n * (e - m)
    return tuple(np.percentile(boot, [2.5, 97.5]))


def _pooled_sd(groups):
    """曜日内の通常日のばらつき（群内平方和をプールしたSD）。自由度が足りなければnan。"""
    dof = sum(max(len(g) - 1, 0) for g in groups)
    if dof <= 0:
        return float("nan")
    return float(np.sqrt(sum(float(np.var(g, ddof=1)) * (len(g) - 1) for g in groups if len(g) > 1) / dof))


def _mde(sd, n_event, n_normal, m_tests):
    """検出可能な最小差の目安（両側・Bonferroni補正α=0.05/m、検出力80%）。正規近似なので概算。"""
    if not np.isfinite(sd) or n_event <= 0 or n_normal <= 0:
        return float("nan")
    z_alpha = float(stats.norm.ppf(1 - 0.05 / (2 * max(m_tests, 1))))
    return float((z_alpha + POWER_Z) * sd * np.sqrt(1.0 / n_event + 1.0 / n_normal))


def _group_by_kind(records):
    kinds = {}
    for r in records:
        kinds.setdefault(r.get("kind") or "(不明)", set()).add(str(r["date"]))
    return {k: sorted(v) for k, v in sorted(kinds.items())}


def analyse_events(metrics, weekdays, records, regime_start, asof, perm=10000, seed=20261001):
    """kindごとの検定表・日別表・検定本数mを返す。"""
    all_event_dates = {str(r["date"]) for r in records}
    in_scope = [d for d in metrics.index if regime_start <= d <= asof and d in weekdays]
    normal = [d for d in in_scope if d not in all_event_dates]
    kinds = _group_by_kind(records)
    usable = {k: [d for d in ds if d in set(in_scope)] for k, ds in kinds.items()}
    pre_regime = {k: [d for d in ds if d < regime_start] for k, ds in kinds.items()}
    m_tests = sum(len(TESTED_METRICS) for ds in usable.values() if len(ds) >= MIN_EVENT_DAYS)
    rows, daily = [], []
    for ki, (kind, dates) in enumerate(usable.items()):
        for mi, (label, col) in enumerate(TESTED_METRICS + (COVARIATE,)):
            strata = []
            for wd in sorted({weekdays[d] for d in dates}):
                ev = metrics.loc[[d for d in dates if weekdays[d] == wd], col].dropna().to_numpy(float)
                nm = metrics.loc[[d for d in normal if weekdays[d] == wd], col].dropna().to_numpy(float)
                if len(ev) and len(nm):
                    strata.append((ev, nm))
            n_ev = sum(len(ev) for ev, _ in strata)
            n_nm = sum(len(nm) for _, nm in strata)
            row = {"kind": kind, "指標": label, "イベント日数(層化後)": n_ev, "通常日数(層化後)": n_nm}
            if n_ev:
                row["イベント日平均"] = sum(len(ev) * ev.mean() for ev, _ in strata) / n_ev
                row["同曜日通常日平均"] = sum(len(ev) * nm.mean() for ev, nm in strata) / n_ev
                if col != COVARIATE[1]:
                    sd = _pooled_sd([nm for _, nm in strata])
                    row["通常日SD(曜日内)"] = sd
                    row["MDE(検出可能な最小差)"] = _mde(sd, n_ev, n_nm, m_tests)
            if (col != COVARIATE[1]) and len(dates) >= MIN_EVENT_DAYS and n_ev >= MIN_EVENT_DAYS:
                t_obs, p = stratified_perm_test(strata, perm, seed + 100 * ki + mi)
                lo, hi = stratified_effect_ci(strata, seed=seed + 100 * ki + mi)
                row.update(
                    {
                        "効果量": t_obs,
                        "効果量_ci_lo": lo,
                        "効果量_ci_hi": hi,
                        "p(並べ替え)": p,
                        "補正p(Bonferroni)": min(1.0, p * m_tests),
                    }
                )
            elif col != COVARIATE[1]:
                row["備考"] = f"n<{MIN_EVENT_DAYS}のため効果量・pは出さない（日別表を参照）"
            rows.append(row)
        for d in dates:
            wd = weekdays[d]
            day = {"kind": kind, "date": d, "曜日": wd, "同曜日通常日数": sum(1 for x in normal if weekdays[x] == wd)}
            for label, col in TESTED_METRICS + (COVARIATE,):
                day[label] = metrics.loc[d, col]
                same = [x for x in normal if weekdays[x] == wd]
                day[f"{label}_同曜日通常日平均"] = float(metrics.loc[same, col].mean()) if same else float("nan")
            daily.append(day)
    return {
        "tests": pd.DataFrame(rows),
        "daily": pd.DataFrame(daily),
        "m_tests": m_tests,
        "pre_regime": pre_regime,
        "kinds": kinds,
        "n_normal": len(normal),
    }


def _result_rows(analysis_db, report_id, business_date):
    """結果コーパスから、発表が名指しした機種と台番号を取る（読み取り専用・記述用）。"""
    con = sqlite3.connect(f"file:{analysis_db}?mode=ro", uri=True)
    try:
        report = con.execute(
            "SELECT event_name, posted_at FROM external_result_reports WHERE report_id=?", (str(report_id),)
        ).fetchone()
        machines = con.execute(
            "SELECT machine_number, actual_name, granularity FROM external_result_machines "
            "WHERE report_id=? AND business_date=? AND actual_name IS NOT NULL",
            (str(report_id), business_date),
        ).fetchall()
    finally:
        con.close()
    return report, machines


def _g_band(games):
    return np.digitize(np.asarray(games, float), G_BINS)


def g_stratified_ranks(rep, ref, min_ref=10):
    """発表対象の各台日が、同機種・同じ回転数帯の通常日の差枚分布のどの分位にあるか。

    差枚の大きさは回転数に比例して散らばるので、回転数の少ない台日の大差枚は偶然で出やすい。
    回転数帯を揃えて比べれば、「2000G以下の大量差枚=マグレ寄り」が分位に織り込まれる。
    比較台日が min_ref 未満の帯は nan（足切りでなく「比べられない」と明示する）。
    """
    ref_band, ref_diff = _g_band(ref.games_normalized), ref.diff_coins_normalized.to_numpy(float)
    out = []
    for g, x in zip(_g_band(rep.games_normalized), rep.diff_coins_normalized.to_numpy(float)):
        pool = ref_diff[ref_band == g]
        out.append(float((pool <= x).mean()) if len(pool) >= min_ref else float("nan"))
    return np.array(out)


def g_band_summary(md_detail):
    """発表対象の台日を回転数帯で分け、差枚の素の分位と、回転数帯を揃えた分位を並べる。"""
    if md_detail.empty:
        return pd.DataFrame()
    rows = []
    for band, g in md_detail.groupby("G帯", sort=True):
        wins = int((g["差枚"] > 0).sum())
        lo, hi = wilson(wins, len(g))
        rows.append(
            {
                "回転数帯": G_BIN_LABELS[int(band)],
                "台日数": len(g),
                "勝率": wins / len(g),
                "勝率_ci_lo": lo,
                "勝率_ci_hi": hi,
                "機械割pp": 100 * g["差枚"].sum() / (3 * g["G"].sum()),
                "差枚中央値": float(g["差枚"].median()),
                "素の通常日分位(中央値)": float(g["q_素"].median()),
                "G帯を揃えた分位(中央値)": float(g["q_G帯"].median()) if g["q_G帯"].notna().any() else float("nan"),
                "G帯分位が計算できた台日": int(g["q_G帯"].notna().sum()),
            }
        )
    return pd.DataFrame(rows)


def result_section(frame, records, regime_start, asof, analysis_db=RESULT_DB, links_path=RESULT_LINKS_LEDGER):
    """linkedの結果発表について、名指し機種の当日実績を同機種の通常日分布と並べる（足切りしない）。

    戻り値: (突き合わせ表, 未確認日の表, announced{(日付,機種):台番号の集合}, 発表対象の台日明細)
    """
    latest = {k: v for k, v in _latest_link_rows(links_path).items() if k[0] == DEFAULT_HALL}
    event_dates = {str(r["date"]) for r in records}
    kind_by_date = {}
    for r in records:
        kind_by_date.setdefault(str(r["date"]), []).append(r.get("kind") or "(不明)")
    normal_frame = frame[(frame.ds >= regime_start) & (frame.ds <= asof) & (~frame.ds.isin(event_dates))]
    rows, status_rows, announced, md_rows = [], [], {}, []
    for (_, bdate), link in sorted(latest.items(), key=lambda kv: kv[0][1]):
        status = link.get("status")
        if bdate < regime_start or bdate > asof:
            status_rows.append(
                {
                    "date": bdate,
                    "status": f"{status}（期間外）",
                    "kind": " + ".join(kind_by_date.get(bdate, [])),
                    "備考": "レジーム前または期間外（比較対象外）",
                }
            )
            continue
        if status != "linked" or not link.get("primary_report_id"):
            status_rows.append(
                {
                    "date": bdate,
                    "status": status,
                    "kind": " + ".join(kind_by_date.get(bdate, [])),
                    "備考": "発表が未確認（「入っていなかった」ことは意味しない）",
                }
            )
            continue
        report, machines = _result_rows(analysis_db, link["primary_report_id"], bdate)
        by_name = {}
        for number, name, granularity in machines:
            by_name.setdefault(name, {"numbers": set(), "gran": set()})
            by_name[name]["numbers"].add(int(number))
            if granularity:
                by_name[name]["gran"].add(granularity)
        for name, info in sorted(by_name.items()):
            day = frame[(frame.ds == bdate) & (frame.machine_name == name)]
            rep = day[day.machine_number.isin(info["numbers"])]
            ref = normal_frame[(normal_frame.machine_name == name) & (normal_frame.ds != bdate)]
            if rep.empty:
                rows.append(
                    {
                        "date": bdate,
                        "kind": " + ".join(kind_by_date.get(bdate, [])),
                        "機種": name,
                        "発表台数": len(info["numbers"]),
                        "備考": "当日の台日データに該当なし",
                    }
                )
                continue
            diff, ref_diff = rep.diff_coins_normalized.to_numpy(float), ref.diff_coins_normalized.to_numpy(float)
            announced[(bdate, name)] = set(info["numbers"])
            q_g = g_stratified_ranks(rep, ref)
            q_raw = (
                np.array([float((ref_diff <= x).mean()) for x in diff]) if len(ref_diff) else np.full(len(diff), np.nan)
            )
            for g_val, d_val, qr, qg in zip(rep.games_normalized.to_numpy(float), diff, q_raw, q_g):
                md_rows.append(
                    {
                        "date": bdate,
                        "機種": name,
                        "G": g_val,
                        "G帯": int(_g_band([g_val])[0]),
                        "差枚": d_val,
                        "q_素": qr,
                        "q_G帯": qg,
                    }
                )
            lo, hi = wilson(int((diff > 0).sum()), len(diff))
            row = {
                "date": bdate,
                "kind": " + ".join(kind_by_date.get(bdate, [])),
                "機種": name,
                "発表の粒度": "/".join(sorted(info["gran"])),
                "発表台数": len(info["numbers"]),
                "当日突合台数": len(rep),
                "設置台数": len(day),
                "実績_差枚p10": np.percentile(diff, 10),
                "実績_差枚p25": np.percentile(diff, 25),
                "実績_差枚中央値": float(np.median(diff)),
                "実績_勝率": float((diff > 0).mean()),
                "実績_勝率_ci_lo": lo,
                "実績_勝率_ci_hi": hi,
                "実績_機械割pp": 100 * rep.diff_coins_normalized.sum() / (3 * rep.games_normalized.sum()),
                "実績_平均G/台": float(rep.games_normalized.mean()),
                "G帯を揃えた分位(台日の中央値)": float(np.nanmedian(q_g)) if np.isfinite(q_g).any() else float("nan"),
                "回転数注記": "平均G<2000: 大量差枚でも低設定のマグレの可能性"
                if rep.games_normalized.mean() < 2000
                else "",
            }
            if len(ref_diff):
                row.update(
                    {
                        "通常日_差枚p10": np.percentile(ref_diff, 10),
                        "通常日_差枚p25": np.percentile(ref_diff, 25),
                        "通常日_差枚中央値": float(np.median(ref_diff)),
                        "通常日_勝率": float((ref_diff > 0).mean()),
                        "通常日_機械割pp": 100 * ref.diff_coins_normalized.sum() / (3 * ref.games_normalized.sum()),
                        "通常日_台日数": len(ref_diff),
                        "実績中央値の通常日分位": float((ref_diff <= np.median(diff)).mean()),
                    }
                )
            else:
                row["備考"] = "通常日の比較分布無し"
            rows.append(row)
    return pd.DataFrame(rows), pd.DataFrame(status_rows), announced, pd.DataFrame(md_rows)


def announced_rb_comparison(frame, announced, specs, perm=10000, seed=20261001):
    """発表で名指しされた判別可能機種と、同日の未発表の判別可能機種を、RBの事後確率で比べる。

    発表は結果を見て選ばれる（事後選択）。ノーマル/BT/A+ATはボーナス回数が出玉に直結するので、
    差枚で選ばれた機種はRBも高く出る。この差は発表の選択の強さを強く含み、「店が設定を入れた」証拠にはならない
    （選択を含んだ上限の目安）。
    比較は日ごとに層別し、同じ日の中で発表/未発表ラベルを入れ替える並べ替え検定。
    """
    strata, rows = [], []
    for ds in sorted({d for d, _ in announced}):
        day = frame[frame.ds == ds]
        ya, yb = [], []
        for name, g in day.groupby("machine_name"):
            spec = find_spec(name, specs)
            if not (spec and spec.get("judgeable") and spec.get("category") in JUDGEABLE_CATEGORIES):
                continue
            is_announced = (ds, name) in announced
            if is_announced:
                g = g[g.machine_number.isin(announced[(ds, name)])]
            games, rb = float(g.games_normalized.sum()), float(g.rb_count.sum())
            if games < MIN_GAMES_FOR_JUDGEMENT or (rb == 0 and float(g.bb_count.sum()) > 0):
                continue
            post = rb_posterior(spec, games, rb)
            if post:
                (ya if is_announced else yb).append(sum(v for s, v in post.items() if s >= 4))
        if ya and yb:
            strata.append((np.array(ya), np.array(yb)))
        rows.append({"date": ds, "発表機種数": len(ya), "未発表機種数": len(yb)})
    n_a, n_b = sum(len(a) for a, _ in strata), sum(len(b) for _, b in strata)
    out = {"n_announced": n_a, "n_unannounced": n_b, "n_dates": len(strata), "by_date": pd.DataFrame(rows)}
    if n_a >= MIN_EVENT_DAYS:
        effect, p = stratified_perm_test(strata, perm, seed)
        lo, hi = stratified_effect_ci(strata, seed=seed)
        out.update(
            {
                "mean_announced": sum(len(a) * a.mean() for a, _ in strata) / n_a,
                "mean_unannounced": sum(len(a) * b.mean() for a, b in strata) / n_a,
                "effect": effect,
                "ci_lo": lo,
                "ci_hi": hi,
                "p": p,
            }
        )
    return out


def build(asof, regime_start, min_games=500, perm=10000, seed=20261001):
    db = hall_db_path()
    frame = load_machine_days(db, regime_start, asof)
    specs = load_specs()
    metrics = hall_day_metrics(frame, specs, min_games)
    weekdays = load_weekdays(db)
    records = hall_event_records()
    analysis = analyse_events(metrics, weekdays, records, regime_start, asof, perm, seed)
    results, unconfirmed, announced, md_detail = result_section(frame, records, regime_start, asof)
    return {
        "analysis": analysis,
        "results": results,
        "unconfirmed": unconfirmed,
        "metrics": metrics,
        "g_summary": g_band_summary(md_detail),
        "rb_comparison": announced_rb_comparison(frame, announced, specs, perm, seed),
    }


def _render_rb_comparison(cmp):
    lines = [
        "### 発表された判別可能機種 vs 同日の未発表機種（RBの事後確率 P(設定4以上)）",
        "",
        "発表は結果を見て選ばれる（事後選択）。ノーマル/BT/A+ATはボーナス回数が出玉に直結するので、差枚で選ばれた機種はRBも高く出る。"
        "したがってこの差は「発表の選択の強さ」を強く含み、「店が設定を入れた」証拠にはならない（選択を含んだ上限の目安）。"
        "店の投入を測るには、発表前に決まっている情報（予告）との突き合わせが要る。"
        "同じ日の中で発表/未発表ラベルを入れ替える並べ替え検定（日で層別）。",
        "",
        f"- 発表機種×日 n={cmp['n_announced']}、未発表機種×日 n={cmp['n_unannounced']}、比較できた日数={cmp['n_dates']}"
        "（合計2000G未満、RB列が空の機種は除く）",
    ]
    if "effect" in cmp:
        lines.append(
            f"- P(設定4以上) 発表 {cmp['mean_announced']:.3f} / 未発表 {cmp['mean_unannounced']:.3f}、"
            f"差 {cmp['effect']:+.3f} [95%CI {cmp['ci_lo']:+.3f}, {cmp['ci_hi']:+.3f}]、p(並べ替え)={cmp['p']:.3f}"
        )
    else:
        lines.append(f"- 発表機種×日が{MIN_EVENT_DAYS}未満のため、差とpは出さない。")
    return lines + [""]


def render(built, asof, regime_start, min_games, perm, seed):
    a = built["analysis"]
    lines = [
        "# 楽園蒲田 月初レポート（層2 イベント実績）",
        "",
        "イベント日は楽園蒲田のレコードのみ（他ホールの値は借りない）。結果発表は記述にだけ使い、層1・層3の入力に混ぜない。",
        "",
        f"- 期間: {regime_start}〜{asof}（工事後レジーム）。{REGIME_NOTE}",
        f"- min-games: {min_games}G未満の台日は除外（除外 {built['metrics'].attrs['excluded_below_min_games']} 台日）",
        f"- 通常日: イベント台帳に載らない日（{a['n_normal']}日）。同曜日どうしで比較（曜日は daily_hall_summary）",
        f"- 検定: 曜日で層別した並べ替え検定 B={perm}、seed={seed}。t値は使わない",
        f"- **検定本数 m = {a['m_tests']}**（イベント日>={MIN_EVENT_DAYS}の kind × 3指標。実行前に確定）。Bonferroni補正p=min(1, p×m)",
        "- 稼働量（平均G/台日）がイベント日と通常日で違うと比べられないので、各 kind の平均G/台日を併記",
        "",
        "## kind別の効果（イベント日 − 同曜日通常日）",
        "",
        md_table(a["tests"]),
        "",
    ]
    pre = {k: v for k, v in a["pre_regime"].items() if v}
    if pre:
        lines += ["レジーム前（比較対象外）: " + "、".join(f"{k} {len(v)}日" for k, v in pre.items()), ""]
    lines += [
        "## イベント日の日別実績（n<5のkindは効果量を出さずここで見る）",
        "",
        md_table(a["daily"]),
        "",
        "## 結果発表との突き合わせ（記述のみ・足切りしない）",
        "",
        "公表は店に都合のよい選択でもある。名指しされた機種の当日実績を、同機種の通常日(レジーム内)の分布と並べる。",
        "",
        "### 回転数帯で見る（大量差枚でも回転数が少なければ、低設定のマグレの可能性が高い）",
        "",
        "差枚の大きさは回転数に比例して散らばるので、素の分位は回転数の少ない台日の大差枚を過大評価する。"
        "「G帯を揃えた分位」は同機種・同じ回転数帯の通常日と比べる（帯は G<2000 / 2000〜3999 / 4000以上）。"
        "素の分位との差が、回転数の影響の大きさ。",
        "",
        md_table(built["g_summary"]),
        "",
        *_render_rb_comparison(built["rb_comparison"]),
        "### 発表機種ごとの表",
        "",
        "kind の「A + B」は、同じ日に別種のイベントが重なっていることを示す（kind ではなく日付の属性）。",
        "",
        md_table(built["results"]),
        "",
        "### 発表が未確認の日（「入っていなかった」ではない）",
        "",
        md_table(built["unconfirmed"]),
    ]
    return "\n".join(lines)


def run(args):
    built = build(args.asof, args.regime_start, args.min_games, args.perm, args.seed)
    if args.format == "json":
        a = built["analysis"]
        return json.dumps(
            {
                "m_tests": a["m_tests"],
                "tests": a["tests"].to_dict("records"),
                "daily": a["daily"].to_dict("records"),
                "results": built["results"].to_dict("records"),
                "unconfirmed": built["unconfirmed"].to_dict("records"),
                "seed": args.seed,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    return render(built, args.asof, args.regime_start, args.min_games, args.perm, args.seed)
