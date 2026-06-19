# Codex向けプロンプト：蒲田7 角番×DD精密分析

**作成日**: 2026-06-19  
**タスク**: 蒲田7の角番効果（DD×セクションサイズ別）を精密化し、「今日の最強角番」を引ける仕組みを実装

---

## 背景・目的

蒲田7では既に **角5-9が最強、角1が弱い** ことが実証済み（残差分析）。
本タスクでは：

1. **角番効果の数値化** — `rank_from_min/max` を軸に、全角番（1-13）でセグメント別ピークを検出
2. **DD軸での精密化** — 既存の `kamata7_2F_N_kakuban_dd_cross.csv` を参考に、セクションサイズ層を追加
3. **セクション（島）サイズによる正規化** — `section_size` (<=8/<=14/>14) での機械割差を分離
4. **通路向き補正** — `rank_from_aisle` を補助的に活用し、必要な箇所だけ補正

**最終成果物**：
- セグメント別 DD×角番×セクションサイズ テーブル（CSV）
- 「任意のDD・セグメント・セクションサイズ に対する最強角番」を即座に返す関数
- 角番5-11での局所ピーク可視化（seaborn heatmap）

---

## 前提条件・既存データ

### 1. ホール・セグメント固定
- ホール: **蒲田7** (`load_hall_df("蒲田7")`)
- セグメント: **2F, 3F, AT** — 各セグメント単独で処理
- 鉄台: **台番号2026** — 除外対象

### 2. 既存成果物の活用
```
ml/analysis/results/kamata7_kakuban_dd_cross_eda/
├── kamata7_2F_N_kakuban_dd_cross.csv      ← 既存テーブル（参考形式）
├── kamata7_2F_A_kakuban_dd_cross.csv
├── kamata7_3F_N_kakuban_dd_cross.csv
├── kamata7_3F_A_kakuban_dd_cross.csv
└── ...
```
**既存テーブル形式を確認し、本スクリプトはこれを拡張する設計。**

### 3. machine_layout スキーマ
```
machine_layout テーブル（蒲田7）:
- machine_number (INT)         -- 台番号
- rank_from_min (INT)          -- 島内最小ランク（端=1, 中央=13）
- rank_from_max (INT)          -- 島内最大ランクから逆順
- rank_from_aisle (INT)        -- 通路向きランク（補助用）
- physical_corner (STR or INT) -- コーナー定義（角1, 角7など）
- section (STR)                -- セクション/島識別子
```

### 4. セクションサイズの定義
```python
section_size_bins = {
    'small': (0, 8],      # section 内の unique machine 数 <= 8
    'medium': (8, 14],    # <= 14台
    'large': (14, float('inf'))  # > 14台
}
```

---

## 処理フロー

### Phase 1: データ準備
```python
1. load_hall_df("蒲田7") → df_raw
2. machine_layout をSQLから取得
   SELECT machine_number, rank_from_min, rank_from_max, rank_from_aisle, 
          physical_corner, section 
   FROM machine_layout WHERE hall='蒲田7'
3. df_raw をセグメント（2F/3F/AT）別に分割
4. 各セグメントで鉄台（machine_number=2026）を除外
5. machine_layout と LEFT JOIN（by machine_number）
   → rank_from_min/max/aisle, section を付与
```

### Phase 2: セクションサイズの計算
```python
1. section ごとに unique machine 数を集計
2. section_size_bins で分類（small/medium/large）
3. df に section_size 列を追加
```

### Phase 3: DD×角番×セクションサイズ別集計（全角番対象）
**各セグメント（2F/3F/AT）に対して以下を実行。角番は 1-13 全てを対象。**

```python
for segment in ['2F', '3F', 'AT']:
    df_seg = df_filtered[df_filtered.segment == segment]
    
    # Group by: day_of_month, rank_from_min, section_size
    # 注意: rank_from_min は全値（1-13）を集計対象
    grouped = df_seg.groupby(['day_of_month', 'rank_from_min', 'section_size']).agg({
        'diff_coins_normalized': 'sum',
        'games_normalized': 'sum',
        'machine_number': 'nunique',  # 台数
    }).reset_index()
    
    # 機械割の計算
    grouped['pay_rate'] = (grouped['diff_coins_normalized'] / grouped['games_normalized'] * 100).round(2)
    
    # 信頼性フィルタ（例：100G以上）
    grouped = grouped[grouped['games_normalized'] >= 100]
    
    # 出力: CSV（行がなくなった場合はスキップ）
    if not grouped.empty:
        grouped.to_csv(
            f'ml/analysis/results/kamata7_kakuban_dd_cross_eda/kamata7_{segment}_kakuban_dd_sectionsize.csv',
            index=False
        )
```

