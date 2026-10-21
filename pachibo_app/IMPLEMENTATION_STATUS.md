# 遊技収支帳：実装済み機能と検証状況

確認日: 2026-10-21。`実装済` はソースコードで動作経路を確認した意味で、実機で十分に検証した意味ではない。`要検証` はコードがあっても公開品質を確認できていない項目。特に公開・配布を示す一覧ではない。

## 画面と日常入力

| 機能 | 状態 | 根拠・補足 |
|---|---|---|
| 起動時カレンダー、下部「カレンダー・分析・記録」 | 実装済 | `MainActivity.java` の `onCreate`、`page` |
| 日付別・月別の収支、正負の色分け、イベント表示 | 実装済 | `CalendarScreen.java`。小画面での視認性は要検証 |
| 一台単位の開始・終了・訂正・削除 | 実装済 | `SessionEditor.java`、`SessionScreen.java`。削除は確認後に実行し、操作の取消し機能はない |
| 現金と玉・メダルの投資・回収を併用 | 実装済 | `SessionEditor.java`、`RecordEditor.java`、`Accounting.java` |
| 開始・終了時刻と「現在時刻」入力、時刻の表示切替 | 実装済 | `FormUi.java`、`SessionEditor.java`、`EntryPreferences.java` |
| 台番号・回転数・仕事量の表示切替 | 実装済 | `EntryPreferences.java`、編集画面。仕事量の計算欄は4円パチンコ用 |
| タグ、メモ、機種・ホール候補、履歴に応じた並び | 実装済 | `TagPicker.java`、`Catalog.java`、編集画面。候補の画面操作は要検証 |
| 新機種の手入力・UTF-8一覧読込 | 実装済 | `MainActivity.java`、`Catalog.java`。ネット経由の自動更新はなし |
| ホール交換率の登録 | 実装済 | `SessionScreen.java`、`AccountStore.java`。時期別レート履歴の管理画面はなし |
| 台移動、明細訂正、訂正履歴の一部取消し | 実装済 | `SessionStore.java`、`SessionScreen.java`。通常の一画面編集とは操作が異なる |

## 分析

| 機能 | 状態 | 根拠・補足 |
|---|---|---|
| 期間・種別・ホール・機種・タグ絞り込み | 実装済 | `SessionReportScreen.java`。開始・終了日は日付選択式 |
| 累積収支、月別、日別、曜日別、ホール別、機種別、ホール×機種、タグ別 | 実装済 | `SessionReportScreen.java`、`AnalysisMetrics.java` |
| グラフ目盛り、上下幅の自動・±3万・5万・10万円 | 実装済 | `DateProfitChart.java`、`SessionReportScreen.java`。実端末の文字サイズ・横幅は要検証 |
| 一台・一日の勝率、中央値、回収率、収支分布、最大落ち込み | 実装済 | `AnalysisMetrics.java`。一日勝率は経費だけの日も含む |
| 時間当たり収支と対象件数 | 実装済 | `AnalysisMetrics.java`。時刻不明の履歴は対象外 |
| 回転数、4円パチンコの計算仕事量と加重回転単価、手入力仕事量 | 実装済 | `PachinkoWork.java`、`PachinkoWorkInput.java`、`AnalysisMetrics.java`。計算仕事量は記録単位で円に丸める |
| 比較結果から元記録を開く | 実装済 | `SessionReportScreen.java`。大量の組合せは先頭30群・各群直近200件に表示制限あり |
| 統計的な勝ちやすさの推定、将来の期待値予測 | 未実装 | 選択バイアス・時期差・少数標本への対策が必要 |

## 移行、保存、公開

| 機能 | 状態 | 根拠・補足 |
|---|---|---|
| Android からの `.pcb` 読込と重複・衝突処理 | 実装済 | `PcbReader.java`、`LedgerDb.java`。形式は非公開であり、他ユーザーの全バックアップでの互換性は未確認 |
| 取込記録とアプリ作成記録のカレンダー・分析・一覧への統合 | 実装済 | `UnifiedLedger.java`。編集フォームと保存形式は別 |
| 統合 CSV、復元用 JSON、全データ ZIP | 実装済 | `UnifiedLedger.java`、`ExportBundle.java`、`MainActivity.java`。CSV単体は完全な復元形式ではない |
| 保存先選択による Dropbox 等への手動保存 | 実装済 | Android のファイル選択画面に依存。Dropbox アカウント連携・自動同期は未実装 |
| 単発・毎週・毎月・DD日のカレンダーイベント | 実装済 | `CalendarEventEditor.java`、`CalendarEventStore.java` |
| ライト・ダーク・端末設定連動、タップ時の触覚反応 | 実装済 | `MainActivity.java`、`FormUi.java`。端末の触覚設定と機種に依存 |
| 広告、買い切り広告解除、購入復元 | 未実装 | 方針のみ `RELEASE_MONETIZATION_PLAN.md` |
| ストア向け署名・AAB・審査素材・公開申請 | 未実施 | `build.gradle` は `versionCode 1`、`targetSdk 35` の試作設定 |

## 検証の事実と空白

- この資料作成前の開発ターンに、`PachinkoWorkTest.java` を含む純 Java の計算テストと `:app:assembleDebug` が成功した。コードがビルドできることと、実端末で入力・復元できることは別に扱う。
- `tests/` と `androidTest/BackupVerification.java` に検証コードがある。すべての画面遷移、表示倍率、端末のファイル提供者、長期利用データについて網羅的に検証した記録はない。
- `.pcb` の分類を個人のバックアップで検証したが、他ユーザーのデータに対する保証ではない。未知のバックアップでの文字コード、壊れた入力、旧版差異、重複・再取込を追加で検証する。個人の原本と件数を公開リポジトリには載せない。
- 保存と復元を異なるエミュレーター・アプリ更新前後で検証し、元データの件数・タグ・金額・イベント・計算条件が一致することを確認する必要がある。実機操作は未確認。
- カレンダーは描画時に統合記録を読み直す。記録が数千件ある場合の描画時間とメモリ使用量は計測していない。
- 公開リポジトリにはソース、テスト、公開用資料のみを含める。個人の `.pcb` 原本、生成した CSV・ZIP・DB、エミュレーターイメージ、デバッグ APK は含めない。

## 読む順序

利用者・共同開発者には [PRODUCT_SPEC.md](PRODUCT_SPEC.md) → この一覧 → [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) の順で提示する。古いAndroidアプリ作成計画は、起動タブなどが現在と異なるため履歴資料とする。実バックアップの件数や金額を含む履歴資料は公開対象から外す。
