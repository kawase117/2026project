# 引退した事前登録

`plan-all` は `backtest/prereg/*.json` だけを読むので、ここの規則はもう凍結されない。
凍結済みの plan の採点はハッシュ照合にこのファイルを使うため、**中身を書き換えず、消さない**。

| 規則 | 引退日 | 理由 | 後継 |
|---|---|---|---|
| `mitoya_mjv_prevph_top3` | 2026-11-06 | みとやのマイジャグラーVが 11/01 を最後にDBから消え、全34台がⅥに替わった | `mitoya_myj6_prevph_top3` |
| `mitoya_mjv_prevdiff_top3` | 2026-11-06 | 同上 | `mitoya_myj6_prevdiff_top3` |

Vの実績はⅥに引き継がない。別の機種なので、Ⅵの規則は標本ゼロから数える。
