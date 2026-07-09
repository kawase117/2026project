# 前日レポートページ（日次ホールレポート）の追加

## 目的

現在、前日の結果を確認するためにスクレイピング元のana-slo.comを毎回見に行っており非常に見づらい。これをダッシュボード内で完結させる。

**「特定の1日（デフォルト=前日）を選ぶと、そのホールでその日何が起きたかを1ページで把握できる」**レポートページを新設する。既存ページ群（page_05, page_08〜10等）はすべて「期間集計」志向の設計だが、今回は単日フィルタのみで完結する新規ページとして作る（既存ページの改修は不要）。

## 背景データ・既存資産（必ず再調査の上で再利用する）

- `dashboard/utils/data_loader.py`
  - `load_machine_detailed_by_date(db_path, date_str)` — **対象日の個別台データをすでに1件取得できる**（`machine_detailed_results`を`date`一致でSELECT済み）。このページの主要データソースとして再利用する
  - `load_daily_hall_summary(db_path)` — ホール日次集計（`avg_diff_per_machine`, `win_rate`等）。直近7日/30日平均との比較に使う
  - `ALLOWED_ATTRIBUTES`, `VALID_MACHINE_TYPES` は変更しない
- `dashboard/utils/filters.py`
  - `apply_machine_filters`, `filter_by_date_range` — min_games等サイドバー設定の適用に再利用する
- `dashboard/design_system.py`
  - `metric_card_with_delta` — KPIカード（page_10と同じパターン）に再利用する
- `Heatmap/coordinate_utils.py`
  - `find_floor_csvs(hall_name, project_root)` — 対象ホールに座標CSVがあるか判定。無ければヒートマップセクションを非表示にする（page_17と同じ分岐）
- `Heatmap/heatmap_common.py`
  - `render_heatmap_page(...)` — 既存のヒートマップ描画関数。`date_range=(target_date, target_date)`として単日を渡せばそのまま流用できるはずだが、単日1件のデータで正しく描画されるか実装時に確認すること。挙動が合わない場合のみ最小限の対応を検討する
- **`machine_layout`テーブル**（各ホールDB内、`machine_number`で`machine_detailed_results`とJOIN可能）
  - 列: `machine_number, hall_name, x, y, display_y, section, section_min, section_max, rank_from_min, rank_from_max`（みとやのみ追加で`is_reversed_section, rank_from_aisle, physical_corner, physical_corner_valid`）
  - **確認済み**: `マルハンメガシティ2000-蒲田1.db`（360行）, `マルハンメガシティ2000-蒲田7.db`（715行）, `みとや大森町店.db`（266行）に投入済み。他ホールのDBには本テーブルが存在しない場合がある
  - 角番別・Section別集計はこのテーブルを`machine_number`でJOINするだけで実現できる。**EDA側の座標CSVパース処理（`eda/kamata7_lastdigit_lr_eda.load_coords()`等）を再実装・再利用する必要はない** — DBに揃っている
- **`machine_master`テーブル**（各ホールDB内）
  - 列: `machine_name_normalized, jug_flag, hana_flag, oki_flag, bt_flag, display_names, official_name, ...`
  - **確認済み**: 蒲田1/蒲田7/みとやで100件超のデータが投入済み。`machine_detailed_results.machine_name`を`display_names`または正規化ロジックで`machine_name_normalized`に対応させてJOINする必要がある（既存の`ml/corner_section/mitoya_corner_section_analysis.py`の`load_analysis_frame`のJOIN方法を参考にする。ただし正規化ロジックの詳細は実装時に該当ファイルおよび`update-machine-master`スキルの実装を確認すること）
  - これを**セグメント別成績の汎用プロキシ**として使う（ジャグラー系／ハナハナ系／沖系／BT系／その他の5区分）。蒲田7固有の`classify_seg`（A/N軸）やみとや固有の複雑なセグメント定義は使わない。ホール固有の詳細セグメント分析はEDA側の役割とし、ダッシュボードでは全ホール共通で機械的に出せる粒度に留める

## 対象ホールの機能範囲

| 機能 | 全ホール共通 | 追加条件 |
|---|---|---|
| 機種別成績 | ○ | なし |
| 末尾別成績 | ○ | なし |
| 機械割104%超え | ○ | なし |
| 全台テーブル（台番号順+検索） | ○ | なし |
| セグメント別成績 | ○ | `machine_master`にJOINできるレコードがある場合のみ。無ければ非表示 |
| 角番別成績 | △ | 対象ホールの`machine_layout`テーブルが存在する場合のみ表示。無ければ非表示 |
| Section別成績 | △ | 同上 |
| フロアヒートマップ | △ | `find_floor_csvs`で座標CSVが見つかった場合のみ表示。無ければ非表示 |

角番・Section・ヒートマップの判定は**それぞれ独立**して行うこと（`machine_layout`の有無とHeatmap CSVの有無は別条件）。どちらも無いホールでは、機種別・末尾別・セグメント別・104%超え・全台テーブルのみの縮小版になる。

