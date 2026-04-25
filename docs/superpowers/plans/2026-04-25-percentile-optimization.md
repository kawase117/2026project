# 分割比率最適化の実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PERCENTILE_CANDIDATES の7つの分割比率（50/0/50, 45/10/45, 40/20/40, 36/28/36, 33/34/33, 20/60/20, 10/80/10）を、DD別・曜日別・複数訓練期間で系統的にテストし、各比率の予測精度を比較検証する。

**Architecture:** 既存の cross_attribute_performance_analysis.py のロジックを拡張して、外層ループで比率をイテレーション。各比率について、訓練属性×分割単位の9パターン（3属性 × 3分割単位）の勝者カウントを測定し、マトリクス形式で結果を可視化。

**Tech Stack:** Python 3.x, pandas, SQLite, scipy (spearman rank correlation)

---

### Task 1: 比率比較スクリプトの骨組み作成

**Files:**
- Create: `backtest/compare_percentile_ratios.py` - メイン実装スクリプト
- Reference: `backtest/analysis_base.py` - PERCENTILE_CANDIDATES, 定数, 共通関数
- Reference: `backtest/cross_attribute_performance_analysis.py` - 分析ロジックの参考実装

- [ ] **Step 1: 雛形コード作成**

`backtest/compare_percentile_ratios.py` に以下の雛形を作成：

```python
"""比率最適化分析 - 複数分割比率の系統的テスト"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import (
    TRAINING_PERIODS, TEST_START, TEST_END, ATTRIBUTES, ATTRIBUTES_JA,
    WEEKDAYS, WEEKDAY_JP, HALLS, PERCENTILE_CANDIDATES,
    split_groups_triple_custom, load_and_split_data, print_header,
    print_dd_section_triple, print_weekday_section_triple
)
from cross_attribute_performance_analysis import analyze_cross_attribute


def run_percentile_comparison_analysis(db_path: str):
    """複数分割比率での相対パフォーマンス分析（全比率テスト）"""

    print(f"\n分割比率最適化分析 (DB: {Path(db_path).stem})")
    print("=" * 180)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    # 結果保存用：比率 → [訓練期間1, 訓練期間2, 訓練期間3] の構造
    ratio_results = {}  # {(top%, mid%, low%): {'dd': {...}, 'wd': {...}}}

    for top_pct, mid_pct, low_pct in PERCENTILE_CANDIDATES:
        ratio_name = f"{top_pct}/{mid_pct}/{low_pct}"
        print(f"\n{'='*180}")
        print(f"分割比率: {ratio_name}")
        print(f"{'='*180}")

        ratio_results[ratio_name] = {}

        # TODO: 訓練期間ループ、DD別・曜日別分析の実装

    # TODO: 最終統計と比率比較マトリクスの出力

    print(f"\n{'='*180}")
    print(f"分割比率最適化分析 完了")
    print(f"{'='*180}")


if __name__ == "__main__":
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    output_file = results_dir / "compare_percentile_ratios.txt"

    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_percentile_comparison_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
```

- [ ] **Step 2: 構造確認のため動作テスト**

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\backtest
python compare_percentile_ratios.py
```

Expected: スクリプトが起動し、各比率のヘッダーが出力され、未実装の TODO メッセージが表示される。出力ファイルが生成される。

- [ ] **Step 3: Commit**

```bash
git add backtest/compare_percentile_ratios.py
git commit -m "feat: 分割比率比較スクリプトの雛形実装"
```

---

### Task 2: DD別分析ロジックの実装

**Files:**
- Modify: `backtest/compare_percentile_ratios.py` - DD別分析ロジックを追加

- [ ] **Step 1: DD別分析関数の実装**

`run_percentile_comparison_analysis()` 内の TODO を以下で置き換え：

```python
        # 訓練期間ループ
        for period_name, start_date, end_date in TRAINING_PERIODS:
            df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

            print_header(db_path, period_name, start_date, end_date)

            # ========== DD別分析 ==========
            print_dd_section_triple(period_name)

            dd_results = {}  # {dd: {attr: result_dict}}

            for dd in range(1, 21):
                dd_results[dd] = {}
                for attr in ATTRIBUTES:
                    result = analyze_cross_attribute(
                        df_train, df_test, 'dd', dd, attr,
                        top_pct=top_pct, mid_pct=mid_pct, low_pct=low_pct
                    )
                    if result:
                        dd_results[dd][attr] = result
                        r = result
                        condition_label = f"D{dd:<3}"
                        attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                        top_sign = "+" if r['top_relative'] >= 0 else ""
                        mid_sign = "+" if r['mid_relative'] >= 0 else ""
                        low_sign = "+" if r['low_relative'] >= 0 else ""
                        sig_label = "(*)" if r['p_value'] < 0.05 else ""

                        print(f"{condition_label:<5} {attr_label} {r['condition_avg']*100:>6.1f}% "
                              f"{r['top_avg']*100:>6.1f}% {top_sign}{r['top_relative']*100:>7.1f}% "
                              f"{r['mid_avg']*100:>6.1f}% {mid_sign}{r['mid_relative']*100:>7.1f}% "
                              f"{r['low_avg']*100:>6.1f}% {low_sign}{r['low_relative']*100:>7.1f}% "
                              f"{r['winner']:<12} | Rho={r['corr']:.2f} p={r['p_value']:.3f} {sig_label}")

            ratio_results[ratio_name]['dd'] = dd_results
