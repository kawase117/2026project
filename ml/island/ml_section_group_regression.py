#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集団レベル(セクションx日)regression: islandより細かい粒度での over_104_rate 予測検証

背景:
- これまでの実験は machine_number レンジによる4島分類(island: main_jug/main_mix/bari/other)を
  グループ化単位として使っていた(avg Pearson=0.419, avg Top30%=0.519, 6ヶ月学習/1ヶ月検証)
- ユーザーから「予測の単位は machine_layout.section (501-522 のような物理区画、18区画)が
  より適切なのでは」という指摘があり、同条件(dd, dow, bucket, walk-forward 6mo/1mo)で
  section粒度に置き換えて island粒度の結果と比較する

検証対象:
- ベースライン同型モデル: over_104_rate ~ dd + dow + bucket + section (island の代わりに section)
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from catboost import CatBoostRegressor
from sklearn.metrics import mean_squared_error
from scipy.stats import pearsonr, spearmanr
import json
import warnings

warnings.filterwarnings('ignore')

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"
OUTPUT_JSON = Path(__file__).parent / "ml_section_group_regression_results.json"

EVENT_DAYS = {1, 4, 7, 14, 17, 24, 27, 30}
RANDOM_STATE = 42


def classify_bucket(dd, mm):
    if dd % 10 in (4, 7):
        return "x_day"
    if mm == dd:
        return "strong_zorome"
    if dd in (11, 22):
        return "date_tail_zorome"
    return "others"


def load_grouped_data():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql("""
        SELECT
            m.date, m.machine_number,
            m.games_normalized, m.diff_coins_normalized,
            COALESCE(ml.section, 'unknown') AS section
        FROM machine_detailed_results m
        LEFT JOIN machine_layout ml ON m.machine_number = ml.machine_number
        ORDER BY m.date
    """, conn)
    conn.close()

    df = df[df['section'] != 'unknown'].copy()
    df['date_obj'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['dd'] = df['date_obj'].dt.day
    df['mm'] = df['date_obj'].dt.month
    df['dow'] = df['date_obj'].dt.dayofweek
    df['is_event'] = df['dd'].isin(EVENT_DAYS).astype(int)
    df['kikaiwari'] = 100 + (df['diff_coins_normalized'] / (df['games_normalized'] * 3)) * 100
    df['target_104'] = (df['kikaiwari'] > 104).astype(int)

    grouped = df.groupby(['date_obj', 'section']).agg(
        over_104_rate=('target_104', 'mean'),
        avg_kikaiwari=('kikaiwari', 'mean'),
        n_machines=('machine_number', 'count'),
        dd=('dd', 'first'),
        dow=('dow', 'first'),
        mm=('mm', 'first'),
        is_event=('is_event', 'first'),
    ).reset_index().rename(columns={'date_obj': 'date'})
    grouped['bucket'] = [classify_bucket(d, m) for d, m in zip(grouped['dd'], grouped['mm'])]
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
                'test_end': test_end,
            })
        current_train_start = test_start
    return splits


def evaluate(y_test, y_pred, y_train):
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    baseline_pred = np.full_like(y_test, y_train.mean(), dtype=float)
    baseline_rmse = np.sqrt(mean_squared_error(y_test, baseline_pred))

    if len(set(y_pred)) > 1 and len(set(y_test)) > 1:
        pearson_corr, pearson_p = pearsonr(y_test, y_pred)
        spearman_corr, spearman_p = spearmanr(y_test, y_pred)
    else:
        pearson_corr, pearson_p = 0.0, 1.0
        spearman_corr, spearman_p = 0.0, 1.0

    n_top = max(1, int(len(y_test) * 0.3))
    pred_top = set(np.argsort(-y_pred)[:n_top])
    actual_top = set(np.argsort(-y_test)[:n_top])
    top30 = len(pred_top & actual_top) / n_top

    return {
        'rmse': float(rmse),
        'baseline_rmse': float(baseline_rmse),
        'rmse_improvement_pct': float((baseline_rmse - rmse) / baseline_rmse * 100) if baseline_rmse > 0 else 0.0,
        'pearson_corr': float(pearson_corr),
        'pearson_p': float(pearson_p),
        'spearman_corr': float(spearman_corr),
        'top30_overlap': float(top30),
    }


