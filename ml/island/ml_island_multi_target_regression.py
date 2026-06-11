#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集団レベル(島x日) 多目的regression
- 単一の over_104_rate だけでなく、under_100_rate, avg_kikaiwari も同時に予測
- 「分布が上振れ/下振れしているか」を多面的に捉え、単一指標では見えない判断材料を得る
- Walk-forward validation
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
OUTPUT_JSON = Path(__file__).parent / "ml_island_multi_target_results.json"

TARGETS = ['over_104_rate', 'under_100_rate', 'avg_kikaiwari']

def load_grouped_data():
    df = pd.read_csv(DATA_CSV)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['under_100'] = (df['kikaiwari'] < 100).astype(int)

    grouped = df.groupby(['date', 'island']).agg(
        over_104_rate=('target_104', 'mean'),
        under_100_rate=('under_100', 'mean'),
        avg_kikaiwari=('kikaiwari', 'mean'),
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
    baseline_pred = np.full_like(y_test, y_train.mean())
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

def train_multi_target(df, features, split):
    train_mask = (df['date'] >= split['train_start']) & (df['date'] < split['train_end'])
    test_mask = (df['date'] >= split['test_start']) & (df['date'] < split['test_end'])

    df_train = df[train_mask]
    df_test = df[test_mask]

    if len(df_train) < 50 or len(df_test) < 5:
        return None

    X_train = df_train[features]
    X_test = df_test[features]

    target_results = {}
    predictions = {}

    for target in TARGETS:
        y_train = df_train[target].values
        y_test = df_test[target].values

        model = CatBoostRegressor(
            iterations=200, depth=4, learning_rate=0.05,
            random_state=42, verbose=0, cat_features=['island']
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], early_stopping_rounds=20)
        y_pred = model.predict(X_test)
        predictions[target] = y_pred

        target_results[target] = evaluate_target(y_test, y_pred, y_train)

    # 複合スコア: over_104予測が高く、かつunder_100予測が低い島x日を「狙い目」とする
    composite_score = predictions['over_104_rate'] - predictions['under_100_rate']
    actual_composite = df_test['over_104_rate'].values - df_test['under_100_rate'].values

    if len(set(composite_score)) > 1 and len(set(actual_composite)) > 1:
        composite_corr, composite_p = pearsonr(actual_composite, composite_score)
    else:
        composite_corr, composite_p = 0.0, 1.0

    n_top = max(1, int(len(actual_composite) * 0.3))
    pred_top = set(np.argsort(-composite_score)[:n_top])
    actual_top = set(np.argsort(-actual_composite)[:n_top])
    composite_top30 = len(pred_top & actual_top) / n_top

    return {
        'train_start': split['train_start'].strftime('%Y-%m-%d'),
        'test_start': split['test_start'].strftime('%Y-%m-%d'),
        'test_end': split['test_end'].strftime('%Y-%m-%d'),
        'test_size': len(df_test),
        'targets': target_results,
        'composite_score': {
            'pearson_corr': float(composite_corr),
            'pearson_p': float(composite_p),
            'top30_overlap': float(composite_top30),
        }
    }

print("=" * 80)
print("Multi-Target Group-level Regression: over_104 / under_100 / avg_kikaiwari")
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
    result = train_multi_target(df, features, split)
    if result:
        results.append(result)
        print(f"\nSplit {i}: {result['test_start']} - {result['test_end']} (n={result['test_size']})")
        for target in TARGETS:
            tr = result['targets'][target]
            print(f"  [{target}] RMSE改善={tr['rmse_improvement_pct']:+.1f}%, Pearson={tr['pearson_corr']:.3f}(p={tr['pearson_p']:.3f}), Top30%重複={tr['top30_overlap']:.3f}")
        cs = result['composite_score']
        print(f"  [複合スコア(104%率-100%未満率)] Pearson={cs['pearson_corr']:.3f}(p={cs['pearson_p']:.3f}), Top30%重複={cs['top30_overlap']:.3f}")

print("\n" + "=" * 80)
print("Summary")
print("=" * 80)

if results:
    for target in TARGETS:
        avg_pearson = np.mean([r['targets'][target]['pearson_corr'] for r in results])
        avg_top30 = np.mean([r['targets'][target]['top30_overlap'] for r in results])
        avg_rmse_imp = np.mean([r['targets'][target]['rmse_improvement_pct'] for r in results])
        print(f"{target}: avg Pearson={avg_pearson:.3f}, avg Top30%={avg_top30:.3f}, avg RMSE改善={avg_rmse_imp:+.1f}%")

    avg_composite_pearson = np.mean([r['composite_score']['pearson_corr'] for r in results])
    avg_composite_top30 = np.mean([r['composite_score']['top30_overlap'] for r in results])
    print(f"\n複合スコア(over_104 - under_100): avg Pearson={avg_composite_pearson:.3f}, avg Top30%={avg_composite_top30:.3f}")
    print(f"(単目的の over_104_rate 単独 Top30%=0.519 と比較)")

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nSaved: {OUTPUT_JSON}")
