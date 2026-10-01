# -*- coding: utf-8 -*-
"""楽園蒲田 月初レポート 層2b（予告で事前に名指しされた機種 vs 同日の未名指し機種）。

結果発表の突き合わせ(層2)は、結果を見て選ばれた機種を扱うので事後選択を強く含み、店の投入を測れない。
予告は前日に凍結された情報（結果を見る前に決まっている）なので、名指しされた機種が実際に良かったかを、
事後選択なしで測れる。ここでは「名指し機種 − 同日の未名指し機種」を、日で層別した並べ替え検定で見る。

指標（いずれも機種×日。二値化しない、絶対閾値を使わない）:
  - G帯を揃えた差枚分位: 同機種・同じ回転数帯の通常日の差枚分布に対する台日の分位（機種内の台日中央値）
  - 機械割pp: 機種プール 100×Σ差枚/(3×ΣG)。合計2000G以上の機種×日のみ
  - P(設定4以上): ノーマル/BT/A+ATの機種プールRBの事後確率。合計2000G以上・RB列が空でない機種のみ
予告は結果発表と違って「入っていた」の証明にはならないが、名指しに店の投入が乗っていれば同日の未名指しより良く出るはず。
注意: 名指し機種は台数が多い大型機種に偏ることがある（同日内の比較で日の稼働は揃うが、機種の大きさは揃わない）。
仕様: document/plans/monthly_report_rakuen_kamata_spec.md §3
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from backtest import announce as announce_module
from backtest.bonus_specs import JUDGEABLE_CATEGORIES, MIN_GAMES_FOR_JUDGEMENT, find_spec, load_specs
from backtest.monthly_report import (
    DEFAULT_HALL,
    REGIME_NOTE,
    hall_db_path,
    hall_event_records,
    load_machine_days,
    md_table,
    rb_posterior,
)
from backtest.monthly_report_layer2 import (
    MIN_EVENT_DAYS,
    g_stratified_ranks,
    stratified_effect_ci,
    stratified_perm_test,
)

NAMED_TYPES = ("model_named", "model_named_ratio")
METRICS = (("G帯を揃えた差枚分位", "q_g"), ("機械割pp(G>=2000)", "pp"), ("P(設定4以上)(判別可機種)", "y"))


def load_named(hall, regime_start, asof, bundles=None):
    """予告束から {(日付, 機種名): {claim種別}} を作る。有効(active)な本体束だけ。取り下げ・振り返り・補遺は使わない。"""
    if bundles is None:
        bundles = announce_module.load_announce_bundles()["bundles"]
    named = {}
    for bundle in bundles:
        if bundle.get("status") != "active":
            continue
        payload = bundle.get("payload") or {}
        if payload.get("hall") != hall:
            continue
        date = str(payload.get("target_date"))
        if not (regime_start <= date <= asof):
            continue
        for claim in payload.get("claims") or []:
            if claim.get("type") in NAMED_TYPES and claim.get("machine_name"):
                named.setdefault((date, claim["machine_name"]), set()).add(claim["type"])
    return named


def machine_day_table(frame, named, specs, normal_frame):
    """名指しがあった日の全機種について、機種×日の指標を作る。名指し/未名指しのラベル付き。"""
    dates = sorted({d for d, _ in named})
    rows = []
    for date in dates:
        day = frame[frame.ds == date]
        for name, g in day.groupby("machine_name"):
            ref = normal_frame[(normal_frame.machine_name == name) & (normal_frame.ds != date)]
            ranks = g_stratified_ranks(g, ref)
            games = float(g.games_normalized.sum())
            spec = find_spec(name, specs)
            y = float("nan")
            if (
                spec
                and spec.get("judgeable")
                and spec.get("category") in JUDGEABLE_CATEGORIES
                and games >= MIN_GAMES_FOR_JUDGEMENT
            ):
                rb = float(g.rb_count.sum())
                if not (rb == 0 and float(g.bb_count.sum()) > 0):
                    post = rb_posterior(spec, games, rb)
                    if post:
                        y = float(sum(v for s, v in post.items() if s >= 4))
            rows.append(
                {
                    "date": date,
                    "machine": name,
                    "named": (date, name) in named,
                    "claim": "+".join(sorted(named.get((date, name), []))),
                    "n_machines": len(g),
                    "games": games,
                    "q_g": float(np.nanmedian(ranks)) if np.isfinite(ranks).any() else float("nan"),
                    "pp": 100 * float(g.diff_coins_normalized.sum()) / (3 * games) if games >= 2000 else float("nan"),
                    "y": y,
                }
            )
    return pd.DataFrame(rows)


def compare(table, perm=10000, seed=20261001, claim=None):
    """名指し − 未名指し を、日で層別した並べ替え検定で比べる。claim を指定するとその種別の名指しだけを名指し側に使う。"""
    rows = []
    for label, col in METRICS:
        strata, n_named, n_unnamed = [], 0, 0
        for _, day in table.groupby("date"):
            flag = day["named"] if claim is None else day["claim"].str.contains(claim)
            ev = day.loc[flag, col].dropna().to_numpy(float)
            nm = day.loc[~day["named"], col].dropna().to_numpy(float)
            if len(ev) and len(nm):
                strata.append((ev, nm))
                n_named, n_unnamed = n_named + len(ev), n_unnamed + len(nm)
        row = {"指標": label, "名指し機種×日": n_named, "未名指し機種×日": n_unnamed, "比較できた日数": len(strata)}
        if n_named:
            row["名指し平均"] = sum(len(e) * e.mean() for e, _ in strata) / n_named
            row["未名指し平均(同日)"] = sum(len(e) * m.mean() for e, m in strata) / n_named
        if n_named >= MIN_EVENT_DAYS:
            effect, p = stratified_perm_test(strata, perm, seed)
            lo, hi = stratified_effect_ci(strata, seed=seed)
            row.update({"差(名指し−未名指し)": effect, "ci_lo": lo, "ci_hi": hi, "p(並べ替え)": p})
        else:
            row["備考"] = f"名指し機種×日が{MIN_EVENT_DAYS}未満のため差・pは出さない"
        rows.append(row)
    return pd.DataFrame(rows)


def build(asof, regime_start, perm=10000, seed=20261001):
    db = hall_db_path()
    frame = load_machine_days(db, regime_start, asof)
    event_dates = {str(r["date"]) for r in hall_event_records()}
    normal_frame = frame[~frame.ds.isin(event_dates)]
    named = load_named(DEFAULT_HALL, regime_start, asof)
    table = machine_day_table(frame, named, load_specs(), normal_frame)
    present = {(r.date, r.machine) for r in table.itertuples() if r.named} if len(table) else set()
    unmatched = sorted(set(named) - present)
    overall = compare(table, perm, seed) if len(table) else pd.DataFrame()
    by_claim = {c: compare(table, perm, seed + 7, claim=c) for c in NAMED_TYPES} if len(table) else {}
    return {"named": named, "table": table, "overall": overall, "by_claim": by_claim, "unmatched": unmatched}


def render(built, asof, regime_start, perm, seed):
    table = built["table"]
    lines = [
        "# 楽園蒲田 月初レポート（層2b 予告の名指し機種）",
        "",
        "予告は前日に凍結された情報で、結果を見る前に決まっている。結果発表と違って事後選択を含まないので、"
        "名指しされた機種が同日の未名指し機種より良く出たかを、店の投入の手がかりとして測れる。",
        "",
        f"- 期間: {regime_start}〜{asof}（工事後）。{REGIME_NOTE}",
        f"- 予告: 有効(active)な本体束の model_named / model_named_ratio（取り下げ・振り返り・補遺は不使用）。名指し (日付×機種) = {len(built['named'])}、"
        f"うち当日のDBに該当しない {len(built['unmatched'])}",
        f"- 検定: 同じ日の中で名指し/未名指しラベルを入れ替える並べ替え検定（日で層別）B={perm}、seed={seed}。**検定本数 m=3**（3指標。Bonferroni補正pを併記）",
        "- 注意: 名指し機種は台数の多い大型機種に偏ることがある（同日内の比較で日の稼働は揃うが機種の大きさは揃わない）。"
        "差があっても、予告者の選定眼（過去の好調機種を選ぶ）と店の投入を分けられない。",
        "",
        "## 名指し機種 − 同日の未名指し機種",
        "",
    ]
    if table.empty:
        return "\n".join(lines + ["予告の名指しが期間内に無い。"])
    overall = built["overall"].copy()
    if "p(並べ替え)" in overall.columns:
        overall["補正p(Bonferroni)"] = np.minimum(1.0, overall["p(並べ替え)"] * 3)
    lines += [md_table(overall), "", "## claim種別ごと（探索的。検定本数に含めず、補正pは出さない）", ""]
    for claim, frame in built["by_claim"].items():
        lines += [f"### {claim}", "", md_table(frame), ""]
    lines += ["## 名指し機種×日の明細（機種×日）", "", md_table(table[table["named"]].drop(columns=["named"])), ""]
    if built["unmatched"]:
        lines += ["### 当日のDBに該当しない名指し", "", "- " + "、".join(f"{d} {m}" for d, m in built["unmatched"])]
    return "\n".join(lines)


def run(args):
    built = build(args.asof, args.regime_start, args.perm, args.seed)
    if args.format == "json":
        return json.dumps(
            {
                "overall": built["overall"].to_dict("records"),
                "by_claim": {k: v.to_dict("records") for k, v in built["by_claim"].items()},
                "unmatched": built["unmatched"],
                "seed": args.seed,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    return render(built, args.asof, args.regime_start, args.perm, args.seed)
