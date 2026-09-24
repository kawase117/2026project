---
name: backtest-module-guide
description: backtest/ 配下39モジュールの役割分担と使い分けの地図。「予告を登録したい」「答え合わせしたい」「設定が入ったか判定したい」「並びを検出したい」「セオリーが死んでいないか見たい」といった要求から正しいモジュール・サブコマンドへ最短で辿り着くために使う。backtest/ に新しい分析スクリプトを追加する前にも必ず参照し、既存モジュールの再実装を防ぐ。
---

# backtest モジュール地図

`backtest/` は直近60日で **255ファイル変更** と本プロジェクト最大の主戦場。
39モジュールあり、名前が似た派生が多いので、書き始める前にここで行き先を確認する。

## 大原則

1. **新規スクリプトを書く前に、この地図で既存モジュールを探す。** 特に相対パフォーマンス系は8変種あり、9個目を作りがち。
2. **DBパスを固定値で書かない。** `database/pachinko.db` と `db/pachinko.db` は **0バイトのダミー**。実体は `db/<ホール名>.db`（例 `db/みとや大森町店.db`）のホール別ファイル。
3. **差枚だけで「設定が入った」と判定しない。** ボーナス確率を機種の自己ベースラインと比べる（`bonus_rate.py` / `bonus_specs.py`）。

---

## 行き先早見表

| やりたいこと | モジュール | サブコマンド |
|---|---|---|
| 予測3軸(同種/同名イベント実績・直近トレンド・カレンダー)を5次元で一括取得する | `prediction_axes.py` | `briefing` |
| ホール予告を事前登録する | `announce.py` | `register` |
| 予告の答え合わせをする | `announce.py` | `score` |
| DBの最新日を確認する | `announce.py` | `dbmax` |
| 機種名のあいまい照合 | `announce.py` | `match-name` |
| ベースレート／名指し機種の文脈 | `announce.py` | `baserate` / `named-context` |
| 未来日の選択を凍結する | `forward.py` | `plan` / `plan-all` |
| 凍結した選択を採点する | `forward.py` | `score` / `audit` |
| 予告・結果発表・実績を1表に束ねる | `integrated.py` | `day` / `coverage` / `ingest-*` |
| 結果発表アカウントを正解ラベル化 | `result_corpus.py` | `build` / `ingest-prose` / `link-machines` / `stats` |
| ボーナス確率で設定を判別 | `bonus_specs.py` | `judge` / `coverage` |
| 高設定投入をボーナス確率で検出 | `bonus_rate.py` | （直接実行） |
| 機種の設置台数推移・増減 | `model_inventory.py` | `build` / `recent` |
| 連番ブロック（並び）を検出 | `narabi.py` | （直接実行） |
| 末尾予告の両隣への波及 | `neighbor_effect.py` | （直接実行） |
| 既知セオリーが死んでいないか | `deathwatch.py` | （直接実行） |
| 効果量の非定常性を検定 | `regime.py` | （直接実行） |
| 差枚の打ち切りを検出 | `censoring.py` | （直接実行） |
| 朝の材料を1枚にまとめる | `morning.py` / `scripts/run_morning.py` | （直接実行） |
| 凍結ルールを履歴でwalk-forward | `run_backtest.py` | （直接実行） |

## 層構造

```
基盤     loader.py / analysis_base.py / extractor.py / validator.py / diagnose.py
予告運用  announce.py → prereg.py（凍結フォーマット）→ forward.py → run_backtest.py
ラベル   result_corpus.py（外部正解）/ bonus_rate.py / bonus_specs.py（内部推定）
統合     integrated.py（予告×結果発表×実績）
構造検出  narabi.py / neighbor_effect.py / model_inventory.py
健全性監視 deathwatch.py / regime.py / censoring.py
日次運用  morning.py
```

---

## 罠

### 予告は当日中に凍結する

`announce.py register` は `target_date <= db_max` を **拒否** する。
翌日以降は事後登録になり登録不能。予告ツイートを受け取ったらその日のうちに `register` まで通すこと。
下ごしらえ（DB最大日確認・機種名照合・baserate）は **`announce-prep` スキル** に手順がある。

### 閾値+1800 は取りこぼす

`score` の既定閾値は `1800.0`。ただし結果発表コーパスとの突き合わせで
**取りこぼしが32〜36%（下限）** ある。低G比・低稼働機種は差枚でもボーナス確率でも判定不能。
「閾値を超えなかった＝設定が入らなかった」と読まない。

### 導入日数の交絡

新台は設定不問で高回転する。`announce.py` のコメントに実測が残っている:

```
導入0-6日  : G比中央値 1.42 / 平均差枚 -315 / 閾値+1800超え 10.5%
導入60日+  : G比中央値 0.84 / 平均差枚  +40 / 閾値+1800超え  4.8%
```

導入直後の機種は G比が高く出るだけで設定の証拠にならない。

### relative_performance_* の8変種

```
relative_performance_analysis.py                    条件別平均との比較（原型）
  _coin_diff.py / _coin_diff_triple.py              指標を平均差枚に
  _games.py / _games_triple.py                      指標を平均G数に
relative_performance_multi_period.py / _triple.py   6月・3月・1月の3訓練期間
compare_percentile_ratios.py                        分割比率の系統的テスト
```

`_triple` は2分割でなく3グループ版（上位36%・中間28%・下位36%）。
**新しい指標軸が要るときは9個目を作らず `analysis_base.py`（共通フレームワーク）を拡張する。**

## 関連スキル

- `announce-prep` — 予告登録の下ごしらえ。register前に必ず通す
- `prediction-recheck` — DB欠損が埋まった後の答え合わせ再実行
- `prediction-evaluation` — 答え合わせの評価設計（単日評価の禁止・hit@3優位）
- `site777-highsetting-scan` — リアルタイム収集からの高設定割り出し
