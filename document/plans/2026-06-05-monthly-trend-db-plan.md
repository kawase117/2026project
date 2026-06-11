# 月次トレンドDB 実装プラン — 2026-06-05

## 概要

各ホールのSQLite DB内に月次集計テーブル（18テーブル）を追加する。
日次データから3軸 × 6機種タイプの月次集計を事前計算し、トレンド追跡・ML特徴量として活用する。

**プロジェクトルート**: `C:\Users\apto117\Documents\pachinko-analyzer\src\2026project`

---

## 設計サマリー

| 項目 | 決定事項 |
|---|---|
| テーブル数 | 18（3軸 × 6機種タイプ） |
| 月の定義 | カレンダー月（`year_month TEXT = "202605"`） |
| 更新タイミング | 毎日の日次処理後（`import_single_json` の末尾） |
| 中央値計算 | Pandas で計算してからINSERT |
| ランク指標 | `avg_rank_diff`, `avg_rank_games`, `avg_rank_efficiency`, `times_ranked_1st`, `times_ranked_top3` |
| 月完了管理 | `is_complete`（0/1）+ `days_in_month` |
| DB統合方針 | `create_database()` に最初から組み込む |

---

## テーブル構成

### 命名規則

```
monthly_trend_{axis}_{type}
```

- **axis**: `date_digit`（Xのつく日）, `weekday`（曜日）, `machine_digit`（台末尾）
- **type**: `all`, `jug`, `hana`, `oki`, `bt`, `other`
  - `table_config.py` の `MACHINE_TYPE_CONFIGS` と完全に一致させる（bt を含む6バリアント）

### 全18テーブル一覧

```
monthly_trend_date_digit_all
monthly_trend_date_digit_jug
monthly_trend_date_digit_hana
monthly_trend_date_digit_oki
monthly_trend_date_digit_bt
monthly_trend_date_digit_other

monthly_trend_weekday_all
monthly_trend_weekday_jug
monthly_trend_weekday_hana
monthly_trend_weekday_oki
monthly_trend_weekday_bt
monthly_trend_weekday_other

monthly_trend_machine_digit_all
monthly_trend_machine_digit_jug
monthly_trend_machine_digit_hana
monthly_trend_machine_digit_oki
monthly_trend_machine_digit_bt
monthly_trend_machine_digit_other
```

---

## スキーマ定義

### monthly_trend_date_digit_{type}

```sql
CREATE TABLE monthly_trend_date_digit_{type} (
    year_month      TEXT     NOT NULL,   -- "202605"
    date_digit      INTEGER  NOT NULL,   -- 0〜9（日付末尾）

    -- 信頼性・完了管理
    sample_count    INTEGER,             -- 月内でこのdate_digitが出現した日数（約3日）
    days_in_month   INTEGER,             -- その月の総日数（28〜31）
    is_complete     INTEGER DEFAULT 0,   -- 1=月確定済み, 0=進行中

    -- 差枚指標
    -- avg/median: 全対象台の差枚の平均・中央値（月内全日・全台の生データから計算）
    -- max/min: 月内で最も差枚が大きかった・小さかった個別台の値（生データから計算）
    -- total: 月内全対象台の差枚合計（生データから計算）
    avg_diff_per_machine    REAL,
    median_diff_per_machine REAL,
    max_diff_coins          INTEGER,     -- MAX(diff_coins_normalized) 生データ由来
    min_diff_coins          INTEGER,     -- MIN(diff_coins_normalized) 生データ由来
    total_diff_coins        INTEGER,     -- SUM(diff_coins_normalized) 生データ由来

    -- 稼働・勝率指標
    avg_games_per_machine   REAL,
    win_rate                REAL,
    high_profit_rate        REAL,
    machine_count           REAL,        -- 平均台数/日

    -- ランク指標（月内での日次順位の集計）
    avg_rank_diff           REAL,        -- 月内の差枚順位平均（低いほど良い）
    avg_rank_games          REAL,        -- 月内のG数順位平均
    avg_rank_efficiency     REAL,        -- 月内の効率順位平均
    times_ranked_1st        INTEGER,     -- 月内で1位になった日数
    times_ranked_top3       INTEGER,     -- 月内でTop3に入った日数

    PRIMARY KEY (year_month, date_digit)
)
```

### monthly_trend_weekday_{type}

