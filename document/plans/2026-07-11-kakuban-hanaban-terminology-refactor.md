# 角番/端番 用語分離リファクタ — 実装仕様（2026-07-11）

> Codex 実装用の権威ある仕様書。承認済みプランに基づく。日本語文字列は **一字一句そのままコピー**すること
> （翻訳・要約・「修正」禁止）。実装後 pytest は **実行しないでよい**（Claude が実行・検証する）。
> 変更はファイルへ書き込みつつ、**全ファイルの完全な unified diff も出力**すること。

## 背景と用語（確定）

「角番」が実装ごとに3つの異なる値を指していた混乱を解消し、ユーザー再定義に一致させる：

- **角番 (kakuban)** = メイン通路からの距離 = `rank_from_aisle`（通路定義のあるホールのみ＝蒲田7）
- **端番 (hanaban)** = 列の両端からの距離、1台が2つ持つ = `rank_from_min` / `rank_from_max`

### 用途別の表現（重要）
| 表示先 | 使う値 | コード列 |
|--------|--------|---------|
| クレーム別内訳バーチャート（端番） | `min(rank_from_min, rank_from_max)` 折りたたみ | `hanaban` |
| 探索ヒートマップ（DD×端番タブ）・交互作用エクスプローラ | 折りたたまず min と max を**別々の2軸** | `rank_from_min` / `rank_from_max` |
| 角番クレーム内訳・DD×角番ヒートマップ | 通路距離 | `kakuban`（=`rank_from_aisle`） |

## ⚠️ 最重要: セマンティック・スワップ

現行 `kakuban` 列 = `min(rank_from_min, rank_from_max)`。この**値**は新 `hanaban` 列へ移す。
`kakuban` 列は**新しい値** `rank_from_aisle` を持つ。
既存 registry の `kakuban_focus` は必ず **`hanaban_focus` へ改名**（値は不変）。単に kakuban のまま残さない。

---

## Phase 1a: DB マイグレーション

live DB の `machine_layout` に `rank_from_aisle` 列が無い（`db_setup.py` スキーマにはあるが未再生成）。
`database/` 配下に一回限りのマイグレーションスクリプト（例 `database/migrate_add_rank_from_aisle.py`）を作成：

- 対象 DB を走査（`db/*.db`）。各 DB で `machine_layout` に `rank_from_aisle INTEGER` 列が無ければ `ALTER TABLE` で追加。
- `Heatmap/2F_floor_coordinates_<hall>.csv` / `3F_...csv` に `rank_from_aisle` 列がある場合のみ、
  machine_number をキーに `UPDATE` で投入。蒲田1は CSV に該当列が無いため NULL のまま。
- ホール名→CSV接尾辞の対応: `蒲田7`→`kamata7`, `蒲田1`→`kamata1`（`hall_name` 部分一致で判定）。
- 冪等（再実行安全）にすること。実行は Claude が行う（スクリプト作成のみ）。

## Phase 1b: theory_engine データ層

**`dashboard/utils/theory_engine.py`**（`attach_theory_axes` 349行付近、および座標付与ブロック 245-372行付近）

現行:
```python
if config.get("kakuban_rule", "min_rank") == "min_rank":
    work["kakuban"] = pd.concat([rank_from_min, rank_from_max], axis=1).min(axis=1).astype("Int64")
```
これを次のように変更（2箇所とも: 253行付近の `prepare_layout_segments` と 364行付近の attach 内フォールバック）:
- `hanaban` 列 = `min(rank_from_min, rank_from_max)`（＝旧 kakuban の計算をこの名前へ）。
- `kakuban` 列 = `rank_from_aisle`（`config.get("has_aisle")` が真かつ `rank_from_aisle` 列が存在する場合のみ。
  それ以外は `pd.NA`）。
- `keep_columns`（352行付近のリスト）に `rank_from_aisle` と `hanaban` を追加。`rank_from_min`/`rank_from_max` は従来通り保持。
- `build_dd_kakuban_matrix(frame, *, metric, min_n)`（462行付近）を軸引数付きに一般化:
  `build_dd_position_matrix(frame, axis_column, *, metric, min_n)` を新設し、
  後方互換ラッパー `build_dd_kakuban_matrix`（axis_column=`"kakuban"`）と
  `build_dd_hanaban_matrix`（axis_column=`"hanaban"`）を残す。内部の `axis_column = "kakuban" if ...` を引数化。

