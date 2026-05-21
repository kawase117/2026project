#!/usr/bin/env python3
"""
末尾 × DD（月内日付）相互作用特徴量の分析
マルハンメガシティ2000-蒲田7 専用

仮説: 給料日（20-25日）周辺では末尾0に高設定が集中し、
      月初・月末では末尾を分散させる可能性がある
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
import json

# 日本語フォント設定
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def load_hall_data(db_path: str, start_date: str, end_date: str, period_name: str) -> pd.DataFrame:
    """指定期間のデータを読み込み、DD（月内日付）を抽出"""
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
    df['dd'] = df['date'].dt.day  # 月内日付（1-31）
    df['last_digit'] = df['last_digit'].astype(str)

    # ラベル生成：高利益台（G数>=2000かつ差枚>=1000）
    df['is_high_profit'] = (
        (df['games_normalized'] >= 2000) &
        (df['diff_coins_normalized'] >= 1000)
    ).astype(int)

    df['period'] = period_name

    return df

def analyze_tail_dd_interaction(df: pd.DataFrame, period_name: str):
    """DD × 末尾 クロス集計で高利益率を計算"""
    print(f"\n{'='*80}")
    print(f"📊 {period_name}")
    print(f"{'='*80}\n")

    # DD × 末尾 でクロス集計
    pivot = df.pivot_table(
        values='is_high_profit',
        index='dd',
        columns='last_digit',
        aggfunc=['mean', 'count']
    ) * 100  # パーセント変換

    # 高利益率のみを抽出
    win_rates = pivot['mean'].fillna(0)

    # 見やすく表示
    print(f"高利益率 (%) - DD（月内日付）× 末尾")
    print(f"{'-'*100}")
    print(win_rates.round(1).to_string())
    print(f"{'-'*100}\n")

    # サマリー統計
    print(f"統計サマリー:")
    for tail in sorted(win_rates.columns):
        col_data = win_rates[tail].dropna()
        print(f"  末尾{tail}: 平均 {col_data.mean():.1f}% "
              f"(σ={col_data.std():.1f}, 範囲={col_data.min():.1f}-{col_data.max():.1f}%)")

    # 給料日周辺（20-25日）のパターンを強調
    print(f"\n💰 給料日周辺パターン（20-25日）:")
    dd_payroll = win_rates.loc[20:25]
    for tail in sorted(win_rates.columns):
        mean_payroll = dd_payroll[tail].mean()
        mean_overall = win_rates[tail].mean()
        delta = mean_payroll - mean_overall
        sign = "▲" if delta > 0 else "▼" if delta < 0 else "="
        print(f"  末尾{tail}: {mean_payroll:.1f}% {sign} ({delta:+.1f}pp vs 平均)")

    # 月初（1-10日）のパターンを強調
    print(f"\n📅 月初パターン（1-10日）:")
    dd_early = win_rates.loc[1:10]
    for tail in sorted(win_rates.columns):
        mean_early = dd_early[tail].mean()
        mean_overall = win_rates[tail].mean()
        delta = mean_early - mean_overall
        sign = "▲" if delta > 0 else "▼" if delta < 0 else "="
        print(f"  末尾{tail}: {mean_early:.1f}% {sign} ({delta:+.1f}pp vs 平均)")

    return win_rates

def create_heatmap(win_rates_train: pd.DataFrame, win_rates_test: pd.DataFrame,
                   hall_name: str, output_dir: Path = None):
    """ヒートマップを作成して保存"""

    if output_dir is None:
        output_dir = Path(".")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    # 2つのヒートマップを横並びで作成
    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    # 訓練期間
    sns.heatmap(
        win_rates_train,
        annot=True,
        fmt='.1f',
        cmap='RdYlGn',
        vmin=0,
        vmax=40,
        cbar_kws={'label': 'High Profit Rate (%)'},
        ax=axes[0]
    )
    axes[0].set_title(f'{hall_name} - Train Period (2025-07-07 to 2025-11-01)', fontsize=14, fontweight='bold')
    axes[0].set_xlabel('Last Digit', fontsize=12)
    axes[0].set_ylabel('Day of Month (DD)', fontsize=12)

    # テスト期間
    sns.heatmap(
        win_rates_test,
        annot=True,
        fmt='.1f',
        cmap='RdYlGn',
        vmin=0,
        vmax=40,
        cbar_kws={'label': 'High Profit Rate (%)'},
        ax=axes[1]
    )
    axes[1].set_title(f'{hall_name} - Test Period (2025-11-01 to 2025-12-31)', fontsize=14, fontweight='bold')
    axes[1].set_xlabel('Last Digit', fontsize=12)
    axes[1].set_ylabel('Day of Month (DD)', fontsize=12)

    plt.tight_layout()

    # ファイル名（特殊文字を削除）
    safe_hall_name = hall_name.replace('/', '_').replace('\\', '_')
    output_path = output_dir / f'tail_dd_heatmap_{safe_hall_name}.png'

    try:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"\n✓ Heatmap saved: {output_path}")
    except Exception as e:
        print(f"\n⚠️  Heatmap save failed: {e}")

    plt.close()  # Don't show interactively; just save

def export_to_json(win_rates_train: pd.DataFrame, win_rates_test: pd.DataFrame,
                   hall_name: str, output_dir: Path = None) -> dict:
    """分析結果を JSON 形式で出力"""

    if output_dir is None:
        output_dir = Path(".")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    # 訓練期間の統計
    train_stats = {}
    for tail in sorted(win_rates_train.columns):
        col_data = win_rates_train[tail].dropna()
        train_stats[tail] = {
            "mean": float(col_data.mean()),
            "std": float(col_data.std()),
            "min": float(col_data.min()),
            "max": float(col_data.max()),
        }

    # テスト期間の統計
    test_stats = {}
    for tail in sorted(win_rates_test.columns):
        col_data = win_rates_test[tail].dropna()
        test_stats[tail] = {
            "mean": float(col_data.mean()),
            "std": float(col_data.std()),
            "min": float(col_data.min()),
            "max": float(col_data.max()),
        }

    # ドリフト分析
    drift_stats = {}
    for tail in train_stats.keys():
        train_mean = train_stats[tail]["mean"]
        test_mean = test_stats[tail]["mean"]
        drift = test_mean - train_mean
        drift_stats[tail] = {
            "train_mean": train_mean,
            "test_mean": test_mean,
            "drift": drift,
            "drift_pct": (drift / train_mean * 100) if train_mean != 0 else 0,
        }

    # 給料日効果（訓練期間）
    dd_payroll_train = win_rates_train.loc[20:25].mean()
    dd_other_train = pd.concat([win_rates_train.loc[1:19], win_rates_train.loc[26:31]]).mean()
    payroll_effect_train = dd_payroll_train.mean() - dd_other_train.mean()

    # 給料日効果（テスト期間）
    dd_payroll_test = win_rates_test.loc[20:25].mean()
    dd_other_test = pd.concat([win_rates_test.loc[1:19], win_rates_test.loc[26:31]]).mean()
    payroll_effect_test = dd_payroll_test.mean() - dd_other_test.mean()

    # 月初効果（訓練期間）
    dd_early_train = win_rates_train.loc[1:10].mean()
    dd_late_train = win_rates_train.loc[21:31].mean()
    early_effect_train = dd_early_train.mean() - dd_late_train.mean()

    # 月初効果（テスト期間）
    dd_early_test = win_rates_test.loc[1:10].mean()
    dd_late_test = win_rates_test.loc[21:31].mean()
    early_effect_test = dd_early_test.mean() - dd_late_test.mean()

    # 全体的なドリフト
    mean_drift = np.mean([abs(v["drift"]) for v in drift_stats.values()])

    # 結果をまとめる
    result = {
        "metadata": {
            "hall_name": hall_name,
            "train_period": "2025-07-07 to 2025-11-01",
            "test_period": "2025-11-01 to 2025-12-31",
        },
        "train_period": {
            "tail_statistics": train_stats,
            "payroll_effect": {
                "mean_effect": float(payroll_effect_train),
                "description": "Difference between payroll days (20-25) and other days",
            },
            "early_month_effect": {
                "mean_effect": float(early_effect_train),
                "description": "Difference between early month (1-10) and late month (21-31)",
            },
        },
        "test_period": {
            "tail_statistics": test_stats,
            "payroll_effect": {
                "mean_effect": float(payroll_effect_test),
                "description": "Difference between payroll days (20-25) and other days",
            },
            "early_month_effect": {
                "mean_effect": float(early_effect_test),
                "description": "Difference between early month (1-10) and late month (21-31)",
            },
        },
        "drift_analysis": {
            "by_tail": drift_stats,
            "overall_mean_drift": float(mean_drift),
            "assessment": (
                "high_nonstationarity" if mean_drift > 4
                else "moderate_nonstationarity" if mean_drift > 2
                else "stable"
            ),
        },
        "interaction_value_assessment": {
            "payroll_effect_train": float(payroll_effect_train),
            "payroll_effect_test": float(payroll_effect_test),
            "payroll_effect_change": float(payroll_effect_test - payroll_effect_train),
            "recommendation": (
                "HIGH VALUE" if abs(payroll_effect_train) > 2 and mean_drift < 2
                else "MODERATE VALUE" if abs(payroll_effect_train) > 0.5 and mean_drift < 4
                else "LIMITED VALUE"
            ),
        }
    }

    # JSON ファイルに出力
    safe_hall_name = hall_name.replace('/', '_').replace('\\', '_')
    json_path = output_dir / f'tail_dd_analysis_{safe_hall_name}.json'

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✓ JSON exported: {json_path}")
    return result

def main():
    """メイン処理"""
    # DBパスの解決：複数の候補を試す
    candidates = [
        # 候補1: スクリプト位置から相対パス（標準配置: 2026project/ml/experiments/）
        Path(__file__).parent / "../../db/マルハンメガシティ2000-蒲田7.db",
        # 候補2: 作業ディレクトリから相対（2026project直下から実行される場合）
        Path("db/マルハンメガシティ2000-蒲田7.db"),
        # 候補3: 絶対パス
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
        print(f"❌ DB file not found in any of these locations:")
        for c in candidates:
            print(f"   - {c.resolve()}")
        return

    hall_name = "マルハンメガシティ2000-蒲田7"

    print(f"\n{'#'*80}")
    print(f"# Last Digit × DD (Day of Month) Interaction Analysis")
    print(f"# {hall_name}")
    print(f"{'#'*80}")

    # 訓練期間データを読み込み（利用可能なデータで分割）
    print(f"\n🔍 Loading train period data...")
    df_train = load_hall_data(db_path, "20250707", "20251101", "Train Period (2025-07-07 to 2025-11-01)")
    print(f"  Data rows: {len(df_train)}")

    # テスト期間データを読み込み
    print(f"\n🔍 Loading test period data...")
    df_test = load_hall_data(db_path, "20251101", "20251231", "Test Period (2025-11-01 to 2025-12-31)")
    print(f"  Data rows: {len(df_test)}")

    # 訓練期間の分析
    win_rates_train = analyze_tail_dd_interaction(df_train, "Train Period (2025-07-07 to 2025-11-01)")

    # テスト期間の分析
    win_rates_test = analyze_tail_dd_interaction(df_test, "Test Period (2025-11-01 to 2025-12-31)")

    # ドリフト分析
    print(f"\n{'='*80}")
    print(f"🔍 Drift Analysis (Train vs Test)")
    print(f"{'='*80}\n")

    print(f"Drift by last digit (Mean train vs Mean test):")
    for tail in sorted(win_rates_train.columns):
        train_mean = win_rates_train[tail].mean()
        test_mean = win_rates_test[tail].mean()
        drift = test_mean - train_mean
        sign = "▲" if drift > 0 else "▼" if drift < 0 else "="
        print(f"  Last digit {tail}: {train_mean:.1f}% → {test_mean:.1f}% {sign} ({drift:+.1f}pp)")

    # 出力ディレクトリ（スクリプト位置基準）
    script_dir = Path(__file__).parent  # ml/experiments/
    output_dir = script_dir / "results"

    # ヒートマップ作成
    print(f"\n📊 Generating heatmap...")
    create_heatmap(win_rates_train, win_rates_test, hall_name, output_dir)

    # JSON出力
    print(f"\n📋 Exporting analysis results to JSON...")
    json_result = export_to_json(win_rates_train, win_rates_test, hall_name, output_dir)

    # 結論
    print(f"\n{'='*80}")
    print(f"💡 Analysis Conclusion")
    print(f"{'='*80}\n")

    # 給料日パターンの強さを評価
    dd_payroll_train = win_rates_train.loc[20:25].mean()
    dd_other_train = pd.concat([win_rates_train.loc[1:19], win_rates_train.loc[26:31]]).mean()
    payroll_effect = dd_payroll_train.mean() - dd_other_train.mean()

    if payroll_effect > 2:
        print(f"✓ Strong payroll date effect detected: +{payroll_effect:.1f}pp around payday")
        print(f"  → Last Digit × DD interaction is HIGH VALUE")
    elif payroll_effect > 0.5:
        print(f"⚡ Moderate payroll date effect detected: +{payroll_effect:.1f}pp around payday")
        print(f"  → Last Digit × DD interaction may be EFFECTIVE")
    else:
        print(f"⚠️  Weak payroll date effect: only {payroll_effect:.1f}pp")
        print(f"  → Last Digit × DD interaction value is LIMITED")

    # 非定常性評価
    print(f"\nStability (Train vs Test):")
    drifts = []
    for tail in win_rates_train.columns:
        col_drift = abs(win_rates_test[tail].mean() - win_rates_train[tail].mean())
        drifts.append(col_drift)

    mean_drift = np.mean(drifts)

    if mean_drift < 2:
        print(f"✓ Stable: Mean drift {mean_drift:.2f}pp")
    elif mean_drift < 4:
        print(f"⚡ Moderate: Mean drift {mean_drift:.2f}pp")
    else:
        print(f"⚠️  Unstable: Mean drift {mean_drift:.2f}pp")

if __name__ == "__main__":
    main()