```

- [ ] **Step 2: DD別分析の動作確認**

```bash
python compare_percentile_ratios.py 2>&1 | head -100
```

Expected: DD別セクションが出力され、D1～D20 の分析結果が表示される。

- [ ] **Step 3: Commit**

```bash
git add backtest/compare_percentile_ratios.py
git commit -m "feat: DD別分析ロジックの実装"
```

---

### Task 3: 曜日別分析ロジックの実装

**Files:**
- Modify: `backtest/compare_percentile_ratios.py` - 曜日別分析ロジックを追加

- [ ] **Step 1: 曜日別分析関数の実装**

DD別分析の直後に以下を追加（`print_dd_section_triple()` の直後）：

```python
            # ========== 曜日別分析 ==========
            print_weekday_section_triple(period_name)

            wd_results = {}  # {weekday: {attr: result_dict}}

            for weekday, jp in zip(WEEKDAYS, WEEKDAY_JP):
                wd_results[weekday] = {}
                for attr in ATTRIBUTES:
                    result = analyze_cross_attribute(
                        df_train, df_test, 'weekday', weekday, attr,
                        top_pct=top_pct, mid_pct=mid_pct, low_pct=low_pct
                    )
                    if result:
                        wd_results[weekday][attr] = result
                        r = result
                        attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                        top_sign = "+" if r['top_relative'] >= 0 else ""
                        mid_sign = "+" if r['mid_relative'] >= 0 else ""
                        low_sign = "+" if r['low_relative'] >= 0 else ""
                        sig_label = "(*)" if r['p_value'] < 0.05 else ""

                        print(f"{jp}曜   {attr_label} {r['condition_avg']*100:>6.1f}% "
                              f"{r['top_avg']*100:>6.1f}% {top_sign}{r['top_relative']*100:>7.1f}% "
                              f"{r['mid_avg']*100:>6.1f}% {mid_sign}{r['mid_relative']*100:>7.1f}% "
                              f"{r['low_avg']*100:>6.1f}% {low_sign}{r['low_relative']*100:>7.1f}% "
                              f"{r['winner']:<12} | Rho={r['corr']:.2f} p={r['p_value']:.3f} {sig_label}")

            ratio_results[ratio_name]['wd'] = wd_results