## Phase 1c: hall_config

**`dashboard/config/hall_configs/kamata7.yaml`**: `kakuban_rule: min_rank` を削除し、以下を追加:
```yaml
has_aisle: true
hanaban_rule: min_rank
```
**`dashboard/config/hall_configs/kamata1.yaml`**: `kakuban_rule: min_rank` を削除し、以下を追加:
```yaml
has_aisle: false
hanaban_rule: min_rank
```
kamata1.yaml の warning「角番はスコアではなくフィルタ」の本文はそのまま（「角番」は通路角の意味で残してよい）。

---

## Phase 2: theory registry（`document/theory_registry/kamata7.yaml`）

### 2a. 既存 kakuban_focus 5件 → hanaban_focus へ改名 + title/note の「角N」→「端番N」

各クレームで `kakuban_focus:` を `hanaban_focus:` に改名（best/avoid/note の数値は不変）。
title と note 内の「角番」「角N（Nは数字）」を「端番」「端番N」に置換。
**確定 title（一字一句）:**

- `k7-2f-l-n-corner` title: `2F_L_N は端番5〜7が最強、端番1・8・9は回避`
- `k7-2f-r-n-corner` title: `2F_R_N は端番4・5・6が強い（末尾は末尾軸のp=0.400で無効のため端番のみ採用）`
- `k7-3f-l-a-corner` title: `3F_L_A は端番4〜7が最強（hit104率31%前後）、端番1〜3は回避`
- `k7-3f-l-a-dd-kakuban` title: `3F_L_A は DD1-6で端番5、DD13-24で端番8〜9、DD25-31で端番7が最強`
- `k7-3f-r-a-corner` title: `3F_R_A は端番5〜7が最強（hit104率30%前後）— 末尾軸・機種名軸より効果量が大きい`
- `k7-3f-r-a-dd-kakuban` title: `3F_R_A は DD19-24×端番9が最強セル（q=3.6e-6）`
- `k7-3f-r-n-corner-weak` title: `3F_R_N は端番5〜7で改善するが台依存の疑いが強く一般則としては弱い`

各 note 内の「角1」「角6」「全角番中」等も同様に「端番1」「端番6」「全端番中」へ置換（数値・n・p値は不変）。

### 2b. 新規: 角番(通路)クレーム5件を追加（末尾に追記）

以下をそのまま追記（Phase 0 で live frame 確定、min_games≥1000、全期間241,243行、overall avg_diff=210.9）:

