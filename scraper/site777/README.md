# Site777 intraday collector

楽園蒲田のSite777速報値を収集・分析する独立パイプラインです。日次確定値の
`machine_detailed_results`には書き込みません。

## Reference boundary

- Site777の生成物はこのディレクトリの`output/`へ保存します。
- ブラウザプロファイル、OCR画像、一時JSは`runtime/`へ保存します。
- `db/楽園蒲田店.db`はSQLite URIの`mode=ro`で開き、`machine_layout`、
  `machine_layout_history`、`machine_master`だけを参照します。
- Site777固有の機種名対応が必要な場合は`config/machine_aliases.json`へ
  `{"mdc": "machine_name_normalized"}`形式で追加します。

## Run

```powershell
scraper\site777\run_site777_complete.cmd
```

標準では2000G以上の台だけグラフを取得します。収集前に更新時刻を確認し、
変化がなければ取得を省略します。

通常データとグラフは機種単位のパイプラインで並行収集します。2つのブラウザは
ローカルの共有レート調停器を通るため、合計でも2.5秒に1アクセスを超えません。
通常収集は24機種ごとに部分スナップショットを出力し、グラフ側は完成した機種
だけを処理します。OCRも収集中にバックグラウンド実行されます。最終レポートは
通常データと全対象グラフが完走した後にだけ更新されます。

```powershell
scraper\site777\run_site777_complete.cmd -MinGames 2000
```

従来の直列実行へ戻す場合は`-Sequential`を付けます。共有アクセス間隔と通常側の
部分出力単位は、それぞれ`-GlobalIntervalMs`、`-PipelineBatchModels`で変更できます。

```powershell
scraper\site777\run_site777_complete.cmd -Sequential
```

結果は`output/site777_mobile_report.html`です。
