# Pachinko Analyzer - CLAUDE.md

AIアシスタントへ：このファイルをセッション開始時に必ず参照してください。
サブディレクトリに CLAUDE.md がある場合、該当ディレクトリの作業時にそちらも参照すること。
詳細: `database/CLAUDE.md`, `ml/CLAUDE.md`

## 🔴 最重要ルール（2026-04-29 追加）

**迎合するな。独立した意見を述べよ。**

- ユーザーの提案・予想に同意するだけでは不十分
- 代替案、懸念点、より効果的なアプローチを率先して提案すること
- 技術的・統計的な根拠に基づき、異なる見解があれば明確に述べよ
- このルール自体を口実に、ユーザーの要求を無視することは許されない
- 迎合を避けることと、ユーザーの意図を尊重することは矛盾しない

## Claude / Codex 作業分担（2026-07-26 追加）

指示がなくても、タスクの性質に応じて適時Claude/Codexの分担を判断し、Codexへの委任を能動的に提案・実行すること。

- **Claude = 指揮監督**：プランニング・設計判断・レビュー・結果分析・ユーザーとの対話
- **Codex = 実装**：単純な実装作業、機械的な修正、定型スクリプト作成は基本Codexに割り振る
- **例外（相談）**：思考を突き詰める必要がある設計判断・アプローチ選定などは、実装着手前にCodexへ事前相談してよい（Codexの視点を取り入れるため。最終判断はClaude）
- 委任前に `codex-prompt-precision` スキルでプロンプトを自己チェックしてから `codex:rescue` を使うこと
- Codexはread-onlyサンドボックスのため、調査・レビュー限定の依頼と、書き込みを伴う実装依頼を混同しない

## プロジェクト概要

パチスロホールのデータを収集・分析し、機械学習で高設定台を予測するシステム。4フェーズで構成。

- **Phase 1 (scraper/)**: ana-slo.com からデータをスクレイピング → JSON保存
- **Phase 2 (database/)**: JSONをSQLiteに投入、集計・ランク計算
- **Phase 3 (dashboard/)**: Streamlit + Plotlyで15ページのダッシュボード表示
- **Phase 4 (ml/)**: 機械学習による高設定台予測（詳細は `ml/CLAUDE.md`）

## Phase 4 基本理念（要約）

パチスロの本質的な特性を考慮した予測モデル設計：
1. **ギャンブルの不確実性** — キャリブレーション（予測確率と実績の一致度）が重要
2. **店側のランダム化戦略** — 複数の粒度から並行探索が必要
3. **高設定投入パターン** — DD別・日末尾別・曜日別・イベント日・ゾロ目
4. **ホール別戦略の多様性** — ホール別個別モデルが +2.44% AUC向上（Phase 5 検証済み）

詳細・AUC数値・ホール別比較は `ml/CLAUDE.md` を参照。

### ゾロ目（is_zorome）について

テーブルによって定義が異なる点に注意。

- **`machine_detailed_results.is_zorome`** — 台番号の末尾2桁が同じ場合に 1
  - 例: 台番号 100/200…（末尾 "00"）, 11/111…（末尾 "11"）, 22, 33, 44, 55, 66, 77, 88, 99
  - `database/json_processor.py` の `last_two_digits[0] == last_two_digits[1]` で判定
  - データベースでは `is_zorome = 1` でマーク

- **`daily_hall_summary.is_zorome`** — 日付の日が 11 日または 22 日の場合に 1
  - `database/date_info_calculator.py` の `_check_zorome()` で `day in [11, 22]` として判定
  - ホール全体の集計単位なので台番号は関係しない

- **店側の心理** — 末尾ゾロ目台や特定日付（11・22日）に高設定を投入する可能性がある
  - または逆に「ゾロ目は狙われるから避ける」という戦略も考えられる

## 主要エントリーポイント

- `main_app.py` — 起動エントリーポイント（絶対インポート）
- `dashboard/main.py` — ダッシュボード本体（相対インポート）
- `ml/` — 機械学習パイプライン
- `database/` — DBモジュール群
- `scraper/anaslo-scraper_multi.py` — マルチホール対応スクレイパー

## 起動方法

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
streamlit run main_app.py
```

## Python実行環境の固定（繰り返す迷子の解消）

`python`/`python3`はWindows Storeのダミーエイリアスに解決されて失敗することがある。
このプロジェクトには `venv/` が用意されているので、スクリプト実行時は
`venv\Scripts\python.exe` を明示的に使うこと（`py -3` も可）。

## 技術スタック

- **Streamlit** 1.56.0 - Web UI
- **Plotly** 6.7.0 - グラフ・ヒートマップ
- **Pandas** 3.0.2 - データ処理
- **SQLite** (stdlib) - データベース
- **BeautifulSoup** - HTMLパース（Phase 1）

## DB型の注意（頻出バグ源）

- **last_digit型の違い**：`machine_detailed_results`はTEXT、`daily_hall_summary`はINTEGER
- **weekday_nth**：必ず`daily_hall_summary`から取得（個別台テーブルにはない）
- **is_zorome の二重定義**：台番号末尾ゾロ目 vs 日付ゾロ目（上記参照）

全列定義は `database/CLAUDE.md` を参照。

## 実装上の注意事項

1. **Plotly複合軸**：`make_subplots()`方式を使用（Plotly 6.7.0対応）
2. **インポート**：`main_app.py`は絶対インポート、`dashboard/main.py`は相対インポート
3. **min_gamesフィルタ**：集計**前**に個別台レベルで適用（`games_normalized >= min_games`）
   - ⚠️ **これは表示用の運用規約であって、設定シグナルの測定には使わない**（選択バイアスの詳細は `database/CLAUDE.md` を参照）
4. **フィルタは必ず utils/filters.py を使うこと**：各ページにインライン実装しない
5. **SQLインジェクション対策**：`ALLOWED_ATTRIBUTES` ホワイトリストで検証済み

## テスト実行

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest test/ -v
```

## ドキュメント参照先

設計ドキュメントは `document/` 配下に集約。主要ファイル: `ARCHITECTURE.md`, `PHASE2_完全仕様書.md`, `PHASE5_ML_VALIDATION_REPORT.md`, `PHASE6_IMPLEMENTATION_PLAN.md`。
実装計画は `document/plans/`、高度分析は `document/superpowers/` を参照。

過去の意思決定・バグ修正の記録は `document/sessions/*.md` をgrepで検索。
セッションログ管理の月次手順は `/session-log-management` スキルを参照。

## GitHub

リポジトリ: https://github.com/kawase117/2026project
ブランチ: main
修正完了後、ユーザーに「プッシュしますか？」と確認してからプッシュする。
`/save` コマンドの詳細は `.claude/skills/save/SKILL.md` を参照。
