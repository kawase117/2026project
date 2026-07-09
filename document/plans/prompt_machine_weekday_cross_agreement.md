# 機種横断・曜日一致度スキャン（DD版の曜日版への移植）

## 目的

DD（日にち1〜31）で実装した機種横断一致度スキャン一式（[eda/machine_dd_cross_agreement_scan.py](../../eda/machine_dd_cross_agreement_scan.py), [eda/machine_dd_cross_agreement_machine_deepdive.py](../../eda/machine_dd_cross_agreement_machine_deepdive.py)）を、軸を**曜日（月火水木金土日）**に変えて同じことをやる。DD版で確立した設計（機種ごとの自分自身のbaselineとの残差→ホール×軸での符号多数決の二項検定→ホール単位FDR→既知/新規判定→プール絶対水準の併記→machine_masterカテゴリの支配度ロバストネス検定→機種名フルランキング→機種単体one-vs-rest検定→ホール内常連/ホール横断一致チェック）はそのまま踏襲する。

DD版との主な違いは以下の3点のみ。

1. 軸の水準数が31→7に減る（月,火,水,木,金,土,日）。これによりホール単位のFDR補正の検定数が最大31から最大7に減り、多重比較の厳しさが緩和される
2. 「既知/新規」判定の比較対象が`is_x_day`（ホール固有の固定DDリスト＋月末＋強ゾロ目、部分的にしかカバレッジしない）から`is_weekend`（土日、決定論的に0か1）に変わる。DD版のカバレッジ率は0〜1の連続値を取り得たが、曜日版は本質的に0か1の二値になる
3. `eda/core.py`の`load_hall_df`が返す`day_of_week`列（値は`'月','火','水','木','金','土','日'`の文字列、`_axis_breakdown`は既に`axis="day_of_week"`をサポート済み）を使う。dd列のようなint変換は不要

**注意**: `is_weekend`だけを「既知」の基準にすると、平日側で有意になった曜日を安易に「新規発見」と呼んでしまうリスクがある。蒲田7には既に「火=角番、水=末尾、土=3台並び、木=ニブイチ、金=列1台、月=列全体、日=機種1台」という曜日別イベントの知見が別途蓄積されている（Claude側メモリの`kamata7_weekday_event_pattern.md`。このリポジトリの`document/instincts/`配下には該当YAMLは無い）。実装自体にこの知見を組み込む必要はないが、**結果を報告する際は`is_weekend=0`で有意になった曜日を機械的に「新規」と呼ばず、既存の曜日別知見と照合すべき**という運用上の注意点として引き継ぐ。

## 背景データ・既存資産（必ず再利用する）

DD版と全く同じ理由で、以下は**そのままimportして使う**（再実装しない）。

- `eda/core.py`: `DB_DIR`, `HALL_DBS`, `load_hall_df`
- `eda/machine_axis_pattern_scan.py`: `MIN_CELL_N`, `_axis_breakdown`（`axis="day_of_week"`で呼ぶだけでよい。この関数は既に曜日軸のソート順(`WEEKDAY_ORDER`)に対応済み）
- `eda/machine_name_significance_scan.py`: `DEFAULT_SHINDAI_EXCLUDE_DAYS`, `_prepare_frame`
- `eda/machine_volatility_event_gap_scan.py`: `_parse_halls`
- `scipy.stats.binomtest`, `statsmodels.stats.multitest.multipletests`
- **`eda/machine_dd_cross_agreement_scan.py`の`load_machine_categories(hall)`と`attach_machine_category(residuals, hall)`は軸(dd/weekday)に依存しない実装（machine_nameだけをキーにmachine_masterとJOINしている）。これは複製せずそのままimportして使う**
- DD版の定数のうち軸に依存しないもの: `DEFAULT_HALLS`, `DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE`, `DEFAULT_MIN_MACHINES_FOR_TEST`, `DEFAULT_FDR_ALPHA`, `DEFAULT_KNOWN_EVENT_THRESHOLD`, `UNKNOWN_CATEGORY`, `CATEGORY_FLAG_PRIORITY`もそのままimportする

