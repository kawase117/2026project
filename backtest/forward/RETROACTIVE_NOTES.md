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

## 2026-09-11 バグにより plan を破棄・再凍結（rakuen_increase_window7_top3__20260912）

`load_frame` に足した `days_since_increase` の計算に誤りがあり、
`merge_asof` が索引を振り直すことを見落として `reindex` していたため、
経過日数が無関係な機種に紐付いていた。

その結果、9/7に増台された甲鉄城のカバネリ・革命機ヴァルヴレイヴ2 ではなく
スマスロ北斗の拳・モンスターハンターライズ・戦国乙女4 が選ばれていた。
**ルールが意図した集合をまったく選べていなかった**ので、この plan は
証拠として使えない。対象日(20260912)は未到来・未採点なので破棄し、
修正後に再凍結した。

LEDGER には破棄前の plan_digest = c8a31cd0e5dddb1c が残る。
破棄後の再凍結ぶんと2行並ぶので、突き合わせのときは後者を採る。
結果を見て選び直したわけではない（対象日のデータはまだ存在しない）。
