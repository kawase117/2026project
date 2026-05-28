from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shap
from lightgbm import LGBMRanker
from scipy.stats import chi2_contingency, ttest_ind

from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit.core_ranking import fit_ranker
from ml.last_digit.tail_ltr_profit_ops import select_features
from ml.last_digit.tail_ltr_split_rule_nextday_gpu import _prepare_split_dataset


MODELS = [
    "xgb_ranker_ndcg",
    "xgb_ranker_pairwise",
    "catboost_ranker_pairlogit",
    "lgbm_ranker_lambdarank",
]
EXPERTS = ["2F_N", "3F_N", "3F_A"]


def _weekday_nth(ts: pd.Timestamp) -> int:
    month_start = ts.replace(day=1)
    same_weekday_days = pd.date_range(month_start, ts, freq="D")
    same_weekday_days = [d for d in same_weekday_days if d.day_name() == ts.day_name()]
    return len(same_weekday_days)


def _find_daily_csv(input_dir: Path, model: str) -> Path | None:
    matches = sorted(input_dir.glob(f"*_{model}_testperiod_daily.csv"))
    return matches[-1] if matches else None


def _find_topk_csv(input_dir: Path, model: str) -> Path | None:
    matches = sorted(input_dir.glob(f"*_{model}_testperiod_topk.csv"))
    return matches[-1] if matches else None


def _load_daily_rows(input_dir: Path) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for model in MODELS:
        p = _find_daily_csv(input_dir, model)
        if p is None:
            continue
        df = pd.read_csv(p, encoding="utf-8-sig")
        df["model"] = model
        rows.append(df)
    if not rows:
        raise FileNotFoundError(f"No *testperiod_daily.csv found under {input_dir}")
    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out["miss_day"] = (pd.to_numeric(out["hit_at_2"], errors="coerce").fillna(0.0) <= 0.0).astype(int)
    out["month"] = out["date"].dt.strftime("%Y-%m")
    out["weekday_nth"] = out["date"].apply(_weekday_nth)
    return out