```sql
CREATE TABLE monthly_trend_weekday_{type} (
    year_month      TEXT  NOT NULL,
    day_of_week     TEXT  NOT NULL,   -- "月", "火", "水", "木", "金", "土", "日"

    sample_count    INTEGER,
    days_in_month   INTEGER,
    is_complete     INTEGER DEFAULT 0,

    avg_diff_per_machine    REAL,
    median_diff_per_machine REAL,
    max_diff_coins          INTEGER,
    min_diff_coins          INTEGER,
    total_diff_coins        INTEGER,
    avg_games_per_machine   REAL,
    win_rate                REAL,
    high_profit_rate        REAL,
    machine_count           REAL,

    avg_rank_diff           REAL,
    avg_rank_games          REAL,
    avg_rank_efficiency     REAL,
    times_ranked_1st        INTEGER,
    times_ranked_top3       INTEGER,

    PRIMARY KEY (year_month, day_of_week)
)
```

### monthly_trend_machine_digit_{type}

```sql
CREATE TABLE monthly_trend_machine_digit_{type} (
    year_month      TEXT  NOT NULL,
    machine_digit   TEXT  NOT NULL,   -- "0"〜"9"（台番号末尾、TEXT型）

    sample_count    INTEGER,          -- 月内日数（約30日）
    days_in_month   INTEGER,
    is_complete     INTEGER DEFAULT 0,

    avg_diff_per_machine    REAL,
    median_diff_per_machine REAL,
    max_diff_coins          INTEGER,
    min_diff_coins          INTEGER,
    total_diff_coins        INTEGER,
    avg_games_per_machine   REAL,
    win_rate                REAL,
    high_profit_rate        REAL,
    machine_count           REAL,

    avg_rank_diff           REAL,
    avg_rank_games          REAL,
    avg_rank_efficiency     REAL,
    times_ranked_1st        INTEGER,
    times_ranked_top3       INTEGER,

    PRIMARY KEY (year_month, machine_digit)
)
```

---

## 作成・変更ファイル一覧

| ファイル | 種別 | 内容 |
|---|---|---|
| `database/monthly_trend_calculator.py` | **新規作成** | MonthlyTrendCalculatorクラス |
| `database/db_setup.py` | **修正** | `create_database()` に15テーブル作成を追加 |
| `database/main_processor.py` | **修正** | DataImporterにMonthlyTrendCalculatorを追加 |
| `database/incremental_db_updater.py` | **修正** | IncrementalDBUpdaterにMonthlyTrendCalculatorを追加 |
| `database/migrate_add_monthly_trend.py` | **新規作成** | 既存DBに月次テーブルを追加＋バックフィルするマイグレーション |

---

## Task 1: `database/db_setup.py` 修正

`create_database()` 関数の `conn.commit()` の直前に以下を追加する。

```python
# 月次トレンドテーブル（15テーブル）
_create_monthly_trend_tables(cursor)
```

追加する関数：

```python
def _create_monthly_trend_tables(cursor):
    """月次トレンドテーブルを作成（3軸 × 5機種タイプ = 15テーブル）"""

    AXIS_CONFIGS = [
        {'axis': 'date_digit',    'key_col': 'date_digit INTEGER NOT NULL',  'key_name': 'date_digit'},
        {'axis': 'weekday',       'key_col': 'day_of_week TEXT NOT NULL',     'key_name': 'day_of_week'},
        {'axis': 'machine_digit', 'key_col': 'machine_digit TEXT NOT NULL',   'key_name': 'machine_digit'},
    ]
    TYPE_SUFFIXES = ['all', 'jug', 'hana', 'oki', 'bt', 'other']  # table_config.py と一致

    for axis_cfg in AXIS_CONFIGS:
        axis     = axis_cfg['axis']
        key_col  = axis_cfg['key_col']
        key_name = axis_cfg['key_name']

        for suffix in TYPE_SUFFIXES:
            table_name = f"monthly_trend_{axis}_{suffix}"
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    year_month               TEXT    NOT NULL,
                    {key_col},
                    sample_count             INTEGER,
                    days_in_month            INTEGER,
                    is_complete              INTEGER DEFAULT 0,
                    avg_diff_per_machine     REAL,
                    median_diff_per_machine  REAL,
                    max_diff_coins           INTEGER,
                    min_diff_coins           INTEGER,
                    total_diff_coins         INTEGER,
                    avg_games_per_machine    REAL,
                    win_rate                 REAL,
                    high_profit_rate         REAL,
                    machine_count            REAL,
                    avg_rank_diff            REAL,
                    avg_rank_games           REAL,
                    avg_rank_efficiency      REAL,
                    times_ranked_1st         INTEGER,
                    times_ranked_top3        INTEGER,
                    PRIMARY KEY (year_month, {key_name})
                )
            ''')
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS idx_{table_name}_ym ON {table_name}(year_month)'
            )
            print(f"[OK] {table_name}")

    print("月次トレンドテーブル作成完了: 15テーブル")
```