上記以外（`dd`列を前提に書かれている関数: `compute_machine_dd_residuals`, `aggregate_dd_agreement`, `apply_fdr_per_hall`, `attach_event_coverage`, `compute_pooled_dd_stats`, `attach_pooled_stats`, `build_category_breakdown`, `compute_dominant_category_robustness`, `build_summary_report`, `merge_robustness_into_summary`, `build_hall_outputs`、および機種名深堀り側の`build_full_machine_ranking`, `compute_machine_dd_self_significance`, `apply_fdr_per_hall_dd`, `merge_ranking_with_significance`, `find_repeat_contributors`, `find_cross_hall_consistency`）は、**列名を`dd`→`weekday`に置き換えた同型の実装として新ファイルに書く**。`eda/machine_dd_cross_agreement_scan.py`と`eda/machine_dd_cross_agreement_machine_deepdive.py`は変更しない（この2ファイルをコピー元として参照するのみ）。

これはこのリポジトリの既存の設計方針（`eda/machine_dd_recent_window_scan.py`と`eda/machine_weekday_recent_window_scan.py`、`eda/machine_dd_deepdive_target_machines.py`と`eda/machine_weekday_deepdive_target_machines.py`のようにDD版/曜日版を並行したファイルとして持つ）を踏襲したもの。

## 実装内容

### ファイル1: `eda/machine_weekday_cross_agreement_scan.py`

`eda/machine_dd_cross_agreement_scan.py`の全構造をそのまま移植する。対応関係:

| DD版 | 曜日版 |
|---|---|
| `compute_machine_dd_residuals(hall, frame, *, min_machine_days_total, min_cell_n)` | `compute_machine_weekday_residuals(...)` 同じ引数。内部で`_axis_breakdown(hall, machine_name, machine_frame, axis="day_of_week", outcome="hit104")`を呼ぶ。`RESIDUAL_COLUMNS`の`"dd"`を`"weekday"`に置換 |
| `aggregate_dd_agreement` | `aggregate_weekday_agreement`。ロジック完全同一（`groupby(["hall","dd"])`→`groupby(["hall","weekday"])`） |
| `apply_fdr_per_hall` | 実装前に`eda/machine_dd_cross_agreement_scan.py`のこの関数を読み、`groupby("hall")`のみで`dd`列を直接参照していないことを確認できれば、そのままimportして使ってよい。`dd`列を参照していれば`weekday`版として複製する |
| `attach_event_coverage(agreement, hall_frames, *, known_event_threshold)` | `attach_weekday_coverage(...)`。`is_x_day`の代わりに`is_weekend`列の平均を`weekday_event_coverage_rate`として計算し、`is_known_weekend_day`列を作る。ロジックはgroupbyキーが`dd`→`weekday`、参照列が`is_x_day`→`is_weekend`になるだけ |
| `compute_pooled_dd_stats` / `attach_pooled_stats` | `compute_pooled_weekday_stats` / `attach_pooled_weekday_stats`。ロジック完全同一 |
| `build_category_breakdown` | 同名ロジックで`dd`→`weekday`列置換のみ |
| `compute_dominant_category_robustness` | 同上 |
| `build_summary_report` / `merge_robustness_into_summary` | 同上。`SUMMARY_COLUMNS`の`is_known_event_dd`/`is_novel`は`is_known_weekend_day`/`is_novel`に改名 |
| `build_hall_outputs` | `build_weekday_hall_outputs`。呼び出す関数群を曜日版に差し替えるだけ |
| `main` | CLI引数は`--min-cell-n`(既定`MIN_CELL_N`), `--min-machines-for-test`(既定`DEFAULT_MIN_MACHINES_FOR_TEST`), `--fdr-alpha`(既定`DEFAULT_FDR_ALPHA`), `--known-event-threshold`(既定`DEFAULT_KNOWN_EVENT_THRESHOLD`), `--halls`, `--all-halls`, `--output-dir`(既定`eda/results/machine_weekday_cross_agreement/`)。`--min-machine-days-total`は曜日軸でも機種の最小サンプル日数フィルタとしてDD版と同じ意味で必要（既定は`DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE`のままでよい） |

