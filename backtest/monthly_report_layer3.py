# -*- coding: utf-8 -*-
"""楽園蒲田 月初レポート 層3（機種タイプ×日条件の事前確率）。

- ラベル（正解・評価専用）: 機種×日の連続値 y = P(設定4以上 | その日の機種プールRB)。二値化しない。
- 事前確率: 機種タイプ → 曜日 → DD（日付の「日」）の順に経験ベイズで収縮する。
    曜日セル  = (Σy + k·タイプ平均)/(n + k)             … (タイプ, 曜日)
    DDセル    = (Σy_dd + k·曜日セル)/(n_dd + k)         … (タイプ, DD)。親は「予測対象日の曜日」のセル
  機種名は特徴量にしない（機種単体の直近好調を事前確率に入れない）。イベント日は予測に入れない。
- 信頼区間: 日を単位とした循環ブロックブートストラップで学習データを引き直し、セルの推定値そのものを再計算する。
- このモジュールは結果発表DB(analysis_results.db)を読まない。
仕様: document/plans/monthly_report_rakuen_kamata_spec.md §4
"""

from __future__ import annotations

import calendar
import json
import math
from datetime import date

import numpy as np
import pandas as pd

from backtest.bonus_specs import JUDGEABLE_CATEGORIES, find_spec, load_specs
from backtest.monthly_report import (
    DEFAULT_REGIME_START,
    DEFAULT_SEED,
    block_bootstrap_ci,
    hall_db_path,
    load_machine_days,
    load_weekdays,
    md_table,
    rb_posterior,
)

BOOTSTRAP_B = 2000
MIN_POOL_GAMES = 2000
BLOCK = 7
WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


def _date(ds):
    s = str(ds)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _calendar_weekday(ds):
    return WEEKDAYS[_date(ds).weekday()]


def make_labels(frame, specs, weekdays, min_games=MIN_POOL_GAMES):
    """台日を機種×日に集約し、連続のRB事後確率ラベルを作る。除外件数は attrs に残す。"""
    frame = frame.copy()
    if "ds" not in frame.columns:
        frame["ds"] = frame["date"].astype(str)
    rows, excluded = (
        [],
        {"low_pool_games": 0, "no_spec": 0, "not_judgeable": 0, "no_posterior": 0, "rb_column_empty": 0},
    )
    totals = frame.groupby("machine_name")[["rb_count", "bb_count"]].sum()
    rb_empty = set(totals.index[(totals.rb_count == 0) & (totals.bb_count > 0)])
    for (ds, name), g in frame.groupby(["ds", "machine_name"], sort=True):
        spec = find_spec(name, specs)
        if spec is None:
            excluded["no_spec"] += 1
            continue
        if name in rb_empty:
            # ボーナスがBB列にだけ入る機種はRB単独の事後確率が0に張り付き、タイプ平均を歪めるので除く
            excluded["rb_column_empty"] += 1
            continue
        if not (spec.get("judgeable") and spec.get("category") in JUDGEABLE_CATEGORIES):
            excluded["not_judgeable"] += 1
            continue
        games = float(g["games_normalized"].sum())
        if games < min_games:
            excluded["low_pool_games"] += 1
            continue
        posterior = rb_posterior(spec, games, float(g["rb_count"].sum()))
        if not posterior:
            excluded["no_posterior"] += 1
            continue
        y = float(sum(p for s, p in posterior.items() if int(s) >= 4))
        rows.append(
            {
                "date": str(ds),
                "machine_name": name,
                "category": spec["category"],
                "weekday": weekdays.get(str(ds), _calendar_weekday(ds)),
                "dd": _date(ds).day,
                "y": min(1.0, max(0.0, y)),
                "games": games,
            }
        )
    out = pd.DataFrame(rows, columns=["date", "machine_name", "category", "weekday", "dd", "y", "games"])
    out.attrs["excluded"] = excluded
    return out


def _shrink(total, n, parent, k):
    """n=0 なら親セルの値そのまま。"""
    return float((total + k * parent) / (n + k)) if n else float(parent)


def fit_prior(labels, k=10):
    """タイプ・(タイプ,曜日)・(タイプ,DD) の集計を持つモデル。機種名は使わない。"""
    model = {"k": k, "type": {}, "weekday": {}, "dd_stats": {}, "n_type": {}, "n_weekday": {}}
    if labels is None or labels.empty:
        return model
    for cat, g in labels.groupby("category"):
        model["type"][cat] = float(g.y.mean())
        model["n_type"][cat] = int(len(g))
    for (cat, wd), g in labels.groupby(["category", "weekday"]):
        model["weekday"][(cat, wd)] = _shrink(g.y.sum(), len(g), model["type"][cat], k)
        model["n_weekday"][(cat, wd)] = int(len(g))
    for (cat, dd), g in labels.groupby(["category", "dd"]):
        model["dd_stats"][(cat, int(dd))] = (float(g.y.sum()), int(len(g)))
    return model


