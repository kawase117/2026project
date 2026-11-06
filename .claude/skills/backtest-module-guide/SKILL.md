---
name: backtest-module-guide
description: backtest/ 配下のモジュールの役割分担と使い分けの地図。「予告を登録したい」「答え合わせしたい」「設定が入ったか判定したい」「並びを検出したい」「セオリーが死んでいないか見たい」といった要求から正しいモジュール・サブコマンドへ最短で辿り着くために使う。backtest/ に新しい分析スクリプトを追加する前にも必ず参照し、既存モジュールの再実装を防ぐ。
---

# backtest モジュール地図

`backtest/` は直近60日で **255ファイル変更** と本プロジェクト最大の主戦場。
約70モジュールあり、名前が似た派生が多いので、書き始める前にここで行き先を確認する。

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
| どのルールが無作為より上か一覧する | `scoreboard.py` | （直接実行）→ `backtest/forward/SCOREBOARD.md` |
| 予測文書の名指しを凍結・採点する | `prediction_ledger.py` | `freeze-doc` / `score-due` / `backfill` |
| 予告・結果発表・実績を1表に束ねる | `integrated.py` | `day` / `coverage` / `ingest-*` |
| 結果発表アカウントを正解ラベル化 | `result_corpus.py` | `build` / `ingest-prose` / `link-machines` / `stats` |
| ボーナス確率で設定を判別 | `bonus_specs.py` | `judge` / `coverage` |
| 高設定投入をボーナス確率で検出 | `bonus_rate.py` | （直接実行） |
| 機種の設置台数推移・増減 | `model_inventory.py` | `build` / `recent` |
| 連番ブロック（並び）を検出 | `narabi.py` | （直接実行） |
| 末尾予告の両隣への波及 | `neighbor_effect.py` | （直接実行） |
| 既知セオリーが死んでいないか | `deathwatch.py` | （直接実行） |
| ホールの全軸スキャンと theory 文書の説の再判定 | `theory_rescan.py` | `--key` / `--only` / `--write-doc` |
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

## 上の表に無いモジュール(各ファイルの冒頭の説明から機械的に抜き出した一覧。2026-11-06)

使い分けの判断は載せていない。詳細は各ファイルの docstring を読む。

| モジュール | 説明 |
|---|---|
| `absolute_performance_analysis` | 絶対パフォーマンス分析 - テスト期間で最高勝率を達成するグループの特定 |
| `announce_autodraft` | ホール予告の半自動下ごしらえ(検出→dbmax/match-name/baserate/named-context→claims案)。 |
| `at_rb_audit` | AT機のAT初当り確率が、DBのどの列(bb / rb / bb+rb)に入っているかの監査。 |
| `axis_scan` | 位置軸(末尾・角番・並び)× 時間軸(曜日・D・DD・ゾロ目・イベント公約)の総当たり検定。 |
| `axis_sweep_baserate` | 軸スイープ（機種/列/末尾/角番/フロア×交互作用）のベースレートと再現性を測る。 |
| `check_schema` | (説明なし) |
| `check_test_data` | (説明なし) |
| `condition_drilldown` | 1ホールの日付条件を、カテゴリ → 機種 → 台番号 と掘り下げる。 |
| `conditional_analysis` | 条件付き分析モジュール - 特定の日（DD or 曜日）での台選択有効性検証 |
| `continuation_pace` | 示唆続行台を営業中に拾う: クイック収集の回転数から、閉店時に7,000Gへ届きそうなAT台を凍結して翌朝採点する |
| `continuation_scan` | 示唆続行台の検証: AT機で回転数の多い台に、結果ツイートの台が集まるか(2026-10 振り返り 作業5の1)。 |
| `cross_attribute_performance_analysis` | クロス属性パフォーマンス分析 - 複数訓練期間・複数条件値対応版 |
| `cross_metric_validation_triple` | クロスメトリック検証 - 勝率・G数グループ分割からテスト差枚を検証 |
| `daily_digest` | Generate a per-day announce watch digest from the Twitter monitor state. |
| `date_conditions` | 日付条件（ゾロ目・7のつく日・月末・土日など）が、その店で本当に効くか。 |
| `day_wari` | 日の軸(曜日・末尾日・イベント台帳の日)を、差枚だけでなく割とジャグラーの平均phで測る。 |
| `detailed_conditional_analysis` | 詳細条件付き分析 - 高勝率vs低勝率の再現性比較 |
| `event_days` | 日付単位のイベント日レジストリ（予告ツイート由来）。 |
| `field_obs` | 現場の報告（演出での設定確認・現地組の報告）を台帳に残す。 |
| `juggler_carryover` | ジャグラー設定の持ち越し分析(読み取り専用)。 |
| `lessons` | 学びの台帳(document/registry/LESSONS.jsonl)と、予測文書の判断行の点検。 |
| `main` | バックテスト実行スクリプト |
| `main_conditional` | 条件付き分析実行スクリプト |
| `model_alias` | 結果発表・予告に書かれた機種の略称を、実績DBの正式な機種名に当てる。 |
| `model_standing` | 機種がその店でどう扱われているかの一覧。 |
| `monthly_report` | 楽園蒲田の月初レポート（層1）。層2は monthly_report_layer2.py。 |
| `monthly_report_announce` | 楽園蒲田 月初レポート 層2b（予告で事前に名指しされた機種 vs 同日の未名指し機種）。 |
| `monthly_report_announce_content` | 楽園蒲田 月初レポート 層2b-内容（予告の中身を、請求の種類ごとに分布で測る）。 |
| `monthly_report_layer2` | 楽園蒲田 月初レポート 層2（イベント実績）。 |
| `monthly_report_layer3` | 楽園蒲田 月初レポート 層3（機種タイプ×日条件の事前確率）。 |
| `persistent_units` | 持続して強い台の週次一覧。 |
| `prediction_games` | 予測台帳の名指しを、差枚・RB比とは別に回転数で採点する(2026-10 振り返り 作業5の2〜4)。 |
| `prediction_rb` | 予測台帳のRB判別機種を、同一ホール・機種の過去RB率で採点する。 |
| `rb_candidates` | RB判別機種のホール別候補をDBから生成し、独立した台帳へ凍結する。 |
| `relative_performance_analysis_coin_diff` | 相対パフォーマンス分析 - 平均差枚ベース（勝率の代わりに平均差枚を指標） |
| `relative_performance_analysis_coin_diff_triple` | 相対パフォーマンス分析 - 平均差枚ベース（3グループ版） |
| `relative_performance_analysis_games` | 相対パフォーマンス分析 - 平均G数ベース |
| `relative_performance_analysis_games_triple` | 相対パフォーマンス分析 - 平均G数ベース（3グループ版） |
| `relative_performance_multi_period_triple` | 相対パフォーマンス分析 - 3グループ版（上位36%・中間28%・下位36%） |
| `setting_labels` | 確認された台の設定ラベルを追記専用 JSONL で管理する。 |
| `seven_d_results` | SEVEN-D（@datagasubete）の楽園蒲田の結果投稿を、外部結果テーブルへ取り込む。 |
| `test_analyze_relative_performance` | (説明なし) |
| `unit_time_scan` | 単位(機種・島・機種タイプ)×時間軸の総当たり。 |
