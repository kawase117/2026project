# Kamata7 Dashboard Implementation Plan

**作成日**: 2026-07-07  
**対象**: Kamata7 (蒲田7) ダッシュボード理論ページ実装  
**役割分担**: Claude (設計・仕様) / Codex (実装)

---

## 1. 実装方針

### 1.1 全体戦略
- **段階的実装**: Top 5 priorities を優先度順に実装
- **再利用性**: ML/EDA層の既存ロジックを dashboard に統合
- **安全性**: refutation warning panels で理論書の否定仮説をガード
- **アーキテクチャ**: `dashboard/utils/kamata7_*.py` に集計ロジック、pages は薄いレンダリング層

### 1.2 データフロー
```
ML/EDA層の既存ロジック (scoring_model.py, core.py, EDA CSVs)
    ↓
dashboard/utils/kamata7_*.py (新規ユーティルモジュール)
    ↓
dashboard/pages/page_XX_kamata7_*.py (UI レンダリング)
    ↓
Streamlit画面表示
```

### 1.3 ファイル構成
```
dashboard/
  ├── pages/
  │   ├── page_20_kamata7_event_checks.py       [新規, P#2]
  │   ├── page_21_kamata7_segments.py           [新規, P#1]
  │   ├── page_22_kamata7_dd_kakuban.py         [新規, P#3]
  │   ├── page_23_kamata7_cooling_zones.py      [新規, P#4]
  │   └── page_24_kamata7_theory_hub.py         [新規, 最後]
  └── utils/
      ├── kamata7_segments.py                   [新規, P#1]
      ├── kamata7_event_checks.py               [新規, P#2]
      ├── kamata7_dd_kakuban.py                 [新規, P#3]
      ├── kamata7_cooling_zones.py              [新規, P#4]
      └── kamata7_refutation_warnings.py        [新規, P#5]
```

---

## 2. Priority 順序と依存グラフ

```
P#2 (Event-day checks)  ← 独立（入口）
    ↓
P#1 (Six segments)      ← P#2の後（基盤）
    ↓
P#3 (DD kakuban matrix) ← P#1の後（基盤完成）
    ↓
P#4 (Cooling zones)     ← P#3の後（フィルタ層）
    ↓
P#5 (Refutation panels) ← 全体の後（横串ガード層）
```

---

## 3. 優先度別実装仕様

### 3.1 Priority #2 - Event-day checks（最安コスト・最大効果）

**概要**: 当日の日付がどの条件を満たすかを一覧表示（Layer 1 ゲート）

**UI コンポーネント**:
```
┌─────────────────────────────────────┐
│ 本日のイベント条件チェック          │
├─────────────────────────────────────┤
│ ✓ DD30（月末）                       │
│ ✓ 7系イベント日                      │
│ ✓ トラフゾーン（5-14日）             │
│ ✓ 強ゾロ目（MM=DD）                  │
│ ✗ 機種限定リセット日                 │
│                                     │
│ 警告: 今日は3つのイベント日重複     │
└─────────────────────────────────────┘
```

**実装ファイル**: `dashboard/utils/kamata7_event_checks.py`

**関数設計**:
```python
def get_today_event_flags(today_date) -> dict:
    """
    当日の全イベント条件をチェック
    Returns: {
        'is_dd30': bool,
        'is_7kei': bool,
        'is_trough_zone': bool,
        'is_strong_zorome': bool,
        'is_machine_reset_day': bool,
        ...other flags
    }
    """

def get_event_message(flags) -> str:
    """
    flags 辞書から人間が読みやすいメッセージを生成
    """
```

**データソース**:
- `eda/core.py`: `HALL_EVENT_DIGITS`, `is_x_day()`
- `database/date_info_calculator.py`: 日付系ユーティル

**バッグ対応**: dd30欠落（2026-07-02修正済み）→ 既に修正版を使用

---

### 3.2 Priority #1 - Six physical segments（基盤）

**概要**: 6セグメント（2F_L_N, 2F_L, 2F_R, 3F_L_N, 3F_L, 3F_R）をホール平面図と共に表示

**UI コンポーネント**:
```
┌─────────────────────────────────────┐
│ 蒲田7 フロア構成（6セグメント）     │
├─────────────────────────────────────┤
│                                     │
│   2F_L_N  │  2F_L   │  2F_R        │
│  (角番1-5)│(6-10)   │(11-17)       │
│  ─────────┼─────────┼─────────     │
│   3F_L_N  │  3F_L   │  3F_R        │
│  (角番1-5)│(6-10)   │(11-17)       │
│                                     │
└─────────────────────────────────────┘
```

