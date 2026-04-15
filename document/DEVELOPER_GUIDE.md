# DEVELOPER_GUIDE.md
## 開発環境セットアップガイド

**対象者**: Pachinko Analyzerの開発エンジニア
**最終更新**: 2026-04-15
**Python版**: 3.10+

---

## 📂 ディレクトリ構造

```
C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\
├── CLAUDE.md                    ← AI向け全体仕様（最重要）
├── main_app.py                  ← 起動エントリーポイント
├── dashboard/                   ← Phase 3 ダッシュボード
│   ├── main.py
│   ├── design_system.py
│   ├── config/constants.py
│   ├── utils/data_loader.py
│   ├── utils/styling.py
│   └── pages/page_01〜13.py
├── database/                    ← Phase 2 DB処理
│   ├── main_processor.py
│   ├── data_inserter.py
│   ├── date_info_calculator.py
│   ├── summary_calculator.py
│   ├── rank_calculator.py
│   ├── batch_incremental_updater.py
│   ├── incremental_db_updater.py
│   ├── db_setup.py
│   └── table_config.py
├── scraper/
│   └── anaslo-scraper_multi.py  ← Phase 1
├── config/
│   └── hall_config.json
├── db/                          ← SQLite DB（gitignore）
│   └── {ホール名}.db
└── data/                        ← スクレイピングJSON（gitignore）
```

---

## 🔧 セットアップ手順

### 1. 仮想環境の有効化

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
.venv\Scripts\activate
```

### 2. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

**必須パッケージ**:
```
streamlit==1.56.0
pandas==3.0.2
plotly==6.7.0
numpy==2.4.4
sqlite3  # 標準ライブラリ
```

### 3. ダッシュボード起動

```bash
# プロジェクトルートから
streamlit run main_app.py
```

→ ブラウザで `http://localhost:8501` が自動で開く

---

## 🗄️ データベース接続

各ホール別にDBファイルが存在する。

```python
import sqlite3
import pandas as pd

db_path = r'C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\{ホール名}.db'

conn = sqlite3.connect(db_path)
df = pd.read_sql_query("SELECT * FROM machine_detailed_results LIMIT 10", conn)
conn.close()
```

### 利用可能なテーブル

```sql
SELECT * FROM machine_detailed_results;  -- 個別台詳細（メインデータ）
SELECT * FROM daily_hall_summary;        -- ホール全体日別集計
SELECT * FROM last_digit_summary_*;      -- 末尾別集計（日付ごと）
```

詳細は `パチスロ分析データベース スキーマ説明書.md` を参照。

---

## 🐍 開発時のポイント

### インポートの注意

```python
# main_app.py（絶対インポート）
from dashboard.main import ...
from dashboard.utils.data_loader import ...

# dashboard/main.py（相対インポート）
from .config.constants import ...
from .utils.data_loader import ...
```

### キャッシング

```python
@st.cache_data(ttl=3600)  # 1時間キャッシュ
def load_machine_detailed_results(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
    conn.close()
    return df
```

### min_games フィルタの正しい実装

```python
# ✅ 正しい：集計前に個別台レベルでフィルタ
if not st.session_state.show_low_confidence:
    df = df[df['games_normalized'] >= min_games]
# ← この後に groupby で集計

# ❌ 誤り：集計後にグループ単位でフィルタ
cross_summary = df.groupby(...).agg(...)
cross_summary = cross_summary[cross_summary['avg_games'] >= min_games]  # NG
```

### データ型の注意点

| データ | 型 | 注意 |
|--------|-----|------|
| 勝率 | float（内部）→ 文字列（表示） | ソートのため内部はfloat |
| 差枚・G数 | int | カンマ区切り表示 |
| last_digit（台） | **TEXT** | "0"〜"9" |
| last_digit（日） | **INTEGER** | 0〜9 |
| is_zorome | INTEGER | 0/1（BOOLEANは使わない） |

---

## 🐛 よく発生するエラーと対処

### KeyError: 'diff_coins_normalized'
```
原因: daily_hall_summary から個別台カラムを参照している
対策: load_machine_detailed_results() から取得する
```

### テーブルのソートが機能しない
```
原因: テキスト型（"100" < "200" がNG）
対策: 内部は数値型、表示時のみ文字列変換
```

### Plotly で複合軸が無効
```
原因: Plotly 6.7.0 の厳密な検証
対策: make_subplots() でサブプロット方式に統一
```

### SQLite 接続タイムアウト
```
原因: DBファイルがロック状態
対策: conn.close() で接続を明示的に閉じる
```

### ModuleNotFoundError（相対インポートエラー）
```
原因: dashboard/main.py をルートから直接実行している
対策: streamlit run main_app.py で起動する（main_app.pyが絶対インポート対応）
```

---

## 🧪 デバッグ方法

```bash
# ターミナルから直接テスト
python -c "
import sqlite3, pandas as pd
db_path = r'.\db\{ホール名}.db'
conn = sqlite3.connect(db_path)
df = pd.read_sql_query('SELECT * FROM machine_detailed_results LIMIT 5', conn)
print(df.head())
conn.close()
"

# キャッシュクリア + 再起動
# → Streamlit UIの「Rerun」をクリック、またはキャッシュクリア
```

---

## 📈 パフォーマンス最適化

```python
# ✅ DB側でフィルタリング（推奨）
query = """
SELECT * FROM machine_detailed_results
WHERE date BETWEEN ? AND ?
"""
df = pd.read_sql_query(query, conn, params=(start_date, end_date))

# ❌ 全件取得してPythonでフィルタ（避ける）
df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
```

---

## 📚 参考ドキュメント

| ファイル | 内容 |
|---------|------|
| `CLAUDE.md`（ルート） | 全体仕様・最新構成（最重要） |
| `ARCHITECTURE.md` | システム構成図・データフロー |
| `パチスロ分析データベース スキーマ説明書.md` | DBスキーマ詳細 |
| `PHASE2_完全仕様書.md` | Phase 2 詳細仕様 |
| `PHASE2_API_Reference.md` | Phase 2 API仕様 |
| `Phase1_Scraper実装ドキュメント.md` | スクレイパー仕様 |

---

**作成日**: 2026-04-15
**対象**: 開発エンジニア向け
