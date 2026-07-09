# 蒲田7: machine_dependency テスト体系化

## 目的

みとやPhase10cで確立した machine_dependency テスト（top2_share 検証 + top2除外再検定）を蒲田7の主要シグナルに体系的に適用する。蒲田7の否定仮説リストには「鉄台による偽シグナル」がアンチパターンとして記録されているが、top2_share の定量的な算出と除外再検定は末尾以外の軸で未実施。

対象:
1. 3F_L_N d8/d9（top2_machine_share=51% と既知だが除外再検定が未実施）
2. AT群×土曜の正効果（top1寄与率=2.2% と記録、構造シグナルと判定済み）
3. 角番中間台優位（top1寄与率=0.7% と記録、構造シグナルと判定済み → 再確認）
4. DD×角番の交互作用セル（Top3セルの台依存度を確認）
5. ゾロ目（台末尾ゾロ目+49）

## 前提

### 既存コード依存

- `eda/core.py`: `load_hall_df("蒲田7")`, `compute_debut_features`, `HALL_DBS`
- `eda/kamata7_debut_deep_dive.py`: セグメント分類ロジック、定数群
- 座標CSV: `Heatmap/2F_floor_coordinates_kamata7.csv`, `Heatmap/3F_floor_coordinates_kamata7.csv`

### machine_dependency テスト手順（みとやPhase10cで確立）

1. 対象グループ内の全台の avg_diff を machine_number 別に分解
2. **top2_share** = 上位2台の avg_diff 合計 / グループ全体の avg_diff 合計（abs）
3. top1 / top2 の台を除外して元の検定（KW or MWU）を再実行
4. **判定**:
   - top2_share < 20%: 構造シグナル（台依存なし）
   - top2_share 20-50%: 少数台依存（方向は安定だが注意）
   - top2_share ≥ 50%: 個体効果（シグナルではなく特定台の強さ）
5. 除外再検定で p ≥ 0.05 になれば「偽シグナル」と判定

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/kamata7_machine_dependency_audit.py` | 分析メイン |
| `ml/tests/test_kamata7_machine_dependency_audit.py` | テスト |

## 分析ステップ

### Step 1: 末尾 d8/d9 の machine_dependency — `build_step1_digit_dependency(work)`

3F_L_N セグメントで last_digit = d8/d9 の台別 avg_diff を分解。

出力（台別分解）:
```
segment | digit | machine_number | machine_name | n    | avg_diff | share_pct
3F_L_N  | d8    | 3045           | ...          | ...  | ...      | ...
3F_L_N  | d8    | 3055           | ...          | ...  | ...      | ...
...
3F_L_N  | d9    | 3049           | ...          | ...  | ...      | ...
...
```

出力（サマリ）:
```
segment | digit | top2_share | top2_machines | original_p | excluded_p | verdict
3F_L_N  | d8    | ...        | 3045,3055     | ...        | ...        | ...
3F_L_N  | d9    | ...        | 3049,3059     | ...        | ...        | ...
```

original_p は d8(or d9) vs 残り末尾の MWU p。excluded_p は top2台を除外した後の同じ MWU。

### Step 2: AT群×土曜の machine_dependency — `build_step2_saturday_dependency(work)`

N機（AT群）の土曜 vs 他曜日の diff を台別に分解。top1/top2 寄与率を算出。

出力:
```
top2_share | top2_machines | original_p | excluded_p | verdict
```

### Step 3: 角番中間台の machine_dependency — `build_step3_kakuban_dependency(work)`

全セグメントで角番5-11 vs 角番1-3 の diff 差を台別に分解。既に top1=0.7% と判定済みだが、セグメント別に再確認。

出力:
```
segment | top2_share | top2_machines | original_p | excluded_p | verdict
```

### Step 4: DD×角番 Top3 セルの machine_dependency — `build_step4_dd_kakuban_dependency(work)`

kamata7_theory.md に記載の DD×角番 Top3 セル:
- 3F_R_A: DD19-24×角9 (q=3.6e-6)
- 3F_L_N: DD7-12×角9 (q=4.8e-7)
- 2F_R: DD30×角N-1 (+880)

各セルの台別分解と top2_share を算出。

出力:
```
segment | dd_bin    | kakuban | top2_share | n_cell | original_avg_diff | excluded_avg_diff | verdict
3F_R_A  | DD19-24  | 9       | ...        | ...    | ...               | ...               | ...
...
```

### Step 5: ゾロ目の machine_dependency — `build_step5_zorome_dependency(work)`

台末尾ゾロ目（is_zorome=1）の avg_diff=+49 を台別に分解。ゾロ目桁別（00,11,22,...,99）のうち、top2_share が高い桁を特定。

出力:
```
zorome_digit | n    | avg_diff | top2_share | top2_machines | verdict
00           | ...  | +318     | ...        | ...           | ...
11           | ...  | ...      | ...        | ...           | ...
...
```

### Step 6: 統合サマリ — `build_step6_summary(all_results)`

全5軸の machine_dependency テスト結果を1テーブルに。

出力:
```
axis           | segment | target       | top2_share | original_p | excluded_p | verdict
digit_d8       | 3F_L_N  | d8           | ...        | ...        | ...        | 構造/少数台/個体
digit_d9       | 3F_L_N  | d9           | ...        | ...        | ...        | ...
saturday_at    | all_N   | sat vs other | ...        | ...        | ...        | ...
kakuban_mid    | 3F_L_A  | 5-11 vs 1-3  | ...        | ...        | ...        | ...
dd_kakuban     | 3F_R_A  | DD19-24×角9  | ...        | ...        | ...        | ...
zorome         | all     | zoro vs non  | ...        | ...        | ...        | ...
```

verdict: 構造シグナル / 少数台依存 / 個体効果

## 出力

`tmp/kamata7_machine_dependency/report.md` + 6 CSV（step1〜step6）

## 出力制約

- `to_markdown()` 禁止、自前Markdown生成
- UTF-8（BOMなし）
- DBデフォルトは `HALL_DBS["蒲田7"]`

## テスト要件

`ml/tests/test_kamata7_machine_dependency_audit.py`:

- 日付: `20250101`〜`20250301`（YYYYMMDD形式）
- machine_number: 3F_L_N エリアの台を含める（末尾8/9のゾロ目台を含む）
- games: 1500以上

```python
def test_step1_digit_top2_share(dummy_frame)
def test_step3_kakuban_per_segment(dummy_frame)
def test_step6_summary_all_axes(dummy_frame)
def test_report_creates_files(dummy_frame, tmp_path)
```

## 実行確認

```bash
python -m pytest ml/tests/test_kamata7_machine_dependency_audit.py -v
python -m eda.kamata7_machine_dependency_audit
```
