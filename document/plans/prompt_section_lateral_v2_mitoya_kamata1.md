# Codex Prompt: section_lateral_expansion.py にみとや追加 + 蒲田1のフィルタ強化

## 目的

既存の `eda/section_lateral_expansion.py` に2つの変更を加える:
1. **みとや大森町店**を HALL_CONFIGS に追加し、横展開検証の対象にする
2. **蒲田1**の低稼働問題に対応するため、イベント日限定評価と min_games 感度分析を追加する

## 変更1: みとや追加

### HALL_CONFIGS への追加

```python
"mitoya": HallConfig(
    label="みとや大森町店",
    db_path=PROJECT_ROOT / "db" / "みとや大森町店.db",
    coords_paths=(PROJECT_ROOT / "Heatmap" / "mitoya_omorimachi_floor_coordinates.csv",),
    exclude_machine=None,
    exclude_mmdd=None,
    event_dds=frozenset({1, 4, 7, 14, 17, 24, 27, 30}),
),
```

`HALL_ORDER` にも `"mitoya"` を**末尾に**追加すること（既存ホールの出力順を維持するため）。

### みとやCSVの列差異への対応（最重要修正）

みとやの座標CSVは他のホールと列構成が異なる:

```
hall_name, floor, machine_number, X, Y, display_y, section, section_min, section_max, rank_from_min, rank_from_max
```

**`display_x` 列が存在しない。** 現在の `_load_coords`（173行目付近）は `display_x` を必須列としてチェックしているため、みとやCSVで `ValueError` が発生する。

修正方針:
- `_load_coords` の `required` セット（177-190行目）を以下に変更する:
```python
required = {
    "floor",
    "machine_number",
    "X",
    "Y",
    "section",
    "section_min",
    "section_max",
    "rank_from_min",
    "rank_from_max",
}
```
- `hall_name` も除外する — みとやの座標CSVにhall_nameはあるが、DBの machine_detailed_results テーブルにはhall_name列が存在しないホール（みとや含む）があるため、座標CSV側のhall_nameはロジック上使われていない
- `display_x` / `display_y` の型変換行（201-202行目）もガード付きにする:
```python
if "display_x" in frame.columns:
    frame["display_x"] = pd.to_numeric(frame["display_x"], errors="coerce")
if "display_y" in frame.columns:
    frame["display_y"] = pd.to_numeric(frame["display_y"], errors="coerce")
```
- `display_x` / `display_y` はセクションスコア計算・lr推定・kakuban計算のどこにも使われていない。バリデーション専用であり除外して問題ない

### みとやのデータ仕様
- DB: `db/みとや大森町店.db`
- テーブル: `machine_detailed_results`（hall_name列なし。`load_machine_data` は hall_name を SELECT しないので問題ない）
- 座標CSV: `Heatmap/mitoya_omorimachi_floor_coordinates.csv`
- 台数: 266台、セクション数: 18、日数: 541日
- **2F only**
- 全セクション section_size ≥ 9（ミニセクションなし）
- EVENT_DDS: `{1, 4, 7, 14, 17, 24, 27, 30}`（みとや確定済み）
- **鉄台なし**、**特殊日なし**

### みとやで期待される結果
過去の検証で「Top3セクションが100%固定」と判明済み。この横展開検証でも同じ結果が出るはず。レポートの「セクション順位の安定性」セクションで、top3_unique_sets が極めて少ない（1-3程度）ことを確認する。

## 変更2: 蒲田1のフィルタ強化

蒲田1は低稼働台が多い（games_normalized < 2000 が全体の28.4%、< 3000 が41.7%）。
イベント日（EVENT_DDS該当日）のhit_rate=0.328 vs 非イベント日=0.308 で、イベント日の方が高設定投入が多い。

### 追加する分析軸

#### A. min_games 感度分析
蒲田1のみ、以下の min_games 値で walk-forward を並列実行し、section_rho と section_lift を比較する:
- min_games = 1000（現行）
- min_games = 2000
- min_games = 3000

これは蒲田1のwalk-forward評価ループ内ではなく、**蒲田1の `_load_hall_frame` を異なる min_games で3回呼び、それぞれ `_run_walkforward` する**形で実装する。