```yaml
  - id: k7-2f-l-n-kakuban-aisle
    title: 2F_L_N は角番(通路)5〜8が強い、角番1は回避
    status: robust
    segment:
      floor: 2F
      lr: L
      family: N
    metric: avg_diff
    direction: up
    baseline: hall_all
    min_n: 5
    kakuban_focus:
      best: [5, 6, 7, 8]
      avoid: [1]
      note: 通路距離(rank_from_aisle)ベース。角番7=+322(n7984)・角番8=+262が強く、角番1=+28(n3483)が最弱。折りたたみ端番では端番8が弱く見えるが、通路角番では角番8が強い（折りたたみが両端を混ぜるため）。
    source: eda/reports/kamata7_kakuban_concept_experiment_report.md
    last_reviewed: 2026-07-11
  - id: k7-2f-r-n-kakuban-aisle
    title: 2F_R_N は角番(通路)4が突出、角番1は回避
    status: robust
    segment:
      floor: 2F
      lr: R
      family: N
    metric: avg_diff
    direction: up
    baseline: hall_all
    min_n: 5
    kakuban_focus:
      best: [4, 6]
      avoid: [1]
      note: 通路距離ベース。角番4=+505(n5077)が突出、角番6=+361。角番1=+54が最弱。折りたたみ端番4の+438よりさらに強い。
    source: eda/reports/kamata7_kakuban_concept_experiment_report.md
    last_reviewed: 2026-07-11
  - id: k7-3f-l-a-kakuban-aisle
    title: 3F_L_A は角番(通路)5・7・8が強い、角番1は回避
    status: robust
    segment:
      floor: 3F
      lr: L
      family: A
    metric: avg_diff
    direction: up
    baseline: hall_all
    min_n: 5
    kakuban_focus:
      best: [5, 7, 8]
      avoid: [1]
      note: 通路距離ベース。角番7=+311(n3739)・角番8=+291(n4105)・角番5=+303が強く、角番1=+47(n2128)が最弱。
    source: eda/reports/kamata7_kakuban_concept_experiment_report.md
    last_reviewed: 2026-07-11
  - id: k7-3f-r-a-kakuban-aisle
    title: 3F_R_A は角番(通路)5-6と中央島9-11が強い、角番1-2は回避
    status: robust
    segment:
      floor: 3F
      lr: R
      family: A
    metric: avg_diff
    direction: up
    baseline: hall_all
    min_n: 5
    kakuban_focus:
      best: [5, 6, 9, 10, 11]
      avoid: [1, 2]
      note: 通路距離ベース。通路寄りの角番5-6=+275/+279に加え、中央島の角番9-11が+300前後で二峰性。角番1=+62・角番2=+166が下位。折りたたみ端番では見えない中央島ピークが通路角番で顕在化。
    source: eda/reports/kamata7_kakuban_concept_experiment_report.md
    last_reviewed: 2026-07-11
  - id: k7-3f-r-n-kakuban-aisle
    title: 3F_R_N は角番(通路)7がピーク、角番1-2は赤字（台依存注意）
    status: watching
    segment:
      floor: 3F
      lr: R
      family: N
    metric: avg_diff
    direction: up
    baseline: hall_all
    min_n: 5
    kakuban_focus:
      best: [5, 6, 7]
      avoid: [1, 2]
      note: 通路距離ベース。角番7=+279(n1973)がピーク、角番1=-223・角番2=-106は赤字。ただし3F_R_Nは台依存の疑いが強くwatching維持（一般則として過信しない）。
    source: eda/reports/kamata7_kakuban_concept_experiment_report.md
    last_reviewed: 2026-07-11
```

蒲田1 registry（`kamata1.yaml`）には角番(通路)クレームを追加しない。

---

## Phase 3: セオリー検証ページ（`dashboard/pages/page_20_theory_verification.py`）

- `_claim_mask`（122行付近）: 既存 `"kakuban"` キー（`frame["kakuban"]`＝aisle）に加え `"hanaban"` キー
  （`frame["hanaban"]`）を追加。
- 内訳バーチャートを一般化: `_position_breakdown_chart(frame, claim_segment, metric, focus, axis_col, title)`
  を新設（現 `_kakuban_breakdown_chart` を土台に）。`_render_claim_block`（431行付近）で:
  - `hanaban_focus` があれば `axis_col="hanaban"`, title `端番別内訳` で描画。
  - `kakuban_focus` があれば `axis_col="kakuban"`, title `角番別内訳（通路距離）` で描画。
    ただし `frame["kakuban"]` が全NA（aisle無しホール）ならスキップ。
  - 両方持つクレームは両方描画。best/avoid の色分け（緑=best・赤=avoid・灰=その他）は現行踏襲。
- `_render_dd_kakuban_tab`（648行付近）を改修:
  - **DD×端番min**（`rank_from_min`）と **DD×端番max**（`rank_from_max`）の2ヒートマップを常に表示。
  - `has_aisle` かつ `kakuban` 非全NA のとき **DD×角番**（`kakuban`＝aisle）を追加表示。
  - `build_dd_position_matrix` を各軸で呼ぶ。軸名・タイトルを「端番min / 端番max / 角番（通路）」に。
- **用語集**（763-769行）を下記に**全面置換**（一字一句そのまま）:

```
- **角番 (kakuban)**: メイン通路からの距離でカウントする位置番号（`rank_from_aisle`）。通路が定義されたホール（蒲田7）でのみ有効。角番1=通路直近、数字が大きいほど通路から遠い。
- **端番 (hanaban)**: 列（島）の両端からの距離でカウントする位置番号。1台は min 側・max 側の2つの端番を持つ（`rank_from_min` / `rank_from_max`）。クレーム別内訳では両端の近い方に折りたたんだ値（`min(rank_from_min, rank_from_max)`、値1〜11）を使い、探索用の DD ヒートマップでは min と max を折りたたまず別々に表示する。
- **台特定シグナル**: 効果が「末尾」や「角番/端番」という一般ルールではなく、少数の特定物理台（台番号）に集中している場合の判定。上位2台を除外して再検定し、有意性が消える場合にこの判定となる。
- **可変冷却帯 / 構造冷却帯**: 全期間平均が低い「冷却ゾーン」の分類。判定基準はDD7（イベント日）での104%率リフト。可変冷却=リフト≧5pp（イベント日に通常水準まで回復、非イベント日のみ回避すればよい）。構造冷却=リフト<2pp（イベント日でも回復しない、常時回避）。
- **「最強」「最優先」「構造的に強い」などの表現について**: これらは全て「そのセグメントで対象の軸が統計的に有意（p<0.001程度）かつ耐久性検証（split-half等）を通過した」ことを指す定性的な表現であり、強さの序列を表すものではない。具体的な数値は各クレームの本文・チャートを参照すること。
```

---

## Phase 4: 交互作用エクスプローラ + 横断スクリーニング

**`dashboard/utils/interaction_analysis.py`**
- `INTERACTION_AXIS_OPTIONS`（16行付近）: 現 `"kakuban"` を削除し、`"hanaban_min"`, `"hanaban_max"`, `"kakuban"` を追加
  （最終例: `["segment", "dd", "dd_bin", "hanaban_min", "hanaban_max", "kakuban", "machine_tail", "event_day", "family"]`）。
- `axis_series`（87行付近）/ `sorted_axis_values`（108行付近）/ フォーマッタ（`dd/kakuban/machine_tail` を数値扱いする分岐）:
  - `hanaban_min` → `frame["rank_from_min"]`、`hanaban_max` → `frame["rank_from_max"]`、`kakuban` → `frame["kakuban"]`。
  - 3軸とも Int64 数値軸として扱う（既存 kakuban と同じ経路）。
**`dashboard/pages/page_11b_interaction_explorer.py`**
- `_format_axis_value`（49行付近）等の軸判定に新軸名を反映。aisle 無しホールでは `kakuban` を選択肢から除外
  （`theory.load_hall_config(hall_key).get("has_aisle")` で判定）。UI ラベルは 端番min / 端番max / 角番(通路)。
**`dashboard/pages/page_11c_axis_screening.py`**: 「角番」語や rank_from_min 依存があれば用語整合（要確認）。

## Phase 5: 前日レポート系

**`dashboard/utils/daily_report.py`** / **`page_18_daily_report.py`** / **`page_19_daily_report_visual_test.py`**
- `rank_from_min` を「角番別」とラベルしている箇所を **「端番別（min側）」** に修正（page_18:283/335,
  page_19:33/284/345 など、および「角番×セクション」→「端番×セクション」）。
- `build_kakuban_section_pivot`（daily_report.py:373）→ `build_hanaban_section_pivot` に改名し呼び出し側も追随。

## Phase 6: テスト（`test/test_kamata7_theory_dashboard.py` ほか）

- `test_attach_theory_axes_uses_hall_specific_segment_rules`: kamata1 のアサーション
  `out1["kakuban"].tolist() == [1, 2]` を **`out1["hanaban"].tolist() == [1, 2]`** に変更し、
  さらに **kamata1 で `out1["kakuban"]` が全 NA**（aisle 無し）を検証。
- kamata7 で `out7["kakuban"]` が `rank_from_aisle` と一致し `out7["hanaban"]` が min折りたたみと一致するテストを追加。
- `test_dd_kakuban_matrix_hides_sparse_cells`: 一般化後の `build_dd_hanaban_matrix`（または新シグネチャ）に追随。
- `test/test_theory_verification_baseline.py`・`test_kamata7_page_routing.py`: 影響あれば追随。
- pytest は Claude が実行するため Codex は実行不要。
