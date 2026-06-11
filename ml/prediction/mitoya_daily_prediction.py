"""
みとや大森町店 当日差枚予測スクリプト
対象: 2026-06-07 (日曜, DD=7)
モデル: CatBoost GPU + walk-forward validation
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from datetime import date
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

try:
    from catboost import CatBoostRegressor, Pool
    print("[OK] CatBoost imported")
except ImportError:
    print("[ERROR] CatBoost not installed. Run: pip install catboost")
    sys.exit(1)

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "db" / "みとや大森町店.db"
OUTPUT_DIR = ROOT / "data" / "mitoya_prediction"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DATE = date(2026, 6, 7)
TARGET_DATE_STR = TARGET_DATE.strftime("%Y%m%d")

VALIDATION_DAYS = 30
TOP_PERCENTILE = 0.25

CATBOOST_PARAMS = {
    "iterations": 500,
    "learning_rate": 0.05,
    "depth": 6,
    "loss_function": "RMSE",
    "eval_metric": "RMSE",
    "task_type": "GPU",
    "devices": "0",
    "random_seed": 42,
    "verbose": 50,
    "early_stopping_rounds": 50,
}


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─────────────────────────────────────────────
# 1. データロード
# ─────────────────────────────────────────────
print_section("1. データロード")

conn = sqlite3.connect(DB_PATH)
df_raw = pd.read_sql("""
    SELECT date, machine_number, machine_name, last_digit,
           games_normalized, diff_coins_normalized
    FROM machine_detailed_results
    ORDER BY date, machine_number
""", conn)
df_layout = pd.read_sql("""
    SELECT machine_number, x, y, section, rank_from_min, rank_from_max,
           rank_from_aisle, is_reversed_section
    FROM machine_layout
""", conn)
df_master = pd.read_sql("""
    SELECT machine_name_normalized, jug_flag, hana_flag, oki_flag, bt_flag
    FROM machine_master