---

## Task 2: `database/monthly_trend_calculator.py` 新規作成

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月次トレンドテーブルの計算・更新
毎日の日次処理完了後に呼び出し、当月の月次集計を再計算する。
"""

import calendar
import sqlite3

import pandas as pd


MACHINE_SUFFIXES = ['all', 'jug', 'hana', 'oki', 'bt', 'other']  # table_config.py と一致

# 機種タイプフィルタ（DataFrameのフラグ列で絞り込む）
TYPE_FILTERS = {
    'all':   lambda df: df,
    'jug':   lambda df: df[df['jug_flag'] == 1],
    'hana':  lambda df: df[df['hana_flag'] == 1],
    'oki':   lambda df: df[df['oki_flag'] == 1],
    'bt':    lambda df: df[df['bt_flag'] == 1],
    'other': lambda df: df[
        (df['jug_flag'] == 0) & (df['hana_flag'] == 0) &
        (df['oki_flag'] == 0) & (df['bt_flag'] == 0)
    ],
}

# machine_digitテーブル用 SQL WHERE 条件
TYPE_SQL_CONDITIONS = {
    'all':   '1=1',
    'jug':   'mm.jug_flag = 1',
    'hana':  'mm.hana_flag = 1',
    'oki':   'mm.oki_flag = 1',
    'bt':    'mm.bt_flag = 1',
    'other': 'mm.jug_flag = 0 AND mm.hana_flag = 0 AND mm.oki_flag = 0 AND mm.bt_flag = 0',
}

UPSERT_COLS = [
    'year_month', 'sample_count', 'days_in_month', 'is_complete',
    'avg_diff_per_machine', 'median_diff_per_machine',
    'max_diff_coins', 'min_diff_coins', 'total_diff_coins',
    'avg_games_per_machine', 'win_rate', 'high_profit_rate', 'machine_count',
    'avg_rank_diff', 'avg_rank_games', 'avg_rank_efficiency',
    'times_ranked_1st', 'times_ranked_top3',
]


class MonthlyTrendCalculator:
    """月次トレンドテーブルの計算・更新クラス"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def update_month(self, date: str):
        """日次処理完了後のエントリーポイント。

        当月を再計算し、月が変わった場合は前月を is_complete=1 にする。

        Args:
            date: 処理した日付 "YYYYMMDD"
        """
        year_month = date[:6]          # "20260605" → "202606"
        self._compute_month(year_month)
        self._maybe_complete_prev_month(year_month)

    # ------------------------------------------------------------------ #
    # Core computation
    # ------------------------------------------------------------------ #

    def _compute_month(self, year_month: str):
        """指定月の全15テーブルを再計算して INSERT OR REPLACE"""
        year = int(year_month[:4])
        month = int(year_month[4:])
        days_in_month = calendar.monthrange(year, month)[1]

        conn = self.get_connection()
        try:
            df_machines, df_hall = self._load_month_data(conn, year_month)

            if not df_machines.empty and not df_hall.empty:
                self._compute_date_digit_tables(
                    conn, year_month, days_in_month, df_machines, df_hall)
                self._compute_weekday_tables(
                    conn, year_month, days_in_month, df_machines, df_hall)

            self._compute_machine_digit_tables(conn, year_month, days_in_month)

            conn.commit()
        finally:
            conn.close()

    def _load_month_data(self, conn, year_month: str):
        """machine_detailed_results と daily_hall_summary を月分ロード"""
        df_machines = pd.read_sql_query("""
            SELECT
                m.date,
                m.machine_name,
                m.last_digit           AS machine_digit,
                m.games_normalized,
                m.diff_coins_normalized,
                COALESCE(mm.jug_flag,  0) AS jug_flag,
                COALESCE(mm.hana_flag, 0) AS hana_flag,
                COALESCE(mm.oki_flag,  0) AS oki_flag,
                COALESCE(mm.bt_flag,   0) AS bt_flag
            FROM machine_detailed_results m
            LEFT JOIN machine_master mm
                   ON m.machine_name = mm.machine_name_normalized
            WHERE m.date LIKE ?
        """, conn, params=(f"{year_month}%",))

        df_hall = pd.read_sql_query("""
            SELECT date,
                   last_digit  AS date_digit,
                   day_of_week
            FROM daily_hall_summary
            WHERE date LIKE ?
        """, conn, params=(f"{year_month}%",))

        return df_machines, df_hall

    # ------------------------------------------------------------------ #
    # date_digit tables
    # ------------------------------------------------------------------ #

    def _compute_date_digit_tables(self, conn, year_month, days_in_month,
                                   df_machines, df_hall):
        df = df_machines.merge(df_hall[['date', 'date_digit']], on='date', how='inner')
        df['date_digit'] = df['date_digit'].astype(int)

        for suffix, filter_fn in TYPE_FILTERS.items():
            df_type = filter_fn(df.copy())
            if df_type.empty:
                continue
            rows = self._aggregate_by_key(df_type, 'date_digit', year_month,
                                          days_in_month)
            table = f"monthly_trend_date_digit_{suffix}"
            self._upsert_rows(conn, table, 'date_digit', rows)

    # ------------------------------------------------------------------ #
    # weekday tables
    # ------------------------------------------------------------------ #

    def _compute_weekday_tables(self, conn, year_month, days_in_month,
                                df_machines, df_hall):
        df = df_machines.merge(df_hall[['date', 'day_of_week']], on='date', how='inner')

        for suffix, filter_fn in TYPE_FILTERS.items():
            df_type = filter_fn(df.copy())
            if df_type.empty:
                continue
            rows = self._aggregate_by_key(df_type, 'day_of_week', year_month,
                                          days_in_month)
            table = f"monthly_trend_weekday_{suffix}"
            self._upsert_rows(conn, table, 'day_of_week', rows)

    # ------------------------------------------------------------------ #
    # machine_digit tables
    # ------------------------------------------------------------------ #

    def _compute_machine_digit_tables(self, conn, year_month, days_in_month):
        """last_digit_summary_* から月次集計（既存ランク列を活用）"""
        for suffix in MACHINE_SUFFIXES:
            src = f"last_digit_summary_{suffix}"

            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (src,)
            )
            if not cur.fetchone():
                continue

            df = pd.read_sql_query(f"""
                SELECT
                    last_digit                 AS machine_digit,
                    date,
                    avg_diff_coins,
                    avg_games,
                    max_diff_coins,
                    min_diff_coins,
                    total_diff_coins,
                    win_rate,
                    high_profit_rate,
                    machine_count,
                    last_digit_rank_diff       AS rank_diff,
                    last_digit_rank_games      AS rank_games,
                    last_digit_rank_efficiency AS rank_efficiency
                FROM {src}
                WHERE date LIKE ?
                  AND last_digit NOT IN ('ゾロ目')
            """, conn, params=(f"{year_month}%",))

            if df.empty:
                continue

            # 中央値は raw data から取得
            cond = TYPE_SQL_CONDITIONS[suffix]
            df_raw = pd.read_sql_query(f"""
                SELECT m.last_digit AS machine_digit, m.diff_coins_normalized
                FROM machine_detailed_results m
                LEFT JOIN machine_master mm
                       ON m.machine_name = mm.machine_name_normalized
                WHERE m.date LIKE ?
                  AND m.last_digit IN ('0','1','2','3','4','5','6','7','8','9')
                  AND {cond}
            """, conn, params=(f"{year_month}%",))

            medians = (df_raw.groupby('machine_digit')['diff_coins_normalized']
                       .median()
                       .rename('median_diff_per_machine'))

            result = (df.groupby('machine_digit').agg(
                sample_count        =('date',              'nunique'),
                avg_diff_per_machine=('avg_diff_coins',    'mean'),
                max_diff_coins      =('max_diff_coins',    'max'),
                min_diff_coins      =('min_diff_coins',    'min'),
                total_diff_coins    =('total_diff_coins',  'sum'),
                avg_games_per_machine=('avg_games',        'mean'),
                win_rate            =('win_rate',          'mean'),
                high_profit_rate    =('high_profit_rate',  'mean'),
                machine_count       =('machine_count',     'mean'),
                avg_rank_diff       =('rank_diff',         'mean'),
                avg_rank_games      =('rank_games',        'mean'),
                avg_rank_efficiency =('rank_efficiency',   'mean'),
                times_ranked_1st    =('rank_diff',         lambda x: (x == 1).sum()),
                times_ranked_top3   =('rank_diff',         lambda x: (x <= 3).sum()),
            ).reset_index()
            .merge(medians, on='machine_digit', how='left'))

            result['year_month']   = year_month
            result['days_in_month'] = days_in_month
            result['is_complete']  = 0

            table = f"monthly_trend_machine_digit_{suffix}"
            self._upsert_rows(conn, table, 'machine_digit', result)

    # ------------------------------------------------------------------ #
    # Aggregation helper
    # ------------------------------------------------------------------ #

    def _aggregate_by_key(self, df, key_col, year_month, days_in_month):
        """date_digit / day_of_week をキーに月次集計する汎用メソッド"""

        # high_profit フラグを事前計算（Lambda内での他列参照を避ける）
        df['is_high_profit'] = (
            (df['diff_coins_normalized'] >= 1000) &
            (df['games_normalized'] >= 3000)
        ).astype(int)

        # 1. 日×キーごとの集計
        daily = df.groupby(['date', key_col]).agg(
            avg_diff         =('diff_coins_normalized', 'mean'),
            avg_games        =('games_normalized',       'mean'),
            machine_count_d  =('machine_name',           'count'),
            win_count        =('diff_coins_normalized',  lambda x: (x > 0).sum()),
            high_profit_count=('is_high_profit',         'sum'),
        ).reset_index()

        daily['win_rate']         = daily['win_count']         / daily['machine_count_d'] * 100
        daily['high_profit_rate'] = daily['high_profit_count'] / daily['machine_count_d'] * 100
        daily['efficiency']       = daily['avg_diff'] / daily['avg_games'].replace(0, float('nan'))

        # 2. 日内でキー別ランクを付与
        daily['rank_diff']       = (daily.groupby('date')['avg_diff']
                                    .rank(ascending=False, method='first').astype(int))
        daily['rank_games']      = (daily.groupby('date')['avg_games']
                                    .rank(ascending=False, method='first').astype(int))
        daily['rank_efficiency'] = (daily.groupby('date')['efficiency']
                                    .rank(ascending=False, method='first').astype(int))

        # 3. 生データから中央値・max・min・total を計算
        # NOTE: max/min/total は avg_diff（日次平均）からではなく
        #       生の diff_coins_normalized（個別台）から計算する。
        #       これにより列名が実態と一致する（max=その月で最も差枚が大きかった台の値）。
        raw_agg = df.groupby(key_col)['diff_coins_normalized'].agg(
            median_diff_per_machine='median',
            max_diff_coins='max',
            min_diff_coins='min',
            total_diff_coins='sum',
        )

        # 4. 月次集計（ランク・勝率系は日次集計から）
        result = (daily.groupby(key_col).agg(
            sample_count        =('date',             'nunique'),
            avg_diff_per_machine=('avg_diff',         'mean'),
            avg_games_per_machine=('avg_games',       'mean'),
            win_rate            =('win_rate',         'mean'),
            high_profit_rate    =('high_profit_rate', 'mean'),
            machine_count       =('machine_count_d',  'mean'),
            avg_rank_diff       =('rank_diff',        'mean'),
            avg_rank_games      =('rank_games',       'mean'),
            avg_rank_efficiency =('rank_efficiency',  'mean'),
            times_ranked_1st    =('rank_diff',        lambda x: (x == 1).sum()),
            times_ranked_top3   =('rank_diff',        lambda x: (x <= 3).sum()),
        ).reset_index()
        .merge(raw_agg, on=key_col, how='left'))

        result['year_month']    = year_month
        result['days_in_month'] = days_in_month
        result['is_complete']   = 0

        return result

    # ------------------------------------------------------------------ #
    # DB write helper
    # ------------------------------------------------------------------ #

    def _upsert_rows(self, conn, table_name, key_name, df):
        """DataFrameの行を INSERT OR REPLACE でDBに書き込む"""
        if df.empty:
            return

        cols = [key_name] + UPSERT_COLS
        placeholders = ','.join(['?'] * len(cols))
        sql = (f"INSERT OR REPLACE INTO {table_name} "
               f"({','.join(cols)}) VALUES ({placeholders})")

        records = [tuple(row.get(c) for c in cols) for _, row in df.iterrows()]
        conn.cursor().executemany(sql, records)

    # ------------------------------------------------------------------ #
    # Month completion
    # ------------------------------------------------------------------ #

    def _maybe_complete_prev_month(self, current_year_month: str):
        """前月のデータが存在し is_complete=0 なら is_complete=1 にする"""
        prev = self._get_prev_month(current_year_month)

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            for suffix in MACHINE_SUFFIXES:
                for axis in ['date_digit', 'weekday', 'machine_digit']:
                    table = f"monthly_trend_{axis}_{suffix}"
                    cur.execute(
                        f"UPDATE {table} SET is_complete = 1 "
                        f"WHERE year_month = ? AND is_complete = 0",
                        (prev,)
                    )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _get_prev_month(year_month: str) -> str:
        year  = int(year_month[:4])
        month = int(year_month[4:])
        if month == 1:
            return f"{year - 1}12"
        return f"{year}{month - 1:02d}"