## 実装内容

新規ファイル: `dashboard/pages/page_18_daily_report.py`
新規ファイル: `dashboard/utils/daily_report.py`（集計ロジック本体。ページ側は薄いレンダリング層にする）

### Step 1: 対象日選択とデータ取得

1. `st.date_input`で対象日を選択（デフォルト値 = 昨日の日付）
2. `load_machine_detailed_by_date(db_path, date_str)`で当日の個別台データを取得（`date_str`はYYYYMMDD形式に変換）
3. サイドバーの`min_games`/`show_low_confidence`設定を`apply_machine_filters`相当のロジックで適用（対象が単日データなので`date_range`フィルタは不要、`min_games`フィルタのみ適用）
4. データが0件の場合は「この日のデータがありません」と表示して以降のセクションをレンダリングしない

### Step 2: 機械割・104%超えフラグの計算

`dashboard/utils/daily_report.py`に以下を実装する:

```python
def compute_payout_rate(df: pd.DataFrame) -> pd.Series:
    """games_normalized × 3枚/G を投入枚数とみなし機械割%を計算する。
    games_normalized が0またはNaNの行はNaNを返す（0除算回避）。
    """
    bet = df["games_normalized"] * 3
    payout = bet + df["diff_coins_normalized"]
    rate = (payout / bet) * 100
    return rate.where(bet > 0)


HIT104_THRESHOLD = 104.0

def add_hit104_flag(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["payout_rate"] = compute_payout_rate(df)
    df["hit104"] = (df["payout_rate"] >= HIT104_THRESHOLD).astype("Int64")  # NaN行はNaNのまま
    return df
```

**3枚/G固定の限界を明記する**: 現行機の大半は3枚ベット固定だが、1〜2枚ベット機種が混在する場合は誤差が出る。機種マスタに正確なベット数情報が無い前提のため、既知の限界として`daily_report.py`の docstring に一言残す（新たな機能追加はしない）。

### Step 3: KPIサマリー（当日 vs 直近7日/30日平均）

1. `load_daily_hall_summary(db_path)`から当日を含む直近30日分を取得
2. 当日値、直近7日平均、直近30日平均の3値を`metric_card_with_delta`でカード表示（`avg_diff_per_machine`, `win_rate`, `avg_games_per_machine`）
3. page_10の`_kpi_summary`パターンを参考にしてよいが、コピーせず新規に単日向けの集計関数として書く（期間集計用ロジックとは前提が異なるため）

### Step 4: 機種別・末尾別成績（当日データのみ）

1. `machine_name`でgroupby: `n, avg_diff, avg_payout_rate, hit104_count, hit104_rate`
2. `last_digit`でgroupby: 同上（`last_digit`はTEXT型のため`machine_detailed_results`の型に注意 — `database/CLAUDE.md`参照）
3. いずれもテーブル表示。件数が少ない機種・末尾（`min_games`未満）は既存フィルタで自動的に除外される

### Step 5: 角番別・Section別成績（`machine_layout`がある場合のみ）

1. `machine_detailed_results`（Step1の当日データ）と`machine_layout`を`machine_number`でJOIN
2. `rank_from_min`でgroupby → 角番別テーブル（`n, avg_diff, avg_payout_rate, hit104_rate`）
3. `section`でgroupby → Section別テーブル（同上）
4. みとやの`rank_from_aisle`が存在する場合は角番タブに追加タブとして出す（通路角番）。無い場合は`rank_from_min`のみでよい（両端角番の二重集計は今回のスコープ外、EDA側の`expand_dual_kakuban`は使わない — シンプルな片側ランクで十分）

### Step 6: セグメント別成績（`machine_master`にJOINできる場合のみ）

1. `machine_detailed_results.machine_name` を `machine_master` の正規化名にマッピングしてJOIN（マッピング方法は`ml/corner_section/mitoya_corner_section_analysis.py`の実装を参照して踏襲する）
2. `jug_flag/hana_flag/oki_flag/bt_flag`から`np.select`で単一の`segment`列（"jug"/"hana"/"oki"/"bt"/"other"）を作る（`prepare_analysis_frame`の`machine_type`列と同じロジックでよい）
3. `segment`でgroupby → テーブル表示

### Step 7: TOP5セクション（全台候補）

**前提**: すべて当日実績ベース（結果の振り返り用途）。既存ページのように「TOP10」ではなく「TOP5」で統一する。

