# リポジトリ整理プロンプト（2026-06-11作成）

## 背景

`git status` で確認したところ、約1ヶ月分（document/instincts の日付で 2026-05-08〜2026-06-11）の未コミット変更が蓄積している。
内訳は大きく以下のカテゴリに分かれる：

1. **正規の実装・ドキュメント変更**（コミット対象）
   - `database/`, `dashboard/`, `ml/` 配下の機能追加・修正
   - `document/instincts/*.yaml`（新規・更新・削除）
   - `document/plans/`, `document/sessions/`, `document/reports/` 等の設計・記録ドキュメント
   - 新規テストファイル（`test/`, `ml/tests/`）
   - `dashboard/pages/page_17_heatmap.py`, `database/monthly_trend_calculator.py` などの新機能モジュール

2. **実験成果物**（要検討：保存 or .gitignore）
   - `ml/last_digit/reports/*.csv`, `*.json`（CatBoost/XGBoost実験結果）
   - `ml/experiments/results/`
   - `data/` 配下の中間データ（parquet, csv）

3. **明らかな一時ファイル・デバッグ出力**（削除候補）
   - ルート直下の `_*.txt`, `_*.py`, `_*.parquet`（例: `_accuracy_analysis_0606_0607.txt`, `_eval_0606_0607.py`, `_oof_kamata7.parquet` など多数）
   - `tmp/`, `tmp_*.txt`, `tmp_*.csv`, `nextday_prediction.log`, `db_search_results.txt`, `db_all_machines.txt`, `search_results*.txt`, `validation_report.txt`, `validation_summary.json`
   - `.pytest-tmp-local/`
   - `catboost_info/`（学習時の自動生成ディレクトリ。`.gitignore` 済みのはずが一部追跡されている）

4. **削除された instincts ファイル**（統合・整理済みと思われる）
   - `document/instincts/2026-05-09-phase7-ml-insights.yaml` 等、複数の `D` (deleted) ファイル

## タスク

リポジトリを安全に整理し、複数の論理的なコミットに分割してプッシュする。

### 手順

1. **`git status --porcelain` で全体を再取得**し、上記4カテゴリに再分類する
   - 1ヶ月分のため、現時点では分類が古くなっている可能性がある。必ず再確認すること

2. **カテゴリ3（一時ファイル）の処理**
   - 各ファイルが本当に不要か、内容を軽く確認してから削除（中身に重要な分析結果が眠っていないか注意）
   - 削除前に一覧をユーザーに提示し、確認を取る
   - 再発防止のため、`.gitignore` に該当パターン（`_*.txt`, `_*.py`（ルート直下のみ）, `tmp_*`, `tmp/`, `.pytest-tmp-local/` など）を追加するか検討する

3. **カテゴリ2（実験成果物）の処理**
   - `ml/last_digit/reports/`, `ml/experiments/results/` 等が `.gitignore` 対象か確認
   - 既にgitignore対象のものが `git status` に出ている場合は `git rm --cached` で追跡解除を検討
   - 再現可能な実験結果か、一意で貴重な記録かをユーザーに確認

4. **カテゴリ1（正規の変更）を機能/ドキュメント単位で分割コミット**
   - 例：
     - `feat: add monthly trend summary tables and dashboard page`（database/monthly_trend_calculator.py, page_17_heatmap.py, table_config.py 関連）
     - `docs: update instincts archive (2026-05-08〜2026-06-11)`（document/instincts/*.yaml 一式 + ACTIVE_INSTINCTS）
     - `feat: add bt_flag machine type and 6-table summary expansion`（database配下の機種タイプ拡張）
     - `test: add mitoya/corner-section/segmentation test suite`
     - その他、関連ファイル群ごとにグルーピング
   - 各コミット作成前に `git diff --stat <files>` で範囲を提示し、コミットメッセージ案をユーザーに確認

5. **最終確認**
   - `git status` がクリーンになっていることを確認
   - 各コミットの `git log --oneline -N` を提示
   - `git push` 前にユーザーに確認

### 注意事項

- **一括 `git add -A` は禁止**。必ずファイル/ディレクトリ単位で `git add` し、何を含めたかを都度提示する
- 大量削除（カテゴリ3）は必ず事前にユーザー確認を取る（Always Confirm Large-Scale Operations Explicitly instinct準拠）
- `db/*.db` 等のバイナリ・大容量ファイル、APIキーや個人情報を含むファイルが紛れ込んでいないか最終チェックする
- 1セッションで終わらない場合は、進捗（処理済みカテゴリ・残タスク）を `document/plans/2026-06-11-repo-cleanup-prompt.md` に追記して次セッションへ引き継ぐ