```

---

## Task 3: `database/main_processor.py` 修正

### インポート追加（ファイル冒頭）
```python
from monthly_trend_calculator import MonthlyTrendCalculator
```

### DataImporter.__init__ に追加（既存の `self.date_info_calc = ...` の後）
```python
self.monthly_trend_calc = MonthlyTrendCalculator(db_path)
```

### import_single_json の末尾（既存の try/except ブロックの後）に追加
```python
# 5. 月次トレンド更新（ランク計算完了後に実行すること）
try:
    self.monthly_trend_calc.update_month(date)
    print(f"✅ {date}: 月次トレンド更新完了")
except Exception as e:
    print(f"⚠️ {date}: 月次トレンド更新スキップ - {str(e)}")
```

**重要**: 必ず `rank_calc.calculate_ranks_for_date(date)` の後に呼ぶこと。
`monthly_trend_machine_digit_*` は `last_digit_summary_*` のランク列を参照するため。

---

## Task 4: `database/incremental_db_updater.py` 修正

Task 3 と同様の変更を適用する。

### インポート追加
```python
from monthly_trend_calculator import MonthlyTrendCalculator
```

### IncrementalDBUpdater.__init__ に追加
```python
self.monthly_trend_calc = MonthlyTrendCalculator(self.db_path)
```

### `process_new_date()` メソッドの末尾（ステップ4のtry/exceptブロックの後）に追加

`process_new_date()` は現在ステップ1〜4で構成されている。ステップ4（ランク計算）の
try/except ブロックの直後、`return True` の前に以下を追加する：

```python
            # 5. 月次トレンド更新（ランク計算完了後に実行すること）
            try:
                self.monthly_trend_calc.update_month(date_str)
                print(f"      [OK] 月次トレンド更新完了")
            except Exception as e:
                print(f"      [WARN] 月次トレンド更新スキップ - {str(e)}")
