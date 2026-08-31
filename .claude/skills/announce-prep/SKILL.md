---
name: announce-prep
description: ホール予告(announce)を事前登録する前の下ごしらえ(DB最大日確認・機種名のあいまい照合・baserate計算・名指し機種の直近ランキング集計)を定型化する。予告ツイートを受け取ったら毎回scratchpadに使い捨てスクリプトを書いていた作業を`backtest/announce.py`のCLIサブコマンドに一本化する。
---

# Announce Prep Skill

## トリガー
- ホール予告のツイート(スクリーンショット/本文)を受け取り、`backtest/announce/*.json`として事前登録しようとしているとき
- 「この予告を登録してください」「baserateを出してください」と言われたとき
- 登録済みannounceの対象日が来て「答え合わせしてください」「採点してください」と言われたとき（下記「答え合わせ」節）

## 背景
2026-08-25のmirror-review(`document/mirror_evidence_2026-08-25.md`セクション4-A)で、3つの独立したセッションバッチが同一パターンを発見した: announce登録前に(1) DB最大収録日の確認、(2) ツイート本文の機種略称をmachine_masterの正式表記へ照合、(3) 直近30〜90日のbaserate計算、という3手順を毎回scratchpadに使い捨てスクリプトとして書き直していた。(3)は既に`announce.py baserate`として存在していたが、(1)(2)は未整備だった。

## やること
1. **DB最大日を確認する**
   ```bash
   venv\Scripts\python.exe -m backtest.announce dbmax "<hall>"
   ```
   ここで得た日付を`baserate`の`--before`に渡す。予告のtarget_dateがこの日付以下なら「事後登録」になり`register`が拒否するので、登録前に必ず確認する。

2. **予告本文の機種名を照合する**(`model_named`/`model_named_ratio` claimがある場合)
   ```bash
   venv\Scripts\python.exe -m backtest.announce match-name "<hall>" "<予告本文>"
   ```
   完全部分一致(`substring`, score=1.0)を最優先。`partial`はあくまで候補であり、機種名の採否は必ず人間(ユーザー)に確認してから`machine_name`に入れる。自動確定しない。
   - LB/スマスロ/パチスロ等の接頭辞違いで一致しない場合は、`scraper/site777/config/machine_aliases.json`の接頭辞除去ロジック(`normalize_machine_key`)と同じ問題が起きている可能性がある。手動で正式表記を`database`から確認する。

3. **baserateを計算する**（固定閾値+1800でのp_at_least_N込み）
   ```bash
   venv\Scripts\python.exe -m backtest.announce baserate "<hall>" --before <dbmaxで得た日付> --days 90 --min-machines 3 --threshold 1800.0
   ```
   `zentaikei.threshold`は`--threshold`に渡した絶対値1800.0をそのまま使う（`percentile`由来の`threshold`フィールドは分位点閾値であり別物、`announce.py`冒頭のコメント参照）。`--threshold`指定時は返り値に`fixed_threshold`ブロック（`p_at_least_1`〜`p_at_least_4`,`p_at_least_10`込み）が追加され、`baserate_before_target`の`p_at_least_N`にそのまま使える。

4. **named-contextで名指し機種の直近30日ランキングを出す**（machine_nameは手順2で確定済みのものを使う）
   ```bash
   venv\Scripts\python.exe -m backtest.announce named-context "<hall>" --machines "機種A,機種B,機種C" --as-of <dbmaxで得た日付> --days 30 --min-machines 3 --threshold 1800.0
   ```
   出力の`models`配列（`n_machines`/`rank`/`of`/`n_days_present`/`over_threshold`/`rate`/`mean_score`）を`named_machine_context.models`と`claims`のnoteにそのまま反映できる。`rank`はas_of 1日分のみのプール内順位（少数台設置機種は低く出ることがあり、絶対scoreと合わせて解釈する）。

5. 上記4つの結果を踏まえてannounce JSONを作成し、`backtest.announce register`で凍結する(即日中に行うこと。`feedback-announce-register-same-day`instinct参照)。