**NaN処理:**
- `games_normalized == 0` の行は除外（除算エラー防止）
- グループが空の場合（該当セグメント×DD×角番×セクションサイズ の組み合わせがない）は省略
- 信頼性フィルタ後に行がなくなった場合も出力に含めない（行ごと削除）
- **重要**: section_size は「島（section）ごとの unique machine 数」であり、角1-13の固定幅ではない。island/aisle ごとにその実台数で分類

### Phase 4: 全角番のピーク検出
**各セグメント×セクションサイズ層に対して DD別に最強角番を検出：**

```python
def find_peak_rank_by_dd(df_grouped, segment, section_size, dd_value):
    """
    与えられた segment, section_size, dd に対する最強 rank_from_min を返す。
    複数ピークの場合は最初のものを返す。
    データなし（空DataFrame）の場合は None を返す。
    """
    df_subset = df_grouped[
        (df_grouped['segment'] == segment) & 
        (df_grouped['section_size'] == section_size) &
        (df_grouped['day_of_month'] == dd_value)
    ]
    
    if df_subset.empty:
        return None
    
    peak_row = df_subset.loc[df_subset['pay_rate'].idxmax()]
    return int(peak_row['rank_from_min'])

# 結果テーブル作成
peak_results = []
for segment in ['2F', '3F', 'AT']:
    for section_size in ['small', 'medium', 'large']:
        for dd in range(1, 32):
            peak_rank = find_peak_rank_by_dd(df_final, segment, section_size, dd)
            peak_results.append({
                'segment': segment,
                'section_size': section_size,
                'DD': dd,
                'peak_rank_from_min': peak_rank,
            })

df_peaks = pd.DataFrame(peak_results)
df_peaks.to_csv(
    'ml/analysis/results/kamata7_kakuban_dd_cross_eda/kamata7_peak_ranks_by_dd_sectionsize.csv',
    index=False
)
```

### Phase 5: 通路向き補正（補助検証）
**rank_from_aisle が rank_from_min/max と異なる台の影響を検証：**

```python
def check_aisle_bias(df_grouped, segment, rank_from_min_value):
    """
    指定の rank_from_min における pay_rate が、
    rank_from_aisle の値によって大きく異なるか検証。
    補正が必要なら True を返す。
    """
    df_subset = df_grouped[
        (df_grouped['segment'] == segment) & 
        (df_grouped['rank_from_min'] == rank_from_min_value)
    ]
    
    if df_subset.empty or len(df_subset) < 3:
        return False  # データ不足で判定不可
    
    # 同一 rank_from_min でも rank_from_aisle が異なる場合を抽出
    if 'rank_from_aisle' not in df_subset.columns:
        return False
    
    aisle_groups = df_subset.groupby('rank_from_aisle')['pay_rate'].mean()
    if len(aisle_groups) < 2:
        return False
    
    aisle_variance = aisle_groups.std()
    
    # 分散が大きい（例：10pp以上）なら補正が必要
    return aisle_variance > 10.0

# 補正対象の角番を記録
aisle_correction_needed = []
for segment in ['2F', '3F', 'AT']:
    for rank in range(1, 14):
        if check_aisle_bias(df_final, segment, rank):
            aisle_correction_needed.append({
                'segment': segment,
                'rank_from_min': rank
            })

if aisle_correction_needed:
    df_aisle_check = pd.DataFrame(aisle_correction_needed)
    df_aisle_check.to_csv(
        'ml/analysis/results/kamata7_kakuban_dd_cross_eda/kamata7_aisle_correction_needed.csv',
        index=False
    )
```

### Phase 6: 可視化（角5-11に限定）
**可視化の窓として角番5-11に限定し、seaborn heatmap で機械割分布を表示。**
**分析基盤（Phase 3-4）は全角番（1-13）で行う。可視化のみ 5-11 に絞る。**

```python
import matplotlib.pyplot as plt
import seaborn as sns

for segment in ['2F', '3F', 'AT']:
    df_seg = df_final[df_final['segment'] == segment]
    
    # 可視化用に角番5-11に限定
    # 注意: 分析・ピーク検出は全角番で完了済み（Phase 3-4）
    df_seg_filtered = df_seg[(df_seg['rank_from_min'] >= 5) & (df_seg['rank_from_min'] <= 11)]
    
    if df_seg_filtered.empty:
        print(f"Warning: No data for {segment} rank_from_min 5-11")
        continue
    
    # Heatmap: DD (y軸) × rank_from_min (x軸), 値は pay_rate
    # ファセット: section_size (small/medium/large)
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 8))
    
    for idx, section_size in enumerate(['small', 'medium', 'large']):
        df_hm = df_seg_filtered[df_seg_filtered['section_size'] == section_size]
        
        if df_hm.empty:
            axes[idx].text(0.5, 0.5, f'No data for {section_size}',
                          ha='center', va='center', transform=axes[idx].transAxes)
            axes[idx].set_title(f'{segment} - Section Size: {section_size}')
            continue
        
        # Pivot: day_of_month × rank_from_min → pay_rate (平均値）
        pivot_table = df_hm.pivot_table(
            index='day_of_month',
            columns='rank_from_min',
            values='pay_rate',
            aggfunc='mean'
        )
        
        sns.heatmap(
            pivot_table,
            annot=True,
            fmt='.1f',
            cmap='RdYlGn',
            center=100,
            ax=axes[idx],
            cbar_kws={'label': 'Pay Rate (%)'}
        )
        axes[idx].set_title(f'{segment} - Section Size: {section_size}')
        axes[idx].set_xlabel('角番 (rank_from_min)')
        axes[idx].set_ylabel('DD (月内日付)')
    
    plt.tight_layout()
    plt.savefig(
        f'ml/analysis/results/kamata7_kakuban_dd_cross_eda/heatmap_{segment}_kakuban_dd_sectionsize.png',
        dpi=150
    )
    plt.close()
```