```

これにより `incremental_db_updater.py` を実行するだけで月次テーブルも自動更新される。
複数日をまとめて処理する場合も、日ごとに `update_month()` が呼ばれ月次テーブルが
都度再計算されるため、最終的な状態は常に正しい（`INSERT OR REPLACE` で冪等）。

---

## Task 5: `database/migrate_add_monthly_trend.py` 新規作成

既存ホールDBに月次テーブルを追加し、全履歴をバックフィルする。**新規DB構築時は不要。**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
既存DBへの月次トレンドテーブル追加 + 全履歴バックフィル
実行: cd database && python migrate_add_monthly_trend.py
"""

import glob
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_setup import _create_monthly_trend_tables
from monthly_trend_calculator import MonthlyTrendCalculator


def migrate_db(db_path: str):
    print(f"\n=== マイグレーション: {db_path} ===")

    # 1. テーブル作成（IF NOT EXISTS なので安全）
    conn = sqlite3.connect(db_path)
    _create_monthly_trend_tables(conn.cursor())
    conn.commit()
    conn.close()

    # 2. 全履歴の year_month を取得
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT substr(date, 1, 6) AS ym
        FROM daily_hall_summary
        ORDER BY ym
    """)
    months = [row[0] for row in cur.fetchall()]
    conn.close()

    if not months:
        print("  データなし。スキップ。")
        return

    print(f"  バックフィル対象: {len(months)}ヶ月 ({months[0]} 〜 {months[-1]})")

    calc = MonthlyTrendCalculator(db_path)

    # 3. 月ごとに計算
    for ym in months:
        print(f"  計算中: {ym}", end=' ', flush=True)
        calc._compute_month(ym)
        print("完了")

    # 4. 最終月以外を is_complete=1 に
    for ym in months[:-1]:
        year  = int(ym[:4])
        month = int(ym[4:])
        if month == 12:
            next_ym = f"{year + 1}01"
        else:
            next_ym = f"{year}{month + 1:02d}"
        calc._maybe_complete_prev_month(next_ym)

    print(f"  ✅ 完了: {db_path}")


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    db_files = sorted(glob.glob(str(project_root / "db" / "*.db")))
    db_files = [f for f in db_files if "machine_master" not in f]

    print(f"対象DB: {len(db_files)}件")
    for db_path in db_files:
        try:
            migrate_db(db_path)
        except Exception as e:
            print(f"  ❌ エラー: {db_path} - {e}")
```

