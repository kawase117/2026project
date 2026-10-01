# -*- coding: utf-8 -*-
"""楽園蒲田の月初レポート（層1）。層2は monthly_report_layer2.py。

層1・層3の入力は、ホールDBの確定台日データ、daily_hall_summary、イベント台帳の通常日除外だけ。
結果発表・analysis_results.db は層2（monthly_report_layer2.py）にだけ隔離し、ここでは読まない。
仕様: document/plans/monthly_report_rakuen_kamata_spec.md
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from backtest.bonus_rate import _two_proportion_z
from backtest.bonus_specs import JUDGEABLE_CATEGORIES, MIN_GAMES_FOR_JUDGEMENT, find_spec, load_specs, posterior
from backtest.event_days import active, load as load_event_records
from backtest.run_backtest import DB_DIR, load_frame

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HALL = "楽園蒲田店"
DEFAULT_REGIME_START = "20260706"
DEFAULT_SEED = 20261001
NEW_MACHINE_DAYS = 6
MIN_MACHINES = 3
MIN_LIVE_MACHINES = 3
MIN_LIVE_GAMES = 1000
MIN_TOTAL_GAMES = 6000
REGIME_NOTE = "窓は工事後レジーム(2026-07-06〜)内。窓内に 2026-09-07 の配置替えと 2026-09-14 の機種入替がある。"


def wilson(k, n, z=1.96):
    """二項比率のWilson 95%境界。未定義のn<=0は(nan,nan)とする。"""
    if n <= 0:
        return float("nan"), float("nan")
    p = float(k) / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def block_bootstrap_ci(series_by_date, stat_fn=np.mean, block=7, B=2000, seed=DEFAULT_SEED):
    """日を単位に循環ブロック再標本化するCI（値の集合に対する統計量）。"""
    if isinstance(series_by_date, pd.DataFrame):
        if not {"date", "value"}.issubset(series_by_date.columns):
            raise ValueError("DataFrame input requires date and value columns")
        groups = [g["value"].dropna().to_numpy(float) for _, g in series_by_date.groupby("date", sort=True)]
    elif isinstance(series_by_date, dict):
        groups = [np.asarray(v, dtype=float).ravel() for _, v in sorted(series_by_date.items())]
    else:
        groups = [np.asarray(v, dtype=float).ravel() for v in series_by_date]
    groups = [g for g in groups if len(g)]
    if not groups:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    m = len(groups)
    values = []
    for _ in range(int(B)):
        picked = []
        while len(picked) < m:
            start = int(rng.integers(0, m))
            picked.extend(groups[(start + j) % m] for j in range(block))
        values.append(float(stat_fn(np.concatenate(picked[:m]))))
    return tuple(np.percentile(values, [2.5, 97.5]))


def block_bootstrap_ratio_ci(by_date, scale=1.0, block=7, B=2000, seed=DEFAULT_SEED):
    """比の統計量 scale*Σnum/Σden の日単位・循環ブロックブートストラップCI。

    点推定をプール値（G加重）で出すときは、CIも同じ統計量で作る必要がある。
    by_date: {date: (num, den)}。den<=0 の日は落とす。
    """
    items = [v for _, v in sorted(by_date.items()) if v[1] > 0]
    if not items:
        return float("nan"), float("nan")
    num = np.array([a for a, _ in items], float)
    den = np.array([b for _, b in items], float)
    m = len(num)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, m, size=(int(B), math.ceil(m / block)))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % m).reshape(int(B), -1)[:, :m]
    stat = scale * num[idx].sum(axis=1) / den[idx].sum(axis=1)
    return tuple(np.percentile(stat, [2.5, 97.5]))


def _ro_connect(db_path):
    path = Path(db_path).resolve()
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def hall_db_path(hall=DEFAULT_HALL):
    return Path(DB_DIR) / f"{hall}.db"


def load_machine_days(db_path, start, end):
    """台日テーブルを読み、G=0を除外した機械割ppとdsを付与する。"""
    with closing(_ro_connect(db_path)) as con:
        df = pd.read_sql_query(
            "SELECT date,machine_name,machine_number,games_normalized,diff_coins_normalized,bb_count,rb_count "
            "FROM machine_detailed_results WHERE date BETWEEN ? AND ?",
            con,
            params=(str(start), str(end)),
        )
    for col in ("games_normalized", "diff_coins_normalized", "bb_count", "rb_count"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["ds"] = df["date"].astype(str)
    valid = df["games_normalized"] > 0
    df["payout_pp"] = np.where(valid, 100.0 * df["diff_coins_normalized"] / (3.0 * df["games_normalized"]), np.nan)
    df.attrs["excluded_zero_games"] = int((~valid).sum())
    return df.loc[valid].reset_index(drop=True)


def load_first_seen(db_path):
    """DB全期間での機種ごとの初出日と、DBの最初の日付。"""
    with closing(_ro_connect(db_path)) as con:
        rows = con.execute(
            "SELECT machine_name, MIN(date) FROM machine_detailed_results GROUP BY machine_name"
        ).fetchall()
        db_min = con.execute("SELECT MIN(date) FROM machine_detailed_results").fetchone()[0]
    return {str(n): str(d) for n, d in rows}, str(db_min)


def load_weekdays(db_path):
    """date -> 曜日(漢字1字)。曜日の取得元は daily_hall_summary。"""
    with closing(_ro_connect(db_path)) as con:
        rows = con.execute("SELECT date, day_of_week FROM daily_hall_summary").fetchall()
    return {str(d): w for d, w in rows}


def normal_days(hall_summary, event_dates):
    """hall_summaryの日付からイベント台帳の対象日を除いた通常日を返す。"""
    if isinstance(hall_summary, pd.DataFrame):
        dates = hall_summary["date"].astype(str).tolist()
    else:
        dates = [str(x.get("date", x)) if isinstance(x, dict) else str(x) for x in hall_summary]
    if isinstance(event_dates, (str, Path)):
        event_dates = _read_jsonl(event_dates)
    excluded = {
        str(x.get("date")) if isinstance(x, dict) else str(x)
        for x in event_dates
        if not isinstance(x, dict) or x.get("hall", DEFAULT_HALL) == DEFAULT_HALL
    }
    return [d for d in dates if d not in excluded]


def rb_posterior(spec, games, rb):
    """仕様どおりRBだけで事後確率を求める（BB列の有無に依存しない）。"""
    return posterior(spec, games, bb=None, rb=rb)


def period_dates(asof, window_days=28, baseline_days=90, regime_start=DEFAULT_REGIME_START):
    end = datetime.strptime(str(asof), "%Y%m%d").date()
    window = [(end - timedelta(days=i)).strftime("%Y%m%d") for i in range(window_days - 1, -1, -1)]
    base_end = end - timedelta(days=window_days)
    base_start = max(
        datetime.strptime(str(regime_start), "%Y%m%d").date(), base_end - timedelta(days=baseline_days - 1)
    )
    if base_start > base_end:
        return window, []
    baseline = [(base_start + timedelta(days=i)).strftime("%Y%m%d") for i in range((base_end - base_start).days + 1)]
    return window, baseline


def hall_event_records(path=None):
    """楽園蒲田のイベント台帳（active反映後、hallは完全一致）。"""
    records = active(load_event_records() if path is None else _read_jsonl(path))
    return [r for r in records if r.get("hall") == DEFAULT_HALL]


def _event_dates_for_hall(path=None):
    return {str(r.get("date")) for r in hall_event_records(path)}


def _read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _fisher_ci(r, n):
    if n < 4 or not np.isfinite(r) or abs(r) >= 1:
        return float("nan"), float("nan")
    z = np.arctanh(r)
    half = 1.96 / math.sqrt(n - 3)
    return tuple(np.tanh([z - half, z + half]))


def at_effectiveness_gate(rows):
    """AT機の有効性ゲート: Spearman(ボーナス率, 機械割pp) の下限>0 かつ n台日>=300。"""
    nan = float("nan")
    live = rows[rows["games_normalized"] >= MIN_LIVE_GAMES].copy()
    rate = live["bonus_total"] / live["games_normalized"] if len(live) else live["games_normalized"]
    if len(live) < 4 or rate.nunique() < 2 or live["payout_pp"].nunique() < 2:
        return {"r": nan, "r_ci_lo": nan, "r_ci_hi": nan, "n_gate": int(len(live)), "gate_pass": False}
    r, _ = stats.spearmanr(rate, live["payout_pp"])
    lo, hi = _fisher_ci(float(r), len(live))
    return {
        "r": float(r),
        "r_ci_lo": lo,
        "r_ci_hi": hi,
        "n_gate": int(len(live)),
        "gate_pass": bool(len(live) >= 300 and lo > 0),
    }


def _by_date(rows, num, den_fn):
    out = {}
    for ds, g in rows.groupby("ds"):
        out[ds] = (float(g[num].sum()), float(den_fn(g)))
    return out


def _quantile_or_nan(values, q):
    values = np.asarray(values, float)
    values = values[np.isfinite(values)]
    return float(np.percentile(values, q)) if len(values) else float("nan")


def build_layer1(
    frame,
    asof,
    window_days=28,
    baseline_days=90,
    regime_start=DEFAULT_REGIME_START,
    seed=DEFAULT_SEED,
    event_dates=None,
    specs=None,
    first_seen=None,
    db_min_date=None,
):
    """層1の表をDataFrameで返す。frame引数により合成データだけでも検証できる。

    first_seen / db_min_date: DB全期間での機種の初出日とDBの最初の日付。
    省略時は frame 内の最小日で代用する（テスト用）。
    """
    d = frame.copy()
    d["ds"] = d["date"].astype(str) if "ds" not in d.columns else d["ds"].astype(str)
    d["payout_pp"] = np.where(
        d["games_normalized"] > 0, 100 * d["diff_coins_normalized"] / (3 * d["games_normalized"]), np.nan
    )
    d["bonus_total"] = d["bb_count"].fillna(0) + d["rb_count"].fillna(0)
    specs = specs if specs is not None else load_specs()
    if first_seen is None:
        first_seen = d.groupby("machine_name")["ds"].min().to_dict()
        db_min_date = d["ds"].min()
    asof_date = datetime.strptime(str(asof), "%Y%m%d").date()
    win_dates, base_dates = period_dates(asof, window_days, baseline_days, regime_start)
    win = d[d.ds.isin(win_dates) & (d.games_normalized > 0)]
    base = d[d.ds.isin(base_dates) & (d.games_normalized > 0)]
    excluded = []
    if (d["games_normalized"] <= 0).any():
        excluded.append(
            {"machine_name": "(全体)", "reason": "G=0の台日を除外", "n": int((d["games_normalized"] <= 0).sum())}
        )
    normal_set = None
    if event_dates is not None:
        normal_set = set(normal_days(pd.DataFrame({"date": base_dates}), event_dates))
    rows = []
    for name, current in win.groupby("machine_name", sort=True):
        historical = base[base.machine_name == name]
        spec = find_spec(name, specs)
        category = spec["category"] if spec else "マスター無し"
        if spec is None:
            excluded.append({"machine_name": name, "reason": "マスター無し"})
        total_g = float(current.games_normalized.sum())
        mean_g = float(current.games_normalized.mean())
        base_mean_g = float(historical.games_normalized.mean()) if not historical.empty else float("nan")
        ci_pp = block_bootstrap_ratio_ci(
            _by_date(current, "diff_coins_normalized", lambda g: 3 * g.games_normalized.sum()), scale=100, seed=seed
        )
        ci_diff = block_bootstrap_ratio_ci(_by_date(current, "diff_coins_normalized", len), seed=seed)
        wins = int((current.diff_coins_normalized > 0).sum())
        wlo, whi = wilson(wins, len(current))
        first = first_seen.get(name)
        intro_days = (
            None
            if (first is None or first == db_min_date)
            else (asof_date - datetime.strptime(first, "%Y%m%d").date()).days
        )
        reasons = []
        if intro_days is not None and intro_days <= NEW_MACHINE_DAYS:
            reasons.append(f"新台(導入{intro_days}日)")
        n_machines = int(current.machine_number.nunique())
        live_per_day = current[current.games_normalized >= MIN_LIVE_GAMES].groupby("ds").size()
        live_mean = float(live_per_day.reindex(sorted(current.ds.unique()), fill_value=0).mean())
        if n_machines < MIN_MACHINES:
            reasons.append(f"設置{n_machines}台(<{MIN_MACHINES})")
        if live_mean < MIN_LIVE_MACHINES:
            reasons.append(f"稼働台数(>={MIN_LIVE_GAMES}G)日平均{live_mean:.1f}(<{MIN_LIVE_MACHINES})")
        if total_g < MIN_TOTAL_GAMES:
            reasons.append(f"窓合計{total_g:.0f}G(<{MIN_TOTAL_GAMES})")
        for reason in reasons:
            excluded.append({"machine_name": name, "reason": "判定保留: " + reason})
        notes = []
        row = {
            "machine_name": name,
            "category": category,
            "n_machines": n_machines,
            "n_machine_days": len(current),
            "G合計": total_g,
            "平均G/台日": mean_g,
            "G比": mean_g / base_mean_g if base_mean_g > 0 else float("nan"),
            "機械割pp": float(100 * current.diff_coins_normalized.sum() / (3 * total_g)),
            "機械割pp_ci_lo": ci_pp[0],
            "機械割pp_ci_hi": ci_pp[1],
            "機械割pp_baseline": float(
                100 * historical.diff_coins_normalized.sum() / (3 * historical.games_normalized.sum())
            )
            if len(historical)
            else float("nan"),
            "差枚平均/台日": float(current.diff_coins_normalized.mean()),
            "差枚_ci_lo": ci_diff[0],
            "差枚_ci_hi": ci_diff[1],
            "勝率": wins / len(current),
            "勝率_ci_lo": wlo,
            "勝率_ci_hi": whi,
            "勝率_baseline": float((historical.diff_coins_normalized > 0).mean()) if len(historical) else float("nan"),
            "導入日数": intro_days if intro_days is not None else float("nan"),
            "判定保留理由": " / ".join(reasons),
        }
        if historical.empty:
            notes.append("ベースライン無し")
        if spec and spec.get("judgeable") and category in JUDGEABLE_CATEGORIES:
            rb = float(current.rb_count.sum())
            # ボーナスがBB列にだけ入る機種はRB=0になり、RB単独の事後確率が0に張り付いて誤読を招く
            rb_column_empty = rb == 0 and float(current.bb_count.sum()) > 0
            probs = {} if rb_column_empty else rb_posterior(spec, total_g, rb=rb)
            row.update({"RB回数": rb, "RB確率 1/x": total_g / rb if rb else float("inf")})
            for setting in range(1, 7):
                row[f"設定{setting}_事後確率"] = probs.get(setting, float("nan"))
            row["P(設定4以上)"] = sum(v for s, v in probs.items() if s >= 4) if probs else float("nan")
            row["P(設定5以上)"] = sum(v for s, v in probs.items() if s >= 5) if probs else float("nan")
            if rb_column_empty:
                row["設定判定"] = "RB列が空(ボーナスはBB列に入る機種)。RB単独の事後確率は出さない"
            else:
                row["設定判定"] = (
                    "確率未整備" if not probs else ("判定に足りない" if total_g < MIN_GAMES_FOR_JUDGEMENT else "")
                )
            n2 = float(historical.games_normalized.sum())
            if n2 > 0 and not rb_column_empty:
                row["RB_z"], row["RB_p"] = _two_proportion_z(rb, total_g, float(historical.rb_count.sum()), n2)
        elif spec and not spec.get("judgeable"):
            gate = at_effectiveness_gate(pd.concat([current, historical], ignore_index=True))
            row.update(
                {
                    "r": gate["r"],
                    "r_ci_lo": gate["r_ci_lo"],
                    "r_ci_hi": gate["r_ci_hi"],
                    "n_gate": gate["n_gate"],
                    "gate_pass": gate["gate_pass"],
                    "ゲート判定": "通過" if gate["gate_pass"] else "相関ゲート不通過（使わない）",
                }
            )
            if gate["gate_pass"] and not historical.empty:
                row["AT_bonus_z"], row["AT_bonus_p"] = _two_proportion_z(
                    float(current.bonus_total.sum()),
                    total_g,
                    float(historical.bonus_total.sum()),
                    float(historical.games_normalized.sum()),
                )
        normal = base if normal_set is None else base[base.ds.isin(normal_set)]
        dist = normal[normal.machine_name == name].diff_coins_normalized.to_numpy(float)
        if len(dist):
            ranks = np.array([float((dist <= x).mean()) for x in current.diff_coins_normalized])
        else:
            ranks = np.array([])
            notes.append("通常日の比較分布無し")
        for label, q in (("p10", 10), ("p25", 25), ("median", 50), ("p75", 75), ("p90", 90)):
            row[f"通常日分位_{label}"] = _quantile_or_nan(ranks, q)
        row["備考"] = " / ".join(notes)
        rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs.update(
        {
            "excluded": excluded,
            "masterless": [x["machine_name"] for x in excluded if x.get("reason") == "マスター無し"],
            "window_dates": win_dates,
            "baseline_dates": base_dates,
            "seed": seed,
        }
    )
    return out


_DECIMALS = [
    ("G合計", 0),
    ("G/台日", 0),
    ("RB回数", 0),
    ("1/x", 0),
    ("n_", 0),
    ("差枚", 0),
    ("導入日数", 0),
    ("pp", 2),
    ("G比", 2),
    ("_z", 2),
    ("_p", 3),
]


def _fmt(col, v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "○" if v else "×"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        if math.isinf(v):
            return "∞"
        for key, digits in _DECIMALS:
            if key in col:
                return f"{v:.{digits}f}"
        return f"{v:.3f}"
    return str(v).replace("|", "\\|")


def _merge_ci(part):
    """x, x_ci_lo, x_ci_hi を「x [lo, hi]」の1列にまとめ、設定事後確率も1列にまとめる。"""
    part = part.copy()
    for base, lo, hi in (
        ("機械割pp", "機械割pp_ci_lo", "機械割pp_ci_hi"),
        ("差枚平均/台日", "差枚_ci_lo", "差枚_ci_hi"),
        ("勝率", "勝率_ci_lo", "勝率_ci_hi"),
        ("r", "r_ci_lo", "r_ci_hi"),
    ):
        if base in part.columns and lo in part.columns:
            part[base] = [
                "" if pd.isna(v) else f"{_fmt(base, v)} [{_fmt(base, a)}, {_fmt(base, b)}]"
                for v, a, b in zip(part[base], part[lo], part[hi])
            ]
            part = part.drop(columns=[lo, hi])
    post = [f"設定{i}_事後確率" for i in range(1, 7)]
    if all(c in part.columns for c in post):
        part["設定1-6事後確率"] = [
            "/".join("" if pd.isna(v) else f"{v:.2f}" for v in vals)
            for vals in part[post].itertuples(index=False, name=None)
        ]
        part = part.drop(columns=post)
    return part


def md_table(part):
    """DataFrameをMarkdown表にする。全NaN列は落とす。"""
    if part.empty:
        return "該当なし"
    part = _merge_ci(part).dropna(axis=1, how="all")
    cols = list(part.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for values in part.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(_fmt(c, v) for c, v in zip(cols, values)) + " |")
    return "\n".join(lines)


def _span(dates):
    return f"{dates[0]}〜{dates[-1]}（{len(dates)}日）" if dates else "なし"


def render_layer1_markdown(df):
    excluded = df.attrs.get("excluded", [])
    lines = [
        "# 楽園蒲田 月初レポート（層1）",
        "",
        "結果発表・analysis_results.dbは入力特徴量に使用していません。確定した最終データのみ。",
        "判定は分布と確率で示す。当否の二値判定・絶対閾値(+1800等)による足切りはしない。",
        "",
        f"- 窓: {_span(df.attrs.get('window_dates', []))}",
        f"- ベースライン（工事後レジーム内）: {_span(df.attrs.get('baseline_dates', []))}",
        f"- seed: {df.attrs.get('seed')}",
        f"- 注記: {REGIME_NOTE}",
        "- AT機の有効性ゲート(r)の限界: AT当選数は出玉に直結するため、設定と無関係でも r が高く出る機種がある"
        "（r≈0.9超は機械的な相関を疑う）。ゲート通過は「設定情報がある」ことの証明ではない。判断はボーナス率の自己ベースライン比(AT_bonus_p)と併せて見る。",
        "- RB列が空の機種（ボーナスがBB列に入る）はRB単独の事後確率を出さない（「設定判定」列に理由）。",
        "",
    ]
    for category in ("ノーマル", "BT", "A+AT", "AT", "マスター無し"):
        lines += [f"## {category}", "", md_table(df[df.category == category]) if not df.empty else "該当なし", ""]
    lines += ["## excluded（黙って落とさない）", ""]
    if excluded:
        lines += ["| machine_name | reason | n |", "| --- | --- | --- |"]
        lines += [f"| {x.get('machine_name', '')} | {x.get('reason', '')} | {x.get('n', '')} |" for x in excluded]
    else:
        lines.append("なし")
    return "\n".join(lines)


def run_layer1(args):
    db_path = hall_db_path()
    frame = load_frame(DEFAULT_HALL)
    frame["ds"] = frame["date"].astype(str)
    first_seen, db_min = load_first_seen(db_path)
    start = min(period_dates(args.asof, args.window_days, args.baseline_days, args.regime_start)[1] or [args.asof])
    frame = frame[(frame.ds >= start) & (frame.ds <= args.asof)]
    return build_layer1(
        frame,
        args.asof,
        args.window_days,
        args.baseline_days,
        args.regime_start,
        args.seed,
        hall_event_dates_cached(),
        first_seen=first_seen,
        db_min_date=db_min,
    )


def hall_event_dates_cached():
    return _event_dates_for_hall()


def _parser():
    ap = argparse.ArgumentParser(description="楽園蒲田月初レポート")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("layer1")
    p.add_argument("--asof", required=True)
    p.add_argument("--window-days", type=int, default=28)
    p.add_argument("--baseline-days", type=int, default=90)
    p.add_argument("--regime-start", default=DEFAULT_REGIME_START)
    p.add_argument("--format", choices=("md", "json", "csv"), default="md")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p2 = sub.add_parser("layer2")
    p2.add_argument("--asof", required=True)
    p2.add_argument("--regime-start", default=DEFAULT_REGIME_START)
    p2.add_argument("--min-games", type=int, default=500)
    p2.add_argument("--perm", type=int, default=10000)
    p2.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p2.add_argument("--format", choices=("md", "json"), default="md")
    p3 = sub.add_parser("layer3")
    p3.add_argument("--asof", required=True)
    p3.add_argument("--target-month", required=True)
    p3.add_argument("--regime-start", default=DEFAULT_REGIME_START)
    p3.add_argument("--k", type=float, default=10)
    p3.add_argument("--evaluate", action="store_true")
    p3.add_argument("--all-history", action="store_true")
    p3.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p3.add_argument("--format", choices=("md", "json"), default="md")
    p4 = sub.add_parser("report")
    p4.add_argument("--asof", required=True)
    p4.add_argument("--target-month", required=True)
    p4.add_argument("--out", required=True)
    p4.add_argument("--regime-start", default=DEFAULT_REGIME_START)
    p4.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p4.add_argument("--k", type=float, default=10)
    p4.add_argument("--window-days", type=int, default=28)
    p4.add_argument("--baseline-days", type=int, default=90)
    p4.add_argument("--min-games", type=int, default=500)
    p4.add_argument("--perm", type=int, default=10000)
    return ap


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "layer2":
        from backtest import monthly_report_layer2 as layer2

        print(layer2.run(args))
        return 0
    if args.command == "layer3":
        from backtest import monthly_report_layer3 as layer3

        print(layer3.run(args))
        return 0
    if args.command == "report":
        from backtest import monthly_report_layer2 as layer2
        from backtest import monthly_report_layer3 as layer3

        layer1_args = argparse.Namespace(
            asof=args.asof,
            window_days=args.window_days,
            baseline_days=args.baseline_days,
            regime_start=args.regime_start,
            seed=args.seed,
        )
        l1 = render_layer1_markdown(run_layer1(layer1_args))
        l2_args = argparse.Namespace(
            asof=args.asof,
            regime_start=args.regime_start,
            min_games=args.min_games,
            perm=args.perm,
            seed=args.seed,
            format="md",
        )
        l2 = layer2.run(l2_args)
        l3 = layer3.render(
            layer3.build(args.asof, args.target_month, args.regime_start, args.k, True, False, args.seed)
        )
        text = "\n".join(
            [
                "# 楽園蒲田 月初レポート",
                "",
                "このレポートは日次予測にかける事前確率づくり。次の高設定台の予測ではない。",
                "判定は分布と確率。当否の二値判定はしない。",
                "",
                l1,
                "",
                l2,
                "",
                l3,
                "",
                "## 使った条件",
                "",
                f"- asof={args.asof}, target-month={args.target_month}, seed={args.seed}",
                f"- 層1窓={args.window_days}日、ベースライン={args.baseline_days}日、レジーム境界={args.regime_start}",
                "- 結果発表は層2の記述にだけ使い、層1・層3の入力には使っていない。",
            ]
        )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(text)
        return 0
    if args.command != "layer1":
        raise NotImplementedError("unknown command")
    result = run_layer1(args)
    if args.format == "json":
        print(
            json.dumps(
                {"rows": result.to_dict("records"), "excluded": result.attrs["excluded"], "seed": args.seed},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    elif args.format == "csv":
        print(result.to_csv(index=False))
    else:
        print(render_layer1_markdown(result))
    return 0


if __name__ == "__main__":
    main()