def predict_cell(model, category, weekday, dd):
    """DDセル →（親）曜日セル →（親）タイプ平均。学習に無いセルは親の値になる。"""
    if category not in model["type"]:
        return float("nan")
    parent = model["weekday"].get((category, weekday), model["type"][category])
    total, n = model["dd_stats"].get((category, int(dd)), (0.0, 0))
    return _shrink(total, n, parent, model["k"])


def _bootstrap_cells(labels, cells, k, seed, B=BOOTSTRAP_B, block=BLOCK):
    """cells=[(category, weekday, dd)] の推定値の95%CIを、日単位ブロックブートストラップで返す。"""
    dates = sorted(labels.date.unique())
    m = len(dates)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, m, size=(int(B), math.ceil(m / block)))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % m).reshape(int(B), -1)[:, :m]
    weights = np.zeros((int(B), m))
    np.add.at(weights, (np.repeat(np.arange(int(B)), m), idx.ravel()), 1.0)
    position = {d: i for i, d in enumerate(dates)}
    out = {}
    for cat in sorted({c for c, _, _ in cells}):
        sub = labels[labels.category == cat]
        s, n = np.zeros(m), np.zeros(m)
        wd_of, dd_of = [None] * m, np.zeros(m, int)
        for d, g in sub.groupby("date"):
            i = position[d]
            s[i], n[i] = g.y.sum(), len(g)
        for d, g in labels.groupby("date"):
            wd_of[position[d]], dd_of[position[d]] = g.weekday.iloc[0], int(g.dd.iloc[0])
        wd_of = np.array(wd_of)
        with np.errstate(invalid="ignore", divide="ignore"):
            type_b = (weights @ s) / (weights @ n)
        type_point = float(sub.y.mean())
        type_b = np.where(np.isfinite(type_b), type_b, type_point)
        wd_cache = {}
        for c, wd, dd in cells:
            if c != cat:
                continue
            if wd not in wd_cache:
                mask = (wd_of == wd).astype(float)
                sw, nw = weights @ (s * mask), weights @ (n * mask)
                wd_cache[wd] = np.where(nw > 0, (sw + k * type_b) / (nw + k), type_b)
            dmask = (dd_of == dd).astype(float)
            sd, nd = weights @ (s * dmask), weights @ (n * dmask)
            est = np.where(nd > 0, (sd + k * wd_cache[wd]) / (nd + k), wd_cache[wd])
            out[(c, wd, dd)] = tuple(np.percentile(est, [2.5, 97.5]))
    return out


def predict_month(labels, weekdays, target_month, k=10, seed=DEFAULT_SEED):
    model = fit_prior(labels, k)
    cats = sorted(model["type"])
    tm = str(target_month).replace("-", "")
    year, month = int(tm[:4]), int(tm[4:6])
    days = []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        ds = f"{year:04d}{month:02d}{day:02d}"
        days.append((ds, day, weekdays.get(ds, _calendar_weekday(ds))))
    cells = [(c, wd, day) for _, day, wd in days for c in cats]
    cis = _bootstrap_cells(labels, cells, k, seed) if cats else {}
    rows = []
    for ds, day, wd in days:
        for c in cats:
            lo, hi = cis.get((c, wd, day), (float("nan"), float("nan")))
            rows.append(
                {
                    "date": ds,
                    "category": c,
                    "weekday": wd,
                    "dd": day,
                    "prior": predict_cell(model, c, wd, day),
                    "ci_lo": lo,
                    "ci_hi": hi,
                    "n_type": model["n_type"][c],
                    "n_weekday": model["n_weekday"].get((c, wd), 0),
                    "n_dd": model["dd_stats"].get((c, day), (0.0, 0))[1],
                }
            )
    out = pd.DataFrame(rows)
    out.attrs["k"] = k
    return out


def _mse_ratio(pred, actual, constant):
    pred, actual = np.asarray(pred, float), np.asarray(actual, float)
    if not len(actual):
        return float("nan")
    base = float(np.mean((constant - actual) ** 2))
    return float(np.mean((pred - actual) ** 2)) / base if base > 0 else float("nan")