---

## パフォーマンス注記

`update_month()` は毎日呼ばれるたびに当月全体を再計算する（当月の全日付を読み直す）。

現在の規模（1ホール・月30日・数百台）では問題ないが、ホール数や履歴が増えた場合の概算：

| 条件 | 推定データ量 | 推定処理時間 |
|---|---|---|
| 1ホール・月30日・台300台 | 約9,000行/月 | < 1秒 |
| 9ホール・月30日・台300台 | 約81,000行/月 | < 5秒 |
| 9ホール・月30日・台300台 × 3年 | ← バックフィル時のみ | < 30秒/月 |

日次増分処理（1日分追加）のコストは「当月の日数 × 台数」に比例するが、
月初よりも月末の方が読み取り行数が多い程度（最大30日分）で実用上問題ない。

ホール数が15を超えたり、処理時間が5秒を超えるようになった場合は、
「新規日付のみ差分更新」方式（前日までの月次集計値を持ち越して加算）への移行を検討する。

---

## 注意事項・実装上のポイント

### 1. machine_master の参照
`machine_master` テーブルは各ホールDBに内蔵されている（`data_inserter.py` の
`_ensure_machine_master_table()` で作成）。`MonthlyTrendCalculator` は同じ
`db_path` に接続するだけで JOIN できる。

