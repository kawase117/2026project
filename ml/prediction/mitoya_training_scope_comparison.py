"""
学習データスコープ比較実験
全期間 / x_dayのみ / 7のつく日のみ / DD=7のみ
各スコープ × sample_weight有無 の組み合わせを評価
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from scipy.stats import spearmanr
from sklearn.metrics import precision_score

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "db" / "みとや大森町店.db"
TOP_PERCENTILE = 0.25
VALIDATION_DAYS = 30

CATBOOST_PARAMS = {
    "iterations": 500,
    "learning_rate": 0.05,
    "depth": 6,
    "loss_function": "RMSE",
    "task_type": "GPU",
    "devices": "0",
    "random_seed": 42,
    "verbose": 0,
    "early_stopping_rounds": 50,
}


def print_section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ─────────────────────────────────────────────
# 1. データロード & 特徴量生成
# ─────────────────────────────────────────────
print_section("1. データロード & 特徴量生成")

conn = sqlite3.connect(DB_PATH)
df_raw = pd.read_sql("SELECT date, machine_number, machine_name, last_digit, games_normalized, diff_coins_normalized FROM machine_detailed_results ORDER BY date, machine_number", conn)
df_layout = pd.read_sql("SELECT machine_number, x, y, section, rank_from_min, rank_from_max, rank_from_aisle, is_reversed_section FROM machine_layout", conn)
df_master = pd.read_sql("SELECT machine_name_normalized, jug_flag, hana_flag, oki_flag, bt_flag FROM machine_master", conn)
conn.close()

df = df_raw.copy()
df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
df["dd"] = df["date_dt"].dt.day
df["weekday_num"] = df["date_dt"].dt.dayofweek
df["month"] = df["date_dt"].dt.month
df["week_of_year"] = df["date_dt"].dt.isocalendar().week.astype(int)
df["is_sunday"] = (df["weekday_num"] == 6).astype(int)
df["is_weekend"] = (df["weekday_num"] >= 5).astype(int)
df["is_dd7"] = (df["dd"] == 7).astype(int)
df["dd_mod5"] = df["dd"] % 5
df["dd_mod10"] = df["dd"] % 10
df["is_xday"] = (df["dd"] % 10).isin([4, 7]).astype(int)
df["is_7day"] = df["dd"].isin([7, 17, 27]).astype(int)
df["is_new_manager"] = (df["date_dt"] >= pd.Timestamp("2026-05-01")).astype(int)
df["last_digit_num"] = pd.to_numeric(df["last_digit"], errors="coerce").fillna(-1).astype(int)

df = df.merge(df_layout, on="machine_number", how="left")
df = df.merge(df_master.rename(columns={"machine_name_normalized": "machine_name"}), on="machine_name", how="left")
for col in ["jug_flag", "hana_flag", "oki_flag", "bt_flag"]:
    df[col] = df[col].fillna(0).astype(int)

def get_machine_type(row):
    if row["jug_flag"]: return "jug"
    if row["hana_flag"]: return "hana"
    if row["oki_flag"]: return "oki"
    if row["bt_flag"]: return "bt"
    return "other"
df["machine_type"] = df.apply(get_machine_type, axis=1)

df["is_corner"] = (df["rank_from_aisle"] == 1).astype(int)
sec_max = df.groupby("section")["rank_from_aisle"].transform("max")
df["is_far_corner"] = (df["rank_from_aisle"] == sec_max).astype(int)
df["is_near_corner"] = (df["rank_from_aisle"] <= 2).astype(int)
df["position_ratio"] = df["rank_from_min"] / df["rank_from_max"].replace(0, 1)
df["section_digit_key"] = df["section"].astype(str) + "_d" + df["last_digit_num"].astype(str)

print("  移動平均計算中...")
df = df.sort_values(["machine_name", "date_dt"])
df["machine_roll7_diff"] = df.groupby("machine_name")["diff_coins_normalized"].transform(lambda x: x.shift(1).rolling(7, min_periods=1).mean())
df["machine_roll30_diff"] = df.groupby("machine_name")["diff_coins_normalized"].transform(lambda x: x.shift(1).rolling(30, min_periods=5).mean())
df = df.sort_values(["machine_number", "date_dt"])
df["seat_roll7_diff"] = df.groupby("machine_number")["diff_coins_normalized"].transform(lambda x: x.shift(1).rolling(7, min_periods=1).mean())
df["seat_roll30_diff"] = df.groupby("machine_number")["diff_coins_normalized"].transform(lambda x: x.shift(1).rolling(30, min_periods=5).mean())
df = df.sort_values(["machine_name", "weekday_num", "date_dt"])
df["model_weekday_roll"] = df.groupby(["machine_name", "weekday_num"])["diff_coins_normalized"].transform(lambda x: x.shift(1).expanding(min_periods=1).mean())
df = df.sort_values(["machine_number", "dd", "date_dt"])
df["seat_dd_roll"] = df.groupby(["machine_number", "dd"])["diff_coins_normalized"].transform(lambda x: x.shift(1).expanding(min_periods=1).mean())

df = df.sort_values("date_dt").reset_index(drop=True)

df["top25_flag"] = 0
for d, grp in df.groupby("date"):
    thr = grp["diff_coins_normalized"].quantile(1 - TOP_PERCENTILE)
    df.loc[grp.index, "top25_flag"] = (grp["diff_coins_normalized"] >= thr).astype(int)

NUMERIC_FEATURES = [
    "dd", "weekday_num", "month", "week_of_year",
    "is_sunday", "is_weekend", "is_dd7", "dd_mod5", "dd_mod10",
    "is_xday", "is_7day", "is_new_manager",
    "last_digit_num",
    "x", "y", "rank_from_min", "rank_from_max", "rank_from_aisle",
    "is_corner", "is_far_corner", "is_near_corner", "is_reversed_section", "position_ratio",
    "jug_flag", "hana_flag", "oki_flag", "bt_flag",
    "machine_roll7_diff", "machine_roll30_diff",
    "seat_roll7_diff", "seat_roll30_diff",
    "model_weekday_roll", "seat_dd_roll",
    "games_normalized",
]
CAT_FEATURES = ["machine_name", "machine_type", "section", "section_digit_key"]
ALL_FEATURES = NUMERIC_FEATURES + CAT_FEATURES
cat_indices = [ALL_FEATURES.index(c) for c in CAT_FEATURES]

for col in NUMERIC_FEATURES:
    if col in df.columns:
        df[col] = df[col].fillna(0)
for col in CAT_FEATURES:
    if col in df.columns:
        df[col] = df[col].fillna("unknown")

df["sample_weight"] = df["is_new_manager"].map({1: 3.0, 0: 1.0})

print(f"  全データ: {len(df):,}行 / {df['date'].nunique()}日")

# スコープ定義
dd_mod = df["dd"] % 10
SCOPES = {
    "全期間":        df,
    "x_dayのみ":     df[dd_mod.isin([4, 7])].copy(),
    "7のつく日のみ": df[df["dd"].isin([7, 17, 27])].copy(),
    "DD=7のみ":      df[df["dd"] == 7].copy(),
}
for name, sub in SCOPES.items():
    print(f"  [{name}] {sub['date'].nunique()}日 / {len(sub):,}台")


# ─────────────────────────────────────────────
# 2. 評価関数
# ─────────────────────────────────────────────
def evaluate(scope_df, use_weight, label):
    all_dates = sorted(scope_df["date"].unique())
    n = len(all_dates)
    min_train = 30
    actual_val = min(VALIDATION_DAYS, n - min_train)
    if actual_val <= 0:
        return {"label": label, "train_days": n, "val_days": 0,
                "spearman": float("nan"), "hit3": float("nan"),
                "prec25": float("nan"), "note": f"データ不足(n={n}日)"}

    cutoff = n - actual_val
    train_dates = set(all_dates[:cutoff])
    val_dates   = set(all_dates[cutoff:])

    df_tr = scope_df[scope_df["date"].isin(train_dates)]
    df_va = scope_df[scope_df["date"].isin(val_dates)].copy()

    weights = df_tr["sample_weight"] if use_weight else None
    tr_pool = Pool(df_tr[ALL_FEATURES], label=df_tr["diff_coins_normalized"],
                   cat_features=cat_indices, weight=weights)
    va_pool = Pool(df_va[ALL_FEATURES], label=df_va["diff_coins_normalized"],
                   cat_features=cat_indices)

    params = CATBOOST_PARAMS.copy()
    try:
        m = CatBoostRegressor(**params)
        m.fit(tr_pool, eval_set=va_pool, use_best_model=True)
    except Exception:
        params = {k: v for k, v in params.items() if k not in ("task_type", "devices")}
        params["task_type"] = "CPU"
        m = CatBoostRegressor(**params)
        m.fit(tr_pool, eval_set=va_pool, use_best_model=True)

    df_va["pred"] = m.predict(va_pool)

    spearman_list, hit3_list = [], []
    for d, grp in df_va.groupby("date"):
        if len(grp) < 10:
            continue
        r, _ = spearmanr(grp["diff_coins_normalized"], grp["pred"])
        spearman_list.append(r)
        t3 = set(grp.nlargest(3, "diff_coins_normalized")["machine_number"])
        p3 = set(grp.nlargest(3, "pred")["machine_number"])
        hit3_list.append(len(t3 & p3) / 3)

    df_va["pred_top25"] = 0
    for d, grp in df_va.groupby("date"):
        top_n = max(1, int(len(grp) * TOP_PERCENTILE))
        df_va.loc[grp.nlargest(top_n, "pred").index, "pred_top25"] = 1

    prec = precision_score(df_va["top25_flag"], df_va["pred_top25"], zero_division=0)

    return {
        "label": label,
        "train_days": len(train_dates),
        "val_days": len(val_dates),
        "spearman": np.mean(spearman_list) if spearman_list else float("nan"),
        "hit3": np.mean(hit3_list) if hit3_list else float("nan"),
        "prec25": prec,
        "note": "",
    }


# ─────────────────────────────────────────────
# 3. 実験実行
# ─────────────────────────────────────────────
print_section("2. 実験実行")

experiments = [
    ("全期間",        False),
    ("全期間",        True),
    ("x_dayのみ",     False),
    ("x_dayのみ",     True),
    ("7のつく日のみ", False),
    ("7のつく日のみ", True),
    ("DD=7のみ",      False),
    ("DD=7のみ",      True),
]

results = []
for i, (scope_name, use_w) in enumerate(experiments, 1):
    w_label = "weight有(新店長3x)" if use_w else "weight無し    "
    label = f"{scope_name:<10} / {w_label}"
    print(f"  [{i}/{len(experiments)}] {label} ...", end=" ", flush=True)
    r = evaluate(SCOPES[scope_name], use_w, label)
    results.append(r)
    if r["note"]:
        print(f"SKIP: {r['note']}")
    else:
        print(f"Spearman={r['spearman']:.4f}  hit@3={r['hit3']:.4f}  prec25={r['prec25']:.4f}  (train={r['train_days']}日 val={r['val_days']}日)")


# ─────────────────────────────────────────────
# 4. 結果表
# ─────────────────────────────────────────────
print_section("3. 比較結果（Spearman降順）")
res_df = pd.DataFrame(results)
valid = res_df.dropna(subset=["spearman"]).sort_values("spearman", ascending=False)
skip  = res_df[res_df["spearman"].isna()]

print(valid[["label", "train_days", "val_days", "spearman", "hit3", "prec25"]].to_string(index=False))
if len(skip):
    print("\n  [スキップ]")
    print(skip[["label", "note"]].to_string(index=False))

best = valid.iloc[0]
print(f"\n  ★ 最良: {best['label'].strip()}")
print(f"     Spearman={best['spearman']:.4f} / hit@3={best['hit3']:.4f} / prec25={best['prec25']:.4f}")
print(f"     train={best['train_days']}日 / val={best['val_days']}日")
