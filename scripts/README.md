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
  - `--recent-slots`（既定60）で `--max-records`（既定120）のうち直近分の枠を確保する。
    confidence だけで並べると、閾値超えのレコード数が枠を大きく上回るため実効カットラインが
    上がり続け（1476件時点で0.97）、直近21日の適格140件中3件しか載らない状態になっていた。
  - frontmatter の `supersedes` / `invalidates` を読み、対象レコードを
    `superseded` / `refuted` に自動で落として出力から除外する。詳細は `INSTINCT_TEMPLATE.md`。
  - `--ttl-days`（既定90）で古いレコードを自動的に引退させる。
    `verification_status: confirmed` が付いたものだけが免除される。
    訂正時の `supersedes` 記帳は3ヶ月で111件中3件しか行われなかったため、
    「引退させるのに作業が要る」方式から「残すのに作業が要る」方式へ反転させたもの。
    2026-07-31 時点では0件（コーパスが2026-05-08開始のため）で、
    2026-08-06頃から効き始める。`0` で無効化。
- 主な実行例:
  - `venv\Scripts\python.exe scripts/compile_instincts.py`
  - `venv\Scripts\python.exe scripts/compile_instincts.py --force`

#### `--sync-homunculus`（セッション開始時の自動注入）

`ACTIVE_INSTINCTS.*` は**人とCodexが読む一覧**であって、セッション開始時に
自動注入される経路ではない。注入は `everything-claude-code` プラグインの
`session-start.js` が `~/.claude/homunculus/projects/257beeaeb232/instincts/`
を読んで行う。このフラグはそこへ書き出す。

```bash
venv\Scripts\python.exe scripts/compile_instincts.py --sync-homunculus --force
```

- 注入枠は**6件**固定（プラグインの `MAX_INJECTED_INSTINCTS`）。多く置いても届かない。
- 1レコード1ファイルで書き出す。連結形式はプラグインのパーサが誤読する。
- 選定は **confidence 順ではなく日付順**。confidence は同点時のみ見る。
- `--dry-run` で書き込まずに注入予定を確認できる。
- 反映は**次のセッション開始時**。実行しただけでは現セッションに影響しない。
- 既存ファイルは毎回退避（`*_archive_YYYYMMDD/`）してから書き直す。`--no-archive` で削除に変更。

特定のInstinctを常に注入したい場合は `document/instincts/INJECTION_PINS.txt` に
id を1行ずつ書く（`#` 以降はコメント）。

経緯と故障の詳細は `document/instinct_injection_investigation_20260727.md` を参照。

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
