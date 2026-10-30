# 予告とイベント日の登録手順

CLAUDE.md の「イベントカレンダー」節と、メモリの登録関連メモを集めた(2026-10-30)。下ごしらえの定型は `announce-prep` スキル、収集は `twitter-monitor-daily` スキル。

## 1. 予告は即日に登録する

- 予告ツイートを読んだら、**その日のうちに** `backtest.announce register` まで通す。対象日がDB最終日以下になると、`register` は事後登録として拒否する。
- 「収集して」と言われても収集で終えない。同じターンで `announce_autodraft draft --date` → claims確定 → `register` → `event_days add` まで通し、`backtest/announce/LEDGER.jsonl` に入ったことを確かめてから報告する。
- **「登録しますか?」と聞いて待たない。** 予測・収集・分析の途中で当日/翌日の予告を見つけたら、頼まれていなくても登録まで通す(ユーザー指示 2026-09-28・10-04)。
- 閾値は `backtest/announce/README.md` の固定値 +1,800(gratio_mean_diff)。
- 登録済みの予告のclaimsは直接編集せず `backtest.announce amend` を使う。

## 2. 書く前の確認(上書き事故の防止)

- `backtest/announce/<id>.json` を書く前に、`LEDGER.jsonl` に同じkeyが無いこと、`git log -- <path>` に既存コミットが無いことを確かめる。既存ファイルは上書きしない(Pythonなら `open(path, 'x')`)。
- 並行セッションが同じ予告を登録しうる。`ListAgents` で稼働中のセッションを確かめ、いれば分担を連絡する。
- 自分の分析を足すときは登録本体を触らず `.addendum.json` にする。

## 3. 下書きの仕分け

- 下書きの `raw_text` が狙いの投稿か必ず読む。`full_text` が無ければ取り直す。画像が別ツイートに紐付くことがある(19%)。
- 結果発表アカウント(slokotae7等)の「◯月◯日(曜)…」は前日の結果。予告として登録しない。
- 他店の一覧だけ・画像のみでclaimsが作れないものは見送り、理由を報告する。機種名も数値も無い予告は `register` が拒否する。型を捏造しない(機種名が無い全台系は `zentaikei_count n_models=1` で登録できた例あり)。
- 機種名の総称はDBの正式名に直す(`MODEL_ALIASES.csv`)。「?」付きの連想や外部の過去データ要約は、noteに確度を書く。
- 「1ゾロ」などは、まず日付(11日)として読む。

## 4. イベント日の台帳(重要、2026-09-19 ユーザー指示)

- イベント日(合同企画・収録来店・取材・周年・改装・版権など)は必ず `document/registry/EVENT_DAYS.jsonl` に残す。`backtest/event_days.py`(`check` / `add` / `scan`)を使う。
- ホールごとに登録し、同日開催は `--related-halls` で結ぶ。同日か別イベントかは本文とユーザー確認で決め、推測で他ホールに当てはめない。
- 来店イベントは演者名・@ID・好み/関連機種も残す。予告文からの推測は「推測」と明記する。他店の投稿にだけ載る演者が自店にも来たかは「未確認」と書く。
- `eda/event_calendar.py` はDDルールの統計的カレンダーで別物(DD定義の正本はこちら)。
