# みとや大森町 解析プロンプト集（Codex向け）

> **目的**: 手順書 `document/plans/hall-analysis-procedure.md` の Phase 3残り → Phase 4 → Phase 5 を順に実行する。
> **作成日**: 2026-06-27
> **使い方**: 各プロンプトを1つずつCodexに投入する。前のタスクの出力ファイルが次のタスクの入力になる箇所がある。

---

## Prompt 1: Phase 3 残り — 末尾・曜日・ゾロ目・debut のセグメント別KW検定

```
# タスク: みとや大森町 変数スクリーニング（Phase 3 残り4変数）

## 目的
みとや大森町のセグメント(section)別に、以下4変数のKruskal-Wallis検定を実施し、
有意な変数リストを作成する。

## 対象変数
1. **台番号末尾 (last_digit)**: 0-9の10群でKW検定
2. **曜日 (day_of_week)**: 月-日の7群でKW検定
3. **ゾロ目 (is_zorome)**: 台番号末尾2桁一致（is_zorome列）でMann-Whitney検定
4. **debut phase**: 新台初日からの経過日数を3フェーズ（1-30日/31-90日/91日+）に分割してKW検定

## 既存インフラ
- `eda/core.py` の `load_hall_df("みとや")` でデータ取得。MIN_GAMES=400で自動フィルタ済み。
- `eda/core.py` の `_epsilon_squared()` で効果量計算。
- DB: `db/みとや大森町店.db` — load_hall_df が自動解決するので直接指定不要。
- section列: DB の `machine_layout` テーブルから取得（後述のデータフロー参照）。

## ⚠️ load_hall_df の返却列名（重要）
load_hall_df は SQL の AS で列名をリネームして返す。DB本来の列名とは異なる:
| DB列名 (machine_detailed_results) | load_hall_df の返却列名 | 型 |
|-----------------------------------|------------------------|-----|
| diff_coins_normalized | **diff** | int |
| games_normalized | **games** | int |
| last_digit | **machine_digit** | TEXT ("0"-"9") |
| is_zorome | **machine_zorome** | int (0/1) |
| machine_number | machine_number | int |
| machine_name | machine_name | TEXT |
| date | date | TEXT (YYYYMMDD) |

スクリプト内では必ず `df["diff"]`, `df["machine_digit"]`, `df["machine_zorome"]` を使うこと。
`df["diff_coins_normalized"]` や `df["last_digit"]` は KeyError になる。
load_hall_df が追加計算する列: plus, dd, dd_mod10, day_of_week, is_x_day, is_weekend, is_any_event, hall 等。

## セグメント（section）一覧
以下の10 sectionが存在する:
| section | 台数 | 備考 |
|---------|------|------|
| 501-522 | 22 | 片面島 |
| 523-556 | 34 | 両面島 |
| 557-590 | 34 | 両面島 |
| 591-623 | 33 | 両面島 |
| 624-657 | 34 | 両面島 |
| 658-691 | 34 | 両面島 |
| 692-711 | 20 | バラエティ |
| 712-733 | 22 | バラエティ |
| 734-755 | 22 | バラエティ |
| 805-815 | 11 | 片面島 |

## データフロー
1. `load_hall_df("みとや")` → df（日付フィーチャー計算済み: day_of_week, dd, is_x_day等）
   - 差枚列は `df["diff"]`、末尾は `df["machine_digit"]`、ゾロ目は `df["machine_zorome"]`
2. section の取得: DB の `machine_layout` テーブルから読み込む
   ```python
   conn = sqlite3.connect(str(Path(__file__).resolve().parent.parent / "db" / "みとや大森町店.db"))
   ml = pd.read_sql_query("SELECT machine_number, section FROM machine_layout", conn)
   conn.close()
   ```
3. df と ml を `machine_number` で LEFT JOIN → section列付与
4. **machine_name は df 側にある。machine_layout にはない。**
5. 日付フォーマット: YYYYMMDD（例: 20260101）

## debut phase の計算方法
- df の各 machine_number ごとに、machine_name が変わった日を「その機種の debut_date」とする
- debut_days = (date - debut_date).days
- phase分類: debut(1-30), growth(31-90), mature(91+)
- debut_date 不明の台（データ開始時から存在）は **pre_existing** として独立カテゴリにする
  （mature と混ぜない。pre_existing は検定に含めるが、解釈時に「開始前から存在」と注記する）
- date 列は YYYYMMDD 文字列 → pd.to_datetime(df['date'], format='%Y%m%d') で変換

## is_zorome（台番号ゾロ目）
- load_hall_df が `machine_zorome` 列として返す（DB の is_zorome 列のリネーム）
- スクリプト内では `df["machine_zorome"]` を使うこと。自前計算は不要。

## 出力ファイル
`eda/results/mitoya_phase3_screening.md`

## 出力フォーマット
各変数×各section の結果を以下の形式で出力:

### 例
```
## 1. 台番号末尾 (last_digit)

