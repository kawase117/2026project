# 事前登録スキーマに「機種粒度」を実装

**日時**: 2026-08-04
**セッション**: 2026project (main)
**背景**: 2026-08-01のセッションで「選択粒度（機種を選ぶ／台を選ぶ）はホールの属性」であることが測定済みだった（みとや・楽園・ヒロキ・レイトギャップは機種型、蒲田7は台型）。しかし `backtest/prereg.py` + `backtest/forward.py` のフォワードテスト基盤は台粒度しか表現できず、日々の予測は機種粒度で手作業に頼っていた（実際に使っている手法が永遠にフォワード検証されない状態）。この断絶を埋めるのが目的。詳細な根拠は `document/sessions/2026-08-03T-rakuen-dd1-prediction-allhall-and-metric-correction.md` §2.1・§2.4・§2.5。

## 実装内容

### 1. `backtest/prereg.py`
- `PreRegistration` に `selection_unit: str = "machine"`（許容値 `{"machine", "machine_model"}`）と `min_machines_per_model: int = 1` を追加。
- **freeze_hash の後方互換**: `freeze_hash()` は `asdict(self)` 全体のSHA256なので、フィールド追加だけで既存ルールのハッシュが変わり、`backtest/forward/*.json` に蓄積した既存のフォワードテスト証拠が全部「plan作成後に書き換えられた」扱いで検証不能になる恐れがあった。対策として `_V1_FIELDS`（v1時代のフィールド集合）を定数化し、`freeze_hash()` は「v1以降に追加されたフィールドが現在デフォルト値と一致する場合」はpayloadから除去してからハッシュする実装にした。理由はコード内コメントに明記済み。
- `validate()` に `selection_unit` / `min_machines_per_model` の検証を追加。

### 2. `backtest/run_backtest.py`
- `ALLOWED_SCORES` に `hist_model_gratio_mean_diff`（機種粒度専用: G比×平均差枚、総和ベース）を追加。2026-08-01の正解ラベル6件検証でこの複合指標が最上位（平均順位5.2位・上位10.1%）だった一方、hit104率は下から2番目と判明していたため、hit104率ではなくこちらを主指標にした。
- `usable_models(hist, reg)` を新設: `min_history_days`（行数）と `min_machines_per_model`（lookback窓内の異なる台番号数）の両方を満たす機種名の集合を返す。これは*過去*データのみで決まるので当日の候補集合を絞ることにはならない（2026-08-01の「n台≥9足切りが全台系を構造的に取り逃がした」という教訓を踏まえ、当日の候補プールをこの下限で絞ってはいけない、という制約を守っている）。
- `run()` を `reg.selection_unit` で分岐。機種粒度のときは機種名でスコアリングし、選ばれた機種の全設置台を picks に含める。

### 3. `backtest/forward.py`
- `plan()`: `selection_unit == "machine_model"` のとき機種名でスコアリング → 直近営業日ロスターを (machine_number, machine_name) ペアで取得（games>0等の稼働フィルタを先にかけると台入替直後・低稼働台が欠落するバグを回避）→ 選択機種の設置台を全部 `picks` に記録。`picks` の既存キー（machine_number/machine_name/score/history_days）は維持しつつ、`models` セクション（機種名・スコア・履歴行数・所属台番号リスト）を追加。
- `score()`: `_model_perspective()` を追加。機種ごとの総和ベース集計（sum_diff/sum_games/mean_diff）を出す。既存の `mean_diff_per_pick`/`mean_edge_per_pick`（全pick行を等重みで扱う総和ベース平均）はそのまま有効。

### 4. 新規ルール登録
`backtest/prereg/mitoya_model_gratio_top2.json` — みとや、機種粒度top2、`hist_model_gratio_mean_diff`、lookback 21日、min_history_days 10。楽園は8/1以降のレジーム変更で機種エッジが失効判定済み（`2026-08-03-rakuen-zentai-regime-invalidates-model-edge`）のため対象外にした。
評価期間 `eval_start=20260805`（実行日翌日）〜`20270805`。成功基準: フォワード20エントリー日経過時点で、指名機種全台の総和ベースedge（対ホール全体同日平均）の平均が正かつ95%CI(block7)下限>0。

未来日（2026-08-05、DB最終日2026-08-02より後）でplanを実際に凍結: `backtest/forward/mitoya_model_gratio_top2__20260805.json`（`--allow-past` は不使用、証拠として有効）。

## 検証

- `test/backtest/test_prereg_freeze_hash_compat.py` を新設。既存11ルール全件のfreeze_hashが変更前と完全一致することを固定し、既存38件の凍結済みplanが全て `_reg_from_plan`/`_verify_ledger` を通ることを確認（score済みなので再採点はしていない）。
- フルテストスイート（`pytest test/`）505件パス。
  - 失敗1件（`test_kamata7_theory_dashboard.py::test_real_kamata7_event_kind_summary_keeps_2026_dd17_counts`）と、ハング1件（`test_gate_ranking_test.py::test_run_gate_ranking_test_writes_expected_files_and_is_deterministic`）が見つかったが、`git stash` で変更前ツリーに戻しても同じ失敗/ハングが再現することを確認済み。今回の変更とは無関係の既存問題。
- 作業中、`scraper/anaslo-scraper_multi.py` に自分が加えていない差分（date range更新）が既にワーキングツリーにあることに気づいたが、無関係な既存の未コミット変更のため触れていない。

## 次のステップ

1. データが2026-08-05分まで反映されたら以下で採点:
   ```bash
   venv\Scripts\python.exe -m backtest.forward score backtest/forward/mitoya_model_gratio_top2__20260805.json
   ```
2. 判定は本ルール1本のフォワード結果のみで行う（バックテスト数値は採否根拠にしない）。20エントリー日を待つ。
3. ヒロキでの機種粒度ルール登録は未着手（今回はみとやのみ）。必要なら同様の枠組みで追加登録できる。

---
**記録者**: Claude Sonnet 5
**ステータス**: ✅ 完了
