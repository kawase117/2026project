---
name: daidata-mitoya-daily
description: Collect current-day, per-machine data from Daidata Online for Mitoya Omorimachi (store 101309). Use for this hall's slot data only; include 21.3-yen slots and exclude 5-yen slots and pachinko.
---

# みとや大森町・当日スロット収集

## 対象

- ホール: みとや大森町店、store ID `101309`。
- 当日分のみ。日付は Asia/Tokyo の今日を基準にし、ページの更新日時も照合する。
- スロットのみ。`21.30`（21.3円）を対象にし、`5.00`（5円）とパチンコは含めない。
- 台番号別の一覧値を収集する。`最大持ち玉` は差枚ではないので、別の指標として扱う。
- この会話でユーザーは対象サイトの収集許可を得たと明言している。この許可は store `101309` のこの用途に限定し、別ホールや別サービスへ広げない。新しい会話で許可の文脈がなければ、サイト運営者側の許可が自動取得にも及ぶかだけ確認する。ホールの管理権限だけから運営者の許可を推定しない。

## 取得経路

スマートフォン用 User-Agent を用い、同一のHTTPセッションとCookieを維持する。

1. `/101309/ballPriceList?ps=S` から貸玉別へ進む。
2. `/101309/list?mode=psModelNameSearch&ballPrice=21.30&ps=S` を開き、21.3円の機種名リンクと各リンクに表示された台数を読む。5円の `ballPrice=5.00` リンクは辿らない。
3. 機種名リンクの `unit_list?model=...&ballPrice=21.30&ps=S` を開く。各機種ページに台番号別の当日集計がある。
4. 同意画面が表示された場合は、許可範囲内でサイトの通常フォームを使い、同じセッションで続ける。CAPTCHA、403、同意画面の反復など通常手順で通らない制限は回避しない。

`/all_list?ps=S` は5円台も混在し、`ballPrice=21.30` を付けても21.3円だけに絞れなかった。機種別リンクから `unit_list` を辿ること。

## 行と列の対応

`unit_list` の表は10個の見出しに対し、データ行の先頭に空のアイコン用 `<td>` が付くことがある。台番号セルを先頭列と誤認すると全フィールドが1列ずれる。毎回見出し・セル数を確認し、下の対応を満たさないページは出力しない。

| データ行セル | 項目 |
|---:|---|
| 0 | 空のアイコン列（読み飛ばす） |
| 1 | 台番号 |
| 2 | 累計スタート |
| 3 | BB回数 |
| 4 | RB回数 |
| 5 | 最大持ち玉 |
| 6 | BB確率 |
| 7 | RB確率 |
| 8 | 合成確率 |
| 9 | 前日最終スタート |
| 10 | 当日スタート回数 |

台番号は行の `detail?unit=...` リンクと照合する。確率は `1/252.3` のような表示を文字列のまま保ち、空値やゼロを推測で補わない。

## 負荷と停止条件

- 機種ページは直列で取得し、リクエスト間に少なくとも3秒空ける。
- `429 Too Many Requests` が1回でも返ったら直ちに巡回を止める。UA変更、プロキシ、並列化、即時再試行で制限を迂回しない。再開が必要なら十分な間隔を置く。
- 403、繰り返す同意画面、台数不一致、列構造変更でも停止する。
- 全機種の取得が成功するまで最終CSVを書かない。部分結果は完成データとして提示しない。

## 検算と出力

- 機種一覧に表示された台数の合計と、取得した行数が一致すること。
- 台番号が一意であること、全行の貸玉が21.3円であること、別区分の台がないことを確認する。
- 代表行を元HTMLの見出し・値と直接照合して列ずれを防ぐ。
- ページの日付が対象日と一致することを確認する。ページ更新時刻、巡回開始・終了時刻を記録し、巡回中に更新があり得ることを明記する。
- 出力先はリポジトリルートの `mitoya_omorimachi_slots_21.3yen_YYYY-MM-DD.csv`。同名ファイルがあれば上書きせず、取得時刻をファイル名に加える。
- 列は `BusinessDate, ObservedAt, Price, Machine, Unit, CumulativeStart, BBCount, RBCount, MaxPayout, BBProbability, RBProbability, CombinedProbability, PreviousFinalStart, StartCount`。
- 完了報告では対象日・取得時刻・機種数・台数・除外条件・保存先を伝える。最大持ち玉を差枚として説明しない。

## 実装(2026-10-05)

収集から分析までの一括実行: `scraper\daidata\run_mitoya_complete.cmd`(個別: `python -m scraper.daidata.collect` / `.analyze`)。
CSVとレポートは `scraper/daidata/output/` に出る。同意画面はユーザー承認のうえ通常フォームで自動送信する。
差枚が無いため分析はRB単独・設定推定・回転数比のみ。詳細は `scraper/daidata/README.md`。
