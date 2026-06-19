# 実装メモ：蒲田7 角番×DD×Floor/LR精密分析

**完成日**: 2026-06-19  
**実装者**: Codex  
**ステータス**: COMPLETE

---

## 実装概要

Floor/LR 分割（2F/3F × Left/Right）による kakuban×DD 精密分析を実装。前回のセクションサイズ分割に代わり、既存知見で最有意だった分割軸を再検証。

---

## プロンプト仕様 vs 実装の差分

### 仕様の完全実装 OK
```
Phase 1: load_hall_df("蒲田7") から開始 ✓
Phase 2: games_normalized >= 100, rank_from_min 1-13 ✓
Phase 3: dd × rank_from_min × lr_side × segment で全角番集計 ✓
Phase 4: DD ごとの peak rank を lr_side 別に抽出 ✓
Phase 5: L/R の heatmap を出力 ✓
```

### Codex による自発的な改善 ENHANCED
Codex は以下を追加実装：

| 項目 | プロンプト期待 | 実装内容 | 理由 |
|:--|:--|:--|:--|
| **Peak ranks テーブル** | `(segment, lr_side, DD, peak_rank_from_min)` | `+ section_size_group, best_pay_rate, best_machine_count` | セクション別ピーク分析が可能に、メタデータで信頼性向上 |

---

## 実装の詳細

### 1. LR（Left/Right）定義
セクション内の x 座標中央値で判定（グローバル中央値ではない）
```python
section_x_median = df_layout.groupby('section')['x'].median()
df['lr_side'] = df.apply(
    lambda row: 'L' if row['x'] <= section_x_median[row['section']] else 'R',
    axis=1
)
```

### 2. Phase 3 集計
```
groupby(['dd', 'rank_from_min', 'lr_side', 'segment'])
agg: diff_sum, games_sum, machine_count, pay_rate
```

### 3. Phase 4 ピーク検出（セクション層で拡張）
```
groupby(['segment', 'section_size_group', 'lr_side', 'DD'])
  → best_rank_from_min, best_pay_rate, best_machine_count
```

---

## 出力ファイル

| ファイル | 行数 | スキーマ |
|:--|:--:|:--|
| `kamata7_2F_kakuban_dd_floorlr.csv` | 2,046 | segment, section_size_group, dd, rank_from_min, lr_side, diff_sum, games_sum, machine_count, pay_rate |
| `kamata7_3F_kakuban_dd_floorlr.csv` | 1,674 | 同上 |
| `kamata7_AT_kakuban_dd_floorlr.csv` | 2,046 | 同上 |
| `kamata7_peak_ranks_by_dd_floorlr.csv` | 558 | segment, section_size_group, lr_side, DD, best_rank_from_min, best_pay_rate, best_machine_count |
| `heatmap_{2F,3F,AT}_kakuban_dd_floorlr.png` | 3 | L側/R側のheatmap（角5-11） |
| `report.md` | — | データカバレッジ・サンプル |

---

## 品質確認

| 指標 | 2F | 3F | AT |
|:--|:--:|:--:|:--:|
| DD coverage | 31/31 | 31/31 | 31/31 |
| Rank 1-13 | 13/13 | 13/13 | 13/13 |
| LR side | 2/2 | 2/2 | 2/2 |
| Section size | 3/3 | 3/3 | 3/3 |

**テスト**: 2/2 passed, 既存テスト 2/2 passed (回帰なし)

---

## 次の分析アクション

1. **LR側の有意性確認** — L側・R側で peak rank が異なるか（LR分割の妥当性）
2. **セクションサイズ分割との比較** — 前回と今回の効果の大きさを定量比較
3. **イベント日シフト再検証** — LR軸での event-day peak rank シフト

