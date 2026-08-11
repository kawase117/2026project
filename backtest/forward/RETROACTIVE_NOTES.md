# 事後生成 plan の記録

フォワードテストの前提は「対象日より前に plan を凍結する」こと。
`forward.py` は `target_date <= db_max` しか検知できないため、
DB 取り込みが遅れている場合は対象日を過ぎていても `is_dry_run=False` で
plan が通ってしまう。ここに壁時計上の事後生成を手で記録する。

> **2026-08-11 以降は自動記録に移行した。**
> `plan-all` が実行ごとに `backtest/forward/RUNS.jsonl` へ
> `is_late_wallclock`（対象日 0 時 JST を過ぎてからの凍結か）を残す。
> 以下は手書き運用だった時期の記録で、これ以上追記はしない。

## 2026-08-04 分（生成日 2026-08-05）

対象日 2026-08-04 を、生成日 2026-08-05 に plan した。
`data_asof=20260803` であり、DB に 08-04 のデータは存在しないため
**情報リークは生じていない**（使えるのは 08-03 以前のみ）。
汚れているのは「対象日の経過後に生成した」という点のみ。

厳密な証拠として扱う場合は、この 10 件を除外して集計すること。

- k1_jug_plain_rbz_top3__20260804
- k7_at_histdiff_top3__20260804
- k7_jug_hit104_top3__20260804
- k7_jug_rb_top3__20260804
- mitoya_at_eventdd_histdiff_top3__20260804
- mitoya_jug_eventdd_rb_top3__20260804
- mitoya_jug_eventdd_rbz_top3__20260804
- mitoya_model_gratio_top2__20260804
- rakuen_jug_renovation_rb_top3__20260804
- zassiki_jug_fixed_top3__20260804
