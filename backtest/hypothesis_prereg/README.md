# hypothesis_prereg/

`backtest/forward.py` で機械採点しない仮説の事前登録を置く場所。
ユーザー提示の末尾仮説のように、採点手順を文章で凍結して手で答え合わせするものが対象。

`backtest/prereg/` には置かない。
`backtest/prereg/` は `forward.load_preregs()` が読む台選択ルール（`rule_id` を持つ `PreRegistration`）専用で、
テスト `test_load_preregs_reads_all_real_rules` が「ディレクトリ内の JSON は全件ルールとして読める」ことを保証している。
ここに別スキーマの JSON を混ぜると、`rule_id` の欠けた壊れたルールとの区別がつかなくなる。

スキーマは各ファイルの `prereg_id` / `frozen_at` / `hypotheses[].scoring_procedure` / `result` を参照。
台帳は `document/registry/HYPOTHESIS_LEDGER.md`。
