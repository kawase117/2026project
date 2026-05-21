#!/usr/bin/env python3
"""
末尾の相対ランキング分析 - データドリブンなパターン発見

各日ごとに末尾をランキングし、日付属性（DD、曜日）別に
ランキング出現パターンを分析。給料日などの仮説ではなく、
データが示す最も強いパターンを発見する。
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import json
from scipy.stats import chi2_contingency

def load_hall_data(db_path: str, start_date: str, end_date: str) -> pd.DataFrame:
    """指定期間のデータを読み込み"""
    conn = sqlite3.connect(db_path)
    query = """
    SELECT
        date,
        last_digit,
        games_normalized,
        diff_coins_normalized
    FROM machine_detailed_results
    WHERE date >= ? AND date <= ?
    ORDER BY date
    """
    df = pd.read_sql_query(query, conn, params=(start_date, end_date))
    conn.close()

    # 日付を解析
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
    df['dd'] = df['date'].dt.day
    df['weekday'] = df['date'].dt.day_name()
    df['last_digit'] = df['last_digit'].astype(str)

    # ラベル生成：高利益台（G数>=2000かつ差枚>=1000）
    df['is_high_profit'] = (
        (df['games_normalized'] >= 2000) &
        (df['diff_coins_normalized'] >= 1000)
    ).astype(int)

    return df

def compute_daily_rankings(df: pd.DataFrame) -> pd.DataFrame:
    """各日ごとに末尾をランキング"""
    daily_rankings = []

    for date in sorted(df['date'].unique()):
        df_day = df[df['date'] == date]

        if len(df_day) == 0:
            continue

        # 日付情報
        day_info = df_day.iloc[0]
        dd = day_info['dd']
        weekday = day_info['weekday']

        # 末尾別に高利益率を計算
        tail_stats = {}
        for tail in sorted(df_day['last_digit'].unique()):
            df_tail = df_day[df_day['last_digit'] == tail]
            win_rate = df_tail['is_high_profit'].mean() * 100
            count = len(df_tail)
            tail_stats[tail] = {
                'win_rate': win_rate,
                'count': count,
            }

        # ランキング作成（高い順）
        ranking = sorted(tail_stats.items(), key=lambda x: x[1]['win_rate'], reverse=True)

        for rank, (tail, stats) in enumerate(ranking, 1):
            daily_rankings.append({
                'date': date,
                'dd': dd,
                'weekday': weekday,
                'tail': tail,
                'rank': rank,
                'win_rate': stats['win_rate'],
                'count': stats['count'],
            })

    return pd.DataFrame(daily_rankings)

def analyze_ranking_patterns(rankings_df: pd.DataFrame) -> dict:
    """ランキングパターンを分析"""
    results = {
        'overall_statistics': {},
        'dd_patterns': {},
        'weekday_patterns': {},
        'chi_square_tests': {},
    }

    # 全体統計：各末尾がTop K に出現する頻度
    for k in [1, 3, 5]:
        top_k_df = rankings_df[rankings_df['rank'] <= k]
        top_k_counts = top_k_df['tail'].value_counts()
        total_days = rankings_df['date'].nunique()

        top_k_pcts = {}
        for tail in sorted(map(str, range(10))):
            count = top_k_counts.get(tail, 0)
            pct = (count / total_days) * 100
            top_k_pcts[tail] = {
                'count': int(count),
                'percentage': float(pct),
                'expected_random': float(100 * k / 10),
                'strength': float(pct - (100 * k / 10)),
            }

        results['overall_statistics'][f'top_{k}'] = top_k_pcts

    # DD別パターン
    for dd in sorted(rankings_df['dd'].unique()):
        dd_df = rankings_df[rankings_df['dd'] == dd]
        dd_top3_df = dd_df[dd_df['rank'] <= 3]
        dd_total_days = dd_df['date'].nunique()

        dd_pcts = {}
        for tail in sorted(map(str, range(10))):
            count = (dd_top3_df['tail'] == tail).sum()
            pct = (count / dd_total_days) * 100 if dd_total_days > 0 else 0
            dd_pcts[tail] = {
                'count': int(count),
                'percentage': float(pct),
                'n_days': int(dd_total_days),
            }

        results['dd_patterns'][f'dd_{dd:02d}'] = dd_pcts

    # 曜日別パターン
    for weekday in sorted(rankings_df['weekday'].unique()):
        wd_df = rankings_df[rankings_df['weekday'] == weekday]
        wd_top3_df = wd_df[wd_df['rank'] <= 3]
        wd_total_days = wd_df['date'].nunique()

        wd_pcts = {}
        for tail in sorted(map(str, range(10))):
            count = (wd_top3_df['tail'] == tail).sum()
            pct = (count / wd_total_days) * 100 if wd_total_days > 0 else 0
            wd_pcts[tail] = {
                'count': int(count),
                'percentage': float(pct),
                'n_days': int(wd_total_days),
            }

        results['weekday_patterns'][weekday] = wd_pcts

    # Chi-square検定：末尾 vs DD
    contingency_dd = pd.crosstab(rankings_df['tail'], rankings_df['dd'])
    chi2_dd, p_dd, dof_dd, expected_dd = chi2_contingency(contingency_dd)

    results['chi_square_tests']['tail_vs_dd'] = {
        'chi_square': float(chi2_dd),
        'p_value': float(p_dd),
        'dof': int(dof_dd),
        'significant': bool(p_dd < 0.05),
        'interpretation': '末尾とDDは独立していない（関連あり）' if p_dd < 0.05 else '末尾とDDは独立している（関連なし）',
    }

    # Chi-square検定：末尾 vs 曜日
    contingency_wd = pd.crosstab(rankings_df['tail'], rankings_df['weekday'])
    chi2_wd, p_wd, dof_wd, _ = chi2_contingency(contingency_wd)

    results['chi_square_tests']['tail_vs_weekday'] = {
        'chi_square': float(chi2_wd),
        'p_value': float(p_wd),
        'dof': int(dof_wd),
        'significant': bool(p_wd < 0.05),
        'interpretation': '末尾と曜日は独立していない（関連あり）' if p_wd < 0.05 else '末尾と曜日は独立している（関連なし）',
    }

    return results

def main():
    """メイン処理"""
    # DBパスの解決
    candidates = [
        Path(__file__).parent / "../../db/マルハンメガシティ2000-蒲田7.db",
        Path("db/マルハンメガシティ2000-蒲田7.db"),
        Path("C:/Users/apto117/Documents/pachinko-analyzer/src/2026project/db/マルハンメガシティ2000-蒲田7.db"),
    ]

    db_path = None
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            db_path = resolved
            print(f"✓ Found DB: {db_path}")
            break

    if db_path is None:
        print(f"❌ DB file not found")
        return

    hall_name = "マルハンメガシティ2000-蒲田7"

    print(f"\n{'#'*80}")
    print(f"# Last Digit Relative Ranking Analysis (Data-Driven)")
    print(f"# {hall_name}")
    print(f"{'#'*80}")

    # データ読み込み
    print(f"\n🔍 Loading data...")
    df = load_hall_data(db_path, "20250707", "20251231")
    print(f"  Data rows: {len(df)}")
    print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")
    print(f"  Unique days: {df['date'].nunique()}")

    # 日ごとランキング計算
    print(f"\n📊 Computing daily rankings...")
    rankings_df = compute_daily_rankings(df)
    print(f"  Total ranking records: {len(rankings_df)}")

    # パターン分析
    print(f"\n🔬 Analyzing ranking patterns...")
    analysis_results = analyze_ranking_patterns(rankings_df)

    # 結果表示：全体統計
    print(f"\n{'='*80}")
    print(f"📈 Overall Statistics: Top 3 Ranking Appearance Frequency")
    print(f"{'='*80}\n")

    top3_results = analysis_results['overall_statistics']['top_3']
    sorted_tails = sorted(top3_results.items(),
                         key=lambda x: x[1]['percentage'],
                         reverse=True)

    for tail, stats in sorted_tails:
        strength_sign = "▲" if stats['strength'] > 0 else "▼" if stats['strength'] < 0 else "="
        print(f"  末尾{tail}: {stats['percentage']:5.1f}% "
              f"(期待値: {stats['expected_random']:5.1f}%) "
              f"{strength_sign} ({stats['strength']:+5.1f}pp) "
              f"[{stats['count']} days]")

    # Chi-square結果
    print(f"\n{'='*80}")
    print(f"🔬 Chi-Square Tests: Pattern Significance")
    print(f"{'='*80}\n")

    for test_name, test_results in analysis_results['chi_square_tests'].items():
        significant = "⭐ 有意" if test_results['significant'] else "  無意"
        print(f"{test_name}:")
        print(f"  χ² = {test_results['chi_square']:.2f}, p = {test_results['p_value']:.4f} {significant}")
        if 'interpretation' in test_results:
            print(f"  → {test_results['interpretation']}")

    # DD別パターン：最も強い関連を探す
    print(f"\n{'='*80}")
    print(f"🎯 Strongest DD Patterns (Top 3 Appearances)")
    print(f"{'='*80}\n")

    dd_strength = {}
    for dd_key, dd_pcts in analysis_results['dd_patterns'].items():
        dd_num = int(dd_key.split('_')[1])

        # 各末尾の期待値からの偏差を計算
        max_strength = 0
        max_tail = None
        for tail, stats in dd_pcts.items():
            strength = stats['percentage'] - 30
            if abs(strength) > max_strength:
                max_strength = abs(strength)
                max_tail = tail

        if max_strength > 5:
            dd_strength[dd_num] = {
                'tail': max_tail,
                'strength': max_strength,
                'percentage': dd_pcts[max_tail]['percentage'],
                'n_days': dd_pcts[max_tail]['n_days'],
            }

    if dd_strength:
        sorted_dd = sorted(dd_strength.items(),
                          key=lambda x: x[1]['strength'],
                          reverse=True)
        for dd, info in sorted_dd[:5]:
            print(f"  DD {dd:02d}: 末尾{info['tail']} が Top 3 に {info['percentage']:.1f}% "
                  f"({info['strength']:+.1f}pp, n={info['n_days']} days)")
    else:
        print("  (特に強いDD別パターンなし)")

    # 曜日別パターン
    print(f"\n{'='*80}")
    print(f"🎯 Strongest Weekday Patterns (Top 3 Appearances)")
    print(f"{'='*80}\n")

    wd_strength = {}
    for weekday, wd_pcts in analysis_results['weekday_patterns'].items():
        max_strength = 0
        max_tail = None
        for tail, stats in wd_pcts.items():
            strength = stats['percentage'] - 30
            if abs(strength) > max_strength:
                max_strength = abs(strength)
                max_tail = tail

        if max_strength > 5:
            wd_strength[weekday] = {
                'tail': max_tail,
                'strength': max_strength,
                'percentage': wd_pcts[max_tail]['percentage'],
                'n_days': wd_pcts[max_tail]['n_days'],
            }

    if wd_strength:
        for weekday, info in wd_strength.items():
            print(f"  {weekday}: 末尾{info['tail']} が Top 3 に {info['percentage']:.1f}% "
                  f"({info['strength']:+.1f}pp, n={info['n_days']} days)")
    else:
        print("  (特に強い曜日別パターンなし)")

    # JSON出力
    print(f"\n📋 Exporting full analysis to JSON...")
    script_dir = Path(__file__).parent
    output_dir = script_dir / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_output = {
        "metadata": {
            "hall_name": hall_name,
            "analysis_period": f"{df['date'].min().date()} to {df['date'].max().date()}",
            "total_days": int(df['date'].nunique()),
        },
        "analysis_results": analysis_results,
        "dd_strength_ranking": {str(k): v for k, v in sorted(dd_strength.items(), key=lambda x: x[1]['strength'], reverse=True)},
        "weekday_strength_ranking": wd_strength,
    }

    safe_hall_name = hall_name.replace('/', '_').replace('\\', '_')
    json_path = output_dir / f'tail_ranking_analysis_{safe_hall_name}.json'

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)

    print(f"✓ JSON exported: {json_path}")

    # 結論
    print(f"\n{'='*80}")
    print(f"💡 Conclusion")
    print(f"{'='*80}\n")

    if analysis_results['chi_square_tests']['tail_vs_dd']['significant']:
        print(f"✓ 末尾ランキングとDDに統計的に有意な関連あり (p < 0.05)")
        print(f"  → ML的に有用な可能性あり")
    else:
        print(f"⚠️  末尾ランキングとDDに有意な関連なし")

    if analysis_results['chi_square_tests']['tail_vs_weekday']['significant']:
        print(f"\n✓ 末尾ランキングと曜日に統計的に有意な関連あり (p < 0.05)")
        print(f"  → ML的に有用な可能性あり")
    else:
        print(f"\n⚠️  末尾ランキングと曜日に有意な関連なし")

if __name__ == "__main__":
    main()
