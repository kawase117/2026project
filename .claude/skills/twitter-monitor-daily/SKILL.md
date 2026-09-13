---
name: twitter-monitor-daily
description: scraper/twitter_monitor/ の日次収集パイプライン(run_daily.py)の実行手順と既知の罠。X(Twitter)から予告・結果発表を収集する、収集が飛んでいないか確認する、画像から機種・台番号を抽出する、取りこぼしをbackfillする、といったときに使う。「成功したのに取れていない」系の無言の失敗が複数あるため、実行後の検証手順まで含めて必ずこの順で回す。
---

# twitter_monitor 日次運用

`scraper/twitter_monitor/` は直近60日で `run_daily.py` が7回変更と本プロジェクト最多churn。
このパイプラインは **EXIT=0 のまま失敗する経路が複数ある** ため、実行後の検証まで含めて1セットで扱う。

## 監視対象アカウント（`config.py`）

| handle | ホール | 役割 |
|---|---|---|
| kawasakislot | 楽園蒲田 | 予告+答え合わせ |
| slokotae7 | 楽園蒲田 | 答え合わせ |
| fanta_tenchou | 楽園蒲田 | 店長 |
| 999999Q9Q | 蒲田7/蒲田1 | 予告+答え合わせ |
| j75gJ3j1539G | 蒲田7/蒲田1 | 蒲田一店長 |
| ngc2070r136a1 | 蒲田7/蒲田1 | 蒲田七店長 |
| kengyo_niki | ヒロキ | 答え合わせ |
| sloneko222 | ARROW池上・みとや大森町 | 結果報告 |

状態は `scraper/twitter_monitor/state.db`、画像は `images/`、認証は `.auth/state.json`。

## 通常実行

```bash
venv/Scripts/python.exe -m scraper.twitter_monitor.run_daily
```

段階は collect → gap補填 → 本文取り直し → 画像抽出 → ラベル付け。
主なオプション: `--extract-limit` / `--extract-handles` / `--skip-extract` / `--skip-fulltext`。

## パイプライン構成

```
login_setup.py / import_cookies.py   認証（手動・初回のみ）
scrape_tweets.py                     プロフィールTLのクロール
backfill_search.py                   日付窓検索での取りこぼし回収
fetch_full_text.py                   折り畳まれた本文の取り直し
repair_tweet_images.py               誤紐付け画像の取り直し
prefilter.py                         データ表らしい画像だけに絞る
extract_answers.py / extract_local.py 画像→機種・台番号（Codex CLI / Ollama）
infer_hall.py                        台番号・機種からホールを推定
resolve_dates.py                     数字が指す営業日に画像を固定
run_daily.py                         上記の統括
```

---

## 罠

### 1. プロフィールTLは2週半で無言で止まる

**これが最大の落とし穴で、コード側の docstring にも実例が残っている。**
プロフィールTLのページングは約2週半で沈黙し、**エラーを出さずに** 打ち切られる。

> 2026-09-05 の実行が「226 new posts」と成功報告しながら、08-14〜09-01 が
> 全主要アカウントで空。**19日分が1件のエラーも出さずに欠落した。**

`run_daily.py` はこれを踏まえて、クロール前にギャップを測り、数日より古い範囲は
ページング制限を受けない日付窓検索（`backfill_search.py`）に回す設計になっている。
**「成功しました」を信じず、収集後に日付の連続性を必ず確認すること。**

```bash
venv/Scripts/python.exe -c "
import sqlite3
c=sqlite3.connect(r'scraper/twitter_monitor/state.db')
for h,d,n in c.execute('select handle,substr(created_at,1,10) d,count(*) from tweets group by 1,2 order by 1,2 desc'):
    print(h,d,n)
" | head -40
```

### 2. 画像が別ツイートに紐付く

`scrape_tweets.py` が画像を隣のツイートに紐付けていた実績がある（**220投稿中42件・19%**）。
画像由来のデータは本文と突き合わせ、**画像単位で** 検証する。
疑わしければ `repair_tweet_images.py` で個別ステータスページから取り直す。

### 3. 予告は即日登録しないと詰む

収集した予告は当日中に `backtest/announce.py register` まで通す。
`register` は `target_date <= db_max` を拒否するため、翌日以降は事後登録になり登録不能。
下ごしらえは **`announce-prep` スキル**、モジュールの地図は **`backtest-module-guide`** を参照。

### 4. 予告アカウントの自己申告実績は水増し

予告本文に載る「過去の的中実績リスト」をルールの根拠に引用しない。
kawasakislot の実績リストを閾値+1800で採点し直すと **10件中2件**。
合わない日は「ー」で消え、DDの解釈も日替わりで変わる。

### 5. 本文は130〜180字で切れている。読む前に必ず全文を取る

タイムラインの article は長文を畳むので `tweet_text` は途中で切れ、予告では
**仕掛けの列挙が始まる位置でちょうど落ちる**。日次の `fetch_full_text.py` は
`run_daily.py` の `HALL_KEYWORDS` に載ったホールしか取り直さない。

> 2026-09-14、`HALL_KEYWORDS` が楽園・蒲田1・蒲田7 の3ホールしか無く、kawasakislot の
> 「9/14 レイトギャップ平和島」予告が「狙い目」の直前で切れたまま残った。
> 朝の収集も 08:10 時点で全文取得の工程に届いておらず、ホール選びに間に合わなかった。
> 取り直すと「設置上位7機種から最低1機種は必ずニブイチ」「列・末尾ニブイチ」が出てきた。

**指示を待たずに、次を毎回やる。**

1. `state.db` から投稿を読むときは `COALESCE(full_text, tweet_text)` と一緒に
   `full_text IS NULL` と `length(tweet_text)` を出す。
2. `full_text IS NULL` で `tweet_text` が120字以上、または末尾が列挙・見出しの途中で
   終わっている投稿は、**分析や登録に使う前に** その場で取り直す:
   ```bash
   cd scraper/twitter_monitor
   PYTHONUTF8=1 ../../venv/Scripts/python.exe fetch_full_text.py --tweet-ids <id1>,<id2>
   ```
   1件あたり6〜12秒待つので、対象は判断に使う投稿だけに絞る。
3. 取り直しても `full_text` が `tweet_text` と同じ長さなら、切れていなかったと記録する。
4. 新しいホールの DB を作ったら `HALL_KEYWORDS` にも足す（キーは announce の hall 表記）。

### 6. 日本語が化けたら

PowerShell の表示崩れを Python 側のバグと誤診しない。切り分けは `mojibake-debug` スキル。

## 関連スキル

- `announce-prep` — 予告の事前登録の下ごしらえ
- `backtest-module-guide` — 収集後のモジュール地図
- `mojibake-debug` — 機種名・ホール名の文字化け切り分け