### 2. machine_digit の型
`machine_detailed_results.last_digit` は **TEXT型**（"0"〜"9"）。
`last_digit_summary_*` の `last_digit` も TEXT。
月次テーブルの `machine_digit` は TEXT で統一する。

### 3. ゾロ目行の除外
`last_digit_summary_*` には `last_digit = 'ゾロ目'` の行が含まれる。
月次集計では `WHERE last_digit NOT IN ('ゾロ目')` で除外する。

### 4. ランク計算のタイミング
`monthly_trend_calculator.update_month()` は
`rank_calc.calculate_ranks_for_date()` の**後**に呼ぶこと。
`monthly_trend_machine_digit_*` は `last_digit_rank_diff` 等を参照するため。

### 5. bt バリアントについて
`table_config.py` の `MACHINE_TYPE_CONFIGS` は `all/jug/hana/oki/bt/other` の6バリアント。
月次テーブルもこれと一致させる（18テーブル）。
既存の `last_digit_summary_*` が5バリアント（bt なし）であるのは別の経緯によるものであり、
月次テーブルは意図的に6バリアントで揃える。

---

## 実行順序（新規DB構築時）

```
create_database()
  └─ _create_monthly_trend_tables()  ← 15テーブル作成

import_single_json(date) × N日分
  ├─ data_inserter
  ├─ summary_calculator
  ├─ rank_calculator
  ├─ date_info_calculator
  └─ monthly_trend_calc.update_month(date)  ← 月次集計（必ずrank後）
```

## 実行順序（既存DBへの追加）

```bash
cd database
python migrate_add_monthly_trend.py
```
