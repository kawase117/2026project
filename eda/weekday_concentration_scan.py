"""Compare daily placement concentration with a within-day shuffle baseline."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from eda.kamata7_verification_common import classify_seg


ROOT = Path(__file__).resolve().parents[1]
METRICS = ("corner", "last_digit", "three_adjacent", "nibuichi", "whole_row", "single_in_row", "single_in_model")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def groups(values: pd.Series, minimum: int = 1) -> tuple[list[np.ndarray], list[str]]:
    codes, names = pd.factorize(values.astype(str), sort=True)
    indexes = [np.flatnonzero(codes == i) for i in range(len(names))]
    kept = [(idx, str(names[i])) for i, idx in enumerate(indexes) if len(idx) >= minimum]
    return [x[0] for x in kept], [x[1] for x in kept]


class DayMetric:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.reset_index(drop=True)
        self.n = len(frame)
        self.model4, _ = groups(frame["machine_name"], 4)
        self.model3, _ = groups(frame["machine_name"], 3)
        self.digits = []
        for seg in ("A", "N"):
            subset = frame.loc[frame["seg"] == seg]
            if not subset.empty:
                local, _ = groups(subset["last_digit"])
                original = np.flatnonzero(frame["seg"].to_numpy() == seg)
                self.digits.append([original[idx] for idx in local])
        positioned = frame["section"].notna() & frame["rank_from_min"].notna() & frame["rank_from_max"].notna()
        self.sections, _ = groups(frame.loc[positioned, "section"], 5)
        # groups() returns positions within the subset; restore positions in the full day.
        pos = np.flatnonzero(positioned.to_numpy())
        self.sections = [pos[idx] for idx in self.sections]
        self.corner = (
            np.concatenate(
                [
                    idx[
                        (frame.iloc[idx]["rank_from_min"].to_numpy() == 1)
                        | (frame.iloc[idx]["rank_from_max"].to_numpy() == 1)
                    ]
                    for idx in self.sections
                ]
            )
            if self.sections
            else np.array([], dtype=int)
        )
        all_section = np.concatenate(self.sections) if self.sections else np.array([], dtype=int)
        self.noncorner = np.setdiff1d(all_section, self.corner)
        self.run_windows = []
        all_sections, _ = groups(frame.loc[positioned, "section"])
        for local in all_sections:
            idx = pos[local]
            ordered = idx[np.argsort(frame.iloc[idx]["machine_number"].to_numpy())]
            numbers = frame.iloc[ordered]["machine_number"].to_numpy()
            for j in range(len(ordered) - 2):
                if numbers[j + 1] == numbers[j] + 1 and numbers[j + 2] == numbers[j] + 2:
                    # Start of a qualifying run, not each overlapping triple.
                    prev = ordered[j - 1] if j and numbers[j - 1] == numbers[j] - 1 else -1
                    self.run_windows.append((ordered[j : j + 3], prev))

    def measure(self, z: np.ndarray) -> np.ndarray:
        result = np.full(7, np.nan)
        high1, high2 = z >= 1, z >= 2
        if len(self.corner) and len(self.noncorner):
            result[0] = z[self.corner].mean() - z[self.noncorner].mean()
        if len(self.digits) == 2 and all(part for part in self.digits):
            result[1] = np.mean([max(z[idx].mean() for idx in part) for part in self.digits])
        if self.run_windows or self.frame["section"].notna().any():
            result[2] = sum(
                bool(high1[triple].all()) and (prev < 0 or not high1[prev]) for triple, prev in self.run_windows
            )
        if self.sections:
            result[4] = max(z[idx].mean() for idx in self.sections)
            result[5] = sum(high2[idx].sum() == 1 and z[idx[~high2[idx]]].mean() <= 0 for idx in self.sections)
        if self.model4:
            result[3] = sum(0.4 <= high1[idx].mean() <= 0.6 for idx in self.model4)
        if self.model3:
            result[6] = sum(high2[idx].sum() == 1 and z[idx[~high2[idx]]].mean() <= 0 for idx in self.model3)
        return result


def load(hall: str, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    path = ROOT / "db" / f"{hall}.db"
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Nonempty DB required: {path}")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        first = pd.read_sql_query(
            "SELECT machine_name, MIN(date) AS first_date FROM machine_detailed_results GROUP BY machine_name", db
        )
        raw = pd.read_sql_query(
            """SELECT date, machine_number, machine_name, last_digit,
            games_normalized, diff_coins_normalized FROM machine_detailed_results
            WHERE date BETWEEN ? AND ?""",
            db,
            params=(start, end),
        )
        layout = pd.read_sql_query(
            "SELECT machine_number, section, rank_from_min, rank_from_max FROM machine_layout", db
        )
    counts = {
        "raw_rows": len(raw),
        "null_rows": 0,
        "new_rows": 0,
        "special_rows": 0,
        "layout_missing_rows": 0,
        "zero_std_days": 0,
        "empty_days": 0,
    }
    valid = raw["games_normalized"].notna() & raw["diff_coins_normalized"].notna()
    counts["null_rows"] = int((~valid).sum())
    raw = raw.loc[valid].copy()
    if hall == "マルハンメガシティ2000-蒲田7":
        special = raw["date"].str[-4:].eq("0707") & raw["machine_number"].eq(2026)
        counts["special_rows"] = int(special.sum())
        raw = raw.loc[~special].copy()
    raw = raw.merge(first, on="machine_name", how="left", validate="many_to_one")
    age = (pd.to_datetime(raw["date"], format="%Y%m%d") - pd.to_datetime(raw["first_date"], format="%Y%m%d")).dt.days
    new = age.between(0, 6)
    counts["new_rows"] = int(new.sum())
    raw = raw.loc[~new].drop(columns="first_date")
    raw = raw.merge(layout, on="machine_number", how="left", validate="many_to_one")
    counts["layout_missing_rows"] = int(
        (raw["section"].isna() | raw["rank_from_min"].isna() | raw["rank_from_max"].isna()).sum()
    )
    raw["seg"] = raw["machine_name"].map(classify_seg)
    return raw, counts


def fmt(value: float, digits: int = 3) -> str:
    if not np.isfinite(value):
        return "—"
    if 0 < value < 0.5 * 10 ** (-digits):
        return f"< {10 ** (-digits):.{digits}f}"
    return f"{value:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hall", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--perm", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.perm < 1:
        parser.error("--perm must be positive")
    for date in (args.start, args.end):
        if len(date) != 8 or not date.isdigit():
            parser.error("dates must be YYYYMMDD")
        pd.to_datetime(date, format="%Y%m%d")
    if args.start > args.end:
        parser.error("--start must not exceed --end")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    frame, counts = load(args.hall, args.start, args.end)
    rng = np.random.default_rng(args.seed)
    records = []
    metric_skips = np.zeros(7, dtype=int)
    for date, day in frame.groupby("date", sort=True):
        if day.empty:
            counts["empty_days"] += 1
            continue
        diff = day["diff_coins_normalized"].to_numpy(dtype=float)
        std = diff.std()
        if not np.isfinite(std) or std == 0:
            counts["zero_std_days"] += 1
            continue
        z = (diff - diff.mean()) / std
        metric = DayMetric(day)
        observed = metric.measure(z)
        shuffled = np.empty((args.perm, 7))
        for i in range(args.perm):
            shuffled[i] = metric.measure(rng.permutation(z))
        null_mean = np.nanmean(shuffled, axis=0)
        excess = observed - null_mean
        metric_skips += ~np.isfinite(excess)
        records.append(
            {
                "date": date,
                "weekday": pd.Timestamp(date).weekday(),
                "mean_g": day["games_normalized"].mean(),
                **dict(zip(METRICS, excess)),
            }
        )
    daily = pd.DataFrame.from_records(records)
    if daily.empty:
        raise RuntimeError("No usable days in requested period")
    lines = [
        f"# 曜日別・投入集中度: {args.hall}",
        "",
        f"期間: {args.start}–{args.end} / 日内シャッフル: {args.perm}回 / seed: {args.seed}",
        "",
        "差枚を各日の平均・標準偏差でz化。日内のzを台間で置換し、実測値から置換平均を引いた日別超過量を曜日ごとに集計した。差枚は高設定の直接観測ではない。",
        "",
        "分類: `eda.kamata7_verification_common.classify_seg` の返り値を使用。`A`=ジャグラー・ハナハナ・クランキー・ニューパルサー（ノーマル系）、`N`=その他（AT系を含む）。観測された返り値: "
        + ", ".join(sorted(frame["seg"].dropna().unique()))
        + "。この分類関数はOKI/BTを独立に判定しない。",
        "",
        "| 曜日 | 日数 | 平均G | " + " | ".join(METRICS) + " |",
        "|---|---:|---:|" + "---:|" * 7,
    ]
    for wd, label in enumerate(WEEKDAYS):
        part = daily.loc[daily["weekday"] == wd]
        cells = []
        for name in METRICS:
            vals = part[name].dropna()
            se = vals.std(ddof=1) / np.sqrt(len(vals)) if len(vals) >= 2 else np.nan
            cells.append(f"{fmt(vals.mean())} ± {fmt(se)} (n={len(vals)})" if len(vals) else "—")
        lines.append(f"| {label} | {len(part)} | {fmt(part['mean_g'].mean(), 0)} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 検定",
        "",
        "| 指標 | Kruskal-Wallis p | 最小 Mann-Whitney p | 最小pの曜日 | 曜日別 Mann-Whitney p (Mon→Sun) |",
        "|---|---:|---:|---|---|",
    ]
    for name in METRICS:
        by_day = [daily.loc[daily["weekday"] == wd, name].dropna().to_numpy() for wd in range(7)]
        valid = [x for x in by_day if len(x)]
        kw = stats.kruskal(*valid).pvalue if len(valid) >= 2 and len(np.unique(np.concatenate(valid))) > 1 else np.nan
        mw = []
        for wd in range(7):
            other = np.concatenate([by_day[j] for j in range(7) if j != wd])
            mw.append(
                stats.mannwhitneyu(by_day[wd], other, alternative="two-sided").pvalue
                if len(by_day[wd]) and len(other)
                else np.nan
            )
        minimum = int(np.nanargmin(mw)) if np.isfinite(mw).any() else None
        lines.append(
            f"| {name} | {fmt(kw, 4)} | {fmt(mw[minimum], 4) if minimum is not None else '—'} | {WEEKDAYS[minimum] if minimum is not None else '—'} | "
            + ", ".join(fmt(x, 4) for x in mw)
            + " |"
        )
    lines += [
        "",
        "7指標 × 7曜日の多重比較。上のp値は未補正で、探索的な目安。曜日差はイベント日、機種構成、稼働率や時期の交絡を除去していない。",
        "",
        "## 除外・スキップ",
        "",
        f"元の台日数: {counts['raw_rows']}、NULL G/差枚: {counts['null_rows']}、蒲田7の7/7・2026番: {counts['special_rows']}、新機種初登場から7日間: {counts['new_rows']}。",
        f"レイアウト欠損の台日数: {counts['layout_missing_rows']}（位置系の指標から除外）。標準偏差0の日: {counts['zero_std_days']}、空の日: {counts['empty_days']}。",
        "指標別の対象群なし日数: " + ", ".join(f"{name}={int(n)}" for name, n in zip(METRICS, metric_skips)) + "。",
        "",
        "three_adjacent は同一section内の連番3台以上の高zランを1件と数え、4連以上も1件。位置系のsectionはその日の有効な座席が5台以上の場合のみ使用。",
        "",
    ]
    report = "\n".join(lines)
    output = ROOT / "eda" / "reports" / f"weekday_concentration_{args.hall}_{args.start}_{args.end}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
