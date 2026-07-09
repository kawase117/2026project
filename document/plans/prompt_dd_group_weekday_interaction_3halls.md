# DD系統×曜日交互作用 3ホール横断スキャン

## 目的

`document/instincts/2026-06-10-eda-anomaly-techbias-insights.yaml` の既存知見:
- `weekday-digit-nth-single-dim-all-null`（曜日**単独**は全ホールTier C、確定済み・再検証禁止）
- `kamata7-7kei-monday-strongest-signal`（蒲田7: 7系×月=avg+807, CI=[692,930], n=2850 — 全スキャン中最強）
- `mitoya-4kei-saturday-signal`（みとや: 4系×土=avg+356, CI=[217,493], n=2126）

これらは「DD系統（4系/7系）×曜日」の**一部の組み合わせ**のみが報告されており、以下が未確認:
1. 蒲田7の **7系×土曜**（2026-06-27 DD27は7系×土曜だが、この値が instinct に記載されていない）
2. みとやの **7系×全曜日**（みとやのevent_digitsには27が含まれるが、報告済みは4系のみ）
3. **蒲田1の全パターン**（蒲田1のDD系統×曜日スキャンが一度も実施されていない）

2026-06-27（DD27, 土曜）の3ホール候補台予測が実績とほぼ一致しなかった（台レベルヒット率20-30%、Top10重複0-1件）ことの原因を、既存の検証済みフレームワークで説明できるか確認する。

## 背景データ

`eda/core.py` に既に実装済み:
- `load_hall_df(hall_name)` — `machine_detailed_results` から日付フィーチャー付きDataFrameを返す。`dd_group`（4系/7系/その他）, `day_of_week`, `is_x_day`, `is_any_event` 等の列が既に計算済み
- `HALL_EVENT_DIGITS` — ホールごとのevent_digits定義済み:
  ```python
  HALL_EVENT_DIGITS = {
      "みとや": [4, 14, 24, 7, 17, 27],
      "蒲田7": [1, 7, 11, 17, 21, 22, 27, 31],
      "蒲田1": [1, 7, 11, 17, 21, 22, 27, 31],
      ...
  }
  ```
- `scan_dimension(hall_name, group_cols, filters, min_n, df)` — Tier・p値・ε²・Bootstrap CI・Spearman ρ付きの集計関数

既存の参考実装: `eda/kamata7_dd_weekday_interaction.py`（蒲田7専用、DD(1-31)×曜日の全マトリクスを出力。7/7のホール周年イベントを除外する処理あり）。この構造を一般化する。

## 実装内容

新規ファイル: `eda/dd_group_weekday_interaction_3halls.py`

### 処理内容

1. 3ホール（蒲田1, 蒲田7, みとや）それぞれで `load_hall_df` を呼ぶ
2. 各ホールで以下の2種類のマトリクスを出力:
   - **dd_group × 曜日マトリクス**（4系/7系/その他 × 月〜日）— diff, plus_rate, hit104_rate, n, CI
   - **is_x_day × 曜日マトリクス**（event_digits限定 × 月〜日）— 同上
3. 各ホールの「7系×土曜」の値を明示的に出力し、既存instinctの「7系×月」「4系×土」と並べて比較表を作る
4. 蒲田7のみ、`kamata7_dd_weekday_interaction.py` と同様にホール周年日（7/7）を除外するロジックを残す。他2ホールには周年除外は不要（既存スクリプトに周年日定義がなければ除外しない）
5. 出力は標準出力のprint + `eda/results/dd_group_weekday_3halls.csv` にロング形式で保存（列: hall, dd_group, day_of_week, avg_diff, plus_rate, hit104_rate, n, ci_low, ci_high, tier）

### 統計的妥当性

- `scan_dimension` の Tier・CI・p値の仕組みをそのまま使う（独自の検定を新しく実装しない）
- n が小さいセル（min_n=5未満等、`scan_dimension` のデフォルト挙動に従う）は除外またはフラグ表示
- 2026-06-27単日の検証ではなく、**dd_group × 曜日の集団統計**として評価する（単日の的中率の話とは区別する）

## 期待する出力例

```
=== 蒲田7 ===
dd_group × 曜日マトリクス:
  7系×月: avg=+807 (n=2850, CI=[692,930], Tier A)
  7系×土: avg=??? (n=???, CI=[?,?], Tier ?)   <- 今回知りたい値
  7系×木: avg=+386
  7系×日: avg=+323
  ...

=== みとや ===
  7系×土: avg=??? (n=???)   <- 今回知りたい値
  7系×月〜日: 全曜日の値
  4系×土: avg=+356 (既存確認用)
  ...

=== 蒲田1 ===
  （初実施）全dd_group×曜日の値
```

## 実装上の注意

1. **新規ファイルは `eda/dd_group_weekday_interaction_3halls.py` の1ファイルのみ**。既存ファイル（`eda/core.py`, `eda/kamata7_dd_weekday_interaction.py`）は変更しない。
2. `eda/core.py` の `load_hall_df` と `scan_dimension` をそのまま import して使う。独自の集計ロジックを再実装しない。
3. ホール名の文字列は `eda/core.py` の `HALL_DBS` キーと完全一致させる（"蒲田1", "蒲田7", "みとや" の表記揚れに注意）。
4. CSV出力先 `eda/results/` が存在しない場合は作成する。
5. 既存instinct値（蒲田7 7系×月=+807, みとや 4系×土=+356）と今回のスクリプトの出力が一致するか確認するassertまたはログ出力を入れる（再現性チェック）。一致しない場合は警告を出す。

## テスト

`ml/tests/test_dd_group_weekday_interaction_3halls.py` に以下を含める:
- スクリプトの主要関数が例外なく実行できるスモークテスト
- 既存instinct値（蒲田7 7系×月≈+807, みとや 4系×土≈+356）との再現性チェック（許容誤差つき）
