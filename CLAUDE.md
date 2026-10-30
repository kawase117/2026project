# Pachinko Analyzer - CLAUDE.md

AIアシスタントへ：このファイルは索引と鉄則だけ。作業の手順は、下の対応表から作業の種類に応じて読みに行く(2026-10-30 に分割)。
サブディレクトリの作業では `database/CLAUDE.md`・`ml/CLAUDE.md` も参照。

## 🔴 最重要ルール（2026-04-29 追加）

**迎合するな。独立した意見を述べよ。**

- ユーザーの提案・予想に同意するだけでは不十分
- 代替案、懸念点、より効果的なアプローチを率先して提案すること
- 技術的・統計的な根拠に基づき、異なる見解があれば明確に述べよ
- このルール自体を口実に、ユーザーの要求を無視することは許されない
- 迎合を避けることと、ユーザーの意図を尊重することは矛盾しない

## 作業の種類 → 読む文書

| 作業 | 先に読む |
|---|---|
| 予測(「◯日の予測」) | `document/procedures/PREDICTION.md`(手順・ジャグラー規則・凍結)、`prediction-format` スキル(ホール節の形の正本)、`document/registry/LESSONS.jsonl`、対象ホールの `memory/halls/<ホール>.md` |
| 答え合わせ | `document/procedures/ANSWERCHECK.md`、`document/registry/LESSONS.jsonl` |
| 予告・イベント日の登録 | `document/procedures/EVENTS.md`、`announce-prep` スキル |
| ホール分析 | `hall-analysis-checklist` / `hall-axis-scan` スキル、対象ホールの `memory/halls/` |
| ジャグラー・RB判別 | `document/JUGGLER_SETTING_PATTERNS.md`(冒頭の必須手順) |
| backtest/ のモジュール選び・追加 | `backtest-module-guide` スキル |
| 過去の意思決定・バグ修正 | `document/sessions/*.md` を grep。月次手順は `session-log-management` スキル |

メモリ(`memory/`)はホール別・テーマ別の小索引に分けてある。MEMORY.md の索引から、扱うものだけ開く。

鉄則の要約(詳細は各手順書):
- 予測文書は開店(10:00)前に `backtest.prediction_ledger freeze-doc` で凍結する。
- 予告は読んだ日のうちに `backtest.announce register`、イベント日は `EVENT_DAYS.jsonl` へ。
- 前日の継続・少台数機種・過去回3回以下を、推す・避けるの根拠にしない(LESSONS)。

## Claude / Codex 作業分担（2026-07-26 追加）

指示がなくても、タスクの性質に応じて適時Claude/Codexの分担を判断し、Codexへの委任を能動的に提案・実行すること。

- **Claude = 指揮監督**：プランニング・設計判断・レビュー・結果分析・ユーザーとの対話
- **Codex = 実装**：単純な実装作業、機械的な修正、定型スクリプト作成は基本Codexに割り振る
- **例外（相談）**：思考を突き詰める必要がある設計判断・アプローチ選定は、実装着手前にCodexへ事前相談してよい（最終判断はClaude）
- 委任前に `codex-prompt-precision` スキルでプロンプトを自己チェックしてから `codex:rescue` を使うこと
- 調査・レビュー限定の依頼と、書き込みを伴う実装依頼(`--write`)を混同しない

## Python実行環境

`python`/`python3`はWindows Storeのダミーエイリアスに解決されて失敗することがある。
スクリプト実行時は `venv\Scripts\python.exe` を明示的に使うこと（`py -3` も可）。
テスト: `venv\Scripts\python.exe -m pytest test/ -q`

## DB型の注意（頻出バグ源）

- **last_digit型の違い**：`machine_detailed_results`はTEXT、`daily_hall_summary`はINTEGER
- **weekday_nth**：必ず`daily_hall_summary`から取得（個別台テーブルにはない）
- **is_zorome の二重定義**：`machine_detailed_results.is_zorome` は台番号の末尾2桁が同じ(00・11…99、`database/json_processor.py`)。`daily_hall_summary.is_zorome` は日付が11日・22日(`database/date_info_calculator.py` の `_check_zorome()`)
- **min_gamesフィルタ**：集計**前**に個別台レベルで適用。表示用の運用規約で、設定シグナルの測定には使わない（選択バイアス）
- フィルタは `utils/filters.py` を使い、各ページにインライン実装しない。SQLは `ALLOWED_ATTRIBUTES` ホワイトリストで検証

全列定義は `database/CLAUDE.md` を参照。

## プロジェクト概要

パチスロホールのデータを収集・分析し、高設定台を予測する。scraper/(ana-slo収集) → database/(SQLite投入・集計) → dashboard/(Streamlit、`streamlit run main_app.py`) → ml/ と backtest/(予測・採点)。
技術スタック: Streamlit 1.56.0 / Plotly 6.7.0 / Pandas 3.0.2 / SQLite / BeautifulSoup。Phase 4 の基本理念(キャリブレーション重視・ホール別モデル)は `ml/CLAUDE.md`。
`main_app.py` は絶対インポート、`dashboard/main.py` は相対インポート。Plotly複合軸は `make_subplots()`。
設計文書は `document/`(`ARCHITECTURE.md` ほか)、実装計画は `document/plans/`。

## GitHub

リポジトリ: https://github.com/kawase117/2026project 、ブランチ: main
- コミット・プッシュは確認不要で、作業の区切りで行う（ユーザー指示 2026-09-14）。コミットは `scripts/safe_commit.py` 経由（pre-commit の ruff 書き換えを再ステージする）。
- 自分が変更したファイルだけをステージする（`git add -A` 禁止。作業ツリーに別セッションの未コミット変更がある）。プッシュ前に fetch し、先行コミットがあれば rebase。
- force push・履歴改変・他セッションの変更の破棄は、引き続き確認を取る。
- `/save` コマンドの詳細は `.claude/skills/save/SKILL.md` を参照。