| section | KW_stat | p_value | epsilon_sq | n | 判定 |
|---------|---------|---------|------------|---|------|
| 501-522 | 12.34 | 0.0031 | 0.0045 | 2750 | ◎有望 |
...

### 有望な末尾の詳細（p<0.01のsectionのみ）
section 501-522:
| machine_digit | n | mean_diff | plus_rate |
|---------------|---|-----------|-----------|
| 0 | 280 | +125 | 55.2% |
...
```

## 判定基準
- p < 0.01: ◎有望 → Phase 4検証へ
- 0.01 <= p < 0.05: △要注意 → epsilon_sq も確認
- p >= 0.05: ✗脱落

## 実装制約
- テーブル出力は to_markdown() を使わず、f-string で自前Markdown生成すること
- 空セグメントが生じた場合はスキップすること（NaN回避）
- ゾロ目台が0台のsectionはスキップ
- debut計算で machine_name の変更検出は date 昇順ソート後に shift() で検出
- 出力ファイルの末尾に「Phase 4 検証対象リスト」として
  有望判定の (変数, section) ペアをまとめること
- sys.path: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`
  を先頭に入れて eda/core.py をインポートすること

## 実行確認
python eda/mitoya_phase3_screening.py
エラーなく eda/results/mitoya_phase3_screening.md が生成されること。
```

---

## Prompt 2: Phase 4 — 有意変数の耐久性検証

```
# タスク: みとや大森町 耐久性検証（Phase 4）

## 目的
Prompt 1 の mitoya_phase3_screening.py と同じデータ・同じ条件で再計算し、
p<0.01 の (変数, section) ペアに対して3テスト耐久性検証を実施する。

## 前提
- Prompt 1 のスクリプト eda/mitoya_phase3_screening.py が実行済みであること
- ただし出力 .md をパースするのではなく、同じ計算を再実行して p<0.01 を自動検出

## 3テスト検証

### テスト1: Split-half（前半/後半）
- データを日付の中央値で前半/後半に分割
- 各半分で同じKW検定（or MW検定）を実施
- **判定**: 両半分で効果の方向（上位群/下位群の顔ぶれ）が一致するか
  - カテゴリ変数（last_digit, day_of_week, debut_phase）: 上位3群の顔ぶれが2/3以上一致でPASS
  - 2値変数（is_zorome）: 平均diffの符号が同じならPASS

### テスト2: 鉄台除外
- 鉄台 = そのsection内で pos_rate >= 60% の machine_number
  - pos_rate = (df["diff"] > 0 の日数) / (全日数)  ← 列名は "diff"
  - 台ごとに計算
- 鉄台を除外して再検定
- **判定**: 除外後も p<0.05 なら PASS

### テスト3: top2_share（台固有性）
- section内の各machine_numberの平均diff（= df["diff"]）を計算
- top2_share = 上位2台の mean_diff 合計 / 全台の mean_diff 絶対値合計
  - 分母が0に近い場合（|全台合計| < 100）: top2_share = NaN → SKIP判定
- **判定**: <10% PASS, 10-30% WARN, >30% FAIL

## データフロー
Prompt 1 と同じ。列名の注意点も同一:
1. `load_hall_df("みとや")` → df
   - 差枚: `df["diff"]` (not diff_coins_normalized)
   - 末尾: `df["machine_digit"]` (not last_digit)
   - ゾロ目: `df["machine_zorome"]` (not is_zorome)
   - プラス判定: `df["plus"]` (= diff > 0)
2. machine_layout テーブルから section 取得 → machine_number で LEFT JOIN
3. debut phase / is_zorome も Prompt 1 と同じ計算
4. 日付: YYYYMMDD文字列 → pd.to_datetime(format='%Y%m%d')

## 出力ファイル
`eda/results/mitoya_phase4_durability.md`

## 出力フォーマット
```
# みとや大森町 Phase 4: 耐久性検証

## サマリ
| 変数 | section | 元p値 | split_half | 鉄台除外 | top2_share | 総合判定 |
|------|---------|-------|------------|---------|------------|---------|
| last_digit | 501-522 | 0.003 | PASS | PASS | 8.2%(PASS) | ✅堅牢 |
| day_of_week | 557-590 | 0.008 | FAIL | PASS | 15%(WARN) | ⚠️脆弱 |

## 総合判定基準
- ✅堅牢: 3テスト全PASS（WARNは許容）
- ⚠️脆弱: 1テストFAIL
- ❌却下: 2テスト以上FAIL

## 詳細（以下、各ペアごとに）
（各テストの具体的な数値・台番号リスト等を記載）
```