""", conn)
conn.close()

print(f"  全台数: {len(df_raw):,}行 / {df_raw['date'].nunique()}日 / {df_raw['machine_number'].nunique()}台")


# ─────────────────────────────────────────────
# 2. 特徴量エンジニアリング
# ─────────────────────────────────────────────
print_section("2. 特徴量エンジニアリング")

df = df_raw.copy()

df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
df["dd"] = df["date_dt"].dt.day
df["weekday_num"] = df["date_dt"].dt.dayofweek  # 0=月〜6=日
df["month"] = df["date_dt"].dt.month
df["week_of_year"] = df["date_dt"].dt.isocalendar().week.astype(int)
df["is_sunday"] = (df["weekday_num"] == 6).astype(int)
df["is_weekend"] = (df["weekday_num"] >= 5).astype(int)
df["is_dd7"] = (df["dd"] == 7).astype(int)
df["dd_mod5"] = df["dd"] % 5
df["dd_mod10"] = df["dd"] % 10
df["last_digit_num"] = pd.to_numeric(df["last_digit"], errors="coerce").fillna(-1).astype(int)

# 位置・機種マスタ結合
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
# 壁側角番: rank_from_max==1 は reversed_section で誤動作するため
# セクション内の rank_from_aisle 最大値（= 壁側端台）で定義
section_max_aisle = df.groupby("section")["rank_from_aisle"].transform("max")
df["is_far_corner"] = (df["rank_from_aisle"] == section_max_aisle).astype(int)
df["is_near_corner"] = (df["rank_from_aisle"] <= 2).astype(int)
df["position_ratio"] = df["rank_from_min"] / df["rank_from_max"].replace(0, 1)

# セクション×末尾の結合カテゴリ（島内ポジション×末尾の交互作用）
df["section_digit_key"] = df["section"].astype(str) + "_d" + df["last_digit_num"].astype(str)

# 物理的島カテゴリ（machine_type とは独立した軸。mitoya-island-vs-machinetype-dual-axis 信頼度0.90）
df["physical_island"] = np.select(
    [
        (df["machine_number"] >= 501) & (df["machine_number"] <= 640),
        (df["machine_number"] >= 641) & (df["machine_number"] <= 691),
        (df["machine_number"] >= 692) & (df["machine_number"] <= 755),
        (df["machine_number"] >= 805) & (df["machine_number"] <= 815),
    ],
    ["AT島", "ジャグラー島", "バラエティ島", "BT島"],
    default="その他",
)


# x_dayフラグ（DD末尾4,7 = みとやのイベントサイクル）
df["is_xday"] = (df["dd"] % 10).isin([4, 7]).astype(int)

# 新店長期間フラグ（2026-05以降）※重みなし・特徴量としてのみ使用
df["is_new_manager"] = (df["date_dt"] >= pd.Timestamp("2026-05-01")).astype(int)

# 移動平均（データリーク回避: shift(1)）
print("  機種別移動平均 (7日/30日) ...")
df = df.sort_values(["machine_name", "date_dt"])
df["machine_roll7_diff"] = df.groupby("machine_name")["diff_coins_normalized"].transform(
    lambda x: x.shift(1).rolling(7, min_periods=1).mean()
)
df["machine_roll30_diff"] = df.groupby("machine_name")["diff_coins_normalized"].transform(
    lambda x: x.shift(1).rolling(30, min_periods=5).mean()
)

print("  台番号別移動平均 (7日/30日) ...")
df = df.sort_values(["machine_number", "date_dt"])
df["seat_roll7_diff"] = df.groupby("machine_number")["diff_coins_normalized"].transform(
    lambda x: x.shift(1).rolling(7, min_periods=1).mean()
)
df["seat_roll30_diff"] = df.groupby("machine_number")["diff_coins_normalized"].transform(
    lambda x: x.shift(1).rolling(30, min_periods=5).mean()
)

print("  機種×曜日 過去平均 ...")
df = df.sort_values(["machine_name", "weekday_num", "date_dt"])
df["model_weekday_roll"] = df.groupby(["machine_name", "weekday_num"])["diff_coins_normalized"].transform(
    lambda x: x.shift(1).expanding(min_periods=1).mean()
)

# 台番号×DD の過去平均（DDごとにポジション効果が逆転するため必須）
print("  台番号×DD 過去平均 ...")
df = df.sort_values(["machine_number", "dd", "date_dt"])
df["seat_dd_roll"] = df.groupby(["machine_number", "dd"])["diff_coins_normalized"].transform(
    lambda x: x.shift(1).expanding(min_periods=1).mean()
)

df = df.sort_values("date_dt").reset_index(drop=True)

# 機種別 walk-forward 集約特徴量（B案: 機種名ごとに正しい期間のデータで統計を計算）
# 各行は「その日に実際に稼働していた機種名」を使用 → 異なる機種のデータは混在しない
# shift(1) でデータリーク回避
print("  機種別 walk-forward 集約特徴量 (B案)...")
df_name_sorted = df.sort_values(["machine_name", "date_dt"])

# 全期間 expanding: 平均差枚・勝率・サンプル数
df_name_sorted["machine_avg_diff_wf"] = df_name_sorted.groupby("machine_name")["diff_coins_normalized"].transform(
    lambda x: x.shift(1).expanding(min_periods=1).mean()
)
df_name_sorted["machine_plus_rate_wf"] = df_name_sorted.groupby("machine_name")["diff_coins_normalized"].transform(
    lambda x: (x.shift(1) > 0).expanding(min_periods=1).mean()
)
df_name_sorted["machine_sample_n_wf"] = df_name_sorted.groupby("machine_name")["diff_coins_normalized"].transform(
    lambda x: x.shift(1).expanding(min_periods=1).count()
)

df = df.merge(
    df_name_sorted[["date", "machine_number",
                    "machine_avg_diff_wf", "machine_plus_rate_wf", "machine_sample_n_wf"]],
    on=["date", "machine_number"], how="left"
)

# x_day（DD末尾4,7）限定 expanding mean: みとや特有のイベント日パフォーマンス
df_xday_sub = df[df["is_xday"] == 1].sort_values(["machine_name", "date_dt"]).copy()
df_xday_sub["machine_xday_avg_wf"] = df_xday_sub.groupby("machine_name")["diff_coins_normalized"].transform(
    lambda x: x.shift(1).expanding(min_periods=1).mean()
)
df = df.merge(
    df_xday_sub[["date", "machine_number", "machine_xday_avg_wf"]].copy(),
    on=["date", "machine_number"], how="left"
)
# x_day以外の行: 同機種の直前x_day平均を前方補完（最後に知っている値を使用）
df = df.sort_values(["machine_name", "date_dt"])
df["machine_xday_avg_wf"] = df.groupby("machine_name")["machine_xday_avg_wf"].transform(
    lambda x: x.ffill()
)
df = df.sort_values("date_dt").reset_index(drop=True)

# 上位25%フラグ（ターゲット）
print("  上位25%フラグ計算 ...")
df["top25_flag"] = 0
for d, grp in df.groupby("date"):
    thr = grp["diff_coins_normalized"].quantile(1 - TOP_PERCENTILE)
    df.loc[grp.index, "top25_flag"] = (grp["diff_coins_normalized"] >= thr).astype(int)

print(f"  特徴量生成完了: {df.shape}")


# ─────────────────────────────────────────────
# 3. 特徴量定義
# ─────────────────────────────────────────────
print_section("3. 特徴量定義")

NUMERIC_FEATURES = [
    "dd", "weekday_num", "month", "week_of_year",
    "is_sunday", "is_weekend", "is_dd7", "dd_mod5", "dd_mod10",
    "last_digit_num",
    "x", "y", "rank_from_min", "rank_from_max", "rank_from_aisle",
    "is_corner", "is_far_corner", "is_near_corner", "is_reversed_section", "position_ratio",
    "is_new_manager",
    # is_xday は x_day スコープ学習では常に1のため除外
    "jug_flag", "hana_flag", "oki_flag", "bt_flag",
    "machine_roll7_diff", "machine_roll30_diff",
    "seat_roll7_diff", "seat_roll30_diff",
    "model_weekday_roll",
    "seat_dd_roll",   # 台番号×DD の過去平均（DDごとのポジション効果変動を捉える）
    # 機種別 walk-forward 集約特徴量（B案: 各機種が実際に稼働していた期間のデータのみ使用）
    "machine_avg_diff_wf",   # 機種の全期間平均差枚
    "machine_plus_rate_wf",  # 機種の勝率
    "machine_sample_n_wf",   # 機種のサンプル数（統計の信頼性）
    "machine_xday_avg_wf",   # 機種のx_day限定平均差枚
    "games_normalized",
]
CAT_FEATURES = ["machine_name", "machine_type", "section", "section_digit_key",
                # 物理的島カテゴリ（mitoya-island-vs-machinetype-dual-axis 信頼度0.90: machine_type と独立した軸）
                "physical_island"]
ALL_FEATURES = NUMERIC_FEATURES + CAT_FEATURES

for col in NUMERIC_FEATURES:
    if col in df.columns:
        df[col] = df[col].fillna(0)
for col in CAT_FEATURES:
    if col in df.columns:
        df[col] = df[col].fillna("unknown")

print(f"  数値: {len(NUMERIC_FEATURES)}個 / カテゴリ: {len(CAT_FEATURES)}個")

cat_indices = [ALL_FEATURES.index(c) for c in CAT_FEATURES]


# ─────────────────────────────────────────────
# 4. Walk-forward Validation
# ─────────────────────────────────────────────
print_section("4. Walk-forward Validation (x_dayスコープ: DD末尾4,7のみ)")

# x_dayのみに絞る（比較実験で全期間より有意に優秀と確認済み）
dd_mod = df["dd"] % 10
df_xday = df[dd_mod.isin([4, 7])].copy()
print(f"  x_day絞り込み後: {df_xday['date'].nunique()}日 / {len(df_xday):,}台")

all_dates = sorted(df_xday["date"].unique())
cutoff = len(all_dates) - VALIDATION_DAYS
train_dates = set(all_dates[:cutoff])
val_dates = set(all_dates[cutoff:])

df_train = df_xday[df_xday["date"].isin(train_dates)].copy()
df_val   = df_xday[df_xday["date"].isin(val_dates)].copy()

print(f"  Train: {len(train_dates)}日 / {len(df_train):,}台")
print(f"  Val:   {len(val_dates)}日 / {len(df_val):,}台")

train_pool = Pool(df_train[ALL_FEATURES], label=df_train["diff_coins_normalized"], cat_features=cat_indices)
val_pool   = Pool(df_val[ALL_FEATURES],   label=df_val["diff_coins_normalized"],   cat_features=cat_indices)

print("\n  [CatBoost GPU 学習開始]")
model = None
try:
    model = CatBoostRegressor(**CATBOOST_PARAMS)
    model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    print("  [GPU完了]")
except Exception as e:
    print(f"  [GPU失敗: {e}] → CPU fallback")
    params_cpu = {k: v for k, v in CATBOOST_PARAMS.items() if k not in ("task_type", "devices")}
    params_cpu["task_type"] = "CPU"
    model = CatBoostRegressor(**params_cpu)
    model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    print("  [CPU完了]")

# 評価
val_pred = model.predict(val_pool)
df_val = df_val.copy()
df_val["pred_diff"] = val_pred

from scipy.stats import spearmanr
spearman_list, hit3_list = [], []
for d, grp in df_val.groupby("date"):
    if len(grp) < 10:
        continue
    r, _ = spearmanr(grp["diff_coins_normalized"], grp["pred_diff"])
    spearman_list.append(r)
    true_top3 = set(grp.nlargest(3, "diff_coins_normalized")["machine_number"])
    pred_top3 = set(grp.nlargest(3, "pred_diff")["machine_number"])
    hit3_list.append(len(true_top3 & pred_top3) / 3)

df_val["pred_top25"] = 0
for d, grp in df_val.groupby("date"):
    top_n = max(1, int(len(grp) * TOP_PERCENTILE))
    df_val.loc[grp.nlargest(top_n, "pred_diff").index, "pred_top25"] = 1

from sklearn.metrics import precision_score, recall_score
prec = precision_score(df_val["top25_flag"], df_val["pred_top25"], zero_division=0)
rec  = recall_score(df_val["top25_flag"], df_val["pred_top25"], zero_division=0)

print(f"\n  === Validation結果 ({len(val_dates)}日) ===")
print(f"  Spearman (日次平均): {np.mean(spearman_list):.4f}")
print(f"  hit@3    (日次平均): {np.mean(hit3_list):.4f}")
print(f"  top25% Precision:    {prec:.4f}")
print(f"  top25% Recall:       {rec:.4f}")


# ─────────────────────────────────────────────
# 5. 本日予測
# ─────────────────────────────────────────────
print_section(f"5. 本日予測: {TARGET_DATE_STR} (日曜, DD=7)")

latest_date = df["date"].max()
print(f"  最新データ日: {latest_date}")

today = df_layout.copy()
today["date"] = TARGET_DATE_STR
today["dd"] = TARGET_DATE.day
today["weekday_num"] = 6
today["month"] = TARGET_DATE.month
today["week_of_year"] = int(pd.Timestamp(TARGET_DATE).isocalendar().week)
today["is_sunday"] = 1
today["is_weekend"] = 1
today["is_dd7"] = 1
today["dd_mod5"] = today["dd"] % 5
today["dd_mod10"] = today["dd"] % 10
today["is_corner"] = (today["rank_from_aisle"] == 1).astype(int)
today_sec_max = today.groupby("section")["rank_from_aisle"].transform("max")
today["is_far_corner"] = (today["rank_from_aisle"] == today_sec_max).astype(int)
today["is_near_corner"] = (today["rank_from_aisle"] <= 2).astype(int)
today["position_ratio"] = today["rank_from_min"] / today["rank_from_max"].replace(0, 1)
today["is_xday"] = int(TARGET_DATE.day % 10 in [4, 7])
today["is_new_manager"] = 1  # 2026-06-07 は新店長期間
today["last_digit_num"] = today["machine_number"] % 10

# 物理的島カテゴリ・角番3カテゴリ（学習側の特徴量定義をミラー）
today["physical_island"] = np.select(
    [
        (today["machine_number"] >= 501) & (today["machine_number"] <= 640),
        (today["machine_number"] >= 641) & (today["machine_number"] <= 691),
        (today["machine_number"] >= 692) & (today["machine_number"] <= 755),
        (today["machine_number"] >= 805) & (today["machine_number"] <= 815),
    ],
    ["AT島", "ジャグラー島", "バラエティ島", "BT島"],
    default="その他",
)

# 機種名結合
# 最新日付の機種名のみ使用（古い機種の混入を防ぐ）
latest_date = df_raw["date"].max()
mn_map = (
    df_raw[df_raw["date"] == latest_date][["machine_number", "machine_name"]]
    .drop_duplicates("machine_number")
)
print(f"  機種名マッピング: {latest_date} の {len(mn_map)}台を使用")
today = today.merge(mn_map, on="machine_number", how="left")
today["machine_name"] = today["machine_name"].fillna("unknown")

today = today.merge(
    df_master.rename(columns={"machine_name_normalized": "machine_name"}),
    on="machine_name", how="left"
)
for col in ["jug_flag", "hana_flag", "oki_flag", "bt_flag"]:
    today[col] = today[col].fillna(0).astype(int)
today["machine_type"] = today.apply(get_machine_type, axis=1)
today["section_digit_key"] = today["section"].astype(str) + "_d" + (today["machine_number"] % 10).astype(str)

# 機種別 walk-forward 集約特徴量: 現機種名で最終統計を参照
# today["machine_name"] = 現在の機種名 → その機種が稼働していた全期間の実績統計を取得
machine_final_stats = df.groupby("machine_name").agg(
    machine_avg_diff_wf=("diff_coins_normalized", "mean"),
    machine_plus_rate_wf=("diff_coins_normalized", lambda x: (x > 0).mean()),
    machine_sample_n_wf=("diff_coins_normalized", "count"),
).reset_index()
xday_final_stats = (
    df[df["is_xday"] == 1]
    .groupby("machine_name")["diff_coins_normalized"]
    .mean().reset_index(name="machine_xday_avg_wf")
)
machine_final_stats = machine_final_stats.merge(xday_final_stats, on="machine_name", how="left")
# x_dayデータがない機種は全期間平均で代替
machine_final_stats["machine_xday_avg_wf"] = machine_final_stats["machine_xday_avg_wf"].fillna(
    machine_final_stats["machine_avg_diff_wf"]
)

today = today.merge(machine_final_stats, on="machine_name", how="left")

# 移動平均: 最新データから計算
roll7m = df.groupby("machine_name").apply(
    lambda x: x.sort_values("date_dt").tail(7)["diff_coins_normalized"].mean()
).reset_index(name="machine_roll7_diff")
roll30m = df.groupby("machine_name").apply(
    lambda x: x.sort_values("date_dt").tail(30)["diff_coins_normalized"].mean()
).reset_index(name="machine_roll30_diff")
roll7s = df.groupby("machine_number").apply(
    lambda x: x.sort_values("date_dt").tail(7)["diff_coins_normalized"].mean()
).reset_index(name="seat_roll7_diff")
roll30s = df.groupby("machine_number").apply(
    lambda x: x.sort_values("date_dt").tail(30)["diff_coins_normalized"].mean()
).reset_index(name="seat_roll30_diff")
sun_avg = (
    df[df["is_sunday"] == 1]
    .groupby("machine_name")["diff_coins_normalized"]
    .mean().reset_index(name="model_weekday_roll")
)
# 台番号×DD=7 の過去平均（本日のDDに対応する値を使用）
seat_dd_avg = (
    df[df["dd"] == TARGET_DATE.day]
    .groupby("machine_number")["diff_coins_normalized"]
    .mean().reset_index(name="seat_dd_roll")
)
games_avg = df.groupby("machine_number")["games_normalized"].mean().reset_index(name="games_normalized")

today = (today
    .merge(roll7m, on="machine_name", how="left")
    .merge(roll30m, on="machine_name", how="left")
    .merge(roll7s, on="machine_number", how="left")
    .merge(roll30s, on="machine_number", how="left")
    .merge(sun_avg, on="machine_name", how="left")
    .merge(seat_dd_avg, on="machine_number", how="left")
    .merge(games_avg, on="machine_number", how="left")
)

for col in NUMERIC_FEATURES:
    if col in today.columns:
        today[col] = pd.to_numeric(today[col], errors="coerce").fillna(0)
for col in CAT_FEATURES:
    if col in today.columns:
        today[col] = today[col].fillna("unknown")

today_pool = Pool(today[ALL_FEATURES], cat_features=cat_indices)
today["pred_diff"] = model.predict(today_pool)
today["pred_rank"] = today["pred_diff"].rank(ascending=False).astype(int)

print(f"  予測完了: {len(today)}台")


# ─────────────────────────────────────────────
# 6. 結果サマリ表示
# ─────────────────────────────────────────────
print_section("6. 予測結果サマリ")

SHOW_COLS = ["pred_rank", "machine_number", "machine_name", "machine_type",
             "section", "rank_from_aisle", "is_corner", "is_far_corner", "last_digit_num",
             "pred_diff", "machine_roll7_diff", "seat_roll7_diff"]

print("\n  === TOP20 予測台 ===")
print(today.nsmallest(20, "pred_rank")[SHOW_COLS].to_string(index=False))

print("\n  === 機種タイプ別 TOP5 ===")
for mtype in ["jug", "bt", "hana", "oki", "other"]:
    sub = today[today["machine_type"] == mtype].nsmallest(5, "pred_rank")
    if sub.empty:
        continue
    print(f"\n  [{mtype}]")
    print(sub[["pred_rank", "machine_number", "machine_name", "rank_from_aisle", "pred_diff"]].to_string(index=False))

print("\n  === セクション別ベスト台 ===")
sec_best = (
    today.sort_values("pred_diff", ascending=False)
    .groupby("section").head(1)
    [["section", "machine_number", "machine_name", "rank_from_aisle", "pred_diff", "pred_rank"]]
    .sort_values("pred_diff", ascending=False)
)
print(sec_best.to_string(index=False))

print("\n  === 末尾別 平均予測差枚 ===")
print(today.groupby("last_digit_num")["pred_diff"].agg(["mean", "count"]).sort_values("mean", ascending=False))

print("\n  通路側角番(is_corner) vs 壁側角番(is_far_corner) vs 中間台:")
for label, mask in [
    ("通路側角番", today["is_corner"] == 1),
    ("壁側角番",   today["is_far_corner"] == 1),
    ("中間台",     (today["is_corner"] == 0) & (today["is_far_corner"] == 0)),
]:
    sub = today[mask]
    print(f"  {label}: avg={sub['pred_diff'].mean():.0f}, n={len(sub)}")


# ─────────────────────────────────────────────
# 7. 保存
# ─────────────────────────────────────────────
print_section("7. CSV保存")

save_cols = ["pred_rank", "machine_number", "machine_name", "machine_type",
             "section", "rank_from_aisle", "is_corner", "is_far_corner", "last_digit_num",
             "pred_diff", "machine_roll7_diff", "machine_roll30_diff",
             "seat_roll7_diff", "seat_roll30_diff"]
out = OUTPUT_DIR / f"prediction_{TARGET_DATE_STR}.csv"
today[save_cols].sort_values("pred_rank").to_csv(out, index=False, encoding="utf-8-sig")

fi_df = pd.DataFrame({
    "feature": ALL_FEATURES,
    "importance": model.get_feature_importance()
}).sort_values("importance", ascending=False)
fi_out = OUTPUT_DIR / f"feature_importance_{TARGET_DATE_STR}.csv"
fi_df.to_csv(fi_out, index=False, encoding="utf-8-sig")

print(f"  予測CSV:       {out}")
print(f"  特徴量重要度:  {fi_out}")
print("\n  TOP10 特徴量:")
print(fi_df.head(10).to_string(index=False))

print_section("完了")
print(f"  Spearman: {np.mean(spearman_list):.4f} / hit@3: {np.mean(hit3_list):.4f}")
print(f"  予測結果: {out}")