def walk_forward(
    labels,
    weekdays,
    start_month,
    end_month,
    regime_start=DEFAULT_REGIME_START,
    k=10,
    all_history=False,
    seed=DEFAULT_SEED,
):
    """月 t までで学習し月 t+1 を評価する。各foldの学習は評価月の前月末まで（評価月のデータは入らない）。"""
    start_month = str(start_month).replace("-", "")[:6]
    end_month = str(end_month).replace("-", "")[:6]
    months = pd.period_range(
        start=f"{start_month[:4]}-{start_month[4:]}", end=f"{end_month[:4]}-{end_month[4:]}", freq="M"
    )
    rows, folds = [], []
    for target in months:
        prefix = target.strftime("%Y%m")
        train = labels[labels.date.str[:6] < prefix]
        test = labels[labels.date.str[:6] == prefix]
        if not all_history:
            train, test = train[train.date >= str(regime_start)], test[test.date >= str(regime_start)]
        if train.empty or test.empty:
            continue
        model = fit_prior(train, k)
        test = test.copy()
        test["pred"] = [predict_cell(model, c, wd, dd) for c, wd, dd in zip(test.category, test.weekday, test.dd)]
        test["fold"] = prefix
        rows.append(test)
        constant = float(train.y.mean())
        folds.append(
            {
                "fold": prefix,
                "train_n": len(train),
                "test_n": len(test),
                "constant": constant,
                "mse_ratio": _mse_ratio(test.pred, test.y, constant),
            }
        )
    obs = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if obs.empty:
        return {"observations": obs, "folds": folds, "bins": pd.DataFrame()}
    obs["bin"] = pd.qcut(obs.pred.rank(method="first"), min(5, len(obs)), labels=False) + 1
    bins = []
    for b, g in obs.groupby("bin", sort=True):
        lo, hi = block_bootstrap_ci(
            {d: x.y.to_numpy() for d, x in g.groupby("date")}, block=BLOCK, B=BOOTSTRAP_B, seed=seed + int(b)
        )
        bins.append(
            {
                "bin": int(b),
                "pred_mean": float(g.pred.mean()),
                "actual_mean": float(g.y.mean()),
                "actual_ci_lo": lo,
                "actual_ci_hi": hi,
                "n": len(g),
            }
        )
    return {"observations": obs, "folds": folds, "bins": pd.DataFrame(bins)}


def build(
    asof, target_month, regime_start=DEFAULT_REGIME_START, k=10, evaluate=False, all_history=False, seed=DEFAULT_SEED
):
    db = hall_db_path()
    frame = load_machine_days(db, "20250101" if all_history else regime_start, asof)
    weekdays = load_weekdays(db)
    labels = make_labels(frame, load_specs(), weekdays)
    pred = predict_month(
        labels[labels.date >= str(regime_start)] if not all_history else labels, weekdays, target_month, k, seed
    )
    evaluation = (
        walk_forward(labels, weekdays, "202501", asof[:6], regime_start, k, all_history, seed) if evaluate else None
    )
    return {
        "labels": labels,
        "predictions": pred,
        "evaluation": evaluation,
        "excluded": labels.attrs.get("excluded", {}),
        "seed": seed,
        "regime_start": regime_start,
        "asof": asof,
        "target_month": target_month,
        "all_history": all_history,
    }


def render(built):
    p = built["predictions"]
    lines = [
        "## 楽園蒲田 月初レポート（層3・機種タイプ×日条件の事前確率）",
        "",
        "ラベルは機種×日の連続値 P(設定4以上)（RB単独・一様事前）。AT機は対象外。機種名は特徴量にしていない。",
        "イベント日は予測に入れていない（イベントの効果は層2のkind別表を参照）。結果発表は一切使っていない。",
        "",
        f"- 学習期間: {built['regime_start']}〜{built['asof']}、予測対象月: {built['target_month']}、seed={built['seed']}、k={p.attrs.get('k', 10)}",
        f"- 欠測/除外（機種×日の件数）: {json.dumps(built['excluded'], ensure_ascii=False)}",
        "- 95%CIは日単位の循環ブロックブートストラップ(block=7, B=2000)で学習データを引き直し、セルの推定値を再計算したもの",
        "- n_type/n_weekday/n_dd は、それぞれタイプ全体・(タイプ,曜日)・(タイプ,DD)の学習ラベル数。n_dd が小さいセルは親（曜日）セルにほぼ一致する",
        "",
        md_table(p),
        "",
    ]
    ev = built.get("evaluation")
    if ev is not None:
        lines += [
            "### ウォークフォワード評価（月tまでで学習→月t+1）",
            "",
            "fold数が少ないので検出力不足。「効果なし」とは断定しない。キャリブレーション（予測ビンごとの予測平均 vs 実現平均）と、",
            "定数予測（学習期間のタイプ全体平均）に対するMSE比（1未満なら定数より良い）で見る。AUCや的中率だけで判断しない。",
            "",
            md_table(ev["bins"]),
            "",
            "| fold | 学習n(機種×日) | 評価n(機種×日) | MSE比 |",
            "| --- | ---: | ---: | ---: |",
        ]
        lines += [f"| {r['fold']} | {r['train_n']} | {r['test_n']} | {r['mse_ratio']:.4f} |" for r in ev["folds"]]
        if built["all_history"]:
            lines += ["", "警告: レジーム境界を無視。方法の健全性確認のみ（楽園は2026-07-06に改装済み）。"]
    return "\n".join(lines)


def run(args):
    built = build(args.asof, args.target_month, args.regime_start, args.k, args.evaluate, args.all_history, args.seed)
    if args.format == "json":
        ev = built["evaluation"]
        return json.dumps(
            {
                "predictions": built["predictions"].to_dict("records"),
                "excluded": built["excluded"],
                "evaluation": None if ev is None else {"folds": ev["folds"], "bins": ev["bins"].to_dict("records")},
                "seed": built["seed"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    return render(built)
