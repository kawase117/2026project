#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Island vs Section 比較(拡張版): 移動平均ラグ特徴量 + is_event/month_progress_rate を追加し、
ベースライン特徴量(dd, dow, bucket, group)に対する改善有無を island/section 両粒度で再比較する。

追加特徴量(すべて「予測当日より前のデータのみ」を使う、リーク防止済み):
- ma_all_N    : そのisland/sectionの直近N回(全期間)の over_104_rate 移動平均
- ma_event_N  : 同上、イベント日(is_event==1)の履歴に限定
- ma_bucket_N : 同上、当日と同じ bucket の履歴に限定
追加の静的特徴量:
- is_event           : イベント日フラグ(EVENT_DAYS={1,4,7,14,17,24,27,30})
- month_progress_rate: 月内進行度 = dd / その月の日数 (ml/feature_engineering.py の定義に準拠)

設計根拠:
- 過去のスタッキング失敗(同じ潜在因子からの派生値を追加)とは異なり、
  ここで追加するのは「over_104_rate自身の過去の値」であり、独立した時系列構造由来の情報。
  リーク防止のため shift 済み(当日のデータは履歴に含めない)。
- N=5 (各系列で直近5件): event/bucket限定系列は出現頻度が低い(月数回)ため、
  Nを大きくしすぎると数ヶ月分のデータが必要になり初期に欠損(NaN)が増える。CatBoostはNaNをネイティブ処理する。

検証マトリクス: {island, section} x {baseline特徴量, 拡張特徴量}
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
OUTPUT_JSON = Path(__file__).parent / "ml_island_section_lag_comparison_results.json"

EVENT_DAYS = {1, 4, 7, 14, 17, 24, 27, 30}
RANDOM_STATE = 42
LAG_N = 5


def classify_bucket(dd, mm):
    if dd % 10 in (4, 7):
        return "x_day"
    if mm == dd:
        return "strong_zorome"
    if dd in (11, 22):
        return "date_tail_zorome"
    return "others"


def assign_island(machine_num):
    if machine_num < 641:
        return 'other'
    elif machine_num < 692:
        return 'main_jug'
    elif machine_num < 832:
        return 'main_mix'
    else:
        return 'bari'


