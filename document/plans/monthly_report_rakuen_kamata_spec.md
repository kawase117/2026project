# 楽園蒲田 月初レポート 実装仕様（2026-10-02 承認済み設計）

元プロンプト: `monthly_report_rakuen_kamata_prompt.md`。本書はそれを実装契約に落としたもの。
実装先: `backtest/monthly_report.py`（サブコマンド化）+ `test/backtest/test_monthly_report.py`。

## 0. 共通の契約

- Python は `venv\Scripts\python.exe`。DBは `sqlite3` を `file:...?mode=ro` で開く（読み取り専用）。
- DB: `db/楽園蒲田店.db`（ホールごとにDBが分かれる。`hall_name` 列は無い）。
  DBパスは固定値で書かず `backtest/` 既存の流儀（`load_frame` / `ANALYSIS_DB` など）に従う。
- 台日テーブル `machine_detailed_results`: 粒度は **台×日**。
  - `date` は TEXT `YYYYMMDD`。`last_digit` は TEXT。
  - 使う列: `machine_name`, `machine_number`, `games_normalized`(G), `diff_coins_normalized`(差枚・単位は**枚**), `bb_count`, `rb_count`。
- 日次テーブル `daily_hall_summary`: 粒度は **ホール×日**。`date` は TEXT `YYYYMMDD`、`day_of_week` は漢字1字（月火水木金土日）、
  `weekday_nth` は `Wed5` 形式（**曜日の取得元はここ**。台日テーブルには無い）、`is_any_event`。日付境界は営業日（暦日）。JST。
- 機械割(pp) = `100 * diff / (3 * G)`（3枚掛け。`bonus_rate.py` 冒頭の 平均差枚≒3×(機械割−1)×G と同じ）。
  差枚は**必ず機械割ppと並べる**。G=0 の台日は除外し、除外件数を出力に残す。
- 機種タイプは `backtest/bonus_specs.py` の `find_spec(machine_name)` → `spec["category"]`（ノーマル/BT/A+AT/AT/…）、`spec["judgeable"]`。
  `find_spec` が None の機種は「マスター無し」として別枠で件数だけ出す（黙って捨てない）。
- **ノーマル/BT/A+AT の設定推定は RB のみ**。`posterior(spec, games, bb=None, rb=rb)` を使う（`_log_binomial` は k=None を読み飛ばすので RB単独になる）。
  BB+RB合算は使わない。**AT機に設定事後確率は出さない**。
- **全数値に n と95%信頼区間**を付ける。比率は Wilson。平均は t でなく**ブートストラップ**（日単位の循環ブロック block=7, B=2000, seed固定）。
- 除外は必ず `excluded` リストに理由つきで残す（`bonus_rate.py` の流儀）。黙って落とさない。
- 乱数は `numpy.random.default_rng(seed)`。seed は引数で固定（既定 20261001）。出力に seed を残す。
- **リーク禁止**: 結果発表（`EVENT_RESULT_LINKS` が指す報告・`analysis_results.db` の結果コーパス）は
  層1・層3の入力特徴量に絶対に使わない。使ってよいのは ①層2の記述 ②正解ラベルの参照のみ。
  途中データ（サイトセブン等）は一切使わない（DBの確定最終データのみ）。
- 交絡の申し送り（既知）:
  - **新台**（導入0-6日）は設定不問で高回転。層1の機種ごとの結果に `導入日数` を併記し、導入直後は「判定保留」と明示する。
    導入日 = その機種の `machine_detailed_results` 上の初出日（2025-01-01 より前から居る機種は不明扱いで保留しない）。
  - **工事後レジーム**: 楽園蒲田は 2026-07-06 に改装。以降を既定の `--regime-start 20260706` とする。既知の変化点: 2026-09-07 配置替え、2026-09-14 機種入替（出力の注記に載せる）。
  - **鉄台・全設定6の特殊日**は楽園蒲田に定義が無いので除外しない（蒲田7の定義を流用してはいけない）。
  - 楽園の `is_event_dd` フラグは未検証なので**使わない**。DDは日付の「日」を番号単位で扱う。
  - 稼働の少ない機種は `bonus_rate.py` の `min_machines=3, min_live=3(≥1000G), min_total_games=6000` を踏襲（理由つきで excluded に入れる）。

## 1. 共通関数（`backtest/monthly_report.py` 内）