```

- [ ] **Step 2: 曜日別分析の動作確認**

```bash
python compare_percentile_ratios.py 2>&1 | tail -150
```

Expected: 曜日別セクションが出力され、月～日 の分析結果が表示される。

- [ ] **Step 3: Commit**

```bash
git add backtest/compare_percentile_ratios.py
git commit -m "feat: 曜日別分析ロジックの実装"
```

---

### Task 4: マトリクス形式での統計集約と比率比較出力

**Files:**
- Modify: `backtest/compare_percentile_ratios.py` - 最終統計集約ロジックを追加

- [ ] **Step 1: 最終訓練期間での統計集約関数の実装**

`run_percentile_comparison_analysis()` の訓練期間ループ直後（比率ループ内）に以下を追加：

```python
        # 最終訓練期間（1月）での統計集約
        final_period_results = ratio_results[ratio_name].get(TRAINING_PERIODS[-1][0], {})

        print(f"\n{'='*180}")
        print(f"分割比率 {ratio_name} - 統計集約（最終訓練期間 {TRAINING_PERIODS[-1][0]}）")
        print(f"{'='*180}")

        # DD別の勝者統計
        dd_stats = {}
        for attr in ATTRIBUTES:
            dd_stats[attr] = {'top': 0, 'mid': 0, 'low': 0}

        if 'dd' in final_period_results:
            for dd in final_period_results['dd']:
                for attr in ATTRIBUTES:
                    if attr in final_period_results['dd'][dd]:
                        result = final_period_results['dd'][dd][attr]
                        if result['winner'] == "上位G":
                            dd_stats[attr]['top'] += 1
                        elif result['winner'] == "中間G":
                            dd_stats[attr]['mid'] += 1
                        else:
                            dd_stats[attr]['low'] += 1

        print(f"\nDD別勝者統計 ({ratio_name}):")
        for attr in ATTRIBUTES:
            top = dd_stats[attr]['top']
            mid = dd_stats[attr]['mid']
            low = dd_stats[attr]['low']
            total = top + mid + low
            if total > 0:
                print(f"  {ATTRIBUTES_JA[attr]:<15}: 上位G勝利 {top:>2}/20回 ({top/20*100:>5.1f}%) | "
                      f"中間G勝利 {mid:>2}/20回 ({mid/20*100:>5.1f}%) | "
                      f"下位G勝利 {low:>2}/20回 ({low/20*100:>5.1f}%)")

        # 曜日別の勝者統計
        wd_stats = {}
        for attr in ATTRIBUTES:
            wd_stats[attr] = {'top': 0, 'mid': 0, 'low': 0}

        if 'wd' in final_period_results:
            for weekday in final_period_results['wd']:
                for attr in ATTRIBUTES:
                    if attr in final_period_results['wd'][weekday]:
                        result = final_period_results['wd'][weekday][attr]
                        if result['winner'] == "上位G":
                            wd_stats[attr]['top'] += 1
                        elif result['winner'] == "中間G":
                            wd_stats[attr]['mid'] += 1
                        else:
                            wd_stats[attr]['low'] += 1

        print(f"\n曜日別勝者統計 ({ratio_name}):")
        for attr in ATTRIBUTES:
            top = wd_stats[attr]['top']
            mid = wd_stats[attr]['mid']
            low = wd_stats[attr]['low']
            total = top + mid + low
            if total > 0:
                print(f"  {ATTRIBUTES_JA[attr]:<15}: 上位G勝利 {top:>1}/7回 ({top/7*100:>5.1f}%) | "
                      f"中間G勝利 {mid:>1}/7回 ({mid/7*100:>5.1f}%) | "
                      f"下位G勝利 {low:>1}/7回 ({low/7*100:>5.1f}%)")
```

- [ ] **Step 2: 比率比較マトリクス出力の実装**

訓練期間ループの外（`ratio_results` 全体の集約）に以下を追加：

```python
    # ========== 全比率の比較マトリクス ==========
    print(f"\n{'='*180}")
    print(f"全分割比率の比較マトリクス")
    print(f"{'='*180}")

    print(f"\nDD別での勝者出現率（%）")
    print(f"{'比率':<15} {'機械番号-上位':<12} {'機械番号-中間':<12} {'機械番号-下位':<12} "
          f"{'機種名-上位':<12} {'機種名-中間':<12} {'機種名-下位':<12} "
          f"{'末尾-上位':<12} {'末尾-中間':<12} {'末尾-下位':<12}")
    print("-" * 180)

    # TODO: マトリクス行の生成と出力

    print(f"\n曜日別での勝者出現率（%）")
    print(f"{'比率':<15} {'機械番号-上位':<12} {'機械番号-中間':<12} {'機械番号-下位':<12} "
          f"{'機種名-上位':<12} {'機種名-中間':<12} {'機種名-下位':<12} "
          f"{'末尾-上位':<12} {'末尾-中間':<12} {'末尾-下位':<12}")
    print("-" * 180)

    # TODO: マトリクス行の生成と出力
```

- [ ] **Step 3: 動作確認と出力検証**

```bash
python compare_percentile_ratios.py
```

Expected: 最終訓練期間での統計集約が表示される。ただし、マトリクスは未実装なので「TODO」が表示される。

- [ ] **Step 4: Commit**

```bash
git add backtest/compare_percentile_ratios.py
git commit -m "feat: 統計集約と比率比較フレームワークの実装"
```

---

### Task 5: マトリクス行生成ロジックの完成実装

**Files:**
- Modify: `backtest/compare_percentile_ratios.py` - マトリクス行生成ロジック完成

- [ ] **Step 1: DD別マトリクス行の生成実装**

最初の TODO（DD別マトリクス行）を以下で置き換え：

```python
    # results フォルダから dd_stats を再構築（訓練期間ループ内で保存していない場合のため）
    # 簡略化のため、ratio_results から最終訓練期間の統計を抽出
    for ratio_name in sorted(ratio_results.keys(), key=lambda x: (len(x.split('/')), x)):
        row = f"{ratio_name:<15}"

        # 最終訓練期間の結果から統計を抽出（再集約）
        final_period_key = TRAINING_PERIODS[-1][0]
        
        # この部分は ratio_results から取得する必要があるため、
        # 実装の再設計が必要です。簡略化のため、プレースホルダーを記載
        for attr in ATTRIBUTES:
            # dd_stats[attr] が必要だが、ここではスコープ外
            pass

        # マトリクス行出力（今後統計値を埋める）
        print(f"{ratio_name:<15} {'-- %':<12} {'-- %':<12} {'-- %':<12} "
              f"{'-- %':<12} {'-- %':<12} {'-- %':<12} "
              f"{'-- %':<12} {'-- %':<12} {'-- %':<12}")
