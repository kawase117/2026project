# 休止スキル置き場

ここに入っているスキルは **Claude Code の探索対象外** です。
探索対象は `.claude/skills/<name>/SKILL.md` の一階層のみなので、
`_archive/<name>/SKILL.md.archived` は読み込まれません（拡張子でも二重に保証）。

## 復帰手順

```bash
mv .claude/skills/_archive/<name> .claude/skills/<name>
mv .claude/skills/<name>/SKILL.md.archived .claude/skills/<name>/SKILL.md
```

## 収容物（2026-09-11 棚卸）

| スキル | 休止理由 |
|---|---|
| run-ml-experiment | `ml/` が直近60日で3ファイル変更のみ。旧 ltr-pipeline-guide / ml-experiment-logger を統合済み |
| pachinko-ml-evaluation | 同上。LTR内部評価（walk-forward・ECE・NDCG）専用 |
| pachinko-ml-feature-engineering | 同上 |
| ml-hyperparameter-guide | 同上 |

いずれも内容が誤っているわけではなく、`ml/` の稼働が止まっているための退避です。
LTRを再開するときはまず本ディレクトリを見ること。
スクリプト実体（`ml/last_digit/tail_ltr_split_rule_nextday_gpu.py` 等）は削除していません。

## ここに入れなかったもの

- `kamata7-data-processing` — ML固有ではなく `eda/` `backtest/` も使うセグメント分類規約のため現役維持
- `prediction-evaluation` — 予測vs実績の答え合わせ（末尾・ゾロ目）。LTR内部評価とは別物のため現役維持