- `wilson(k, n, z=1.96) -> (lo, hi)`
- `block_bootstrap_ci(series_by_date, stat_fn, block=7, B=2000, seed) -> (lo, hi)`
- `load_machine_days(db_path, start, end) -> DataFrame`（上記の列＋`payout_pp`＋`ds`）
- `normal_days(hall_summary, event_dates) -> list[str]`: **通常日 = EVENT_DAYS.jsonl の楽園蒲田の event 日以外**。
  楽園蒲田のレコードは `hall` フィールドが楽園蒲田を指すもの（実データの表記を `Grep`/`json` で確認して完全一致で絞る。部分一致で他ホールを拾わない。`related_halls` に楽園蒲田が入っているだけの他ホール分は除く）。

## 2. 層1 `layer1`（本体）

`monthly_report.py layer1 --asof YYYYMMDD [--window-days 28] [--baseline-days 90] [--regime-start 20260706]`

- 窓 = asof を含む直近 `window-days` 日（閉区間）。ベースライン = 窓の直前 `baseline-days` 日（閉区間、窓と重ならない）。
  ベースラインは `regime-start` より前に食い込ませない（食い込むなら短くして、実日数を出力に出す）。
- **機種ごとに1行**（`machine_name` 単位、窓内に出現した全機種）。列:
  `category`, `n_machines`(最大設置台数), `n_machine_days`, `G合計`, `平均G/台日`, `G比`(窓の平均G/台日 ÷ ベースラインの同機種平均G/台日),
  `機械割pp`(窓、プール値) と 95%CI、`機械割pp_baseline`、`差枚平均/台日` と CI、
  `勝率`(台日diff>0の割合) と Wilson CI、`勝率_baseline`、`導入日数`、`判定保留理由`(新台/稼働不足 等)。
- **judgeable（ノーマル/BT/A+AT）の機種**には追加で:
  `RB回数`, `RB確率 1/x`, 設定事後確率 6列（一様事前、RBのみ）、`P(設定4以上)`, `P(設定5以上)`、
  自己ベースラインとの比較 `2標本比率検定`（`bonus_rate._two_proportion_z` を再利用。RB回数/G。z, p, 両側）。
  事後確率は G合計 < 2000 なら「判定に足りない」と明記（`MIN_GAMES_FOR_JUDGEMENT`）。
  `spec["judgeable"]` が真でも設定別RB確率が埋まっていない機種は posterior が空になる → 「確率未整備」で出す。
- **AT機（judgeable でない機種）は設定推定を出さない**。代わりに**有効性ゲート**を機種ごとに計算して併記:
  ベースライン＋窓の台日（G≥1000）で `r = Spearman(ボーナス率(BB+RB)/G, 機械割pp)`、n台日、Fisher z による95%CI。
  `gate_pass = (n台日≥300 and r_CI下限>0)`。通らない機種は「相関ゲート不通過（使わない）」と行に出し、**検定は出さない**。
  通る機種のみ、自己ベースライン比（BB+RB/Gの2標本比率検定）を出す。
  ※ AT機のボーナス数が bb 側か rb 側のどちらか一方にしか入る機種があるので、必ず `bb_count+rb_count` の合計を使う（ゲート内のみ。設定推定には使わない）。
- **同機種の通常日分布との対比**（足切りしない）: 窓内の各台日について、同機種の**ベースライン期間・通常日**の
  台日差枚分布に対する分位順位（percent rank）を出し、窓内の台日のその順位の p10/p25/中央値/p75/p90 を表示。
  上側（勝ち）と下側（負け）の分布を**同じ表に並べる**（上位だけ載せない）。
- 出力: DataFrame（`--format md|json|csv`、既定 md）。機種タイプ別にセクション分け（ノーマル / BT / A+AT / AT）。
  `excluded` と `マスター無し` を末尾に必ず出す。
- **やってはいけない**: `+1800` 等の絶対閾値による当否判定、「HIT/MISS」の二値化、AT機の設定事後確率。

## 3. 層2 `layer2`

`monthly_report.py layer2 --asof YYYYMMDD [--min-games 500] [--perm 10000] [--seed 20261001]`

- 入力: `EVENT_DAYS.jsonl`（楽園蒲田・`active` 反映後）、`EVENT_RESULT_LINKS.jsonl`（楽園蒲田・`status=="linked"` の最新行）。
  `backtest/event_days.py` の `load` / `merged` / `active` を使う（再実装しない）。
- **日単位の指標**（ホール×日）: ①台日勝率 ②プール機械割pp ③judgeable機種のプールRB確率。`min-games` 未満の台日は除外して件数を出す。
  あわせて**稼働量（平均G/台日）を併記**し、稼働で層別できるよう列に残す（稼働が違えば比べられない）。