def load_raw():
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

    df['date_obj'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['dd'] = df['date_obj'].dt.day
    df['mm'] = df['date_obj'].dt.month
    df['dow'] = df['date_obj'].dt.dayofweek
    df['days_in_month'] = df['date_obj'].dt.daysinmonth
    df['month_progress_rate'] = df['dd'] / df['days_in_month']
    df['is_event'] = df['dd'].isin(EVENT_DAYS).astype(int)
    df['kikaiwari'] = 100 + (df['diff_coins_normalized'] / (df['games_normalized'] * 3)) * 100
    df['target_104'] = (df['kikaiwari'] > 104).astype(int)
    df['island'] = df['machine_number'].apply(assign_island)
    return df


def build_grouped(df, group_col, exclude_values=None):
    work = df if exclude_values is None else df[~df[group_col].isin(exclude_values)]
    grouped = work.groupby(['date_obj', group_col]).agg(
        over_104_rate=('target_104', 'mean'),
        dd=('dd', 'first'),
        dow=('dow', 'first'),
        mm=('mm', 'first'),
        is_event=('is_event', 'first'),
        month_progress_rate=('month_progress_rate', 'first'),
    ).reset_index().rename(columns={'date_obj': 'date'})
    grouped['bucket'] = [classify_bucket(d, m) for d, m in zip(grouped['dd'], grouped['mm'])]
    return grouped


def add_trailing_lag_features(grouped, group_col, n=LAG_N):
    """当日より前のデータのみを使った移動平均特徴量を追加(リーク防止)"""
    grouped = grouped.sort_values([group_col, 'date']).reset_index(drop=True)
    ma_all = np.full(len(grouped), np.nan)
    ma_event = np.full(len(grouped), np.nan)
    ma_bucket = np.full(len(grouped), np.nan)

    for _, sub in grouped.groupby(group_col, sort=False):
        sub = sub.sort_values('date')
        all_hist, event_hist = [], []
        bucket_hist = {}
        for i, row in zip(sub.index, sub.itertuples()):
            if all_hist:
                ma_all[i] = np.mean(all_hist[-n:])
            if event_hist:
                ma_event[i] = np.mean(event_hist[-n:])
            bh = bucket_hist.get(row.bucket, [])
            if bh:
                ma_bucket[i] = np.mean(bh[-n:])

            all_hist.append(row.over_104_rate)
            if row.is_event == 1:
                event_hist.append(row.over_104_rate)
            bucket_hist.setdefault(row.bucket, []).append(row.over_104_rate)

    # NaN(まだ履歴が蓄積されていない初期行)はセンチネル値(-1)で埋める。
    # over_104_rateは[0,1]の連続値のため、-1は「履歴なし」を示す明確に分離した値になる。
    # (CatBoost on Windowsでこの種のNaN混在数値特徴量が "bad allocation" を起こすケースの回避策)
    grouped[f'ma_all_{n}'] = pd.Series(ma_all).fillna(-1.0).values
    grouped[f'ma_event_{n}'] = pd.Series(ma_event).fillna(-1.0).values
    grouped[f'ma_bucket_{n}'] = pd.Series(ma_bucket).fillna(-1.0).values
    return grouped.sort_values('date').reset_index(drop=True)


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
                'train_start': current_train_start, 'train_end': train_end,
                'test_start': test_start, 'test_end': test_end,
            })
        current_train_start = test_start
    return splits


def evaluate(y_test, y_pred, y_train):
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    baseline_pred = np.full_like(y_test, y_train.mean(), dtype=float)
    baseline_rmse = np.sqrt(mean_squared_error(y_test, baseline_pred))
    if len(set(y_pred)) > 1 and len(set(y_test)) > 1:
        pearson_corr, pearson_p = pearsonr(y_test, y_pred)
        spearman_corr, _ = spearmanr(y_test, y_pred)
    else:
        pearson_corr, pearson_p, spearman_corr = 0.0, 1.0, 0.0
    n_top = max(1, int(len(y_test) * 0.3))
    pred_top = set(np.argsort(-y_pred)[:n_top])
    actual_top = set(np.argsort(-y_test)[:n_top])
    top30 = len(pred_top & actual_top) / n_top
    return {
        'rmse': float(rmse),
        'rmse_improvement_pct': float((baseline_rmse - rmse) / baseline_rmse * 100) if baseline_rmse > 0 else 0.0,
        'pearson_corr': float(pearson_corr),
        'pearson_p': float(pearson_p),
        'spearman_corr': float(spearman_corr),
        'top30_overlap': float(top30),
    }


def run_split(df, split, features, cat_features):
    train_mask = (df['date'] >= split['train_start']) & (df['date'] < split['train_end'])
    test_mask = (df['date'] >= split['test_start']) & (df['date'] < split['test_end'])
    df_train, df_test = df[train_mask], df[test_mask]
    if len(df_train) < 50 or len(df_test) < 5:
        return None
    model = CatBoostRegressor(
        iterations=200, depth=4, learning_rate=0.05,
        random_state=RANDOM_STATE, verbose=0, cat_features=cat_features,
        allow_writing_files=False
    )
    model.fit(df_train[features], df_train['over_104_rate'], verbose=0)
    y_pred = model.predict(df_test[features])
    return evaluate(df_test['over_104_rate'].values, y_pred, df_train['over_104_rate'].values)