1. **勝率TOP5**（個別台）: `payout_rate`降順TOP5
2. **差枚TOP5**（個別台）: `diff_coins_normalized`降順TOP5
3. **機械割104%超えTOP5**（カテゴリ単位、個別台ではない）: 以下3種類を**別々のテーブルとして**表示する
   - 末尾別104%超え率TOP5: `last_digit`でgroupby → `hit104_rate = hit104.mean()`降順TOP5
   - 角番別104%超え率TOP5: `rank_from_min`でgroupby → 同上（`machine_layout`が無いホールでは非表示）
   - 機種別104%超え率TOP5: `machine_name`でgroupby → 同上

   **懸念**: 当日G数が極端に少ない台は機械割が偶然104%を超えやすく、カテゴリ単位の集計が歪む。**このTOP5計算にも`min_games`フィルタ（サイドバー設定）を適用すること**（Step1のフィルタ済みデータフレームをそのまま使えば自動的に満たされる）。加えて、カテゴリ自体の最小サンプル数も設ける: `MIN_GROUP_SIZE_FOR_RANKING = 3`（このグループに属する当日稼働台数が3台未満の末尾/角番/機種はランキング対象外とする）。この定数は`daily_report.py`にモジュール定数として定義する

### Step 8: 全台テーブル（台番号順・検索付き）

1. Step1の当日データ（フィルタ後）を`machine_number`昇順でソートしテーブル表示。列: `台番号, 機種名, 末尾, 差枚, G数, 機械割%, 104%超えフラグ`（角番・Sectionが使えるホールでは列を追加）
2. `st.text_input`で検索ボックスを1つ設置。入力値を「台番号の部分一致 OR 機種名の部分一致」でフィルタする
   - 台番号は`str(machine_number)`に変換してから部分一致判定する（前方一致に限定しない。「23」で検索したら"23"を含む台番号・機種名の両方がヒットしてよい）
3. 検索欄が空の場合は全件表示

### Step 9: フロアヒートマップ（ページ最下部）

1. `find_floor_csvs(hall_name, project_root)`でCSVの有無を確認し、無ければセクション自体を非表示（見出しも出さない）
2. あれば`render_heatmap_page`を`date_range=(target_date, target_date)`で呼び出す。単日データで正しく機能しない場合（例: 内部で期間の複数日平均を前提にしている等）は、最小限のオプション追加で対応する。大きな改修が必要になりそうな場合は実装を止めて相談すること

## ページ全体の構成順序

```
1. ホール選択（サイドバー、既存）
2. 対象日選択（st.date_input、デフォルト=昨日）
3. KPIサマリーカード（当日 vs 直近7日/30日平均）
4. 機種別成績テーブル
5. 末尾別成績テーブル
6. 角番別成績テーブル（対応ホールのみ）
7. Section別成績テーブル（対応ホールのみ）
8. セグメント別成績テーブル（対応可能な場合のみ）
9. 全台TOP5（勝率TOP5 / 差枚TOP5 / 104%超えTOP5×3種）
10. 全台テーブル（台番号順・検索付き）
11. フロアヒートマップ（対応ホールのみ、最下部）
```

## 実装上の注意

1. 新規ファイルは`dashboard/pages/page_18_daily_report.py`と`dashboard/utils/daily_report.py`の2つ。既存の`dashboard/utils/data_loader.py`, `dashboard/utils/filters.py`, `Heatmap/heatmap_common.py`は**変更しない**（読み取り専用で再利用）
2. `machine_layout`・`machine_master`テーブルの有無は`sqlite3`で`sqlite_master`を都度チェックする関数を`daily_report.py`に用意する（`ml/corner_section/mitoya_corner_section_analysis.py`の`_has_required_tables`パターンを参考にしてよいが、コピーせず必要な最小限のテーブル存在チェックのみ書く）
3. 機械割・104%超えの計算式は`daily_report.py`に一度だけ実装し、Step2〜7のすべてのセクションから同じ関数を呼ぶ（重複実装しない）
4. `dashboard/pages/__init__.py`にページ登録が必要な場合は既存ページと同じ形式で追加する
5. サイドバーで選択中のホールに`machine_layout`/`machine_master`/座標CSVが無い場合、該当セクションを非表示にするだけでエラーは出さない（try/exceptで握りつぶすのではなく、事前にテーブル存在確認をしてから分岐する）

## テスト

`test/test_daily_report.py`に以下を含める（既存の`test/test_filters.py`と同じ配置パターン）:

- `compute_payout_rate`の単体テスト: 人工データで既知の投入枚数・差枚から期待される機械割%が算出されることを確認（例: 総投入2100枚・+300枚 → 114.3%になるケースを含める）。`games_normalized`が0の行はNaNになることの確認
- `add_hit104_flag`の単体テスト: 104%ちょうど・103.9%・104.1%の境界値で正しくフラグが立つことを確認
- カテゴリ別104%超え率ランキング関数の単体テスト: `MIN_GROUP_SIZE_FOR_RANKING`未満のグループが結果から除外されることを確認
- 全台テーブル検索フィルタの単体テスト: 台番号の部分一致・機種名の部分一致それぞれで正しい行が返ることを確認
- `machine_layout`/`machine_master`テーブル不在時に角番/Section/セグメント関連の集計関数が例外を出さず空DataFrameまたはNoneを返すことの確認（人工的にテーブルを持たないSQLite DBを作って検証する）
