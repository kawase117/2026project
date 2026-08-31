"""
機種単位の「周期保証」「連続回避」仮説の全ホール横断スキャン。

仮説（ユーザー提示、2026-08-11）:
  - 周期保証: 長期生存機種は、最後に高設定が疑われてからの経過日数が伸びるほど
    次に高設定が投入される確率が上がる（客離れ防止のため）。
  - 連続回避: 直前に高設定が疑われた機種は、翌日は入りにくい。

粒度: 機種単位（同一 machine_name の全台のうち、どれか1台でも高設定が
疑われた日を「その機種のイベント日」とみなす）。台番号単位ではない。

イベント代理指標: 機種×日の score = その日その機種の稼働台の平均 diff_coins_normalized。
  hit104（payout_rate>=104%の単純比率）は蒲田7実測でベースレート32%と高くノイズ源に
  なるため単独では使わない（feedback_scoring_must_separate_setting_from_pnlの教訓）。
  event_flag は score がその機種自身の全稼働日分布の上位 EVENT_QUANTILE 分位点
  （機種ごとの自己相対閾値、ホール・機種間の当たりやすさの違いを吸収する）以上の
  ときに 1 とする。閾値は感度分析として複数の分位点を試す。

除外:
  - 新台助走期間（days_since_debut < SHINDAI_EXCLUDE_DAYS、pre_existing機種は
    対象外＝除外しない）: feedback_shindai_exclude_from_games_analysis
  - 蒲田7 2026-07-07（全台設定6の特殊日）: kamata7_0707_all_setting6
  - games_normalized < 400 は eda.core.load_hall_df が既にフィルタ済み

日付境界: 「翌日」は暦日で連続する日（(next_date - date).days == 1）のみを
ペアとして扱う。データの欠測日を挟むペアは作らない
（ml/experiments/label_redesign/persistence_validation.py の
_build_next_day_pairs と同じ規約）。経過日数(days_since_last_event)は
最終イベント日からの暦日差（欠測日も日数に含める）。

セグメント（排他ではない2軸のフラグ、machine_name×hall単位で静的に決定）:
  - is_long_survivor: lifespan_days(debut〜hall内最終出現日) >= 365
                       かつ hall内最終出現日がDB最終日から30日以内（現役）
  - is_multi_unit   : 稼働日全体の平均 machine_count >= MULTI_UNIT_THRESHOLD

出力:
  document/analysis/periodicity_hazard/{hall}_hazard_bins.csv
  document/analysis/periodicity_hazard/{hall}_antistreak.csv
  document/analysis/periodicity_hazard/{hall}_machine_segments.csv
  document/analysis/periodicity_hazard/ALL_HALLS_summary.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, compute_debut_features, load_hall_df  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

COINS_PER_GAME = 3
SHINDAI_EXCLUDE_DAYS = 30
STILL_ACTIVE_GRACE_DAYS = 30
LONG_SURVIVOR_MIN_LIFESPAN_DAYS = 365
MULTI_UNIT_THRESHOLD = 8.0
EVENT_QUANTILES = [0.80, 0.90, 0.95]
DAYS_SINCE_BINS = [1, 7, 14, 21, 28, 35, 42, np.inf]
DAYS_SINCE_LABELS = ["1-6", "7-13", "14-20", "21-27", "28-34", "35-41", "42+"]

# ホール固有の全設定6等の特殊日を除外（date は YYYYMMDD 文字列）
HALL_EXCLUDE_DATES: dict[str, list[str]] = {
    "蒲田7": ["20260707"],
}

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "document" / "analysis" / "periodicity_hazard"


def _payout_rate(frame: pd.DataFrame) -> pd.Series:
    games = pd.to_numeric(frame["games"], errors="coerce")
    diff = pd.to_numeric(frame["diff"], errors="coerce")
    denom = games * COINS_PER_GAME
    return pd.Series(np.where(denom.gt(0), ((denom + diff) / denom) * 100.0, np.nan), index=frame.index)


def _load_and_prepare(hall: str) -> pd.DataFrame:
    raw = load_hall_df(hall)
    df = compute_debut_features(raw, db_start_grace_days=0)

    df["payout_rate"] = _payout_rate(df)
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    exclude_dates = HALL_EXCLUDE_DATES.get(hall, [])
    if exclude_dates:
        df = df.loc[~df["date"].isin(exclude_dates)].copy()

    # 新台助走期間の除外（既存 pre_existing 機種は対象外＝除外しない）
    keep_mask = (
        df["pre_existing"].fillna(False)
        | df["days_since_debut"].isna()
        | (df["days_since_debut"] >= SHINDAI_EXCLUDE_DAYS)
    )
    df = df.loc[keep_mask].copy()
    return df


def _build_machine_segments(df: pd.DataFrame, hall: str) -> pd.DataFrame:
    db_last_date = pd.to_datetime(df["date"], format="%Y%m%d").max()

    rows = []
    for machine_name, group in df.groupby("machine_name", sort=False):
        dates = pd.to_datetime(group["date"], format="%Y%m%d")
        debut_dt = dates.min()
        last_seen_dt = dates.max()
        lifespan_days = int((last_seen_dt - debut_dt).days)
        still_active = bool((db_last_date - last_seen_dt).days <= STILL_ACTIVE_GRACE_DAYS)
        avg_units = float(group.groupby("date")["machine_number"].nunique().mean())
        n_days = int(dates.nunique())

        rows.append(
            {
                "hall": hall,
                "machine_name": machine_name,
                "debut_date": debut_dt.strftime("%Y%m%d"),
                "last_seen_date": last_seen_dt.strftime("%Y%m%d"),
                "lifespan_days": lifespan_days,
                "still_active": still_active,
                "avg_units": round(avg_units, 2),
                "n_days_present": n_days,
                "is_long_survivor": bool(lifespan_days >= LONG_SURVIVOR_MIN_LIFESPAN_DAYS and still_active),
                "is_multi_unit": bool(avg_units >= MULTI_UNIT_THRESHOLD),
            }
        )

    return pd.DataFrame(rows)


def _build_machine_day_panel(df: pd.DataFrame, event_quantile: float) -> pd.DataFrame:
    agg = (
        df.groupby(["machine_name", "date"])
        .agg(n_units=("machine_number", "nunique"), score=("diff", "mean"), n_hit=("hit104", "sum"))
        .reset_index()
    )
    # 機種ごとの自己相対閾値（同一機種の稼働日分布の上位 event_quantile）
    cutoff = agg.groupby("machine_name")["score"].transform(lambda s: s.quantile(event_quantile))
    agg["cutoff"] = cutoff
    agg["event_flag"] = (agg["score"] >= agg["cutoff"]).astype(int)
    agg["date_dt"] = pd.to_datetime(agg["date"], format="%Y%m%d")
    agg = agg.sort_values(["machine_name", "date_dt"], kind="mergesort").reset_index(drop=True)
    return agg


def _compute_days_since_last_event(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for machine_name, group in panel.groupby("machine_name", sort=False):
        group = group.sort_values("date_dt", kind="mergesort").reset_index(drop=True)
        last_event_dt = pd.NaT
        for _, row in group.iterrows():
            days_since = np.nan if pd.isna(last_event_dt) else (row["date_dt"] - last_event_dt).days
            rows.append({**row.to_dict(), "days_since_last_event": days_since})
            if row["event_flag"] == 1:
                last_event_dt = row["date_dt"]
    return pd.DataFrame(rows)


def _next_day_pairs(panel_with_gap: pd.DataFrame) -> pd.DataFrame:
    """暦日で連続する (t, t+1) ペアのみを作る。days_since_last_event は t 時点の値。"""
    rows = []
    for machine_name, group in panel_with_gap.groupby("machine_name", sort=False):
        group = group.sort_values("date_dt", kind="mergesort").reset_index(drop=True)
        for idx in range(len(group) - 1):
            cur = group.iloc[idx]
            nxt = group.iloc[idx + 1]
            if (nxt["date_dt"] - cur["date_dt"]).days != 1:
                continue
            rows.append(
                {
                    "machine_name": machine_name,
                    "date": cur["date"],
                    "next_date": nxt["date"],
                    "days_since_last_event": cur["days_since_last_event"],
                    "event_flag": cur["event_flag"],
                    "next_event_flag": nxt["event_flag"],
                }
            )
    return pd.DataFrame(rows)


def _hazard_bins(pairs: pd.DataFrame) -> pd.DataFrame:
    work = pairs.dropna(subset=["days_since_last_event"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["bin", "n_obs", "next_event_rate"])
    work["bin"] = pd.cut(work["days_since_last_event"], bins=DAYS_SINCE_BINS, labels=DAYS_SINCE_LABELS, right=False)
    summary = (
        work.groupby("bin", observed=False)
        .agg(n_obs=("next_event_flag", "size"), next_event_rate=("next_event_flag", "mean"))
        .reset_index()
    )
    return summary


def _antistreak_test(pairs: pd.DataFrame) -> dict:
    valid = pairs.dropna(subset=["event_flag", "next_event_flag"])
    if valid.empty:
        return {"n": 0, "rate_after_event": np.nan, "rate_after_no_event": np.nan, "chi2": np.nan, "p_value": np.nan}

    table = pd.crosstab(valid["event_flag"], valid["next_event_flag"])
    if table.shape != (2, 2):
        rate_after_event = valid.loc[valid["event_flag"] == 1, "next_event_flag"].mean()
        rate_after_no_event = valid.loc[valid["event_flag"] == 0, "next_event_flag"].mean()
        return {
            "n": int(len(valid)),
            "rate_after_event": rate_after_event,
            "rate_after_no_event": rate_after_no_event,
            "chi2": np.nan,
            "p_value": np.nan,
            "note": "degenerate contingency table",
        }

    chi2, p_value, _, _ = chi2_contingency(table)
    rate_after_event = valid.loc[valid["event_flag"] == 1, "next_event_flag"].mean()
    rate_after_no_event = valid.loc[valid["event_flag"] == 0, "next_event_flag"].mean()
    return {
        "n": int(len(valid)),
        "rate_after_event": float(rate_after_event),
        "rate_after_no_event": float(rate_after_no_event),
        "chi2": float(chi2),
        "p_value": float(p_value),
        "note": "",
    }


def run_hall(hall: str, output_dir: Path) -> dict:
    df = _load_and_prepare(hall)
    segments = _build_machine_segments(df, hall)
    segments.to_csv(output_dir / f"{hall}_machine_segments.csv", index=False, encoding="utf-8-sig")

    seg_map = segments.set_index("machine_name")[["is_long_survivor", "is_multi_unit"]]

    hazard_rows = []
    antistreak_rows = []

    for quantile in EVENT_QUANTILES:
        panel = _build_machine_day_panel(df, quantile)
        panel = panel.merge(seg_map, on="machine_name", how="left")
        panel["is_long_survivor"] = panel["is_long_survivor"].fillna(False)
        panel["is_multi_unit"] = panel["is_multi_unit"].fillna(False)

        segment_defs = {
            "all": panel,
            "long_survivor": panel.loc[panel["is_long_survivor"]],
            "multi_unit": panel.loc[panel["is_multi_unit"]],
            "long_survivor_and_multi_unit": panel.loc[panel["is_long_survivor"] & panel["is_multi_unit"]],
        }

        for seg_name, seg_panel in segment_defs.items():
            if seg_panel.empty:
                continue
            with_gap = _compute_days_since_last_event(seg_panel[["machine_name", "date", "date_dt", "event_flag"]])
            pairs = _next_day_pairs(with_gap)

            bins = _hazard_bins(pairs)
            bins["hall"] = hall
            bins["segment"] = seg_name
            bins["event_quantile"] = quantile
            hazard_rows.append(bins)

            anti = _antistreak_test(pairs)
            anti.update({"hall": hall, "segment": seg_name, "event_quantile": quantile})
            antistreak_rows.append(anti)

    hazard_df = pd.concat(hazard_rows, ignore_index=True) if hazard_rows else pd.DataFrame()
    antistreak_df = pd.DataFrame(antistreak_rows)

    hazard_df.to_csv(output_dir / f"{hall}_hazard_bins.csv", index=False, encoding="utf-8-sig")
    antistreak_df.to_csv(output_dir / f"{hall}_antistreak.csv", index=False, encoding="utf-8-sig")

    print(
        f"[{hall}] machines={len(segments)} "
        f"long_survivor={int(segments['is_long_survivor'].sum())} "
        f"multi_unit={int(segments['is_multi_unit'].sum())}"
    )

    return {"hazard": hazard_df, "antistreak": antistreak_df, "segments": segments}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="機種単位の周期保証・連続回避仮説を全ホール横断でスキャンする。")
    parser.add_argument("--halls", type=str, default=",".join(HALL_DBS.keys()))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    halls = [h.strip() for h in args.halls.split(",") if h.strip()]

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    all_antistreak = []
    for hall in halls:
        result = run_hall(hall, output_dir)
        all_antistreak.append(result["antistreak"])

    combined = pd.concat(all_antistreak, ignore_index=True) if all_antistreak else pd.DataFrame()
    combined.to_csv(output_dir / "ALL_HALLS_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\nwrote: {output_dir / 'ALL_HALLS_summary.csv'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