```

実装上の課題：`ratio_results` 構造がネストされすぎているため、最終統計を効率的に抽出できません。

**Step 1 修正版：統計データ構造の再設計**

`run_percentile_comparison_analysis()` 冒頭で統計用データ構造を初期化：

```python
    # グローバル統計（最終訓練期間のみ）
    global_stats = {}  # {ratio_name: {'dd': {...}, 'wd': {...}}}

    for ratio_name, _ in [(f"{t}/{m}/{l}", (t,m,l)) for t, m, l in PERCENTILE_CANDIDATES]:
        global_stats[ratio_name] = {
            'dd': {attr: {'top': 0, 'mid': 0, 'low': 0} for attr in ATTRIBUTES},
            'wd': {attr: {'top': 0, 'mid': 0, 'low': 0} for attr in ATTRIBUTES}
        }
```

訓練期間ループ内の統計カウント部分を修正：

```python
            # 最終訓練期間でのみ統計をカウント
            if period_name == TRAINING_PERIODS[-1][0]:
                if 'dd' in ratio_results[ratio_name]:
                    for dd in ratio_results[ratio_name]['dd']:
                        for attr in ATTRIBUTES:
                            if attr in ratio_results[ratio_name]['dd'][dd]:
                                result = ratio_results[ratio_name]['dd'][dd][attr]
                                if result['winner'] == "上位G":
                                    global_stats[ratio_name]['dd'][attr]['top'] += 1
                                elif result['winner'] == "中間G":
                                    global_stats[ratio_name]['dd'][attr]['mid'] += 1
                                else:
                                    global_stats[ratio_name]['dd'][attr]['low'] += 1

                if 'wd' in ratio_results[ratio_name]:
                    for weekday in ratio_results[ratio_name]['wd']:
                        for attr in ATTRIBUTES:
                            if attr in ratio_results[ratio_name]['wd'][weekday]:
                                result = ratio_results[ratio_name]['wd'][weekday][attr]
                                if result['winner'] == "上位G":
                                    global_stats[ratio_name]['wd'][attr]['top'] += 1
                                elif result['winner'] == "中間G":
                                    global_stats[ratio_name]['wd'][attr]['mid'] += 1
                                else:
                                    global_stats[ratio_name]['wd'][attr]['low'] += 1
```

- [ ] **Step 2: マトリクス行生成のフル実装**

比率ループの外に、以下を追加：

```python
    # ========== マトリクス出力 ==========
    print(f"\n{'='*180}")
    print(f"全分割比率の比較マトリクス - DD別")
    print(f"{'='*180}\n")

    print(f"{'比率':<15} {'機械番号':<20} {'機種名':<20} {'末尾':<20}")
    print(f"{'':':<15} {'上G':<7} {'中G':<7} {'下G':<7} {'上G':<7} {'中G':<7} {'下G':<7} {'上G':<7} {'中G':<7} {'下G':<7}")
    print("-" * 140)

    for ratio_name in sorted(global_stats.keys(), key=lambda x: (
        int(x.split('/')[0]), int(x.split('/')[1]), int(x.split('/')[2])
    )):
        row = f"{ratio_name:<15}"
        for attr in ATTRIBUTES:
            stats = global_stats[ratio_name]['dd'][attr]
            top_pct = stats['top'] / 20 * 100
            mid_pct = stats['mid'] / 20 * 100
            low_pct = stats['low'] / 20 * 100
            row += f"{top_pct:>5.1f}% {mid_pct:>5.1f}% {low_pct:>5.1f}% "
        print(row)

    print(f"\n{'='*180}")
    print(f"全分割比率の比較マトリクス - 曜日別")
    print(f"{'='*180}\n")

    print(f"{'比率':<15} {'機械番号':<20} {'機種名':<20} {'末尾':<20}")
    print(f"{'':':<15} {'上G':<7} {'中G':<7} {'下G':<7} {'上G':<7} {'中G':<7} {'下G':<7} {'上G':<7} {'中G':<7} {'下G':<7}")
    print("-" * 140)

    for ratio_name in sorted(global_stats.keys(), key=lambda x: (
        int(x.split('/')[0]), int(x.split('/')[1]), int(x.split('/')[2])
    )):
        row = f"{ratio_name:<15}"
        for attr in ATTRIBUTES:
            stats = global_stats[ratio_name]['wd'][attr]
            top_pct = stats['top'] / 7 * 100
            mid_pct = stats['mid'] / 7 * 100
            low_pct = stats['low'] / 7 * 100
            row += f"{top_pct:>5.1f}% {mid_pct:>5.1f}% {low_pct:>5.1f}% "
        print(row)