## 実装制約
- to_markdown() 禁止。f-string で自前生成。
- 空セグメント・検定不能（n<3群 or 1群のn<2）はスキップ。
- Phase 3 で p<0.01 だったペアが0件の場合、
  p<0.05 に緩和して再検出し、その旨をレポート先頭に記載する。
- sys.path: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`

## 実行確認
python eda/mitoya_phase4_durability.py
エラーなく eda/results/mitoya_phase4_durability.md が生成されること。
```

---

## Prompt 3: Phase 5a — 曜日パターンとDD×角番交互作用

```
# タスク: みとや大森町 ホール固有法則探索（Phase 5a）

## 目的
Phase 4 で「堅牢」と判定された変数を軸に、
曜日パターン・DD×角番・末尾×section の交互作用を分析する。

## 分析内容

### 5a-1: 曜日別プロファイル
- 曜日（月〜日）× section別の平均payout(%)、平均diff、104%率を集計
- **全日版**と**イベント日除外版**の2テーブルを出力
  - イベント日(is_x_day=1)が特定曜日に偏ると交絡するため
- 各sectionで「最強曜日」「最弱曜日」を明示

### 5a-2: DD × 角番(rank_from_aisle) 交互作用
- rank_from_aisle を3バケット:
  - 各sectionの rank_from_aisle 最大値を3等分して境界を動的決定
  - 例: 最大11 → 角(1-3), 中間(4-7), 奥(8-11)
- DD を5バケット: DD1-6, DD7-12, DD13-18, DD19-24, DD25-31
- (DDバケット × 角番バケット) のセル別 平均diff と n を出力
- 全section合算 + section別の2レベル

### 5a-3: 末尾 × section 交互作用
- Phase 4 で末尾(last_digit)が「堅牢」だったsectionのみ対象
  - 堅牢sectionが0件なら「脆弱」も含めて実施し、その旨記載
- 対象section の末尾別(0-9) 平均diff ランキング
- 上位末尾と下位末尾の差が section 間で逆転するか確認

## データフロー
1. `load_hall_df("みとや")` → df
   - 列名注意: diff, machine_digit, machine_zorome（Prompt 1 参照）
2. `machine_layout` テーブルから section, rank_from_aisle, rank_from_min, rank_from_max を取得:
   ```python
   conn = sqlite3.connect(str(Path(__file__).resolve().parent.parent / "db" / "みとや大森町店.db"))
   ml = pd.read_sql_query("""
       SELECT machine_number, section, rank_from_aisle, rank_from_min, rank_from_max
       FROM machine_layout
   """, conn)
   conn.close()
   ```
   - rank_from_aisle は machine_layout に格納済み（hall_config.json の reversed_sections から生成済み）
   - **machine_detailed_results には rank_from_aisle はない。machine_layout が正。**
   - フォールバック計算は不要。
3. df と ml を machine_number で LEFT JOIN

## 出力ファイル
- `eda/results/mitoya_phase5a_weekday.md` — 曜日プロファイル
- `eda/results/mitoya_phase5a_interactions.md` — DD×角番 + 末尾×section
- `eda/results/mitoya_dd_kakuban_heatmap.csv` — DD×角番ヒートマップ用CSV
  - 列: dd_bucket, kakuban_bucket, mean_diff, n, section(全体合算は"ALL")

## 実装制約
- to_markdown() 禁止
- 空セル（n<3）はスキップ、NaN出力禁止
- 日付: YYYYMMDD文字列
- sys.path: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`

## 実行確認
python eda/mitoya_phase5a_analysis.py
エラーなく3ファイルが生成されること。
```

---

## Prompt 4: Phase 5b — mitoya_theory.md 作成

```
# タスク: みとや大森町 theory.md 作成（Phase 5b）

## 目的
Phase 3-5a の分析結果を統合し、蒲田7の kamata7_theory.md と同じ構成で
みとや固有の法則ドキュメントを作成する。

## 入力ファイル（必ず全て読むこと）
1. `eda/results/mitoya_phase3_screening.md` — 変数スクリーニング結果
2. `eda/results/mitoya_phase4_durability.md` — 耐久性検証結果
3. `eda/results/mitoya_phase5a_weekday.md` — 曜日プロファイル
4. `eda/results/mitoya_phase5a_interactions.md` — 交互作用分析
5. `document/kamata7_theory.md` — **構成の参照用（内容は移植しない）**

