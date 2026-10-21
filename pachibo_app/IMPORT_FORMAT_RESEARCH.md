# 他アプリのエクスポート形式調査（2026-10-21）

この資料は公開されている仕様・ソースコードで確認した範囲を示す。個人の遊技履歴や他アプリの実エクスポート原本は収集・配布していない。検証用データは公開形式に合わせた合成値である。

| アプリ | 確認できた出力 | 今回の取込 | 検証限界 |
|---|---|---|---|
| ぱち簿 | 利用者が保有する `.pcb` | 既存の専用取込を維持 | 他の版・他利用者の原本は未検証 |
| pRecord | [公式Android CSV出力説明](https://p-cloud.info/manual/pages/android-export.html)と[公式CSV例](https://p-cloud.info/manual/pages/android-import.html)。例の見出しは `日付,店舗コード,店舗,メーカー,機種コード,機種,台番号,投資額,回収額,収支,メモ,稼働時間,時給` | 汎用CSV画面で見出しを認識し、日付・投資・回収・店舗・機種・台番号・メモ・稼働時間・照合用収支を自動候補にする | 公式掲載例に基づく。現行版から実際に出力したCSVは未入手。種別・タグ・貯玉のない列を補完しない |
| pachi-ev-analyzer | [公開ソースのCSV・JSON出力実装](https://github.com/kawano09023-droid/pachi-ev-analyzer/blob/main/src/app/page.tsx)。CSV見出しは `date,machine,store,investment,return,profit,memo`。JSONは `records` と `settings` を持つ | CSVは列自動候補、JSONは専用入口。JSONの `type` から遊技種別を設定し、`unitDiff` を含む元の行と元JSON全体を保存する | 公開ソースと合成データによる検証。配布版の実出力ファイルでは未検証。元アプリの資金設定は適用しない |
| パチンコ・パチスロ収支管理など | [Google Playの説明](https://play.google.com/store/apps/details?id=com.gevvoihorry.PachinkoBalance)にCSV出力機能の記載あり | 汎用CSVの列対応で取り込める可能性がある | 見出し・文字コード・行の例が公開確認できず、アプリ固有の対応を名乗らない |
| まわパチ | [Google Playの説明](https://play.google.com/store/apps/details?id=com.reasin.pachiapp)にCSV・JSON出力機能の記載あり | CSVは汎用列対応の対象 | 実際のCSV/JSON構造が未確認。JSONを専用形式と誤認して読まない |

汎用CSVはUTF-8を先に厳密に読み、失敗したときだけ利用者に確認してWindows-31Jで再読込する。カンマ・タブ区切りを判定し、必須列と先頭行を確認してから一括保存する。行の欠損、収支の不一致、同一IDの内容衝突は取り込まず、保存済みデータを部分変更しない。CSVにない遊技種別や現金・玉メダル内訳は推測しない。

今後、アプリ名を冠した正式対応を増やすには、そのアプリの実出力ファイルを権利者・利用者の許可を得て入手し、個人情報を除いた再現用フィクスチャで列、文字コード、欠損値、複数行、再取込、形式の版差を検証する。実原本はリポジトリにコミットしない。