```

- [ ] **Step 3: フル動作テスト**

```bash
python compare_percentile_ratios.py
```

Expected: 5つの分割比率すべてについて、DD別・曜日別の分析結果が出力され、最後にマトリクス形式での比率比較が表示される。

- [ ] **Step 4: 出力ファイル確認**

```bash
cat results/compare_percentile_ratios.txt | tail -100
```

Expected: マトリクス形式での比率比較結果が確認できる。

- [ ] **Step 5: Commit**

```bash
git add backtest/compare_percentile_ratios.py
git commit -m "feat: マトリクス行生成のフル実装と統計集約完成"
```

---

### Task 6: 結果検証と最適化分析

**Files:**
- Reference: `backtest/results/compare_percentile_ratios.txt` - 生成された出力ファイル
- Analyze: マトリクス結果から最適な分割比率を特定

- [ ] **Step 1: 出力ファイルの全体確認**

```bash
wc -l backtest/results/compare_percentile_ratios.txt
cat backtest/results/compare_percentile_ratios.txt | head -50
```

Expected: 出力ファイルが生成され、複数ホール分の分析結果が含まれている。

- [ ] **Step 2: マトリクス結果の分析**

出力ファイルから以下の項目を抽出・分析：
- 各比率での DD別勝者出現率（上位G/中間G/下位G）
- 各比率での 曜日別勝者出現率
- 比率ごとの安定性（訓練期間を通じた一貫性）
- 現在の 36/28/36 比率との相比較
- 最適な比率の特定（最高精度を示す比率）

Example analysis output を `compare_percentile_analysis.txt` に記載：

```
【分割比率最適化分析結果】

1. DD別での勝者出現率分析
   - 50/0/50: 上位G出現率が最も高い（機械番号では60%）
   - 45/10/45: バランス型で安定性良好
   - 40/20/40: 中間Gを重視するため、中間G出現が増加
   - 36/28/36: 現在設定。バランス型の最適点
   - 33/34/33: ほぼ均等で、中間Gの出現が最多

2. 曜日別での勝者出現率分析
   - [各比率の詳細結果]

3. 安定性評価（3訓練期間での一貫性）
   - [各比率の安定性スコア]

4. 推奨される最適比率
   - 機械番号分割: 50/0/50 （上位G予測精度が最高）
   - 機種名分割: 45/10/45 （バランス型で安定）
   - 末尾分割: 36/28/36 （現在設定が最適）

5. 現在の 36/28/36 からの改善可能性
   - [改善ポテンシャル分析]
```

- [ ] **Step 3: 最終レポート作成**

`document/compare_percentile_analysis_report.md` に最終分析レポートを作成：

```markdown
# 分割比率最適化分析レポート

## 目的
5つの分割比率（50/0/50, 45/10/45, 40/20/40, 36/28/36, 33/34/33）を、DD別・曜日別・複数訓練期間で系統的にテストし、予測精度を比較検証する。

## 分析結果概要
[上記の分析内容を記載]

## 推奨事項
[最適な分割比率を特定し、その理由を説明]
```

- [ ] **Step 4: Commit**

```bash
git add backtest/results/compare_percentile_ratios.txt document/compare_percentile_analysis_report.md
git commit -m "docs: 分割比率最適化分析結果の記録"
```

---

## 検証チェックリスト

- [ ] スクリプトが エラーなく実行される
- [ ] PERCENTILE_CANDIDATES の5つの比率すべてが処理される
- [ ] DD別（1-20）のすべての条件が分析される
- [ ] 曜日別（7日）のすべての条件が分析される
- [ ] 3つの訓練期間（6月, 3月, 1月）それぞれで分析が実行される
- [ ] 最終訓練期間でのみ統計カウントが行われる
- [ ] マトリクス形式での比率比較結果が見やすく出力される
- [ ] 各比率での勝者出現率（%）が正確に計算されている
- [ ] 出力ファイル `compare_percentile_ratios.txt` が生成される
- [ ] 分析結果から最適な分割比率が特定できる
