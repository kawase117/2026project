# DMM / Goraggio on-demand collector

ヒロキMAX蒲田店のDMMぱちタウン内「台データオンライン」から、スロット当日速報を手動取得します。
定期実行は行いません。日次確定値のDBには書き込みません。

## モード

```powershell
# Quick: 全台一覧 + BB/RBが前回から変化した台の当日詳細
scraper\dmm_goraggio\run_collect.cmd -Mode Quick

# Full: 全424台の当日詳細。変化のない同日データは安全に再利用
scraper\dmm_goraggio\run_collect.cmd -Mode Full

# 指定台はQuickでも必ず詳細取得
scraper\dmm_goraggio\run_collect.cmd -Mode Quick -Units 1001,1002,1287

# キャッシュを使わず再取得
scraper\dmm_goraggio\run_collect.cmd -Mode Full -Force
```

標準は4ワーカー、全体のリクエスト開始間隔2.5秒です。4ワーカーは通信・HTML解析・SVG保存を重ねるために使い、
リクエスト開始自体は全ワーカー共通で調停します。iPhone相当のPlaywrightコンテキストでDMM入口を検証し、
画像・フォント・広告等を遮断したうえで、同一モバイルセッションのHTTP接続を再利用します。
429を検知した場合は全ワーカーを65秒休止して同じURLから再開します。端末警告、403、再試行後の429を
検知した場合は完全取得扱いにしません。

## 出力

- `output/latest_quick.json`
- `output/latest_full.json`
- `output/latest_analysis.json`
- `output/latest_run.json`
- `output/mobile_report.html`
- `output/graphs/<台番号>.svg`

個別台ページに過去日が同梱されても、当日の概要・履歴・スランプグラフだけを採用します。
推定差枚はSVG軸とグラフ終点から計算し、サイトの直接表示値とは区別します。
Fullの再利用元は常に同日の`latest_full.json`を優先するため、その後にQuickを実行しても全台キャッシュを失いません。
