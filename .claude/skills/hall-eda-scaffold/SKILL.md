---
name: hall-eda-scaffold
description: 既存ホールのEDAスクリプトを別ホール/別軸へ複製・改変する際の定型手順(共通ユーティリティの再利用・命名規約・重複確認)をガイドする。eda/配下に221本以上あるスクリプトを都度ゼロから書き直すのではなく、eda/core.py・eda/briefing_common.pyの既存関数を優先して呼び出す。
---

# Hall EDA Scaffold Skill

## トリガー
- 「〇〇ホールでも同じ分析をやってください」「このスクリプトをXXホール向けに」と言われたとき
- 既存のDD別/角番別/末尾別分析を別ホールや別軸(セクション、曜日等)へ横展開するとき

## 背景
2026-08-25のmirror-review(`document/mirror_evidence_2026-08-25.md`セクション4-B)で、既存の類似EDAスクリプトをコピーして定数だけ差し替える作業が4回以上独立に確認された(mitoya_current_q5_list→mitoya_xdds_screening→mitoya_machinename_axis_eda等、kamata7_dd_internal_structure等)。`kamata7-data-processing`スキルは蒲田七固有の処理に限定されており、この「横展開」自体の定型化はカバーしていない。

## やること

1. **新規に書く前に必ず既存スクリプトをGlobで探す**
   ```
   Glob eda/*<キーワード>*.py
   ```
   同じ軸(DD/角番/末尾/セクション/曜日)で別ホール向けに書かれたスクリプトが既にあれば、それを土台にする。ゼロから書き直さない。

2. **DB読み込み・統計処理は`eda/core.py`と`eda/briefing_common.py`の既存関数を優先する**
   - `eda.core.load_hall_df(hall_name)` — ホール別DataFrameの標準ロード
   - `eda.core.scan_dimension(...)` — 次元別スキャン(ε², bootstrap CI付き)
   - `eda.core.cross_hall_scan(...)` — 複数ホール横断スキャン(ただしプールしての法則性発見は`feedback-no-cross-hall-pooling`instinctにより非推奨。ホールごとの独立結果比較にのみ使う)
   - `eda.core.compute_section_size` / `compute_edge_side` / `compute_debut_features` — レイアウト・新台特徴量
   - `eda.core._epsilon_squared` / `_bootstrap_ci` / `_classify_tier` — 効果量・信頼区間・ティア分類
   - `eda/briefing_common.py` — 機種カテゴリ判定(JUG/HANA/AT/BT)などの共通ロジック
   統計検定(z検定、Fisher検定、Bonferroni補正)を毎回手書きしている場合は、まずこれらのモジュールに同等の関数が無いか確認する。

3. **ホール固有定数はdataclassで明示的に分離する**(`eda/dd_sweep_multihhall.py`の`HallConfig`/`SchemaColumns`パターンを参照)。
   - DB接続パスをハードコードせず`PROJECT_ROOT / "db" / db_name`形式にする
   - スキーマ列名の違い(last_digit型がmachine_detailed_resultsではTEXT、daily_hall_summaryではINTEGER等)は`database/CLAUDE.md`を必ず確認する

4. **出力エンコーディングを最初から固定する**(mojibake-debugスキルの予防策)
   ```python
   if hasattr(sys.stdout, "reconfigure"):
       sys.stdout.reconfigure(encoding="utf-8")
   ```

5. **命名規約**: `<ホール略称>_<分析軸>_<用途>.py`(例: `kamata7_kakuban_dd_precision_eda.py`)。ホール略称は既存スクリプトと揃える(mitoya, kamata1, kamata7, rakuen等)。

## やらないこと
- ホール横断でのプール分析による「共通法則」の探索(`feedback-no-cross-hall-pooling`instinctにより非推奨)。横展開はあくまで「同じ手法を各ホール独立に適用する」ためであり、結果を合算して一般化しない。
- 既存スクリプトと完全に重複する内容の新規作成(Globでの重複確認を必ず先に行う)。

## 実装メモ
このスキルはコードを生成しない。既存の共通ユーティリティ(`eda/core.py`, `eda/briefing_common.py`)を優先させ、重複確認とホール固有定数の分離を徹底させるための手順書として機能する。
