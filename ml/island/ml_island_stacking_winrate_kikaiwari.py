#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スタッキング実験: win_rate予測値 + avg_kikaiwari予測値 を特徴量として
over_104_rate を予測するメタモデルが、単独モデルより優れるかを検証する。

設計根拠:
- over_104_rate と win_rate の実測相関は 0.536（意味のある橋渡し信号）
- over_104_rate と avg_kikaiwari の実測相関は 0.099（弱いが診断価値あり）
- over_104_rate と avg_games の実測相関は 0.030（構造的に無関係 -> メタ特徴量から除外）
- 過去の教訓: 同じ潜在変数の閾値射影(over_104/under_100)を単純合成すると劣化する
  -> 単純演算ではなく学習型メタモデル(スタッキング)を採用し、サブモデルにはOOF予測を使う

検証対象:
1. ベースライン: over_104_rate単独モデル (dd, dow, bucket, island)
2. スタッキング: 上記 + win_rate_pred(OOF) + kikaiwari_pred(OOF)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from catboost import CatBoostRegressor
from sklearn.model_selection import KFold
from sklearn.metrics import mean_squared_error
from scipy.stats import pearsonr, spearmanr
import json
import warnings

warnings.filterwarnings('ignore')

DATA_CSV = Path(__file__).parent / "ml_data_island_submodel.csv"
OUTPUT_JSON = Path(__file__).parent / "ml_island_stacking_winrate_kikaiwari_results.json"

N_FOLDS = 5
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
    df = pd.read_csv(DATA_CSV)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['win'] = (df['diff_coins_normalized'] > 0).astype(int)
    df['mm'] = df['date'].dt.month

    grouped = df.groupby(['date', 'island']).agg(
        over_104_rate=('target_104', 'mean'),
        win_rate=('win', 'mean'),
        avg_kikaiwari=('kikaiwari', 'mean'),
        dd=('dd', 'first'),
        dow=('dow', 'first'),
        mm=('mm', 'first'),
        is_event=('is_event', 'first'),
    ).reset_index()
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


def fit_predict(X_train, y_train, X_test):
    model = CatBoostRegressor(
        iterations=200, depth=4, learning_rate=0.05,
        random_state=RANDOM_STATE, verbose=0, cat_features=['island', 'bucket']
    )
    model.fit(X_train, y_train, verbose=0)
    return model.predict(X_test)


def oof_predictions(df_train, feature_cols, target_col):
    """train窓内でK-fold out-of-fold予測を生成(メタ特徴量のリーク防止)"""
    oof = np.zeros(len(df_train))
    kf = KFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    X = df_train[feature_cols].reset_index(drop=True)
    y = df_train[target_col].reset_index(drop=True)
    for tr_idx, val_idx in kf.split(X):
        oof[val_idx] = fit_predict(X.iloc[tr_idx], y.iloc[tr_idx], X.iloc[val_idx])
    return oof


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


def run_split(df, split):
    train_mask = (df['date'] >= split['train_start']) & (df['date'] < split['train_end'])
    test_mask = (df['date'] >= split['test_start']) & (df['date'] < split['test_end'])
    df_train = df[train_mask].reset_index(drop=True)
    df_test = df[test_mask].reset_index(drop=True)

    if len(df_train) < 50 or len(df_test) < 5:
        return None

    base_features = ['dd', 'dow', 'bucket', 'island']

    # --- ベースライン: over_104_rate単独モデル ---
    base_pred = fit_predict(df_train[base_features], df_train['over_104_rate'], df_test[base_features])
    base_eval = evaluate(df_test['over_104_rate'].values, base_pred, df_train['over_104_rate'].values)

    # --- サブモデル(win_rate, avg_kikaiwari)のOOF予測(train) + test予測 ---
    df_train = df_train.copy()
    df_train['win_rate_pred'] = oof_predictions(df_train, base_features, 'win_rate')
    df_train['kikaiwari_pred'] = oof_predictions(df_train, base_features, 'avg_kikaiwari')

    df_test = df_test.copy()
    df_test['win_rate_pred'] = fit_predict(df_train[base_features], df_train['win_rate'], df_test[base_features])
    df_test['kikaiwari_pred'] = fit_predict(df_train[base_features], df_train['avg_kikaiwari'], df_test[base_features])

    # --- メタモデル: ベースライン特徴量 + サブモデル予測値 ---
    meta_features = base_features + ['win_rate_pred', 'kikaiwari_pred']
    meta_pred = fit_predict(df_train[meta_features], df_train['over_104_rate'], df_test[meta_features])
    meta_eval = evaluate(df_test['over_104_rate'].values, meta_pred, df_train['over_104_rate'].values)

    # サブモデル自体の予測力(参考: test windowでの精度)
    win_eval = evaluate(df_test['win_rate'].values, df_test['win_rate_pred'].values, df_train['win_rate'].values)
    kik_eval = evaluate(df_test['avg_kikaiwari'].values, df_test['kikaiwari_pred'].values, df_train['avg_kikaiwari'].values)

    return {
        'train_start': split['train_start'].strftime('%Y-%m-%d'),
        'test_start': split['test_start'].strftime('%Y-%m-%d'),
        'test_end': split['test_end'].strftime('%Y-%m-%d'),
        'test_size': len(df_test),
        'baseline_over104': base_eval,
        'meta_over104': meta_eval,
        'submodel_win_rate': win_eval,
        'submodel_kikaiwari': kik_eval,
        'improvement_meta_vs_baseline': {
            'pearson_delta': float(meta_eval['pearson_corr'] - base_eval['pearson_corr']),
            'top30_delta': float(meta_eval['top30_overlap'] - base_eval['top30_overlap']),
        }
    }