## 出力ファイル
`document/mitoya_theory.md`

## 構成（kamata7_theory.md に準拠）
1. **ホール概要**: 台数・セクション数・データ期間・min_games
   - **台数・日数はDBから再計算すること（固定値を書かない）**:
     ```python
     conn = sqlite3.connect(str(Path(__file__).resolve().parent.parent / "db" / "みとや大森町店.db"))
     n_machines = pd.read_sql("SELECT COUNT(DISTINCT machine_number) FROM machine_layout", conn).iloc[0,0]
     n_days = pd.read_sql("SELECT COUNT(DISTINCT date) FROM machine_detailed_results", conn).iloc[0,0]
     date_range = pd.read_sql("SELECT MIN(date), MAX(date) FROM machine_detailed_results", conn).iloc[0]
     conn.close()
     ```
2. **セグメント構造**: 10 section の台番号範囲・台数・A群/N群分類
   - A群/N群の判定: DB の `machine_master` テーブルの `jug_flag` / `hana_flag` を使用
     ```python
     # 各section × 最新日の machine_name → machine_master JOIN で jug_flag/hana_flag 取得
     # jug_flag=1 OR hana_flag=1 → A群、それ以外 → N群
     mm = pd.read_sql("SELECT machine_name, jug_flag, hana_flag FROM machine_master", conn)
     ```
   - 参考実装: `ml/corner_section/mitoya_aisle_distance_analysis.py` の JOIN パターン
3. **変数の効果と限界**:
   - 角番: rank_from_aisle の効果、有効な角番位置
   - 末尾: section別の有効末尾（Phase 4で堅牢なもののみ）
   - DD: イベント日 DD{4,7,14,17,24,27} の効果（確定済み知見を引用）
   - 曜日: みとや固有の曜日パターン（イベント日交絡除外後）
   - ゾロ目: 台番号ゾロ目の効果
   - debut: 新台効果（debut/growth/mature/pre_existing の4フェーズ）
4. **否定された仮説**: Phase 4 で「❌却下」された変数×section
5. **台選びフロー**: イベント日/通常日に分けた意思決定ツリー
6. **蒲田7との差異**: 明確に異なる点のリスト
7. **Instinct参照マップ**: 関連する instinct id の一覧

## 制約
- Phase 4 で「❌却下」された変数×section を「有効」として記載しないこと
- 数値は全てPhase 3-5a の出力ファイルから引用し、独自計算しないこと
- **台数・日数等の基本統計量は固定値ではなくDBから当日再計算**
- 「蒲田7では○○だが、みとやでは△△」の対比形式で差異を書くこと
- 仮説の強度を明示: confirmed(堅牢) / tentative(脆弱) / refuted(却下)
- ファイルエンコーディング: UTF-8（BOMなし）
```

---

## 投入順序と依存関係

```
Prompt 1 (Phase 3)
  ↓ 出力: mitoya_phase3_screening.md
Prompt 2 (Phase 4) ← Prompt 1 と同じ計算を再実行
  ↓ 出力: mitoya_phase4_durability.md
Prompt 3 (Phase 5a) ← Phase 4 の堅牢/脆弱判定を参照
  ↓ 出力: mitoya_phase5a_weekday.md, mitoya_phase5a_interactions.md
Prompt 4 (Phase 5b) ← 上記3つの .md を全て読んで統合
  ↓ 出力: mitoya_theory.md
```

## Codex地雷回避チェックリスト
- [ ] **列名**: diff (not diff_coins_normalized), machine_digit (not last_digit), machine_zorome (not is_zorome)
- [ ] **section**: machine_layout テーブルから取得（座標CSVではない）
- [ ] **rank_from_aisle**: machine_layout テーブルに格納済み（machine_detailed_results にはない）
- [ ] **A/N分類**: machine_master の jug_flag/hana_flag で判定
- [ ] **固定値禁止**: 台数・日数等はDBから再計算
- [ ] **debut pre_existing**: データ開始前から存在する台は mature と混ぜず独立カテゴリ
- [ ] **top2_share分母ゼロ**: |全台合計| < 100 のときは SKIP
- [ ] DBパス: load_hall_df が自動解決。直接パス指定不要
- [ ] to_markdown() 禁止 → f-string で自前生成
- [ ] 空セグメントのNaN → スキップ処理
- [ ] 日付フォーマット: YYYYMMDD（ハイフンなし）
- [ ] machine_name は DB側にある（machine_layout にはない）
- [ ] sys.path 設定を明示
- [ ] ファイルエンコーディング: UTF-8（BOMなし）
