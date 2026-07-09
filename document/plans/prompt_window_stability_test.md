# Codex プロンプト: 窓幅60d vs 90dの安定性検証

## 背景

窓幅最適化の結果、60日窓が1台あたり差枚+570で最強だった（90日は+440）。
しかしrhoは全窓幅で+0.185〜+0.201とほぼ同じで、diff/台の差が実力なのか偶然なのか不明。
eval期間を変えても60dの優位性が再現するか検証する。

## 固定前提

- DB: `db/マルハンメガシティ2000-蒲田7.db`
- セクション定義: `ml/experiments/walkforward_scoring/config.py` の SECTION_RANGES_2F, SECTION_RANGES_3F
- 座標: `scoring_model.build_score_context()` を使用
- フィルタ: `games_normalized >= 1500`、日付`0707`除外、台番号`2026`除外
- リーク防止: `date_dt < target_date` を厳密適用
- 評価対象: Top5セクション × 5台（25台/日）
- 差枚は1台あたり平均で出力する

## 実装

```
ファイル: eda/window_stability_test.py
```

### 検証方法

eval期間をずらして複数回walk-forwardを実行し、60d vs 90dの優劣が安定するか確認する。

1. **eval期間のスライド**: eval_days=30で、開始日を30日ずつずらす
   ```
   期間A: 最新30日（例: 2026-05-29 〜 2026-06-28）
   期間B: その前の30日（例: 2026-04-28 〜 2026-05-28）
   期間C: さらに前の30日（例: 2026-03-29 〜 2026-04-27）
   期間D: さらに前の30日（例: 2026-02-27 〜 2026-03-28）
   期間E: さらに前の30日（例: 2026-01-28 〜 2026-02-26）
   期間F: さらに前の30日（例: 2025-12-29 〜 2026-01-27）
   ```
   DB内の全日付を取得し、末尾から30日ずつスライスして最大6期間を作る。
   各期間の先頭日からwindow_days分のデータが確保できない場合はスキップ。

2. 各期間で window=60d と window=90d の両方を実行し、以下を比較:
   - Spearman rho（section score vs actual hit rate）
   - hit率
   - 1台あたり平均差枚
   - 勝率（diff > 0の日数/全日数）

3. 60dが90dを上回った期間数 / 全期間数 で安定性を判定

### 出力

```
| period | start | end | days | window | rho | hit_rate | avg_diff | win_rate |
| A | 2026-05-29 | 2026-06-28 | 30 | 60 | ... | ... | ... | ... |
| A | 2026-05-29 | 2026-06-28 | 30 | 90 | ... | ... | ... | ... |
| B | 2026-04-28 | 2026-05-28 | 30 | 60 | ... | ... | ... | ... |
| B | 2026-04-28 | 2026-05-28 | 30 | 90 | ... | ... | ... | ... |
...
```

サマリー:
```
| metric | 60d_wins | 90d_wins | ties | total_periods |
| rho | X | Y | Z | N |
| avg_diff | X | Y | Z | N |
| hit_rate | X | Y | Z | N |
```

Wilcoxon signed-rank test（60d vs 90dのpaired比較）:
```
| metric | 60d_mean | 90d_mean | diff | wilcoxon_p |
```

### 注意
- DBデフォルトパスは `db/マルハンメガシティ2000-蒲田7.db`（`--db-path`引数で変更可能にする）
- `to_markdown()` は使わない。print文で出力する
- 出力先: `eda/results/window_stability_test/report.md` + CSV
- 期間ごとのサンプル数が少ない（30日）ため、Wilcoxonのp値は参考程度
- 全期間でwindow分のtrainデータが確保できることを確認してからループに入る

## 評価基準

- 60dが全期間または大多数（5/6以上）でavg_diffで90dを上回れば、60dへの変更を推奨
- 60dが勝ったり負けたりする場合は、90d（安全策）を維持
- rhoの差は小さいと予想されるため、avg_diffとwin_rateで判断する