def main():
    print("=" * 80)
    print("スタッキング実験: win_rate + avg_kikaiwari -> over_104_rate メタモデル")
    print("=" * 80)

    df = load_grouped_data()
    print(f"\nGrouped rows: {len(df)}")
    print(f"Bucket distribution:\n{df['bucket'].value_counts()}")

    splits = create_walk_forward_splits(df)
    print(f"\nWalk-forward splits: {len(splits)}")

    results = []
    for i, split in enumerate(splits):
        r = run_split(df, split)
        if r:
            results.append(r)
            print(f"\nSplit {i}: {r['test_start']} - {r['test_end']} (n={r['test_size']})")
            b, m = r['baseline_over104'], r['meta_over104']
            print(f"  [ベースライン]   Pearson={b['pearson_corr']:.3f} Top30%={b['top30_overlap']:.3f} RMSE改善={b['rmse_improvement_pct']:+.1f}%")
            print(f"  [スタッキング]   Pearson={m['pearson_corr']:.3f} Top30%={m['top30_overlap']:.3f} RMSE改善={m['rmse_improvement_pct']:+.1f}%")
            d = r['improvement_meta_vs_baseline']
            print(f"  [差分]          Pearson Δ={d['pearson_delta']:+.3f} Top30% Δ={d['top30_delta']:+.3f}")
            print(f"  (参考)サブモデル: win_rate Pearson={r['submodel_win_rate']['pearson_corr']:.3f}, "
                  f"kikaiwari Pearson={r['submodel_kikaiwari']['pearson_corr']:.3f}")

    print("\n" + "=" * 80)
    print("Summary (avg across splits)")
    print("=" * 80)
    if results:
        avg_base_pearson = np.mean([r['baseline_over104']['pearson_corr'] for r in results])
        avg_meta_pearson = np.mean([r['meta_over104']['pearson_corr'] for r in results])
        avg_base_top30 = np.mean([r['baseline_over104']['top30_overlap'] for r in results])
        avg_meta_top30 = np.mean([r['meta_over104']['top30_overlap'] for r in results])

        print(f"ベースライン: avg Pearson={avg_base_pearson:.3f}, avg Top30%={avg_base_top30:.3f}")
        print(f"スタッキング: avg Pearson={avg_meta_pearson:.3f}, avg Top30%={avg_meta_top30:.3f}")
        print(f"差分:        Pearson Δ={avg_meta_pearson - avg_base_pearson:+.3f}, Top30% Δ={avg_meta_top30 - avg_base_top30:+.3f}")

        if avg_meta_pearson > avg_base_pearson + 0.02 and avg_meta_top30 > avg_base_top30:
            print("\n-> スタッキングはベースラインを上回る。組み合わせに価値あり。")
        elif abs(avg_meta_pearson - avg_base_pearson) <= 0.02:
            print("\n-> ほぼ差なし。組み合わせの価値は限定的(複雑性増加に見合わない可能性)。")
        else:
            print("\n-> スタッキングはベースラインを下回る。単純な組み合わせは推奨しない(過去の同類射影合成の劣化と同型)。")

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {OUTPUT_JSON}")


if __name__ == '__main__':
    main()
