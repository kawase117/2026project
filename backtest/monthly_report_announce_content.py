# -*- coding: utf-8 -*-
"""楽園蒲田 月初レポート 層2b-内容（予告の中身を、請求の種類ごとに分布で測る）。

予告は前日に凍結された情報で、結果を見る前に決まっている。「名指し機種が当たったか」ではなく、
予告が言っている中身そのものを測る。二値化しない・絶対閾値を使わない。比べるのは分布とその差。

- 末尾の請求（「末尾7が1/2⑤⑥」など）: **同日・同機種の中で**、指定末尾の台 vs その他の台。機種と日が揃うので、
  大型機種への偏りの問題が出ない。指標は台日の「G帯を揃えた差枚分位」と、判別可能機種の台のP(設定4以上)。
  無関係な末尾で同じ検定をした場合(プラセボ)の分布と並べ、「指定した末尾だけ特別か」を見る。
- 比率つき名指し（「ニブイチ⑤⑥」＝半数だけ高設定）: 半数だけ高いなら機種内の台の結果が割れる（ばらつきが大きい）はず。
  機種内の台のG帯分位の標準偏差を、同日の未名指し機種(4台以上)と比べる。
- 予告の棚卸し: どんな請求が何件あるか。
結果発表は一切使わない。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import numpy as np
import pandas as pd

from backtest import announce as announce_module
from backtest.bonus_specs import JUDGEABLE_CATEGORIES, MIN_GAMES_FOR_JUDGEMENT, find_spec
from backtest.monthly_report import DEFAULT_HALL, hall_db_path, md_table, rb_posterior
from backtest.monthly_report_layer2 import (
    MIN_EVENT_DAYS,
    g_stratified_ranks,
    stratified_effect_ci,
    stratified_perm_test,
)

SEGMENT_FLAGS = {"JUG": "jug_flag", "HANA": "hana_flag", "OKI": "oki_flag"}
PLACEBO_DRAWS = 500
MIN_RATIO_MACHINES = 4  # 機種内ばらつきを測る最小台数
# RB率の比較用の細かい回転数帯（2000G刻み）。粗い帯だと4000G以上の帯の中に回転数の偏りが残る
RATE_G_BINS = (2000, 4000, 6000, 8000)
MIN_RATE_GAMES = 1000  # 台ごとのRB率を出す最小G（これ未満は偶然で振れすぎる）
M_TESTS = 3  # 末尾×2指標 + 比率つき名指しのばらつき×1。実行前に確定


def _active_bundles(hall, regime_start, asof, bundles=None):
    if bundles is None:
        bundles = announce_module.load_announce_bundles()["bundles"]
    out = []
    for bundle in bundles:
        payload = bundle.get("payload") or {}
        if bundle.get("status") == "active" and payload.get("hall") == hall:
            if regime_start <= str(payload.get("target_date")) <= asof:
                out.append(payload)
    return out


def load_position_claims(hall, regime_start, asof, bundles=None):
    """末尾の請求を [{claim_id, date, digits, segment}] で返す。複数請求は別々に扱う。"""
    claims = []
    for payload in _active_bundles(hall, regime_start, asof, bundles):
        for index, claim in enumerate(payload.get("claims") or []):
            if claim.get("type") == "position_rule" and claim.get("field") == "last_digit":
                digits = {int(v) for v in claim.get("values") or []}
                if digits:
                    claims.append(
                        {
                            "claim_id": f"{payload['target_date']}#{index}",
                            "date": str(payload["target_date"]),
                            "digits": digits,
                            "segment": claim.get("segment"),
                        }
                    )
    return claims


def load_ratio_named(hall, regime_start, asof, bundles=None):
    """比率つき名指し {(日付, 機種): 比率} 。"""
    out = {}
    for payload in _active_bundles(hall, regime_start, asof, bundles):
        for claim in payload.get("claims") or []:
            if claim.get("type") == "model_named_ratio" and claim.get("machine_name"):
                out[(str(payload["target_date"]), claim["machine_name"])] = claim.get("ratio")
    return out


def inventory(hall, regime_start, asof, bundles=None):
    """予告の棚卸し: 請求の種類ごとの件数・日数・アカウント。"""
    rows = {}
    for payload in _active_bundles(hall, regime_start, asof, bundles):
        account = (payload.get("source") or {}).get("account") if isinstance(payload.get("source"), dict) else None
        for claim in payload.get("claims") or []:
            row = rows.setdefault(
                claim.get("type"), {"請求の種類": claim.get("type"), "件数": 0, "_dates": set(), "_acc": set()}
            )
            row["件数"] += 1
            row["_dates"].add(payload["target_date"])
            row["_acc"].add(account or "?")
    out = pd.DataFrame(
        [
            {
                "請求の種類": r["請求の種類"],
                "件数": r["件数"],
                "日数": len(r["_dates"]),
                "アカウント": "、".join(sorted(r["_acc"])),
            }
            for r in rows.values()
        ]
    )
    return out.sort_values("件数", ascending=False).reset_index(drop=True) if len(out) else out


def load_machine_flags(db_path):
    """機種名 -> {jug_flag, hana_flag, oki_flag}。"""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
        rows = con.execute(
            "SELECT machine_name_normalized, jug_flag, hana_flag, oki_flag FROM machine_master"
        ).fetchall()
    return {n: {"jug_flag": j, "hana_flag": h, "oki_flag": o} for n, j, h, o in rows}


def tai_day_table(frame, dates, specs, normal_frame):
    """指定日の全台について、台日の指標（G帯を揃えた差枚分位、判別可機種のP(設定4以上)）を作る。"""
    rows = []
    for date in sorted(dates):
        day = frame[frame.ds == date]
        for name, g in day.groupby("machine_name"):
            ref = normal_frame[(normal_frame.machine_name == name) & (normal_frame.ds != date)]
            ranks = g_stratified_ranks(g, ref)
            spec = find_spec(name, specs)
            judgeable = bool(spec and spec.get("judgeable") and spec.get("category") in JUDGEABLE_CATEGORIES)
            rb_empty = float(g.rb_count.sum()) == 0 and float(g.bb_count.sum()) > 0
            for (_, r), q in zip(g.iterrows(), ranks):
                y = float("nan")
                if judgeable and not rb_empty and r.games_normalized >= MIN_GAMES_FOR_JUDGEMENT:
                    post = rb_posterior(spec, float(r.games_normalized), float(r.rb_count))
                    if post:
                        y = float(sum(v for s, v in post.items() if s >= 4))
                rb_rate = (
                    1000.0 * float(r.rb_count) / float(r.games_normalized)
                    if judgeable and not rb_empty and r.games_normalized >= MIN_RATE_GAMES
                    else float("nan")
                )
                rows.append(
                    {
                        "date": date,
                        "machine": name,
                        "number": int(r.machine_number),
                        "digit": int(r.machine_number) % 10,
                        "q_g": float(q),
                        "y": y,
                        "games": float(r.games_normalized),
                        "gband": int(np.digitize([r.games_normalized], RATE_G_BINS)[0]),
                        "rb_rate": rb_rate,
                    }
                )
    return pd.DataFrame(rows)


def _eligible(machine, claim, flags):
    if not claim["segment"]:
        return True
    flag = SEGMENT_FLAGS.get(str(claim["segment"]).upper())
    return bool(flag and flags.get(machine, {}).get(flag) in (1, 1.0, True))


def _groups(tai, claims, flags, col, by_gband=False):
    """(請求, 日, 機種[, 回転数帯]) ごとの台日の値と末尾。指定末尾の台と他の台が両方いるグループだけが検定に使える。

    by_gband: 回転数帯でも層別する。RB率・P(設定4以上)は回転数に依存し、指定末尾の台には人が集まって回転数が増える
    （勝つ台が残る＝ヤメの偏り）ので、同じ回転数帯の台どうしで比べる。
    """
    groups = []
    by_date = {d: g for d, g in tai.groupby("date")}
    for claim in claims:
        day = by_date.get(claim["date"])
        if day is None:
            continue
        for machine, mg in day.groupby("machine"):
            if not _eligible(machine, claim, flags):
                continue
            parts = mg.groupby("gband") if by_gband else [(None, mg)]
            for _, g in parts:
                g = g.dropna(subset=[col])
                if len(g):
                    groups.append(
                        {"claim": claim["claim_id"], "vals": g[col].to_numpy(float), "digs": g["digit"].to_numpy(int)}
                    )
    return groups


def _strata(groups, digits_by_claim):
    strata = []
    for grp in groups:
        mask = np.isin(grp["digs"], list(digits_by_claim[grp["claim"]]))
        if mask.any() and (~mask).any():
            strata.append((grp["vals"][mask], grp["vals"][~mask]))
    return strata


def _pooled_effect(strata):
    n = sum(len(e) for e, _ in strata)
    return sum(len(e) * (e.mean() - m.mean()) for e, m in strata) / n if n else float("nan")


def last_digit_test(tai, claims, flags, col, label, perm=10000, seed=20261001, draws=PLACEBO_DRAWS, by_gband=False):
    """指定末尾の台 − 同日同機種のその他の台。層別並べ替え検定＋無関係な末尾のプラセボ分布。"""
    groups = _groups(tai, claims, flags, col, by_gband)
    digits = {c["claim_id"]: c["digits"] for c in claims}
    strata = _strata(groups, digits)
    n_targeted = sum(len(e) for e, _ in strata)
    row = {"指標": label, "指定末尾の台日": n_targeted, "比較に使えた(日×機種)": len(strata), "請求数": len(claims)}
    if n_targeted < MIN_EVENT_DAYS:
        row["備考"] = f"指定末尾の台日が{MIN_EVENT_DAYS}未満のため差・pは出さない"
        return row
    effect, p = stratified_perm_test(strata, perm, seed)
    lo, hi = stratified_effect_ci(strata, seed=seed)
    rng = np.random.default_rng(seed + 1)
    placebo = []
    for _ in range(int(draws)):
        draw = {
            cid: set(rng.choice([d for d in range(10) if d not in ds], size=len(ds), replace=False))
            for cid, ds in digits.items()
        }
        placebo.append(_pooled_effect(_strata(groups, draw)))
    placebo = np.array([x for x in placebo if np.isfinite(x)])
    row.update(
        {
            "指定末尾の平均": sum(len(e) * e.mean() for e, _ in strata) / n_targeted,
            "同機種その他の台の平均": sum(len(e) * m.mean() for e, m in strata) / n_targeted,
            "差": effect,
            "ci_lo": lo,
            "ci_hi": hi,
            "p(並べ替え)": p,
            "補正p(Bonferroni)": min(1.0, p * M_TESTS),
            "プラセボ差の平均": float(placebo.mean()) if len(placebo) else float("nan"),
            "プラセボ差のSD": float(placebo.std()) if len(placebo) else float("nan"),
            "プラセボのうち|差|が同等以上": float((np.abs(placebo) >= abs(effect) - 1e-12).mean())
            if len(placebo)
            else float("nan"),
        }
    )
    return row


def crowding(tai, claims, flags):
    """指定末尾の台に人が集まっているか（平均G）。同日・同機種の中で、指定末尾の台とその他の台の平均Gを比べる。"""
    strata = _strata(_groups(tai, claims, flags, "games"), {c["claim_id"]: c["digits"] for c in claims})
    n = sum(len(e) for e, _ in strata)
    if not n:
        return {}
    return {
        "n": n,
        "targeted": sum(len(e) * e.mean() for e, _ in strata) / n,
        "others": sum(len(e) * m.mean() for e, m in strata) / n,
    }


def last_digit_by_digit(tai, claims, flags, col, by_gband=False):
    """末尾ごとの内訳（記述のみ・検定しない）。"""
    rows = []
    for digit in range(10):
        sub = [c for c in claims if digit in c["digits"]]
        if not sub:
            continue
        strata = _strata(_groups(tai, sub, flags, col, by_gband), {c["claim_id"]: {digit} for c in sub})
        n = sum(len(e) for e, _ in strata)
        rows.append(
            {
                "指定末尾": digit,
                "請求数": len(sub),
                "指定末尾の台日": n,
                "差(指定−同機種その他)": _pooled_effect(strata) if n else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def ratio_dispersion(tai, ratio_named, perm=10000, seed=20261001):
    """比率つき名指し（半数だけ高設定）なら機種内の台の結果が割れるはず。機種内ばらつきを同日の未名指し機種と比べる。"""
    rows = []
    for (date, machine), g in tai.groupby(["date", "machine"]):
        q = g["q_g"].dropna().to_numpy(float)
        if len(q) >= MIN_RATIO_MACHINES:
            rows.append(
                {"date": date, "machine": machine, "named": (date, machine) in ratio_named, "sd": float(q.std(ddof=1))}
            )
    table = pd.DataFrame(rows)
    out = {"n_named": 0, "n_unnamed": 0, "n_dates": 0}
    if table.empty:
        return out, table
    strata = []
    for _, day in table.groupby("date"):
        ev, nm = day.loc[day.named, "sd"].to_numpy(float), day.loc[~day.named, "sd"].to_numpy(float)
        if len(ev) and len(nm):
            strata.append((ev, nm))
    out.update(
        {"n_named": sum(len(e) for e, _ in strata), "n_unnamed": sum(len(m) for _, m in strata), "n_dates": len(strata)}
    )
    if out["n_named"] >= MIN_EVENT_DAYS:
        effect, p = stratified_perm_test(strata, perm, seed)
        lo, hi = stratified_effect_ci(strata, seed=seed)
        out.update(
            {
                "mean_named": sum(len(e) * e.mean() for e, _ in strata) / out["n_named"],
                "mean_unnamed": sum(len(e) * m.mean() for e, m in strata) / out["n_named"],
                "effect": effect,
                "ci_lo": lo,
                "ci_hi": hi,
                "p": p,
            }
        )
    return out, table


def build(frame, bundles, specs, normal_frame, flags, regime_start, asof, perm=10000, seed=20261001, hall=DEFAULT_HALL):
    claims = load_position_claims(hall, regime_start, asof, bundles)
    ratio_named = load_ratio_named(hall, regime_start, asof, bundles)
    dates = {c["date"] for c in claims} | {d for d, _ in ratio_named}
    tai = tai_day_table(frame, dates, specs, normal_frame) if dates else pd.DataFrame()
    result = {"inventory": inventory(hall, regime_start, asof, bundles), "claims": claims, "ratio_named": ratio_named}
    if tai.empty:
        return {
            **result,
            "digit_tests": pd.DataFrame(),
            "digit_breakdown": {},
            "crowding": {},
            "ratio": ({}, pd.DataFrame()),
        }
    metrics = (
        ("G帯を揃えた差枚分位（台日）", "q_g", False),
        ("RB/1000G（判別可機種の台。同日・同機種・同じ回転数帯どうし）", "rb_rate", True),
    )
    result["digit_tests"] = pd.DataFrame(
        [last_digit_test(tai, claims, flags, col, label, perm, seed, by_gband=g) for label, col, g in metrics]
    )
    result["digit_breakdown"] = {label: last_digit_by_digit(tai, claims, flags, col, g) for label, col, g in metrics}
    result["crowding"] = crowding(tai, claims, flags)
    result["ratio"] = ratio_dispersion(tai, ratio_named, perm, seed)
    return result


def crowding_line(c):
    if not c:
        return "（人の集まり具合は計算できず）"
    return (
        f"- 人の集まり具合（同日・同機種の中、指定末尾の台日 {c['n']}）: 平均G 指定末尾 {c['targeted']:.0f} / その他の台 {c['others']:.0f}"
        f"（比 {c['targeted'] / c['others']:.2f}）"
    )


def render(built, perm, seed):
    lines = [
        "## 予告の中身を分析する（請求の種類ごと）",
        "",
        "予告は前日に凍結された情報。予告が言っている中身そのものを、分布で測る（二値化・絶対閾値なし）。",
        f"検定本数 m={M_TESTS}（末尾×2指標＋比率つき名指しのばらつき×1。実行前に確定）。Bonferroni補正pを併記。並べ替え検定 B={perm}、seed={seed}。",
        "",
        "### 予告の棚卸し（楽園蒲田・有効な本体束）",
        "",
        md_table(built["inventory"]),
        "",
        "### 末尾の請求: 指定末尾の台 − 同日・同機種のその他の台",
        "",
        "同日・同機種の中で比べるので、日の稼働・機種の大きさ・機種の出やすさが揃う。請求にセグメント（JUG など）があるときは、その機種群の中だけで比べる。",
        "「プラセボ」は、同じ請求数・同じ日に、無関係な末尾を無作為に選んで同じ検定をしたときの差の分布。"
        "指定末尾だけが特別なら、プラセボのうち同等以上の割合が小さくなる。",
        "",
        "**回転数の偏りに注意**: 予告で指定された末尾の台には人が集まり、回転数が増える。当たらなければやめる・当たれば続ける、という行動の偏りで、"
        "回転数の多い台はRB率・出率が高く見える。そこで RB率は「同日・同機種・同じ回転数帯」の台どうしで比べる（P(設定4以上)は回転数に依存するので末尾比較には使わない）。"
        "それでも、この偏りを完全には除けない。プラセボは無関係な末尾に人が集まらないので、この偏りを再現できない点にも注意。",
        "",
        crowding_line(built.get("crowding")),
        "",
        md_table(built["digit_tests"]),
        "",
        "#### 末尾ごとの内訳（記述のみ）",
        "",
    ]
    for label, frame in built["digit_breakdown"].items():
        lines += [f"**{label}**", "", md_table(frame), ""]
    ratio, _ = built["ratio"]
    lines += [
        "### 比率つき名指し（ニブイチ⑤⑥など）: 機種内の台の結果は割れているか",
        "",
        "半数だけ高設定なら、機種内の台のG帯分位がばらつくはず。機種内の標準偏差を、同日の未名指し機種（4台以上）と比べる。",
        "",
    ]
    if "effect" in ratio:
        lines.append(
            f"- 名指し {ratio['n_named']} 機種×日 / 未名指し {ratio['n_unnamed']} 機種×日 / {ratio['n_dates']} 日。"
            f"標準偏差 名指し {ratio['mean_named']:.3f}、未名指し(同日) {ratio['mean_unnamed']:.3f}、"
            f"差 {ratio['effect']:+.3f} [95%CI {ratio['ci_lo']:+.3f}, {ratio['ci_hi']:+.3f}]、p(並べ替え)={ratio['p']:.3f}、補正p={min(1.0, ratio['p'] * M_TESTS):.3f}"
        )
    else:
        lines.append(
            f"- 名指し機種×日 {ratio.get('n_named', 0)}（4台以上）が{MIN_EVENT_DAYS}未満のため、差・pは出さない。"
        )
    return "\n".join(lines)


def run_content(frame, bundles, specs, normal_frame, regime_start, asof, perm, seed):
    flags = load_machine_flags(hall_db_path())
    built = build(frame, bundles, specs, normal_frame, flags, regime_start, asof, perm, seed)
    return render(built, perm, seed)
