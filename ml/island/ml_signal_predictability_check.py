#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
複合モデル構築の前段階チェック:
over_104_rate に加え、win_rate / avg_games (回転数) も
「前日までに既知の情報」だけからどの程度予測可能かを個別に検証する。

各シグナルを個別の CatBoostRegressor で学習し、予測力(Pearson, Top30%重複率)を比較する。
ここではまだ複合(スタッキング)は行わない -- 各シグナル単体の予測性を見るのが目的。
"""

import pandas as pd
import numpy as np
from pathlib import Path
from catboost import CatBoostRegressor
from sklearn.metrics import mean_squared_error
from scipy.stats import pearsonr
import json
import warnings

warnings.filterwarnings('ignore')

DATA_CSV = Path(__file__).parent / "ml_data_island_submodel.csv"
OUTPUT_JSON = Path(__file__).parent / "ml_signal_predictability_results.json"

TARGETS = ['over_104_rate', 'win_rate', 'avg_games']


def load_grouped_data():
    df = pd.read_csv(DATA_CSV)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['win'] = (df['diff_coins_normalized'] > 0).astype(int)

    grouped = df.groupby(['date', 'island']).agg(
        over_104_rate=('target_104', 'mean'),
        win_rate=('win', 'mean'),
        avg_games=('games_normalized', 'mean'),
        n_machines=('machine_number', 'count'),
        dd=('dd', 'first'),
        dow=('dow', 'first'),
        is_event=('is_event', 'first'),
    ).reset_index()

    return grouped


def create_walk_forward_splits(df, train_months=6, test_months=1):
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


def evaluate_target(y_test, y_pred, y_train):
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    baseline_pred = np.full_like(y_test, y_train.mean(), dtype=float)
    baseline_rmse = np.sqrt(mean_squared_error(y_test, baseline_pred))

    if len(set(y_pred)) > 1 and len(set(y_test)) > 1:
        pearson_corr, pearson_p = pearsonr(y_test, y_pred)
    else:
        pearson_corr, pearson_p = 0.0, 1.0

    n_top = max(1, int(len(y_test) * 0.3))
    pred_top_idx = set(np.argsort(-y_pred)[:n_top])
    actual_top_idx = set(np.argsort(-y_test)[:n_top])
    top30_overlap = len(pred_top_idx & actual_top_idx) / n_top

    return {
        'rmse': float(rmse),
        'baseline_rmse': float(baseline_rmse),
        'rmse_improvement_pct': float((baseline_rmse - rmse) / baseline_rmse * 100) if baseline_rmse > 0 else 0.0,
        'pearson_corr': float(pearson_corr),
        'pearson_p': float(pearson_p),
        'top30_overlap': float(top30_overlap),
    }


def train_split(df, features, split):
    train_mask = (df['date'] >= split['train_start']) & (df['date'] < split['train_end'])
    test_mask = (df['date'] >= split['test_start']) & (df['date'] < split['test_end'])

    df_train = df[train_mask]
    df_test = df[test_mask]

    if len(df_train) < 50 or len(df_test) < 5:
        return None

    X_train = df_train[features]
    X_test = df_test[features]

    target_results = {}
    for target in TARGETS:
        y_train = df_train[target].values
        y_test = df_test[target].values

        model = CatBoostRegressor(
            iterations=200, depth=4, learning_rate=0.05,
            random_state=42, verbose=0, cat_features=['island']
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], early_stopping_rounds=20)
        y_pred = model.predict(X_test)

        target_results[target] = evaluate_target(y_test, y_pred, y_train)

    return {
        'train_start': split['train_start'].strftime('%Y-%m-%d'),
        'test_start': split['test_start'].strftime('%Y-%m-%d'),
        'test_end': split['test_end'].strftime('%Y-%m-%d'),
        'test_size': len(df_test),
        'targets': target_results,
    }


print("=" * 80)
print("Signal Predictability Check: over_104_rate vs win_rate vs avg_games")
print("(各シグナルが事前情報のみからどの程度予測できるかを個別に検証)")
print("=" * 80)

df = load_grouped_data()
print(f"\nGrouped rows: {len(df)}")
for t in TARGETS:
    print(f"  {t}: mean={df[t].mean():.4f}, std={df[t].std():.4f}")

features = ['dd', 'dow', 'is_event', 'island']
splits = create_walk_forward_splits(df)
print(f"\nWalk-forward splits: {len(splits)}")

results = []
for i, split in enumerate(splits):
    result = train_split(df, features, split)
    if result:
        results.append(result)
        print(f"\nSplit {i}: {result['test_start']} - {result['test_end']} (n={result['test_size']})")
        for target in TARGETS:
            tr = result['targets'][target]
            print(f"  [{target}] RMSE改善={tr['rmse_improvement_pct']:+.1f}%, "
                  f"Pearson={tr['pearson_corr']:.3f}(p={tr['pearson_p']:.3f}), "
                  f"Top30%重複={tr['top30_overlap']:.3f}")

print("\n" + "=" * 80)
print("Summary (avg across splits)")
print("=" * 80)

if results:
    for target in TARGETS:
        avg_pearson = np.mean([r['targets'][target]['pearson_corr'] for r in results])
        avg_top30 = np.mean([r['targets'][target]['top30_overlap'] for r in results])
        avg_rmse_imp = np.mean([r['targets'][target]['rmse_improvement_pct'] for r in results])
        print(f"{target}: avg Pearson={avg_pearson:.3f}, avg Top30%={avg_top30:.3f}, avg RMSE改善={avg_rmse_imp:+.1f}%")
        if avg_pearson > 0.3 and avg_top30 > 0.4:
            print(f"  -> 予測性あり。複合モデルの構成要素として有望")
        elif avg_pearson > 0.15:
            print(f"  -> 弱いが予測性は確認できる")
        else:
            print(f"  -> ほぼ予測不能。複合モデルに含める価値は薄い")

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nSaved: {OUTPUT_JSON}")