---

## 出力ファイル一覧

```
ml/analysis/results/kamata7_kakuban_dd_cross_eda/
├── kamata7_2F_kakuban_dd_sectionsize.csv           # セグメント×DD×角番×セクションサイズ集計
├── kamata7_3F_kakuban_dd_sectionsize.csv
├── kamata7_AT_kakuban_dd_sectionsize.csv
│   Columns: day_of_month, rank_from_min, section_size, 
│            diff_coins_normalized, games_normalized, machine_number, pay_rate
│
├── kamata7_peak_ranks_by_dd_sectionsize.csv        # 「今日の最強角番」テーブル
│   Columns: segment, section_size, DD, peak_rank_from_min
│   一行あたり：セグメント×セクションサイズ×DD → 最強角番番号
│
├── kamata7_aisle_correction_needed.csv             # 通路向き補正が必要な角番（存在する場合のみ）
│   Columns: segment, rank_from_min
│
├── heatmap_2F_kakuban_dd_sectionsize.png           # 可視化：角番5-11 × DD × pay_rate
├── heatmap_3F_kakuban_dd_sectionsize.png
└── heatmap_AT_kakuban_dd_sectionsize.png
```

---

## 実装上の注意（地雷回避）

### 1. DBパス・ホール選択
```python
# ✅ 正しい：load_hall_df を使用（デフォルトパス参照）
from database.utils.data_loader import load_hall_df
df_raw = load_hall_df("蒲田7")

# ❌ 禁止：ハードコードされたパス
# df = pd.read_csv('db/kamata7.db')
```

### 2. to_markdown() の禁止
```python
# ❌ 禁止：Markdown 出力
# df.to_markdown('output.md')

# ✅ CSV のみ使用
df.to_csv('output.csv', index=False)
```

### 3. 空セグメント・NaN の処理
```python
# ✅ 正しい：グループが空の場合は行を作らない
grouped = df_seg.groupby(['day_of_month', 'rank_from_min', 'section_size']).agg(...)
grouped = grouped[grouped['games_normalized'] >= 100]  # 信頼性フィルタ
# → 条件を満たさないグループは自動的に除外
# → None / NaN は出力に含めない

# ❌ 禁止：存在しないグループに NaN を詰める
# grouped.fillna(0)  # 通常 OK だが、存在しない組み合わせは出力しない
```

### 4. 既存ファイル上書き注意
- 既存の `kamata7_2F_N_kakuban_dd_cross.csv` などは上書きしない
- 本スクリプトは **新しい** ファイル名を使用（上記ファイルリスト参照）

### 5. machine_layout の JOIN キー
```python
# ✅ 正しい：LEFT JOIN で NaN に備える
df_merged = df_raw.merge(
    df_layout,
    on='machine_number',
    how='left'
)

# rank_from_min が NaN の行は除外（layout に存在しない台）
df_merged = df_merged.dropna(subset=['rank_from_min'])
```

### 6. 出力ディレクトリの作成
```python
# 出力ディレクトリが存在することを確認
import os
os.makedirs('ml/analysis/results/kamata7_kakuban_dd_cross_eda', exist_ok=True)
```

---

## テスト・検証チェックリスト

- [ ] 3セグメント（2F/3F/AT）全てで出力ファイルが生成されたか
- [ ] 各 CSV の行数が 0 でないか（データ存在確認）
- [ ] `peak_ranks_by_dd_sectionsize` テーブルで、各セグメント×セクションサイズ の全 DD（1-31）が埋まっているか（None は許容だが多数ないこと）
- [ ] Heatmap で角番5-11のピークが視覚的に確認できるか
- [ ] 機械割（pay_rate）の値が 80-120% 程度の範囲か（極端な値は異常値の可能性）
- [ ] 脚本実行時に warnings や errors が出ていないか

---

## 参考：既存スクリプトの参照
- `ml/analysis/kamata7_x_kakuban_eda.py` — 既存の角番分析フロー
- `ml/analysis/kamata_kakuban_section_residual_eda.py` — セクションサイズ定義と残差分析