## 出力
- `dbmax`: DB最終収録日(YYYYMMDD)
- `match-name`: 機種名候補のリスト(JSON、score降順)
- `baserate`: 閾値・日次超過数の統計(JSON)。`--threshold`指定時は`fixed_threshold`（p_at_least_N込み）も出力
- `named-context`: 名指し機種ごとの直近N日ランキング・閾値超え率(JSON)

## 答え合わせ（登録済みannounceの対象日が来たとき）

2026-08-27のセッションで確立したパターン。`backtest.announce score`は機種平均スコアの閾値判定を機械的に返すだけで、それだけを見て「hit/miss」を報告すると重要な信号を見落とす。scraping分析(site777)のときと同じ深さで、以下を必ず行う。

1. **まず機械的な採点を走らせる**
   ```bash
   venv\Scripts\python.exe -m backtest.announce score backtest/announce/<id>.json
   ```
2. **名指し機種は台番号別に個別確認する**（機種平均だけで判断しない）
   - `machine_detailed_results`をmachine_number別に見て、1台だけが平均を押し上げていないか（project-kishu-ichi-decoyの撒き餌パターン）を確認する
   - 逆に、機種平均が閾値未達でも一部の台だけ極端に強い（東京喰種31台中1台だけ+5096等）ケースを見逃さない
3. **並びブロックを検出する**（announceが機種名しか名指ししていなくても）
   - 隣接する台番号で複数台が同時にプラスになっている連続ブロックがないか、machine_numberでソートして目視確認する
   - 万枚超えなど突出した台があれば、その前後を並びの起点として疑う（2026-08-27にモンキーターンVで実例: 3122[+11619]と3129[+10810]を起点に2ブロック検出）
4. **外部報告（Zeno等の実況アカウント）と突き合わせるが、報告の網羅性を信用しない**
   - 外部報告に載っている機種は自前のnamed-context/DB集計と数値を比較し、方向・水準が一致するか確認する（一致すれば自前の計算方法の健全性チェックにもなる）
   - 外部報告に**載っていない**好調機種がDB上に無いか、必ず全体スキャンで確認する。2026-08-27の実例では、Zenoの報告に無かったモンキーターンV(2並びブロック、6台合計+36,097)と東京喰種(1台+5096)がDB上で発見された。「外部報告に無い＝仕掛けが無かった」と判定してはならない（project-kawasakislot-selfreport-inflatedと同様、外部ソースの自己申告・選定基準を鵜呑みにしない）
5. **実際にその場で打ったユーザー自身の観測（小役確率・体感など）は、台数の少ないサンプルのBB/RB確率計算より優先する**。統計的な尤度計算（設定1/2/5/6の事後確率など）はあくまで補助であり、隣接設定のスペック差が小さい機種（例: アレックスブライトの設定1/2/5）ではサンプルサイズ不足で統計的に絞り込めないことが多い。その場合は「統計では区別できないが、現場観測は◯◯を支持する」と両方を併記する

この節の内容が汎用化・再利用されるようなら、独立した`announce-score`スキルへの切り出しを検討する。

## 実装メモ
- 5つのサブコマンドは`backtest/announce.py`に実装されている(`db_max_date`/`match_machine_names`/`baserate`/`named_context`関数)。このスキル自体は新しいロジックを持たず、既存CLIを正しい順序で呼ぶ手順書として機能する。
- `match_machine_names`は完全一致優先+最長共通部分列によるあいまい照合で、difflib標準ライブラリのみに依存する。誤マッチのリスクがあるため、scoreが1.0未満の候補は必ず目視確認すること。
- `match_machine_names`は「転生」「カバネリ」のような1機種名に複数の実在バリエーション(旧作/派生/新旧verなど)がある場合や、接頭辞違い(LB/スマスロ等)を解決できないことがある。その場合は`machine_master`の`official_name`列をキーワードでLIKE検索し、`machine_detailed_results`で対象日の設置台数を見て一番自然な候補にユーザー確認を取る（自動確定しない）。
- `named_context`の`rank`はas_of日1日分のみで作ったプール内での順位。設置台数が少ない機種はある1日のスコアが偶然低いだけで大きく順位が動くことがあるため、`rate`(窓内の閾値超え率)と`mean_score`(窓内平均)を優先して解釈すること。