**実装ファイル**: `dashboard/utils/kamata7_segments.py`

**関数設計**:
```python
def classify_segment(machine_number: int, x_coord: int, y_coord: int) -> str:
    """
    機械番号と座標からセグメント分類
    Returns: '2F_L_N' | '2F_L' | '2F_R' | '3F_L_N' | '3F_L' | '3F_R'
    
    Logic:
    1. Y座標で階層判定 (2F or 3F)
    2. X座標で左右判定 (L or R)
    3. Y座標が角番ゾーン(1-5範囲)なら N サフィックス
    """

def get_segment_layout() -> dict:
    """
    セグメント→台番号リストのマッピングテーブル
    Returns: {
        '2F_L_N': [100, 101, 102, ...],
        '2F_L': [...],
        ...
    }
    """

def infer_segment_from_database(machine_id: int) -> str:
    """DB から machine_layout.section を取得"""
```

**データソース**:
- `ml/experiments/walkforward_scoring/scoring_model.py`: `classify_seg()` (line 39)
- `ml/experiments/walkforward_scoring/scoring_model.py`: `_infer_lr()` (line 126, 正しい版)
- `database/schema.py`: `machine_layout.section`, `rank_from_min`, `rank_from_max`

**既知問題対応**: LR逆転バグ（旧版で左右判定が55-58%逆転）→ 新版 `_infer_lr` を使用

**テストケース**:
- 台番号100 (2F角番) → '2F_L_N' ✓
- 台番号200 (3F左側) → '3F_L' ✓
- 台番号711 (異常値, 理論書で注記) → 例外処理 or 警告

---

### 3.3 Priority #3 - DD by kakuban matrix（理論中核・事前予測対応）

**概要**: 理論書2.1節の確定テーブル（DD 1-31 × 角番 A-N）を可視化

**UI コンポーネント**:
```
┌─────────────────────────────────────────────┐
│ DD × 角番 マトリックス（高設定投入パターン）│
├─────────────────────────────────────────────┤
│     A    B    C  ... N                       │
│ DD1  ✓    ✗    ✗  ...  ✗                    │
│ DD2  ✗    ✗    ✗  ...  ✗                    │
│ ...                                         │
│ DD7  ✓    ✓    ✗  ...  ✓ ← event 重複      │
│ ...                                         │
│ DD30 ✓    ✓    ✓  ...  ✓ ← 全強調         │
│                                             │
│ 凡例: ✓=高設定頻出, ✗=低頻度               │
└─────────────────────────────────────────────┘
```

**実装ファイル**: `dashboard/utils/kamata7_dd_kakuban.py`

**関数設計**:
```python
def get_dd_kakuban_matrix() -> pd.DataFrame:
    """
    理論書2.1節のマトリックスを返す
    Returns: DataFrame
        index: DD (1-31)
        columns: kakuban ('A', 'B', ..., 'N')
        values: 0 (低頻度) ~ 2 (高頻度)
    
    Data source: 理論書2.1節の確定テーブル (hand-authored)
    """

def highlight_matrix_cell(dd: int, kakuban: str) -> str:
    """セルの色/背景を返す"""
```

**データソース**:
- `document/kamata7_theory.md`: 第2.1節, DD×角番テーブル（確定値）

**表現方法**:
- Plotly Heatmap（白～赤のグラデーション）
- または Streamlit table with CSS bg-color

**特記事項**:
- 事前予測対応（実績データ不要、理論値で十分）
- Ablation検証: 角番の除去で hit@10 が -42% → 中核要素

---

### 3.4 Priority #4 - Cooling zones and 3F blocks（実運用バグ再発防止）

**概要**: 冷却ゾーン座標の定義と、台選時の自動フィルタ/警告

**UI コンポーネント**:
```
┌─────────────────────────────────────┐
│ フロア図（冷却ゾーン overlay）      │
├─────────────────────────────────────┤
│                                     │
│   [冷却ゾーン（可変）]              │
│   3061-3070, 3081-3090 (赤囲い)    │
│                                     │
│   [構造的冷却ゾーン]                │
│   3131-3140 (黄囲い)               │
│                                     │
│ ⚠ この台は冷却ゾーン内です         │
│   低設定投入の可能性が高い         │
└─────────────────────────────────────┘
```

**実装ファイル**: `dashboard/utils/kamata7_cooling_zones.py`