### ファイル2: `eda/machine_weekday_cross_agreement_machine_deepdive.py`

`eda/machine_dd_cross_agreement_machine_deepdive.py`の全構造をそのまま移植する。`build_hall_outputs`の代わりに`build_weekday_hall_outputs`をimportする。`compute_machine_dd_self_significance`の曜日版(`compute_machine_weekday_self_significance`)は、`target_dds: set[int]`の代わりに`target_weekdays: set[str]`(値は`'月'〜'日'`)を受け取り、`machine_frame["day_of_week"] == weekday`で分割する。`apply_fdr_per_hall_dd`の曜日版(`apply_fdr_per_hall_weekday`)は`groupby(["hall","weekday"])`。`find_repeat_contributors`/`find_cross_hall_consistency`はロジック完全同一で列名置換のみ（`dds_appeared`→`weekdays_appeared`、`dd_matches_across_halls`→`weekday_matches_across_halls`等、列名も曜日版に改名する）。

## 出力

- `eda/results/machine_weekday_cross_agreement/{hall}_machine_weekday_residuals.csv`
- `eda/results/machine_weekday_cross_agreement/{hall}_weekday_agreement.csv`
- `eda/results/machine_weekday_cross_agreement/{hall}_category_breakdown.csv`
- `eda/results/machine_weekday_cross_agreement/{hall}_category_robustness.csv`
- `eda/results/machine_weekday_cross_agreement/summary_report.csv`
- `eda/results/machine_weekday_cross_agreement_deepdive/{hall}_full_ranking.csv`
- `eda/results/machine_weekday_cross_agreement_deepdive/repeat_contributors.csv`
- `eda/results/machine_weekday_cross_agreement_deepdive/cross_hall_consistency.csv`

標準出力の形式もDD版の`_print_hall_report`と同じ体裁（novel/known相当の一覧、`to_string(index=False)`、`to_markdown()`禁止）を踏襲する。曜日版では「known-event」の見出し文言を「known-weekend」に変えるなど、DD専用の用語をそのまま流用しない（曜日版として自然な列名・見出しにする）。

## 実装上の注意

1. 新規ファイルは`eda/machine_weekday_cross_agreement_scan.py`と`eda/machine_weekday_cross_agreement_machine_deepdive.py`の2ファイルのみ。`eda/machine_dd_cross_agreement_scan.py`, `eda/machine_dd_cross_agreement_machine_deepdive.py`は変更しない
2. `load_machine_categories`, `attach_machine_category`は複製せず`eda.machine_dd_cross_agreement_scan`からimportする
3. `day_of_week`列は既に文字列(`'月'〜'日'`)なので、DD版のようなint変換(`astype(int)`)は不要。ソート順が必要な箇所（フルランキングの表示順など）は`machine_axis_pattern_scan.WEEKDAY_ORDER`をimportして使う
4. one-vs-rest検定（機種単体の曜日別有意性）は、7水準しかないため`min_cell_n`（既定5）を満たさないケースはDD版よりずっと少なくなる想定。それでも足切りロジック自体は同じ実装にする
5. CSV出力は`encoding="utf-8-sig"`。ファイル冒頭で`sys.stdout.reconfigure(encoding="utf-8")`
6. 出力先ディレクトリが存在しない場合は作成する

## テスト

`ml/tests/test_machine_weekday_cross_agreement_scan.py`と`ml/tests/test_machine_weekday_cross_agreement_machine_deepdive.py`を新規作成する。テスト内容はDD版の`ml/tests/test_machine_dd_cross_agreement_scan.py`・`ml/tests/test_machine_dd_cross_agreement_machine_deepdive.py`と同型（残差フィルタ、二項検定・FDR・ゼロ残差の扱い、既知/新規判定、プール統計、カテゴリ内訳、支配カテゴリロバストネス、CLIスモークテスト等）で、軸だけ曜日（`月・火・水・木・金・土・日`の値を使う）に差し替える。DD版のテストファイルを実装前に読み、同じ観点を曜日版でも網羅すること。