def run_split(df, split, features, cat_features):
    train_mask = (df['date'] >= split['train_start']) & (df['date'] < split['train_end'])
    test_mask = (df['date'] >= split['test_start']) & (df['date'] < split['test_end'])
    df_train = df[train_mask]
    df_test = df[test_mask]

    if len(df_train) < 50 or len(df_test) < 5:
        return None

    model = CatBoostRegressor(
        iterations=200, depth=4, learning_rate=0.05,
        random_state=RANDOM_STATE, verbose=0, cat_features=cat_features
    )
    model.fit(df_train[features], df_train['over_104_rate'], verbose=0)
    y_pred = model.predict(df_test[features])
    ev = evaluate(df_test['over_104_rate'].values, y_pred, df_train['over_104_rate'].values)

    return {
        'train_start': split['train_start'].strftime('%Y-%m-%d'),
        'test_start': split['test_start'].strftime('%Y-%m-%d'),
        'test_end': split['test_end'].strftime('%Y-%m-%d'),
        'train_size': len(df_train),
        'test_size': len(df_test),
        **ev,
    }


def main():
    print("=" * 80)
    print("Group-level (Section x Date) Regression vs Island-level baseline")
    print("=" * 80)

    df = load_grouped_data()
    print(f"\nGrouped rows: {len(df)} (date x section, {df['section'].nunique()} sections)")
    print(f"Section distribution:\n{df['section'].value_counts()}")
    print(f"\nover_104_rate stats: mean={df['over_104_rate'].mean():.3f}, std={df['over_104_rate'].std():.3f}")

    features = ['dd', 'dow', 'bucket', 'section']
    cat_features = ['bucket', 'section']
    splits = create_walk_forward_splits(df, train_months=6, test_months=1)
    print(f"\nWalk-forward splits: {len(splits)} (train=6mo, test=1mo)")

    results = []
    for i, split in enumerate(splits):
        r = run_split(df, split, features, cat_features)
        if r:
            results.append(r)
            print(f"\nSplit {i}: {r['test_start']} - {r['test_end']} (train={r['train_size']}, test={r['test_size']})")
            print(f"  Pearson={r['pearson_corr']:.3f} Spearman={r['spearman_corr']:.3f} "
                  f"Top30%={r['top30_overlap']:.3f} RMSE改善={r['rmse_improvement_pct']:+.1f}%")

    print("\n" + "=" * 80)
    print("Summary (avg across splits) -- Section grouping")
    print("=" * 80)
    if results:
        avg_pearson = np.mean([r['pearson_corr'] for r in results])
        avg_spearman = np.mean([r['spearman_corr'] for r in results])
        avg_top30 = np.mean([r['top30_overlap'] for r in results])
        avg_rmse_improve = np.mean([r['rmse_improvement_pct'] for r in results])

        print(f"Section粒度: avg Pearson={avg_pearson:.3f}, avg Spearman={avg_spearman:.3f}, "
              f"avg Top30%={avg_top30:.3f}, avg RMSE改善={avg_rmse_improve:+.1f}%")
        print(f"(参考)Island粒度ベースライン: avg Pearson=0.419, avg Top30%=0.519 (同一walk-forward条件)")
        print(f"差分: Pearson Δ={avg_pearson - 0.419:+.3f}, Top30% Δ={avg_top30 - 0.519:+.3f}")

        if avg_pearson > 0.419 + 0.02 and avg_top30 > 0.519:
            print("\n-> Section粒度の方が予測しやすい。粒度をsectionに切り替える価値あり。")
        elif abs(avg_pearson - 0.419) <= 0.02:
            print("\n-> Island粒度とほぼ同等。粒度変更による明確な利得はない。")
        else:
            print("\n-> Island粒度の方が優れる。section粒度は標本数減少・ノイズ増加のデメリットが上回る可能性。")

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {OUTPUT_JSON}")


if __name__ == '__main__':
    main()
