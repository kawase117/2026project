# scripts/README.md

このフォルダは、**日常運用で繰り返し実行する補助スクリプト**をまとめる場所です。  
主に次の2系統があります。

1. `instincts` 同期（ClaudeCode -> Codex 実行ループ）
2. `tail_ltr` の保守・月次チェック実行

## 運用ルール（AI向け）

- 作業開始時は `instincts` を更新する。
- 長時間セッションでは、重要判断の前または15-20分ごとに再実行する。
- 参照優先順は `document/instincts/ACTIVE_INSTINCTS.jsonl` -> `ACTIVE_INSTINCTS.md` -> 元 `*.yaml`。
- Instinct を書くときは `document/instincts/INSTINCT_TEMPLATE.md` を使い、レビュー時は `document/instincts/EDA_CHECKLIST.md` を通す。

## スクリプト一覧

### `compile_instincts.py`

- 役割: `document/instincts/*.yaml` から有効なInstinctを抽出し、`ACTIVE_INSTINCTS.jsonl`（正本）と `ACTIVE_INSTINCTS.md`（ビュー）を生成する。
- 特徴:
  - 差分なし時は再生成をスキップ（高速）。
  - 既定で `_cli_export.yaml` は除外（必要時のみ `--include-underscored-sources`）。
- 主な実行例:
  - `venv\Scripts\python.exe scripts/compile_instincts.py`
  - `venv\Scripts\python.exe scripts/compile_instincts.py --force`

### `refresh_instincts.ps1`

- 役割: `compile_instincts.py` のPowerShellラッパー。
- 特徴:
  - `venv\Scripts\python.exe` を優先使用し、なければ `python` を使用。
  - 引数はそのまま `compile_instincts.py` に渡す。
- 実行例:
  - `powershell -File scripts/refresh_instincts.ps1`
  - `powershell -File scripts/refresh_instincts.ps1 --force`

### `run_tail_ltr_monthly_update_check.ps1`

- 役割: `ml.experiments.tail_ltr_wed_ops_suite monthly-update-check` を固定パラメータで実行。
- 出力先: `db/experiments/tail_ltr_monthly_update_check_<yyyy-mm-dd>.*`
- 用途: 月次更新可否の判定を再現性ある条件で実行する。

### `run_tail_ltr_split_rule_maintenance.ps1`

- 役割: `ml.experiments.tail_ltr_split_rule_ops_suite run-maintenance` を固定パラメータで実行。
- 出力先: `db/experiments/tail_ltr_split_rule_maintenance.*` など。
- 用途: split-rule の保守チェックと品質確認を定型化する。

## 注意点

- すべてリポジトリルートを基準に実行される前提。
- DB/実験成果物を更新するスクリプトがあるため、必要に応じて事前に `git status` を確認する。
