# database/ — DBモジュール ガイド

## DBスキーマ（主要テーブル）

### machine_detailed_results（メインデータ）
| カラム | 型 | 注意 |
|--------|-----|------|
| date | TEXT | YYYYMMDD形式 |
| machine_number | INTEGER | 台番号 |
| machine_name | TEXT | 機種名 |
| last_digit | **TEXT** | "0"〜"9"（文字列！） |
| is_zorome | **INTEGER** | 0/1（BOOLEAN非対応）。台番号の末尾2桁が同じ場合に 1 |
| games_normalized | INTEGER | 正規化ゲーム数 |
| diff_coins_normalized | INTEGER | 正規化差枚 |

### daily_hall_summary（ホール集計）
| カラム | 型 | 注意 |
|--------|-----|------|
| date | TEXT | YYYYMMDD形式 |
| day_of_week | TEXT | 曜日（日本語） |
| last_digit | INTEGER | 日付末尾（整数！） |
| weekday_nth | TEXT | 第N曜日（"Mon1"など）必ずこのテーブルから取得 |
| win_rate | FLOAT | 勝率（%） |
| avg_games_per_machine | INTEGER | 台平均G数 |
| avg_diff_per_machine | INTEGER | 台平均差枚 |
| is_zorome | INTEGER | 日付の日が 11 または 22 の場合に 1 |

### machine_layout / machine_layout_history（台の物理位置）

🔴 **位置を過去データに当てるときは必ず `machine_layout_history` を使うこと。**

| テーブル | 粒度 | 用途 |
|---|---|---|
| `machine_layout` | `machine_number` 単独がPK。**現行エポックのスナップショット**（日付次元なし） | 当日の推薦・ダッシュボード等「今」の位置が欲しい場合 |
| `machine_layout_history` | PK `(machine_number, valid_from)`。`valid_from`〜`valid_to`（TEXT `YYYYMMDD`、`valid_to` が NULL なら現在まで） | **過去に遡る分析すべて** |

主な位置列は両テーブル共通: `section`(TEXT 例 `2223-2240`)、`section_min`/`section_max`、
`rank_from_min`/`rank_from_max`（台番号順のセクション内順位）、`rank_from_aisle`（通路角番）。
`rank_from_aisle` が入っているのは蒲田7とみとやのみ。楽園・蒲田1は全NULL、雑色ほか5ホールは
`machine_layout` 自体が空。

🔴 **`rank_from_min`/`rank_from_max` は「台番号順の順位」であって物理的な島の端ではない。**
背中合わせ2列の島では台番号が蛇行(U字)で振られるため、`rank==1` は**島の片方の端の2台だけ**を
拾い、**反対側の端の2台は順位が中央（n/2, n/2+1）になって「最も中間」扱いになる**。
楽園は43セクション中17〜18が2列島で、物理端130台のうち45台（35%）がこの取りこぼしだった
（`backtest/results/regime/FINDINGS.md` 追試11）。物理的な端が必要なら座標から導出すること:

```python
# 島が縦(X が列インデックス)か横(Y が列)かを、値の種類が少ないほうで決める
key, pos = ("x", "y") if g.x.nunique() <= g.y.nunique() else ("y", "x")
is_edge = (g[pos] == g.groupby(key)[pos].transform("min")) | \
          (g[pos] == g.groupby(key)[pos].transform("max"))
```

ホール別の状況: 楽園=2列島が多数で要注意 / みとや=全島1列で問題なし /
蒲田7=2列島ゼロでほぼ問題なし（主軸は `rank_from_aisle`）/
**蒲田1=x,y が台番号に沿った対角線状（座標重複0・30セクション中14が完全対角）で
合成座標の疑いが濃厚。座標ベースの位置検証は不可**。

**なぜ分けているか**: `machine_layout` は構造上ただ1つの時代についてしか正しくありえない。
楽園蒲田の 2026-07-06 の改装で section 定義が書き換わり（`2223-2240` → `2225-2242` 等）、
工事後の位置が工事前のデータに遡って適用された結果、技術介入の端番効果が
+1.127pp → +0.211pp と**「効果が消えた」ように見える事故**が実際に起きた。
効果の消滅ではなく測定対象の破壊である（`backtest/results/regime/FINDINGS.md` 追試10）。

`machine_layout` を作り替えなかったのは、このテーブルを参照する約60ファイルが
いずれも `ON r.machine_number = l.machine_number` の単純結合をしており、
日付次元を足すと1台に複数行が対応して**全て静かに二重計上になる**ため。
参照側は1つずつ history へ移行する。移行済み: `backtest/run_backtest.py`。

結合の書き方:

```sql
LEFT JOIN machine_layout_history l
       ON r.machine_number = l.machine_number
      AND r.date >= l.valid_from
      AND (l.valid_to IS NULL OR r.date <= l.valid_to)
```

構築・検証は `database/migrate_machine_layout_history.py`（`bootstrap` / `insert-era` / `verify`）。
`verify` はエポックの重なり（重なると結合で行が増える）とカバレッジを検査する。

## モジュール構成

| ファイル | 役割 |
|---------|------|
| main_processor.py | 全処理のオーケストレーター |
| data_inserter.py | SQLiteへのデータ投入 |
| date_info_calculator.py | 日付フラグ計算（is_zorome, weekday_nth等） |
| summary_calculator.py | 集計処理 |
| rank_calculator.py | ランク・移動平均計算（ROW_NUMBER()使用） |
| batch_incremental_updater.py | バッチ増分更新 |
| incremental_db_updater.py | 増分DB更新 |
| db_setup.py | テーブル定義・スキーマ |
| table_config.py | テーブル設定 |

## キャッシング

```python
@st.cache_data(ttl=3600)  # 1時間キャッシュ
def load_machine_detailed_results(db_path): ...
def load_daily_hall_summary(db_path): ...
```

## 実装済み改善（2026-04）

- rank_calculator.py：サブクエリ O(n²) → ROW_NUMBER() ウィンドウ関数 O(n)（SQLite 3.25.0以上必須）
- main_processor.py / incremental_db_updater.py：ランク計算と日付フラグ追加を同一 try/except に統合