def run_scenario(grouped, group_col, label):
    grouped = add_trailing_lag_features(grouped, group_col, LAG_N)
    base_features = ['dd', 'dow', 'bucket', group_col]
    ext_features = base_features + ['is_event', 'month_progress_rate',
                                    f'ma_all_{LAG_N}', f'ma_event_{LAG_N}', f'ma_bucket_{LAG_N}']
    splits = create_walk_forward_splits(grouped)

    out = {'label': label, 'n_groups': int(grouped[group_col].nunique()), 'n_rows': len(grouped),
           'baseline': [], 'extended': []}
    for split in splits:
        b = run_split(grouped, split, base_features, [group_col, 'bucket'])
        e = run_split(grouped, split, ext_features, [group_col, 'bucket'])
        if b:
            out['baseline'].append(b)
        if e:
            out['extended'].append(e)
    return out


def summarize(results_block):
    rows = results_block
    if not rows:
        return None
    return {
        'avg_pearson': float(np.mean([r['pearson_corr'] for r in rows])),
        'avg_spearman': float(np.mean([r['spearman_corr'] for r in rows])),
        'avg_top30': float(np.mean([r['top30_overlap'] for r in rows])),
        'avg_rmse_improve': float(np.mean([r['rmse_improvement_pct'] for r in rows])),
    }


def _catboost_warmup():
    """CatBoost Windows+Python 3.14 workaround: 最初の fit() が bad allocation で落ちる問題。
    ダミーデータで1回 fit を先行させて内部スレッドプール/メモリアリーナを初期化する。"""
    dummy_X = pd.DataFrame({'a': np.arange(20, dtype=float), 'b': np.arange(20, dtype=float)})
    dummy_y = np.arange(20, dtype=float)
    CatBoostRegressor(iterations=10, depth=2, verbose=0, allow_writing_files=False).fit(dummy_X, dummy_y)


def main():
    print("=" * 80)
    print(f"Island vs Section x {{baseline, +lag特徴量(N={LAG_N})}} 比較")
    print("=" * 80)

    _catboost_warmup()

    df = load_raw()

    scenarios = [
        ('island', build_grouped(df, 'island', exclude_values=['other']), 'island(3島: main_jug/main_mix/bari)'),
        ('section', build_grouped(df, 'section', exclude_values=['unknown']), 'section(18区画)'),
    ]

    final = {}
    for group_col, grouped, label in scenarios:
        print(f"\n--- {label}: {grouped[group_col].nunique()}グループ, {len(grouped)}行 ---")
        result = run_scenario(grouped, group_col, label)
        final[group_col] = result

        base_summary = summarize(result['baseline'])
        ext_summary = summarize(result['extended'])
        print(f"  [baseline]      avg Pearson={base_summary['avg_pearson']:.3f} "
              f"avg Top30%={base_summary['avg_top30']:.3f} avg RMSE改善={base_summary['avg_rmse_improve']:+.1f}%")
        print(f"  [+lag特徴量]    avg Pearson={ext_summary['avg_pearson']:.3f} "
              f"avg Top30%={ext_summary['avg_top30']:.3f} avg RMSE改善={ext_summary['avg_rmse_improve']:+.1f}%")
        print(f"  差分: Pearson Δ={ext_summary['avg_pearson']-base_summary['avg_pearson']:+.3f}, "
              f"Top30% Δ={ext_summary['avg_top30']-base_summary['avg_top30']:+.3f}")
        final[group_col]['summary'] = {'baseline': base_summary, 'extended': ext_summary}

    print("\n" + "=" * 80)
    print("総合比較 (拡張特徴量込み)")
    print("=" * 80)
    isl = final['island']['summary']['extended']
    sec = final['section']['summary']['extended']
    print(f"Island(+lag): avg Pearson={isl['avg_pearson']:.3f} avg Top30%={isl['avg_top30']:.3f}")
    print(f"Section(+lag): avg Pearson={sec['avg_pearson']:.3f} avg Top30%={sec['avg_top30']:.3f}")

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {OUTPUT_JSON}")


if __name__ == '__main__':
    main()
