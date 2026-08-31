# 機械マスターデータベース 完成 & LLM 抽出パイプライン設計

**日時**: 2026-06-12  
**セッション ID**: 継続セッション  
**ステータス**: ✅ 完了 (機械マスター), 🔄 進行中 (LLM パイプライン)

---

## 背景

パチスロ ML モデル構築の前提として、299機械の spec データ（発売日、メーカー、機械割/RTP、ボーナス初当たり確率）を 1geki.jp から完全収集する必要があった。前セッションで curl + regex で多くの機械を埋めたが、RTP データが部分的に欠落していた。

---

## 実装内容

### 1. 機械マスター CSV 完成

**ファイル**: `document/machine_master_research/machine_master.csv`

| 属性 | 状態 | 備考 |
|------|------|------|
| **release_date** | 100% (299/299) | 1geki.jp curl + regex で全機械埋入 |
| **manufacturer** | 100% (299/299) | メーカー情報も同時埋入 |
| **RTP (機械割)** | 100% (299/299) | 最後の 1 機械（マジハロBT）はユーザー提供 |
| **BB 初当たり確率** | 0% (未着手) | 次フェーズ対象 |
| **RB 初当たり確率** | 0% (未着手) | 次フェーズ対象 |

**初期状態 → 最終状態**:
- release_date 欠落: 88 行 → 0 行
- RTP 欠落: 32 行 → 0 行
- manufacturer 欠落: 不明 → 0 行

### 2. 1geki.jp スクレイピング手法の確立

**手法**: WebSearch (site:1geki.jp) で slug 特定 → curl で取得 → regex で HTML テーブル抽出

**セッション中に確認された HTML 日付パターン** (3 種類):
```
パターン 1: <td class="c-w" style="width : 50%;">YYYY年M月D日</td>
パターン 2: <th>導入開始日</th><td>YYYY年M月D日</td>
パターン 3: <time datetime="YYYY-MM-DD">YYYY年MM月DD日</time>
```

**確立された SLUG_CACHE**: 30+ 機械
```python
"1000ちゃんA": "lb_1000chan_a",
"異世界かるてっと": "l_isekai_quartet",
"ストライクウィッチーズ2": "l_strikewitches2",
# ... 30+ entries
```

### 3. LLM ベース RTP 抽出パイプライン設計

**課題**: HTML テーブル構造が 1geki.jp ページごとに異なるため単純 regex では対応不可

**提案されたアーキテクチャ**:
1. `extract_and_batch_tables.py`: HTML テーブル抽出 → batch_N.txt に保存
2. Claude Code (このチャット): batch_N.txt Read → LLM で HTML → JSON 変換
3. Bash: JSON パース → CSV update

**スクリプト実装状況**:
- ✓ `extract_and_batch_tables.py` (完成)
- ✓ `fetch_rtp_via_llm.py` (設計; API キー不要版に変更)
- ⏳ チャット上での JSON 変換処理 (スタンバイ)

### 4. セッション中の重要発見

#### a. 4号機/5号機 vs スマスロ remake の区別
- 旧機種: "データ割愛" → スキップ (既存データ上書き禁止)
- 新機種: 新規 row として記録 ✓

#### b. ゾロ目（is_zorome）定義の統一
- `machine_detailed_results.is_zorome`: 台番号末尾 2 桁が同じ（00, 11, 22...）
- `daily_hall_summary.is_zorome`: 日付が 11 日または 22 日
- テーブルごとに異なる → dashboard で使い分け ✓

#### c. RTP 値の統一フォーマット
- CSV 保存: 小数値 (97.3, 99.8) — % 記号なし
- 1geki.jp: 97.3%, 99.8% 形式 → regex で % 削除して格納 ✓

---

## 検出された品質メトリクス

### データ整合性チェック

| チェック項目 | 結果 |
|------------|------|
| RTP 範囲チェック (97-114%) | ✅ 全て範囲内 |
| 設定1 ≤ 設定2 ≤ 設定5 ≤ 設定6 単調性 | ✅ 確認済み |
| 重複行（同機械の複数 row）の値一致性 | ✅ 検証済み |
| メーカー情報の整合性 | ✅ 確認済み |

### 完成度指標

```
Release Date Completion: 100% (299/299)
Manufacturer Completion: 100% (299/299)
RTP Completion:         100% (299/299)
Overall Readiness:      ✅ ML Feature Engineering Ready
```

---

## 技術的な学習

### LLM を使った HTML 解釈の有効性

**利点**:
- 構造の多様性に対応（regex では不可能）
- 自然言語で指示可能（maintainable）
- エラーハンドリングが容易

**課題**:
- API キー管理が必要
- トークン消費量が多い

**解決策**: チャット上での処理 (会話キャッシュで節約)

### 1geki.jp スクレイピングの実際

**成功率**: 60-70% (slug が正確な場合)
**失敗要因**: 
- 機械が新しすぎて 1geki に未掲載
- slug が標準命名規則から外れている

**対策**: WebSearch を使った slug 特定

---

## 推奨される次のステップ

**優先度 1: ヒートマップ統合完了**
- テスト版から本番版への統合
- UI/UX の確定

**優先度 2: BB/RB 初当たり確率の埋入**
- `extract_and_batch_tables.py` + 同じ LLM バッチ処理フロー
- CSV 列拡張（現在: col 10-21 が未使用）

**優先度 3: ML フェーズへの移行**
- 機械マスター CSV を特徴量ベクトルに変換
- release_date → 経過日数（人気度 proxy）
- manufacturer → ホット/コールド分類
- RTP → 設定配置傾向学習

---

## 次セッションへの引き継ぎ

**保存済み成果物**:
- ✅ `machine_master.csv` (299 行, 100% 完成)
- ✅ `extract_and_batch_tables.py` (RTP/BB/RB 抽出用)
- ✅ `fetch_rtp_via_llm.py` (設計のみ; API キー不要に変更)
- ✅ SLUG_CACHE (30+ 機械マッピング)

**未完了タスク**:
- ⏳ ヒートマップ統合 (page_17_heatmap へ統合)
- ⏳ BB/RB 確率埋入 (チャット上でのバッチ処理)

**推奨の再開地点**:
機械マスターデータが完成したので、**ML 特徴量エンジニアリング フェーズ**に移行するか、**ヒートマップ統合**を先に完了するかを決定してください。

---

**記録者**: Claude Haiku 4.5  
**実行環境**: Windows 11, Python 3.14, curl (1geki.jp scraping)  
**キー成果**: **299 機械 × 3 主要属性 = 100% 完成** ✅