**関数設計**:
```python
# 定数定義
COOLING_ZONES_VARIABLE = [(3061, 3070), (3081, 3090)]  # 可変
COOLING_ZONES_STRUCTURAL = [(3131, 3140)]               # 構造的

def is_in_cooling_zone(machine_id: int) -> bool:
    """機械番号が冷却ゾーン内か判定"""

def get_cooling_zone_warning(machine_id: int) -> str:
    """警告メッセージ生成"""
```

**データソース**:
- `document/kamata7_theory.md`: 第2.3節, 冷却ゾーン座標

**既知バグ対応**:
- 2026-07-04 Instinct 記載: 角番ルール機械適用で台3135（構造的冷却ゾーン内）を誤推薦
- 対応: kakuban ルール適用後の最終フィルタとして実装

**テストケース**:
- 台番号3065 (可変) → 警告 ✓
- 台番号3135 (構造的) → 警告 ✓
- 台番号2000 (外部) → 警告なし ✓

---

### 3.5 Priority #5 - Refutation warning panels（低コスト安全網）

**概要**: 理論書の否定仮説（22件）・アンチパターン（6件）をガード層として実装

**UI コンポーネント**:
```
┌─────────────────────────────────────────┐
│ ⚠ 注意: 以下の条件に注意してください    │
├─────────────────────────────────────────┤
│ • 小サンプル (n<5) は統計的に無効      │
│ • 鉄台は除外済み（蒲田7: 台2026）     │
│ • Simpson's Paradox: セグメント毎に    │
│   反転することがあります               │
│ • 単一機種・少数日依存の法則は無効     │
│                                         │
│ 詳細: document/kamata7_theory.md       │
│      第3.1節（否定仮説）               │
│      第3.2節（アンチパターン）         │
└─────────────────────────────────────────┘
```

**実装ファイル**: `dashboard/utils/kamata7_refutation_warnings.py`

**関数設計**:
```python
def get_negation_hypotheses() -> list:
    """
    第3.1節の22件の否定仮説をリスト化
    Returns: [
        '末尾9ゾロ目は高設定の必要条件ではない',
        'DD11末尾9の組み合わせ効果はDD軸の脈略',
        ...
    ]
    """

def get_antipatterns() -> list:
    """
    第3.2節の6件アンチパターン
    Returns: [
        {'name': 'Simpson\'s Paradox', 'condition': 'pos_rate>=60%', ...},
        ...
    ]
    """

def check_small_sample_warning(df: pd.DataFrame) -> bool:
    """サンプル数 n < 5 か判定"""

def check_iron_machine_filter(machine_id: int) -> bool:
    """鉄台除外（蒲田7: 2026）"""
```

**データソース**:
- `document/kamata7_theory.md`: 第3.1節 (22件リスト), 第3.2節 (6件アンチパターン)

**実装方針**:
- 他の4つの priority ページ（event-checks, segments, DD matrix, cooling zones）に対して、汎用の warning banner を挿入
- または各ページの下部に reference として表示

---

## 4. 実装シーケンス

### Phase 1: 基盤準備（P#2 + P#1）
1. **P#2 実装** → `dashboard/utils/kamata7_event_checks.py`
   - 所要時間: 1-2h
   - 依存: eda/core.py (既存)
   - テスト: 当日の日付で今日の条件を正確に抽出

2. **P#1 実装** → `dashboard/utils/kamata7_segments.py`
   - 所要時間: 2-3h
   - 依存: scoring_model.py + database (既存)
   - テスト: 全台番号についてセグメント分類の正確性を検証

3. **P#2 + P#1 統合** → `dashboard/pages/page_20_kamata7_event_checks.py`, `page_21_kamata7_segments.py`
   - 所要時間: 1h
   - 手順: Event-day checks ページで当日条件表示 → Segments ページでセグメント可視化

### Phase 2: 理論中核（P#3 + P#4）
4. **P#3 実装** → `dashboard/utils/kamata7_dd_kakuban.py`
   - 所要時間: 1-2h
   - 依存: 理論書2.1節データ (hand-authored)
   - テスト: ヒートマップの色グラデーションが理論値と一致