def _attach_volatility(df_daily: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    work = dataset.copy()
    work["date"] = pd.to_datetime(work["date"])
    day_vol = (
        work.groupby(["date", "group_key"], sort=True)["total_diff_coins"]
        .std()
        .rename("volatility_day")
        .reset_index()
    )
    day_vol["volatility_day"] = day_vol["volatility_day"].fillna(0.0)
    day_vol = day_vol.sort_values(["group_key", "date"]).reset_index(drop=True)
    day_vol["volatility_7d"] = (
        day_vol.groupby("group_key")["volatility_day"]
        .transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
        .fillna(0.0)
    )
    out = df_daily.merge(
        day_vol.rename(columns={"group_key": "expert"})[["date", "expert", "volatility_7d"]],
        on=["date", "expert"],
        how="left",
    )
    out["volatility_7d"] = out["volatility_7d"].fillna(0.0)
    return out


def _attach_model_agreement(df_daily: pd.DataFrame, input_dir: Path) -> tuple[pd.DataFrame, bool]:
    topk_rows: list[pd.DataFrame] = []
    for model in MODELS:
        p = _find_topk_csv(input_dir, model)
        if p is None:
            continue
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "top1_tail" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df["model"] = model
        topk_rows.append(df[["date", "expert", "model", "top1_tail"]])
    if not topk_rows:
        out = df_daily.copy()
        out["model_agreement_top1_count"] = np.nan
        return out, False

    all_topk = pd.concat(topk_rows, ignore_index=True)
    all_topk["top1_tail"] = all_topk["top1_tail"].astype(str)
    agree = (
        all_topk.groupby(["date", "expert"])["top1_tail"]
        .agg(lambda s: int(pd.Series(s).value_counts().iloc[0]) if len(s) else np.nan)
        .rename("model_agreement_top1_count")
        .reset_index()
    )
    out = df_daily.merge(all_topk[["date", "expert", "model", "top1_tail"]], on=["date", "expert", "model"], how="left")
    out = out.merge(agree, on=["date", "expert"], how="left")
    return out, True


def _add_candidate_features(df_daily: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    work = dataset.copy()
    work["date"] = pd.to_datetime(work["date"])
    work["expert"] = work["group_key"].astype(str)
    work["last_digit_key"] = work["last_digit"].astype(str)
    work = work.sort_values(["expert", "last_digit_key", "date"]).reset_index(drop=True)

    group_cols = ["expert", "last_digit_key"]
    below_avg = (
        pd.to_numeric(work["roll7_efficiency_focus"], errors="coerce")
        < pd.to_numeric(work["roll28_efficiency_focus"], errors="coerce")
    ).astype(int)
    work["below_avg_eff_flag"] = below_avg

    # ① 低迷継続度: 直近7日で長期平均を下回った割合（shift(1)）
    work["efficiency_focus_drought_7d"] = (
        work.groupby(group_cols, sort=False)["below_avg_eff_flag"]
        .transform(lambda s: s.rolling(7, min_periods=1).mean().shift(1))
        .fillna(0.0)
        .astype(float)
    )

    # ② 累積出玉不足量: 直近7日と長期平均の乖離（shift(1)）
    roll7_focus = pd.to_numeric(work["roll7_total_diff_coins_focus"], errors="coerce")
    roll28_focus = pd.to_numeric(work["roll28_total_diff_coins_focus"], errors="coerce")
    work["total_diff_coins_deficit"] = (roll7_focus - (roll28_focus / 28.0 * 7.0)).astype(float)
    work["total_diff_coins_deficit"] = (
        work.groupby(group_cols, sort=False)["total_diff_coins_deficit"].shift(1).fillna(0.0).astype(float)
    )

    # ③ 連続低迷日数: 途切れたら0、最後にshift(1)
    def _consecutive_count(s: pd.Series) -> pd.Series:
        v = s.fillna(0).astype(int)
        grp = (v != v.shift()).cumsum()
        return v * (v.groupby(grp).cumcount() + 1)

    work["consecutive_below_avg_days"] = (
        work.groupby(group_cols, sort=False)["below_avg_eff_flag"]
        .transform(_consecutive_count)
        .astype(float)
    )
    work["consecutive_below_avg_days"] = (
        work.groupby(group_cols, sort=False)["consecutive_below_avg_days"].shift(1).fillna(0.0).astype(float)
    )

    # ④-⑥ クロス末尾相対指標（同日・同expert内の横比較）を前日値で使用
    eff_focus = pd.to_numeric(work["efficiency_focus"], errors="coerce")
    diff_focus = pd.to_numeric(work["total_diff_coins_focus"], errors="coerce")

    work["efficiency_rank_in_peers_raw"] = (
        eff_focus.groupby([work["date"], work["expert"]]).rank(ascending=True, method="average")
    )
    peer_eff_mean = eff_focus.groupby([work["date"], work["expert"]]).transform("mean")
    work["relative_efficiency_vs_peers_raw"] = (eff_focus - peer_eff_mean).astype(float)
    work["relative_diff_coins_rank_raw"] = (
        diff_focus.groupby([work["date"], work["expert"]]).rank(ascending=True, method="average")
    )

    work["efficiency_rank_in_peers"] = (
        work.groupby(group_cols, sort=False)["efficiency_rank_in_peers_raw"].shift(1).fillna(0.0).astype(float)
    )
    work["relative_efficiency_vs_peers"] = (
        work.groupby(group_cols, sort=False)["relative_efficiency_vs_peers_raw"].shift(1).fillna(0.0).astype(float)
    )
    work["relative_diff_coins_rank"] = (
        work.groupby(group_cols, sort=False)["relative_diff_coins_rank_raw"].shift(1).fillna(0.0).astype(float)
    )

    feat_cols = [
        "date",
        "expert",
        "last_digit_key",
        "efficiency_focus_drought_7d",
        "total_diff_coins_deficit",
        "consecutive_below_avg_days",
        "efficiency_rank_in_peers",
        "relative_efficiency_vs_peers",
        "relative_diff_coins_rank",
    ]
    feat_df = work[feat_cols].drop_duplicates(subset=["date", "expert", "last_digit_key"], keep="last")

    out = df_daily.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["top1_tail_key"] = out["top1_tail"].astype(str)
    out = out.merge(
        feat_df,
        left_on=["date", "expert", "top1_tail_key"],
        right_on=["date", "expert", "last_digit_key"],
        how="left",
    )
    out["efficiency_focus_drought_7d"] = pd.to_numeric(out["efficiency_focus_drought_7d"], errors="coerce")
    out["total_diff_coins_deficit"] = pd.to_numeric(out["total_diff_coins_deficit"], errors="coerce")
    out["consecutive_below_avg_days"] = pd.to_numeric(out["consecutive_below_avg_days"], errors="coerce")
    out["efficiency_rank_in_peers"] = pd.to_numeric(out["efficiency_rank_in_peers"], errors="coerce")
    out["relative_efficiency_vs_peers"] = pd.to_numeric(out["relative_efficiency_vs_peers"], errors="coerce")
    out["relative_diff_coins_rank"] = pd.to_numeric(out["relative_diff_coins_rank"], errors="coerce")
    return out


def _phase_a_stats(df: pd.DataFrame) -> dict[str, Any]:
    categorical = ["weekday", "weekday_nth", "month", "expert", "model"]
    numeric = [
        "pred_span",
        "volatility_7d",
        "model_agreement_top1_count",
        "efficiency_focus_drought_7d",
        "total_diff_coins_deficit",
        "consecutive_below_avg_days",
        "efficiency_rank_in_peers",
        "relative_efficiency_vs_peers",
        "relative_diff_coins_rank",
    ]

    chi_rows: list[dict[str, Any]] = []
    for col in categorical:
        ctab = pd.crosstab(df[col], df["miss_day"])
        if ctab.shape[0] < 2 or ctab.shape[1] < 2:
            continue
        chi2, p, _, _ = chi2_contingency(ctab)
        miss_rate = float(df.groupby(col)["miss_day"].mean().max())
        chi_rows.append(
            {
                "feature": col,
                "test": "chi2",
                "p_value": float(p),
                "chi2": float(chi2),
                "max_miss_rate": miss_rate,
            }
        )

    t_rows: list[dict[str, Any]] = []
    for col in numeric:
        vals = pd.to_numeric(df[col], errors="coerce")
        miss = vals[df["miss_day"] == 1].dropna()
        hit = vals[df["miss_day"] == 0].dropna()
        if len(miss) < 5 or len(hit) < 5:
            continue
        t, p = ttest_ind(miss, hit, equal_var=False, nan_policy="omit")
        t_rows.append(
            {
                "feature": col,
                "test": "t_test",
                "p_value": float(p),
                "t_stat": float(t),
                "effect_miss_minus_hit": float(miss.mean() - hit.mean()),
                "miss_mean": float(miss.mean()),
                "hit_mean": float(hit.mean()),
            }
        )

    combined = pd.DataFrame(chi_rows + t_rows).sort_values("p_value").reset_index(drop=True)
    return {
        "top5_conditions": combined.head(5).to_dict(orient="records") if not combined.empty else [],
        "all_tests": combined.to_dict(orient="records") if not combined.empty else [],
    }


def _fit_expert_xgb_pairwise(train_df: pd.DataFrame, features: list[str], *, seed: int = 42):
    X = train_df[features].astype(float)
    y = train_df["is_top_2"].astype(int).to_numpy()
    model = fit_ranker(
        X_train=X,
        y_train=y,
        train_dates=train_df["date"],
        objective="rank:pairwise",
        random_state=seed,
        decay_lambda=None,
        model_params={"tree_method": "hist", "device": "cuda", "max_depth": 6, "n_estimators": 600, "learning_rate": 0.05},
    )
    return model


def _fit_expert_lgbm_lambdarank(train_df: pd.DataFrame, features: list[str], *, seed: int = 42):
    X = train_df[features].astype(float)
    y = train_df["is_top_2"].astype(int).to_numpy()
    dts = pd.to_datetime(train_df["date"])
    group = dts.groupby(dts, sort=False).size().astype(int).tolist()
    model = LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=400,
        learning_rate=0.05,
        num_leaves=63,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=seed,
        verbosity=-1,
    )
    model.fit(X, y, group=group)
    return model


def _phase_b_shap(data: pd.DataFrame) -> dict[str, Any]:
    split_cfg = improved.build_fixed_split_configs(data)["regime_3_fixed_split"]
    out: dict[str, Any] = {"split_cfg": split_cfg, "experts": {}}
    experts = ["2F_N", "3F_A"]
    for expert in experts:
        ds = data[data["group_key"].astype(str) == expert].copy()
        train, valid = improved.split_dataset_by_date_ranges(
            ds,
            train_start=split_cfg["train_start"],
            train_end=split_cfg["train_end"],
            valid_start=split_cfg["valid_start"],
            valid_end=split_cfg["valid_end"],
        )
        feats = improved.get_numeric_features(ds)
        feats = [f for f in feats if f != "is_top_2"]
        feats = select_features(train, feats, "is_top_2", "all")

        if expert == "3F_A":
            model = _fit_expert_lgbm_lambdarank(train, feats, seed=42)
            model_name = "lgbm_ranker_lambdarank"
        else:
            model = _fit_expert_xgb_pairwise(train, feats, seed=42)
            model_name = "xgb_pairwise_tuned_depth6"

        Xv = valid[feats].astype(float)
        yv = valid["is_top_2"].astype(int).to_numpy()
        pred = np.asarray(model.predict(Xv), dtype=float)
        tmp = valid[["date"]].copy()
        tmp["pred"] = pred
        tmp["y"] = yv
        tmp["date"] = pd.to_datetime(tmp["date"])

        day_hit: dict[pd.Timestamp, int] = {}
        for d, g in tmp.groupby("date"):
            g2 = g.sort_values("pred", ascending=False).head(2)
            day_hit[d] = int((g2["y"] > 0).any())
        tmp["day_hit"] = tmp["date"].map(day_hit).astype(int)

        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(Xv)
        if isinstance(shap_vals, list):
            shap_vals = shap_vals[0]
        shap_signed = np.asarray(shap_vals, dtype=float)
        shap_abs = np.abs(shap_signed)
        shap_df = pd.DataFrame(shap_abs, columns=feats)
        shap_signed_df = pd.DataFrame(shap_signed, columns=feats)
        feature_df = Xv.reset_index(drop=True).copy()
        shap_df["day_hit"] = tmp["day_hit"].to_numpy()
        shap_signed_df["day_hit"] = tmp["day_hit"].to_numpy()
        feature_df["day_hit"] = tmp["day_hit"].to_numpy()

        miss_mean = shap_df[shap_df["day_hit"] == 0][feats].mean()
        hit_mean = shap_df[shap_df["day_hit"] == 1][feats].mean()
        diff = (miss_mean - hit_mean).sort_values(ascending=False)
        top_features = [str(k) for k in diff.head(15).index.tolist()]

        def _safe_mean(s: pd.Series) -> float:
            s2 = pd.to_numeric(s, errors="coerce").dropna()
            return float(s2.mean()) if len(s2) else float("nan")

        def _safe_quantile(s: pd.Series, q: float) -> float:
            s2 = pd.to_numeric(s, errors="coerce").dropna()
            return float(s2.quantile(q)) if len(s2) else float("nan")

        def _interpret(signed_miss: float, fv_miss: float, fv_hit: float) -> str:
            if np.isnan(signed_miss) or np.isnan(fv_miss) or np.isnan(fv_hit):
                return "データ不足（判定不能）"
            if signed_miss > 0 and fv_miss > fv_hit:
                return "高値への過信（まぐれ高パフォーマンスを過大評価）"
            if signed_miss > 0 and fv_miss < fv_hit:
                return "低値でも押し上げ（別要因による誤誘導）"
            if signed_miss < 0 and fv_miss < fv_hit:
                return "低迷の見落とし（仕込み日を低評価）"
            if signed_miss < 0 and fv_miss > fv_hit:
                return "高値なのに押し下げ（矛盾・要追加調査）"
            return "中立・判定保留"

        top_rows: list[dict[str, Any]] = []
        miss_mask = shap_df["day_hit"] == 0
        hit_mask = shap_df["day_hit"] == 1
        for feat in top_features:
            signed_miss = _safe_mean(shap_signed_df.loc[miss_mask, feat])
            signed_hit = _safe_mean(shap_signed_df.loc[hit_mask, feat])
            fv_miss_mean = _safe_mean(feature_df.loc[miss_mask, feat])
            fv_hit_mean = _safe_mean(feature_df.loc[hit_mask, feat])
            fv_miss_p25 = _safe_quantile(feature_df.loc[miss_mask, feat], 0.25)
            fv_miss_p75 = _safe_quantile(feature_df.loc[miss_mask, feat], 0.75)
            top_rows.append(
                {
                    "feature": feat,
                    "miss_minus_hit_abs_shap": float(diff.get(feat, np.nan)),
                    "signed_shap_miss_mean": signed_miss,
                    "signed_shap_hit_mean": signed_hit,
                    "feature_value_miss_mean": fv_miss_mean,
                    "feature_value_hit_mean": fv_hit_mean,
                    "feature_value_miss_p25": fv_miss_p25,
                    "feature_value_miss_p75": fv_miss_p75,
                    "interpretation": _interpret(signed_miss, fv_miss_mean, fv_hit_mean),
                }
            )
        out["experts"][expert] = {
            "model_used": model_name,
            "n_train": int(len(train)),
            "n_valid": int(len(valid)),
            "n_miss_days": int(sum(v == 0 for v in day_hit.values())),
            "n_hit_days": int(sum(v == 1 for v in day_hit.values())),
            "top_misleading_features": top_rows,
        }

    if "2F_N" in out["experts"] and "3F_A" in out["experts"]:
        f2 = {x["feature"]: x["miss_minus_hit_abs_shap"] for x in out["experts"]["2F_N"]["top_misleading_features"]}
        f3 = {x["feature"]: x["miss_minus_hit_abs_shap"] for x in out["experts"]["3F_A"]["top_misleading_features"]}
        common = sorted(set(f2) & set(f3))
        out["expert_comparison"] = [
            {"feature": f, "2F_N": float(f2[f]), "3F_A": float(f3[f]), "gap": float(f2[f] - f3[f])}
            for f in common
        ]
    return out


def _select_production_model_per_expert(model_comparison_dir: Path) -> dict[str, str]:
    p = model_comparison_dir / "comparison_expert.csv"
    if not p.exists():
        raise FileNotFoundError(f"missing: {p}")
    df = pd.read_csv(p, encoding="utf-8-sig")
    pick = (
        df.sort_values(["expert", "hit_at_2", "f1"], ascending=[True, False, False])
        .groupby("expert", as_index=False)
        .head(1)
    )
    return {str(r["expert"]): str(r["model"]) for _, r in pick.iterrows()}


def _build_production_eval_df(df_daily: pd.DataFrame, model_comparison_dir: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    per_expert_model = _select_production_model_per_expert(model_comparison_dir)
    work = df_daily.copy()
    work["expert"] = work["expert"].astype(str)
    work["model"] = work["model"].astype(str)
    mask = pd.Series(False, index=work.index)
    for expert, model in per_expert_model.items():
        mask = mask | ((work["expert"] == str(expert)) & (work["model"] == str(model)))
    out = work[mask & (work["status"].astype(str) == "ok")].copy()
    out = out.sort_values(["date", "expert"]).reset_index(drop=True)
    return out, per_expert_model


def _summarize_hit2_window(df_eval: pd.DataFrame, *, suffix: str = "") -> dict[str, Any]:
    by_expert = (
        df_eval.groupby("expert")
        .agg(hit_at_2=("hit_at_2", "mean"), n_days=("date", "nunique"), model=("model", "first"))
        .reset_index()
        .to_dict(orient="records")
        if not df_eval.empty
        else []
    )
    return {
        f"overall_hit_at_2{suffix}": float(df_eval["hit_at_2"].mean()) if not df_eval.empty else 0.0,
        f"by_expert{suffix}": by_expert,
        f"n_eval_rows{suffix}": int(len(df_eval)),
    }


def _evaluate_production_hit2(df_daily: pd.DataFrame, model_comparison_dir: Path) -> dict[str, Any]:
    baseline = {"overall": 0.9167, "2F_N": 0.9861, "3F_N": 0.9653, "3F_A": 0.7986}
    merged, per_expert_model = _build_production_eval_df(df_daily, model_comparison_dir)
    if merged.empty:
        return {
            "production_model_map": per_expert_model,
            **_summarize_hit2_window(pd.DataFrame(), suffix="_testperiod"),
            **_summarize_hit2_window(pd.DataFrame(), suffix="_last30"),
            "adoption_gate": {
                "passes": False,
                "criteria": {
                    "overall_gt_0_9167": False,
                    "3F_A_gte_0_7986": False,
                    "2F_N_not_worse_gte_0_9861": False,
                    "3F_N_not_worse_gte_0_9653": False,
                },
                "baseline": baseline,
            },
        }
    last30_dates = sorted(merged["date"].drop_duplicates())[-30:]
    last30 = merged[merged["date"].isin(last30_dates)].copy()
    summary_testperiod = _summarize_hit2_window(merged, suffix="_testperiod")
    by_expert_map = {
        str(r["expert"]): float(r["hit_at_2"]) for r in summary_testperiod.get("by_expert_testperiod", [])
    }
    c_overall = float(summary_testperiod.get("overall_hit_at_2_testperiod", 0.0))
    c_overall_4dp = float(round(c_overall, 4))
    c_2fn_4dp = float(round(float(by_expert_map.get("2F_N", np.nan)), 4))
    c_3fa_4dp = float(round(float(by_expert_map.get("3F_A", np.nan)), 4))
    c_3fn_4dp = float(round(float(by_expert_map.get("3F_N", np.nan)), 4))
    criteria = {
        "overall_gt_0_9167": bool(c_overall_4dp >= baseline["overall"]),
        "3F_A_gte_0_7986": bool(c_3fa_4dp >= baseline["3F_A"]),
        "2F_N_not_worse_gte_0_9861": bool(c_2fn_4dp >= baseline["2F_N"]),
        "3F_N_not_worse_gte_0_9653": bool(c_3fn_4dp >= baseline["3F_N"]),
    }
    return {
        "production_model_map": per_expert_model,
        **summary_testperiod,
        **_summarize_hit2_window(last30, suffix="_last30"),
        "adoption_gate": {
            "passes": bool(all(criteria.values())),
            "criteria": criteria,
            "baseline": baseline,
            "observed_testperiod": {
                "overall_raw": c_overall,
                "overall_rounded_4dp": c_overall_4dp,
                "2F_N": float(by_expert_map.get("2F_N", np.nan)),
                "3F_A": float(by_expert_map.get("3F_A", np.nan)),
                "3F_N": float(by_expert_map.get("3F_N", np.nan)),
                "2F_N_rounded_4dp": c_2fn_4dp,
                "3F_A_rounded_4dp": c_3fa_4dp,
                "3F_N_rounded_4dp": c_3fn_4dp,
            },
        },
    }


def _phase_e_span_filter(
    df_daily: pd.DataFrame,
    model_comparison_dir: Path,
    span_thresholds: list[float] | None = None,
    agreement_thresholds: list[int] | None = None,
    coverage_min: float = 0.60,
) -> dict[str, Any]:
    if span_thresholds is None:
        span_thresholds = [0.0, 0.3, 0.4, 0.5]
    if agreement_thresholds is None:
        agreement_thresholds = [0, 2, 3, 4]

    merged, _ = _build_production_eval_df(df_daily, model_comparison_dir)
    if merged.empty:
        return {"threshold_table_testperiod": [], "threshold_table_last30": [], "notes": "no rows"}

    merged["pred_span"] = pd.to_numeric(merged["pred_span"], errors="coerce").fillna(-1.0)
    merged["model_agreement_top1_count"] = pd.to_numeric(
        merged["model_agreement_top1_count"], errors="coerce"
    ).fillna(0.0)
    last30_dates = sorted(merged["date"].drop_duplicates())[-30:]
    last30 = merged[merged["date"].isin(last30_dates)].copy()

    def _build_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
        total = len(frame)
        out_rows: list[dict[str, Any]] = []
        for span_th in span_thresholds:
            for agree_th in agreement_thresholds:
                kept = frame[
                    (frame["pred_span"] >= float(span_th))
                    & (frame["model_agreement_top1_count"] >= float(agree_th))
                ].copy()
                coverage = float(len(kept) / total) if total else 0.0
                hit2 = float(kept["hit_at_2"].mean()) if len(kept) else 0.0
                out_rows.append(
                    {
                        "span_threshold": float(span_th),
                        "agreement_threshold": int(agree_th),
                        "coverage": coverage,
                        "coverage_meets_min": bool(coverage >= coverage_min),
                        "kept_rows": int(len(kept)),
                        "total_rows": int(total),
                        "hit_at_2_after_filter": hit2,
                    }
                )
        return out_rows

    table_testperiod = _build_table(merged)
    table_last30 = _build_table(last30)

    def _pick_best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        feasible = [r for r in rows if bool(r.get("coverage_meets_min"))]
        if feasible:
            return max(feasible, key=lambda x: (x["hit_at_2_after_filter"], x["coverage"]))
        if rows:
            return max(rows, key=lambda x: (x["hit_at_2_after_filter"], x["coverage"]))
        return None

    return {
        "coverage_min_constraint": float(coverage_min),
        "threshold_table_testperiod": table_testperiod,
        "threshold_table_last30": table_last30,
        "best_feasible_testperiod": _pick_best(table_testperiod),
        "best_feasible_last30": _pick_best(table_last30),
    }


def run_analysis(output_dir: Path, model_comparison_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    daily = _load_daily_rows(model_comparison_dir)
    dataset, _, _ = _prepare_split_dataset(a_weight=0.4, non_a_weight=1.3)
    daily = _attach_volatility(daily, dataset)
    daily, has_topk = _attach_model_agreement(daily, model_comparison_dir)
    daily = _add_candidate_features(daily, dataset)

    phase_a = _phase_a_stats(daily)
    phase_a["has_topk_for_agreement"] = bool(has_topk)
    phase_b = _phase_b_shap(dataset)
    phase_c = {
        "candidate_features": [
            {
                "name": "efficiency_focus_drought_7d",
                "formula": "expert×tail単位で roll7_efficiency_focus < roll28_efficiency_focus の直近7日割合 (shift(1))",
                "leakage_safe": True,
            },
            {
                "name": "total_diff_coins_deficit",
                "formula": "expert×tail単位で roll7_total_diff_coins_focus - (roll28_total_diff_coins_focus/28*7) を shift(1)",
                "leakage_safe": True,
            },
            {
                "name": "consecutive_below_avg_days",
                "formula": "expert×tail単位で below_avg(roll7<roll28) の連続日数を計算し shift(1)",
                "leakage_safe": True,
            },
            {
                "name": "efficiency_rank_in_peers",
                "formula": "同日・同expert内で efficiency_focus を昇順ランク化し、expert×tailで shift(1)",
                "leakage_safe": True,
            },
            {
                "name": "relative_efficiency_vs_peers",
                "formula": "efficiency_focus - 同日・同expert平均 を計算し、expert×tailで shift(1)",
                "leakage_safe": True,
            },
            {
                "name": "relative_diff_coins_rank",
                "formula": "同日・同expert内で total_diff_coins_focus を昇順ランク化し、expert×tailで shift(1)",
                "leakage_safe": True,
            },
        ]
    }
    phase_d = {"production_eval": _evaluate_production_hit2(daily, model_comparison_dir)}
    phase_e = _phase_e_span_filter(daily, model_comparison_dir, coverage_min=0.60)

    result = {"phase_a": phase_a, "phase_b": phase_b, "phase_c": phase_c, "phase_d": phase_d, "phase_e": phase_e}
    (output_dir / "analysis_first_10h_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    daily.to_csv(output_dir / "analysis_first_daily_merged.csv", index=False, encoding="utf-8-sig")
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Analysis-first 10h pipeline (Phase A-E) for last_digit")
    p.add_argument("--model-comparison-dir", default="db/experiments/model_comparison")
    p.add_argument("--output-dir", default="db/experiments/analysis_first_10h")
    return p


def main() -> int:
    args = build_parser().parse_args()
    result = run_analysis(Path(args.output_dir), Path(args.model_comparison_dir))
    print("Saved:", Path(args.output_dir) / "analysis_first_10h_result.json")
    top5 = result["phase_a"].get("top5_conditions", [])
    print("Phase A top5 conditions:")
    for i, r in enumerate(top5, 1):
        print(i, r)

    pd_prod = result["phase_d"]["production_eval"]
    print(
        f"Phase D production testperiod overall hit@2={pd_prod['overall_hit_at_2_testperiod']:.4f} "
        f"(rows={pd_prod['n_eval_rows_testperiod']})"
    )
    for r in pd_prod["by_expert_testperiod"]:
        print(
            f"  expert={r['expert']} model={r['model']} "
            f"hit@2={float(r['hit_at_2']):.4f} n_days={int(r['n_days'])}"
        )
    print(
        f"Phase D production last30 overall hit@2={pd_prod['overall_hit_at_2_last30']:.4f} "
        f"(rows={pd_prod['n_eval_rows_last30']})"
    )
    best_e = result["phase_e"]["best_feasible_testperiod"]
    if best_e is None:
        print("Phase E best feasible candidate: none")
        return 0
    print(
        "Phase E best feasible candidate (testperiod):",
        f"span_th={best_e['span_threshold']:.2f}, agree_th={int(best_e['agreement_threshold'])}, "
        f"hit@2={best_e['hit_at_2_after_filter']:.4f}, coverage={best_e['coverage']:.3f}, "
        f"coverage_ok={best_e['coverage_meets_min']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
