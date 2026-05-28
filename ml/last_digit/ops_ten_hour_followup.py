from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.tail_ltr_split_rule_wf import aggregate_mode, build_base_rows, resolve_db_path


def _latest_ts(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _compute_2fa_metrics(topk_df: pd.DataFrame, loss_df: pd.DataFrame) -> dict[str, Any]:
    topk_2fa = topk_df[topk_df["expert"].astype(str) == "2F_A"].copy()
    loss_2fa = loss_df[loss_df["expert"].astype(str) == "2F_A"].copy()
    if topk_2fa.empty or loss_2fa.empty:
        return {"available": False}
    return {
        "available": True,
        "n_pairs": int(len(loss_2fa)),
        "n_days": int(loss_2fa["date"].nunique()),
        "hit_at_2": float(pd.to_numeric(topk_2fa["hit_at_2"], errors="coerce").mean()),
        "rank1_match_rate": float(pd.to_numeric(loss_2fa["top1_match"], errors="coerce").mean()),
        "top1_avg_diff_per_machine_mean": float(
            pd.to_numeric(topk_2fa["top1_avg_diff_per_machine"], errors="coerce").mean()
        ),
        "top1_avg_diff_per_machine_median": float(
            pd.to_numeric(topk_2fa["top1_avg_diff_per_machine"], errors="coerce").median()
        ),
    }


def _actual_worst_sets_for_date(db_path: Path, target_date: pd.Timestamp) -> dict[str, set[str]]:
    raw = build_base_rows(db_path=db_path, a_weight=0.4, non_a_weight=1.3)
    agg = aggregate_mode(raw, mode="floor_atype4").copy()
    agg["date"] = pd.to_datetime(agg["date"])
    agg["group_key"] = agg["group_key"].astype(str)
    agg["last_digit"] = agg["last_digit"].astype(str)
    agg["total_diff_coins"] = pd.to_numeric(agg["total_diff_coins"], errors="coerce").fillna(0.0)
    day = agg[agg["date"] == pd.Timestamp(target_date)].copy()
    out: dict[str, set[str]] = {}
    for expert, g in day.groupby("group_key", sort=False):
        ranked = g.sort_values(["total_diff_coins", "last_digit"], ascending=[True, True]).reset_index(drop=True)
        out[str(expert)] = set(ranked.head(3)["last_digit"].astype(str).tolist())
    return out


def _evaluate_bottom3_latest_day(
    *,
    bottom3_csv: Path,
    full_csv: Path,
    db_path: Path,
) -> dict[str, Any]:
    btm = pd.read_csv(bottom3_csv, encoding="utf-8-sig")
    full = pd.read_csv(full_csv, encoding="utf-8-sig")
    if btm.empty or full.empty:
        return {"available": False}
    latest_date = pd.to_datetime(full["date"]).max()
    pred_sets: dict[str, set[str]] = {}
    for expert, g in btm.groupby("expert", sort=False):
        pred_sets[str(expert)] = set(g["last_digit"].astype(str).tolist())
    actual_sets = _actual_worst_sets_for_date(db_path=db_path, target_date=latest_date)
    rows: list[dict[str, Any]] = []
    for expert in sorted(set(pred_sets.keys()) | set(actual_sets.keys())):
        pred = pred_sets.get(expert, set())
        actual = actual_sets.get(expert, set())
        inter = pred & actual
        rows.append(
            {
                "expert": expert,
                "pred_bottom3": ",".join(sorted(pred)),
                "actual_worst3": ",".join(sorted(actual)),
                "overlap_count": int(len(inter)),
                "overlap_rate": float(len(inter) / 3.0) if actual else float("nan"),
            }
        )
    df = pd.DataFrame(rows)
    return {
        "available": True,
        "latest_date": str(pd.Timestamp(latest_date).date()),
        "overall_overlap_mean": float(pd.to_numeric(df["overlap_rate"], errors="coerce").mean()),
        "by_expert": df.to_dict(orient="records"),
    }


def _load_worst_eval(report_json: Path) -> dict[str, Any]:
    if not report_json.exists():
        return {"available": False}
    obj = json.loads(report_json.read_text(encoding="utf-8"))
    worst = obj.get("worst_eval", {})
    if not worst:
        return {"available": False}
    return {"available": True, **worst}


def _latest_hall_anomaly(db_path: Path) -> dict[str, Any]:
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT date, avg_diff_per_machine
    FROM daily_hall_summary
    GROUP BY date
    ORDER BY date
    """
    hall = pd.read_sql_query(q, con)
    con.close()
    if hall.empty:
        return {"available": False}
    hall["date"] = pd.to_datetime(hall["date"], format="%Y%m%d", errors="coerce")
    hall["avg_diff_per_machine"] = pd.to_numeric(hall["avg_diff_per_machine"], errors="coerce").fillna(0.0)
    hall = hall.sort_values("date").reset_index(drop=True)
    hall["rolling_median"] = hall["avg_diff_per_machine"].rolling(28, min_periods=7).median()
    hall["rolling_std"] = hall["avg_diff_per_machine"].rolling(28, min_periods=7).std()
    denom = hall["rolling_std"].replace(0.0, np.nan)
    hall["zscore"] = ((hall["avg_diff_per_machine"] - hall["rolling_median"]) / denom).fillna(0.0)
    last = hall.iloc[-1]
    z = float(last["zscore"])
    return {
        "available": True,
        "date": str(pd.Timestamp(last["date"]).date()),
        "zscore": z,
        "is_anomaly": int(abs(z) >= 1.5),
    }


def _make_morning_summary(
    *,
    payload: dict[str, Any],
    anomaly: dict[str, Any],
) -> str:
    target_date = payload.get("target_date", "")
    top3 = pd.DataFrame(payload.get("latest_test_top3_by_expert", []))
    bottom3 = pd.DataFrame(payload.get("latest_test_bottom3_by_expert", []))
    lines: list[str] = [f"【{target_date} 予測サマリー】"]
    lines.append("■ TOP3（座る候補）")
    if top3.empty:
        lines.append("  - データなし")
    else:
        for expert, g in top3.groupby("expert", sort=False):
            g = g.sort_values("rank")
            segs = [f"末尾{str(r['last_digit'])}" for r in g.to_dict(orient="records")]
            lines.append(f"  {expert}: " + " > ".join(segs))
    lines.append("■ BOTTOM3（避け候補）")
    if bottom3.empty:
        lines.append("  - データなし")
    else:
        for expert, g in bottom3.groupby("expert", sort=False):
            g = g.sort_values("rank")
            segs = [f"末尾{str(r['last_digit'])}" for r in g.to_dict(orient="records")]
            lines.append(f"  {expert}: " + ", ".join(segs))
    if anomaly.get("available"):
        lines.append(
            "■ 今日の注意: "
            + (
                f"異常日（zscore={anomaly['zscore']:.2f}）"
                if int(anomaly["is_anomaly"]) == 1
                else f"通常日（zscore={anomaly['zscore']:.2f}）"
            )
        )
    return "\n".join(lines) + "\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Follow-up executor for 10-hour last_digit ops plan.")
    p.add_argument(
        "--nextday-prefix",
        default="ml/last_digit/reports/nextday_kamata7_20260527_tasks123_verify_xgb_ranker_ndcg",
        help="Prefix of nextday output (without extension).",
    )
    p.add_argument(
        "--worst-report-json",
        default="ml/last_digit/exploratory/kamata7_only/target_auto_explore_20260526_103548/report.json",
        help="target_auto_explore report.json path for worst-model comparison.",
    )
    p.add_argument("--db-path", default="", help="DB path override.")
    p.add_argument(
        "--output-dir",
        default="ml/last_digit/exploratory/kamata7_only/ten_hour_plan_20260527",
        help="Output directory for consolidated report files.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db_path) if str(args.db_path).strip() else resolve_db_path()
    prefix = Path(args.nextday_prefix)
    topk_csv = Path(str(prefix) + "_testperiod_topk.csv")
    loss_csv = Path(str(prefix) + "_ceiling_effect/loss_scenarios.csv")
    payload_json = Path(str(prefix) + ".json")
    btm_csv = Path(str(prefix) + "_latest_test_bottom3.csv")
    full_csv = Path(str(prefix) + "_latest_test_full.csv")

    topk = pd.read_csv(topk_csv, encoding="utf-8-sig")
    loss = pd.read_csv(loss_csv, encoding="utf-8-sig")
    payload = json.loads(payload_json.read_text(encoding="utf-8"))

    hour1 = _compute_2fa_metrics(topk, loss)
    hour2_current = _evaluate_bottom3_latest_day(bottom3_csv=btm_csv, full_csv=full_csv, db_path=db_path)
    hour2_worst = _load_worst_eval(Path(args.worst_report_json))
    anomaly = _latest_hall_anomaly(db_path)
    morning_summary = _make_morning_summary(payload=payload, anomaly=anomaly)

    hypothesis_scout = """# Hour5-6: 未探索領域スカウト

## 候補
- クロスエキスパート特徴量: 他expertのrank1/rank2 tail一致率、前日一致フラグ
- 機種名粒度特徴量: machine_name_normalized単位の末尾バイアス履歴（shift(1)厳守）
- イベント日×末尾交互作用: event_group, days_to_next_event_any と last_digit 系の交互作用
- 他ホール共通パターン: 先に同一機種構成ホールだけで小規模検証

## 実装優先度
1. クロスエキスパート（既存CSVだけで追加しやすい）
2. イベント交互作用（既存event特徴を拡張しやすい）
3. 機種名粒度（過学習対策が必要）
4. 他ホール共通（スコープ管理が難しい）
"""
    _write_text(out_dir / "hour3_morning_summary.txt", morning_summary)
    _write_text(out_dir / "hour5_6_hypothesis_scout.md", hypothesis_scout)

    consolidated = {
        "generated_at": datetime.now().isoformat(),
        "source_files": {
            "topk_csv": str(topk_csv),
            "loss_csv": str(loss_csv),
            "payload_json": str(payload_json),
            "bottom3_csv": str(btm_csv),
            "full_csv": str(full_csv),
            "worst_report_json": str(Path(args.worst_report_json)),
            "db_path": str(db_path),
            "nextday_prefix_mtime": _latest_ts(payload_json),
        },
        "hour1_2fa_metrics": hour1,
        "hour2_bottom3_current_latest_day": hour2_current,
        "hour2_worst_model_reference": hour2_worst,
        "latest_anomaly": anomaly,
        "notes": {
            "hour2_scope": "current bottom3はlatest日評価、worstモデルはtestperiod評価の参照。",
            "hour7_8_next_step": "target_auto_exploreを新DBで再実行して比較を更新する。",
        },
    }
    (out_dir / "ten_hour_progress.json").write_text(json.dumps(consolidated, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# 10時間プラン進捗",
        "",
        "## Hour1: 2F_A評価",
        f"- available: {hour1.get('available')}",
        f"- hit@2: {hour1.get('hit_at_2')}",
        f"- rank1_match_rate: {hour1.get('rank1_match_rate')}",
        f"- top1_avg_diff_per_machine_median: {hour1.get('top1_avg_diff_per_machine_median')}",
        "",
        "## Hour2: BOTTOM3評価",
        f"- current_latest_day_overlap_mean: {hour2_current.get('overall_overlap_mean')}",
        f"- worst_model_ref_available: {hour2_worst.get('available')}",
        f"- worst1_hit_rate(ref): {hour2_worst.get('worst1_hit_rate')}",
        "",
        "## Hour3-4: 朝サマリー",
        f"- file: `{out_dir / 'hour3_morning_summary.txt'}`",
        "",
        "## Hour5-6: 探索候補",
        f"- file: `{out_dir / 'hour5_6_hypothesis_scout.md'}`",
        "",
        "## Hour7-8: 次アクション",
        "- `python -m ml.last_digit.target_auto_explore --db-path <最新DB> --output-root <新規dir>` を実行して再評価",
    ]
    _write_text(out_dir / "ten_hour_progress.md", "\n".join(md_lines) + "\n")
    print(f"saved: {out_dir / 'ten_hour_progress.json'}")
    print(f"saved: {out_dir / 'ten_hour_progress.md'}")
    print(f"saved: {out_dir / 'hour3_morning_summary.txt'}")
    print(f"saved: {out_dir / 'hour5_6_hypothesis_scout.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