- **イベント種別（kind）ごと**に、イベント日と「同曜日の通常日」（`regime-start` 以降、`daily_hall_summary.day_of_week`で一致）を比較:
  統計量 = 指標の（イベント日平均 − 同曜日通常日平均）。**並べ替え検定**: 同曜日通常日プールから、イベント日と同数をランダムに引き直し（B=`--perm`）、
  経験p（両側）。t値は使わない。効果量にはブートストラップCI。
  n(イベント日数)<5 の kind は**効果量・p を出さず**、日付と生の値を並べるだけ（n=1も同じ）。
- 多重検定: 検定する (kind × 指標) の本数 m を**実行前に確定して出力冒頭に書く**。Bonferroni 補正p（`p*m`、上限1）を併記する。
- **結果発表との突き合わせ**（記述のみ）: linked の行について、発表で名指しされた機種の当日実績
  （台日差枚の p10/p25/中央値、勝率、機械割pp）を、同機種の通常日分布の対応する分位点と**同じ表に並べる**。足切りしない。
  `status` が waiting/not_found/multiple_candidates の日は「発表が未確認」と書くだけで、「入っていなかった」と書かない。
  結果コーパスの読み方（テーブル・列）は `backtest/result_corpus.py` と `backtest/event_days.py` の `_result_data` を読んで合わせる。
- イベント日は必ず楽園蒲田のレコードのみ。他ホールの値を借りない。

## 4. 層3 `layer3`

`monthly_report.py layer3 --asof YYYYMMDD --target-month YYYYMM [--regime-start 20260706]`

- ラベル（正解・評価専用）: 機種×日の `y = P(設定4以上 | その日の機種プールRB)`（judgeable機種のみ。一様事前、RBのみ）。
  日のプールGが 2000 未満の機種×日は欠測（ラベルを作らない）。**二値化しない**。
- 事前確率（予測）: セル = (機種タイプ × 日条件)。日条件 = {曜日, DD(日付の日)}。
  推定は経験ベイズ収縮: `post = (Σy + k·m_type)/(n + k)`、`m_type` は同タイプ全体平均、`k` は固定（既定 10）。
  DDセルは曜日セルへ、曜日セルはタイプ全体平均へ、段階的に収縮する。**機種単体の直近好調を事前確率に直接入れない**
  （機種名はタイプ平均への収縮を通した寄与のみ。instinct: 工事後は機種追いが通らない）。
- 出力: 来月の各日（`target-month` の暦日）×機種タイプの事前確率とCI（ブロックブートストラップ）。
  イベント日は予測に入れず、層2の効果量（あれば）を別欄で併記するだけ。
- **ウォークフォワード評価** `layer3 --evaluate`: 月 t までで学習して月 t+1 を予測。
  楽園は `regime-start` 以降の月のみ（8月・9月の2fold）。あわせて `--all-history` で
  2025-01 以降の全月（レジーム無視・警告表示）を方法の健全性確認として回せるようにする。
  評価指標: ①予測値のビン（5分位）ごとの「予測平均 vs 実現平均」（キャリブレーション表。nとCI付き） ②定数予測（学習期間全体平均）に対するMSE比。
  AUCや的中率だけで判断しない。fold数が少ないので「検出力不足」と明記し、効果なしと断定する文言は出さない。

## 5. `report` サブコマンド

`monthly_report.py report --asof YYYYMMDD --target-month YYYYMM --out document/reviews/YYYY-MM-rakuen-monthly-report.md`
層1→層2→層3の順にMarkdown1本へ。先頭に「このレポートは日次予測にかける事前確率づくり。次の高設定台の予測ではない」「判定は分布と確率。当否の二値判定はしない」を載せる。
結果発表を入力特徴量にしていないことと、使った窓・seed・レジーム境界を末尾に記載。

## 6. テスト（`test/backtest/test_monthly_report.py`、pytest、合成データのみ）

- DB・registry は読まない（`tmp_path` に合成 SQLite/JSONL を作る）。実データ依存のテストを書かない。
- 最低限: wilson の境界(0/n, n/n)、機械割ppの式、RB単独posteriorがBBの有無で変わらないこと、
  AT機に設定事後確率の列が出ないこと、rゲートの通過/不通過、窓とベースラインが重ならないこと、
  n<5 の kind で p が出ないこと、並べ替え検定が seed 固定で再現すること、
  層3の収縮が同タイプ平均へ寄ること、結果発表を渡してもlayer1/3の出力が変わらないこと（リーク防止）。
- 既存テストの流儀（`test/backtest/` の他ファイル）に合わせる。