出力: `eda/results/section_lateral_expansion/kamata1_min_games_sensitivity.csv`
列: min_games, top_k, eval_days, section_rho, section_p, section_lift, machine_baseline_rate, selected_machine_rate, selected_machine_lift, n_machines_per_day_avg

#### B. イベント日限定評価
蒲田1のみ、評価日を EVENT_DDS 該当日（DD ∈ {1, 7, 11, 17, 21, 22, 27, 31}）に限定した walk-forward を追加実行する。

実装: `_run_walkforward` の `eval_dates` をフィルタする。`date_dt.dt.day.isin(cfg.event_dds)` で判定。
**注意**: 学習ウィンドウ（過去90日）はイベント日に限定しない。あくまで**評価対象日のみ**をイベント日に絞る。

出力: `eda/results/section_lateral_expansion/kamata1_event_only.csv`
列: hall_summary.csv と同じ列 + event_filter ("all" or "event_only")

### 実装の注意

- min_games 感度と event_only 評価は**蒲田1限定**。他のホールには適用しない
- メインの hall_summary.csv には蒲田1の min_games=1000（現行）の結果のみを載せる
- 感度分析は追加CSVとして出力し、レポートに新セクションを追加する
- 蒲田1以外のホールの既存結果が変わらないことを確認する

## レポート追加セクション

report.md に以下のセクションを追加:

```markdown
## 8. 蒲田1 感度分析

### 8a. min_games 感度
| min_games | top_k | section_rho | section_lift | n_machines_per_day_avg |
(kamata1_min_games_sensitivity.csv の結果)

### 8b. イベント日限定
| event_filter | top_k | section_rho | section_lift | eval_days |
(kamata1_event_only.csv の結果)

### 8c. 解釈
- min_games を上げることで section_rho が改善するか
- イベント日限定でセクション予測力が向上するか
```

## データフロー図

```
DB (machine_detailed_results)
  │  SELECT date, machine_number, machine_name, last_digit, is_zorome,
  │         games_normalized, diff_coins_normalized
  │  ※ hall_name 列は SELECT しない（みとやDBに存在しない）
  │
  ├─ games_normalized >= min_games でフィルタ
  │
  └─ machine_number で座標CSV と INNER JOIN
      │
      ├─ classify_seg(machine_name) → "A" or "N"
      ├─ payout_rate = ((gn*3 + dc) / (gn*3)) * 100
      ├─ hit_flag = payout_rate >= (104.0 if A else 106.0)
      │
      └─ walk-forward 評価
          ├─ 過去90日の section_score = mean(hit_flag) by section
          ├─ section_rank 付与
          ├─ 当日 section_hit_rate と比較
          └─ Spearman rho 計算
```

## 出力制約

- テーブル出力は `to_markdown()` を使わず、既存の `_markdown_table()` を使う
- 空セグメントやデータなし日は NaN にせずスキップする
- classify_seg のスモークテスト（各ホールの A/N value_counts 出力）を実行の冒頭に入れる（みとや追加分も含む）
- 日付は YYYYMMDD 形式
- CSV出力は `encoding="utf-8-sig"` を維持する

## DBデフォルト

`load_machine_data(cfg.db_path)` は既存の関数をそのまま使う。DBパスは `HALL_CONFIGS` の `db_path` から取得。引数は変更不要。

## 実行確認

1. `python eda/section_lateral_expansion.py --hall mitoya` でエラーなく完走すること
2. `python eda/section_lateral_expansion.py --hall kamata1` で完走し、以下が生成されること:
   - `hall_summary.csv` の蒲田1行（従来通り）
   - `kamata1_min_games_sensitivity.csv`（新規）
   - `kamata1_event_only.csv`（新規）
3. `python eda/section_lateral_expansion.py` で全4ホール処理＋レポート生成されること
4. レポートにセクション8（蒲田1感度分析）が追加されていること
5. みとやの top3_unique_sets が極めて少ない（固定効果パターン）ことが確認できること
6. 蒲田7・楽園の既存結果の行が従来と同一であること（行の追加はOK、既存行の値変更はNG）

## 変更するファイル

- `eda/section_lateral_expansion.py` のみ

## 変更しないファイル

- `ml/experiments/walkforward_scoring/` 配下は一切変更しない
- `Heatmap/` 配下のCSVは変更しない
