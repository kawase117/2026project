#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集団レベル(島x日)regression: 個体x二値分類からの粒度転換
- 目的変数: 島x日ごとの104%超え率(連続値)
- 特徴量: dd, dow, is_event, island (予測時点で既知のもののみ)
- Walk-forward validation, 評価指標: RMSE, MAE, 相関係数, 上位予測の的中率
"""

import pandas as pd
import numpy as np
from pathlib import Path
from catboost import CatBoostRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error
from scipy.stats import pearsonr, spearmanr
import json
import warnings

warnings.filterwarnings('ignore')

DATA_CSV = Path(__file__).parent / "ml_data_island_submodel.csv"
OUTPUT_JSON = Path(__file__).parent / "ml_island_group_regression_results.json"

def load_grouped_data():
    df = pd.read_csv(DATA_CSV)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

    grouped = df.groupby(['date', 'island']).agg(
        over_104_rate=('target_104', 'mean'),
        avg_kikaiwari=('kikaiwari', 'mean'),
        n_machines=('machine_number', 'count'),
        dd=('dd', 'first'),
        dow=('dow', 'first'),
        is_event=('is_event', 'first'),
    ).reset_index()

    return grouped

def create_walk_forward_splits(df, train_months=12, test_months=1):
    min_date = df['date'].min()
    max_date = df['date'].max()
    splits = []
    current_train_start = min_date

    while current_train_start < max_date:
        train_end = current_train_start + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)

        if test_end > max_date:
            test_end = max_date

        if test_start < max_date:
            splits.append({
                'train_start': current_train_start,
                'train_end': train_end,
                'test_start': test_start,
                'test_end': test_end
            })

        current_train_start = test_start

    return splits

def train_group_model(df, features, split):
    train_mask = (df['date'] >= split['train_start']) & (df['date'] < split['train_end'])
    test_mask = (df['date'] >= split['test_start']) & (df['date'] < split['test_end'])

    df_train = df[train_mask]
    df_test = df[test_mask]

    if len(df_train) < 50 or len(df_test) < 5:
        return None

    X_train = df_train[features]
    y_train = df_train['over_104_rate'].values
    X_test = df_test[features]
    y_test = df_test['over_104_rate'].values

    model = CatBoostRegressor(
        iterations=200,
        depth=4,
        learning_rate=0.05,
        random_state=42,
        verbose=0,
        cat_features=['island']
    )

    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], early_stopping_rounds=20)

    y_pred = model.predict(X_test)

    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    mae = mean_absolute_error(y_test, y_pred)

    # ベースライン: 学習期間の平均値で予測した場合のRMSE/MAE
    baseline_pred = np.full_like(y_test, y_train.mean())
    baseline_rmse = np.sqrt(mean_squared_error(y_test, baseline_pred))
    baseline_mae = mean_absolute_error(y_test, baseline_pred)

    # 相関係数(予測値と実際の値の順位相関 = どの島x日が高いかを当てられているか)
    if len(set(y_pred)) > 1 and len(set(y_test)) > 1:
        pearson_corr, pearson_p = pearsonr(y_test, y_pred)
        spearman_corr, spearman_p = spearmanr(y_test, y_pred)
    else:
        pearson_corr, pearson_p = 0.0, 1.0
        spearman_corr, spearman_p = 0.0, 1.0

    # Top-k 的中率: 予測上位30%の島x日の中に、実際の上位30%がどれだけ含まれるか
    n_top = max(1, int(len(y_test) * 0.3))
    pred_top_idx = set(np.argsort(-y_pred)[:n_top])
    actual_top_idx = set(np.argsort(-y_test)[:n_top])
    top30_overlap = len(pred_top_idx & actual_top_idx) / n_top

    return {
        'train_start': split['train_start'].strftime('%Y-%m-%d'),
        'train_end': split['train_end'].strftime('%Y-%m-%d'),
        'test_start': split['test_start'].strftime('%Y-%m-%d'),
        'test_end': split['test_end'].strftime('%Y-%m-%d'),
        'train_size': len(df_train),
        'test_size': len(df_test),
        'rmse': float(rmse),
        'mae': float(mae),
        'baseline_rmse': float(baseline_rmse),
        'baseline_mae': float(baseline_mae),
        'rmse_improvement_pct': float((baseline_rmse - rmse) / baseline_rmse * 100),
        'pearson_corr': float(pearson_corr),
        'pearson_p': float(pearson_p),
        'spearman_corr': float(spearman_corr),
        'spearman_p': float(spearman_p),
        'top30_overlap': float(top30_overlap),
        'top30_baseline': 0.3,
    }

print("=" * 80)
print("Group-level (Island x Date) Regression: Walk-forward Validation")
print("=" * 80)

df = load_grouped_data()
print(f"\nGrouped data: {len(df)} rows (date x island)")
print(f"Date range: {df['date'].min().date()} - {df['date'].max().date()}")
print(f"over_104_rate stats: mean={df['over_104_rate'].mean():.3f}, std={df['over_104_rate'].std():.3f}")

features = ['dd', 'dow', 'is_event', 'island']
splits = create_walk_forward_splits(df, train_months=6, test_months=1)
print(f"\nWalk-forward splits generated: {len(splits)} (train=6mo, test=1mo, for robustness check across multiple windows)")

results = []
for i, split in enumerate(splits):
    result = train_group_model(df, features, split)
    if result:
        results.append(result)
        print(f"\nSplit {i}: {result['test_start']} - {result['test_end']}")
        print(f"  RMSE: {result['rmse']:.4f} (baseline {result['baseline_rmse']:.4f}, improvement {result['rmse_improvement_pct']:+.1f}%)")
        print(f"  MAE:  {result['mae']:.4f} (baseline {result['baseline_mae']:.4f})")
        print(f"  Pearson corr: {result['pearson_corr']:.4f} (p={result['pearson_p']:.4f})")
        print(f"  Spearman corr: {result['spearman_corr']:.4f} (p={result['spearman_p']:.4f})")
        print(f"  Top30% overlap: {result['top30_overlap']:.3f} (random baseline: 0.300)")

print("\n" + "=" * 80)
print("Summary across all splits")
print("=" * 80)

if results:
    avg_rmse_improve = np.mean([r['rmse_improvement_pct'] for r in results])
    avg_pearson = np.mean([r['pearson_corr'] for r in results])
    avg_spearman = np.mean([r['spearman_corr'] for r in results])
    avg_top30 = np.mean([r['top30_overlap'] for r in results])

    print(f"Average RMSE improvement over baseline: {avg_rmse_improve:+.1f}%")
    print(f"Average Pearson correlation: {avg_pearson:.4f}")
    print(f"Average Spearman correlation: {avg_spearman:.4f}")
    print(f"Average Top30% overlap: {avg_top30:.3f} (random: 0.300)")

    print("\nDiagnosis:")
    if avg_pearson > 0.3 and avg_top30 > 0.4:
        print("  -> Meaningful signal detected at group level. Model captures real structure.")
    elif avg_pearson > 0.15 or avg_top30 > 0.35:
        print("  -> Weak but potentially real signal. Worth refining features/segments further.")
    else:
        print("  -> Still close to random at this granularity too. May need finer segment definition or different target.")

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nSaved: {OUTPUT_JSON}")