5. **P#4 実装** → `dashboard/utils/kamata7_cooling_zones.py`
   - 所要時間: 1h
   - 依存: 理論書2.3節 + base segment logic (P#1)
   - テスト: 台3065/3135/2000 の判定が正確

6. **P#3 + P#4 統合** → `dashboard/pages/page_22_kamata7_dd_kakuban.py`, `page_23_kamata7_cooling_zones.py`
   - 所要時間: 1h

### Phase 3: ガード層（P#5）
7. **P#5 実装** → `dashboard/utils/kamata7_refutation_warnings.py`
   - 所要時間: 1-2h
   - 依存: 理論書3.1/3.2節 (既存)
   - テスト: 警告パネルがすべてのページで一貫性あり

8. **汎用 warning banner** を pages に統合
   - 所要時間: 1h

### Phase 4: 最終（Hub + 統合テスト）
9. **Instinct ドキュメント参照** → `dashboard/pages/page_24_kamata7_theory_hub.py`
   - 所要時間: 1-2h
   - 機能: 理論書へのナビゲーションハブ

10. **統合テスト** → 全ページ動作確認
    - 所要時間: 2-3h
    - テストシナリオ: [別途 test plan で定義]

---

## 5. テスト戦略

### Unit Tests
```python
# dashboard/tests/test_kamata7_segments.py
def test_classify_segment_2f_left_north():
    assert classify_segment(100, x=5, y=2) == '2F_L_N'

def test_classify_segment_3f_right():
    assert classify_segment(200, x=15, y=3) == '3F_R'

# dashboard/tests/test_kamata7_cooling_zones.py
def test_cooling_zone_variable():
    assert is_in_cooling_zone(3065) == True

def test_cooling_zone_structural():
    assert is_in_cooling_zone(3135) == True

# dashboard/tests/test_kamata7_event_checks.py
def test_today_event_flags():
    flags = get_today_event_flags(date(2026, 7, 30))  # DD30
    assert flags['is_dd30'] == True
```

### Integration Tests
```python
# dashboard/tests/test_kamata7_integration.py
def test_event_checks_page_renders():
    """ページ表示時のレンダリング成功確認"""

def test_segments_page_with_machine_data():
    """実データでセグメント分類が正確"""

def test_dd_kakuban_heatmap_colors():
    """ヒートマップの色が理論値と一致"""
```

### Manual E2E Tests
1. ブラウザで page_20-24 を順に表示
2. 日付を変更してイベント条件が動的に変わることを確認
3. 台番号をフィルタして冷却ゾーン警告が正確に表示されることを確認
4. 理論書3.1/3.2節との整合性を目視確認

---

## 6. リスク・対応

| リスク | 発生可能性 | 影響 | 対応 |
|------|---------|------|------|
| LR逆転バグ再発 | 低 | セグメント分類ミス | 既に修正版の `_infer_lr` を使用 |
| debut_date データ品質 | 中 | P#10実装時に影響 | 本計画では P#10 対象外 |
| 異常値台（711等） | 低 | 分類エラー | 例外処理 or warning で対応 |
| Simpson's Paradox | 中 | ユーザー誤解 | P#5で警告パネル実装 |

---

## 7. 完成後の運用・保守

### メンテナンスポイント
1. `document/kamata7_theory.md` が更新された場合
   - 理論書3.1/3.2節 → P#5 (refutation_warnings.py) に反映
   - 理論書2.1節 → P#3 (dd_kakuban.py) データテーブルを更新

2. 新しい Instinct が追加された場合
   - 該当する priority ページに reference link を追加
   - 否定仮説が覆る場合は P#5 に追加

3. 新ホール（Kamata1 等）への拡張
   - `kamata7_*.py` をテンプレートに `<hallname>_*.py` を作成
   - `HALL_EVENT_DIGITS` 等の定数をホール別に拡張

---

## 8. 参照資料

- **理論書**: `document/kamata7_theory.md` (第2-3節)
- **ML ロジック**: `ml/experiments/walkforward_scoring/scoring_model.py`
- **EDA ロジック**: `eda/core.py`, `eda/kamata7_dd_heatmap.py`
- **Instinct**: `document/instincts/2026-07-0*.yaml` (冷却ゾーン, DD×角番等)
- **既知バグ**: 
  - LR逆転: scoring_model.py:55-58% (修正済み, 新版使用)
  - dd30欠落: date_info_calculator.py (修正済み 2026-07-02)
  - 冷却ゾーン誤推薦: 2026-07-04 Instinct

---

## 9. Codex への作業依頼

以下の順序で実装してください：

**Phase 1** → **Phase 2** → **Phase 3** → **Phase 4**

各 Phase 完了時に Claude へ報告。質問・ブロッカーは agmsg で随時相談してください。

---

**文書作成者**: Claude (Claude Code)  
**次レビュー**: 実装完了後
