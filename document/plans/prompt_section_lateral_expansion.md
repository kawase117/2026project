# Codex Prompt: セクション予測の横展開検証（蒲田1・楽園）

## 目的

蒲田7で実装済みの `predict_section.py` のセクション予測ロジックを、座標データのある他ホール（蒲田1・楽園）に横展開できるか検証する。
みとやは既に検証済みで「Top3が100%固定」という結果が出ているため、今回のスコープ外。

## ゴール

**新規スクリプト `eda/section_lateral_expansion.py` を作成**し、以下を出力する:
1. 各ホールのセクション予測 walk-forward 評価（60日分）
2. 蒲田7との比較サマリー
3. ホール横断の結論レポート (`eda/results/section_lateral_expansion/report.md`)

## データソースと結合フロー

```
DB (machine_detailed_results テーブル)
  └─ machine_number, machine_name, date, games_normalized, diff_coins_normalized
  └─ hall_name で WHERE 絞り込み

座標CSV (Heatmap/*.csv)
  └─ machine_number, floor, section, section_min, section_max, rank_from_min, rank_from_max
  └─ machine_number で DB データと INNER JOIN
```

**重要**: machine_name は DB 側にしかない。座標 CSV には存在しない。A/N 分類は DB の machine_name から行う。

## ホール別設定

### 蒲田1 (マルハンメガシティ2000-蒲田1)
- DB: `db/マルハンメガシティ2000-蒲田1.db`
- 座標CSV: `Heatmap/2F_floor_coordinates_kamata1.csv`
- CSV列: hall_name, floor, machine_number, X, Y, display_x, display_y, section, section_min, section_max, rank_from_min, rank_from_max
- **2F only**（3F座標ファイルなし）
- 台数: 360台、セクション数: 31、日数: 529日
- 注意: ミニセクション（3-4台）が複数あり（例: 1631-1633）。section_size ≤ 4 のセクションをリストアップすること
- **鉄台（特殊台番号）なし** — 蒲田7の `machine_number != 2026` フィルタは不要
- **特殊日なし** — 蒲田7の `mmdd != "0707"` フィルタは不要
- EVENT_DDS はホール固有だが、まずは蒲田7と同じ `{1, 7, 11, 17, 21, 22, 27, 31}` で検証する（同じマルハン系列のため）

### 楽園 (楽園蒲田店)
- DB: `db/楽園蒲田店.db`
- 座標CSV: 5ファイルに分散
  - `Heatmap/honkan1F_floor_coordinates_rakuen.csv`
  - `Heatmap/honkan2F_floor_coordinates_rakuen.csv`
  - `Heatmap/honkan3F_floor_coordinates_rakuen.csv`
  - `Heatmap/shinkan1F_floor_coordinates_rakuen.csv`
  - `Heatmap/shinkan2F_floor_coordinates_rakuen.csv`
- CSV列: hall_name, floor, machine_number, X, Y, display_x, display_y, section, section_min, section_max, rank_from_min, rank_from_max
- 台数: 569台、セクション数: 43、日数: 542日
- **5フロアに分散**: 本館3フロア + 新館2フロア
- 注意: 2-3台のミニセクションが多い（honkan2Fに3台×2、shinkan2Fに4台×2）
- **鉄台なし**、**特殊日なし**
- EVENT_DDS は `{1, 4, 7, 14, 17, 24, 27, 30}` を使う（みとやと同じDD軸を仮採用。楽園のイベントDD定義が未確定のため）

### 参考: 蒲田7 (比較ベースライン)
- DB: `db/マルハンメガシティ2000-蒲田7.db`
- 座標CSV: `Heatmap/2F_floor_coordinates_kamata7.csv` + `Heatmap/3F_floor_coordinates_kamata7.csv`
- 鉄台除外: `machine_number != 2026`
- 特殊日除外: `mmdd != "0707"`
- EVENT_DDS: `{1, 7, 11, 17, 21, 22, 27, 31}`

## 実装方針

`predict_section.py` の `_prepare_frame`, `_rank_sections`, `_evaluate_walkforward` のロジックを踏襲する。ただし蒲田7固有の以下を**パラメータ化**する:

1. **座標CSV読み込み**: ホールごとにCSVファイルリストを受け取る（1ファイル〜5ファイル）
2. **フィルタ条件**: 鉄台番号(None or int)、特殊日MMDD(None or str)をオプション引数化
3. **REVERSED セクション**: 蒲田7専用の REVERSED_OLD / REVERSED_NEW は蒲田1・楽園には使わない。kakuban計算では全セクション rank_from_min をデフォルトとする
4. **section_size, lr, kakuban**: 座標CSVから計算。lr は X 座標の中央値で L/R を推定（`scoring_model.py` の `_infer_lr` と同じロジック）

### classify_seg (A/N分類)
`scoring_model.py` の `classify_seg` をそのままインポートして使う:
```python
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from ml.experiments.walkforward_scoring.scoring_model import classify_seg
```
A = ジャグラー/ハナハナ/ファンキー/アイム系, N = それ以外。
**スモークテスト必須**: 各ホールで classify_seg の A/N value_counts を出力し、全件Nにならないことを確認する。

### hit_flag 定義
蒲田7と同一:
```python
payout_rate = ((games_normalized * 3 + diff_coins_normalized) / (games_normalized * 3)) * 100
hist_threshold = 104.0 if seg == "A" else 106.0
hit_flag = payout_rate >= hist_threshold
```

### walk-forward 評価パラメータ
- window_days: 90
- eval_days: 60
- top_sections_list: (1, 3, 5, 10)
- top_machines_per_section: 5
- min_games: 1000 (games_normalized >= 1000)

## 出力仕様

### ディレクトリ
`eda/results/section_lateral_expansion/`

### CSV出力

**1. hall_section_eval.csv** (全ホール・全評価日のセクション別実績)
列: hall, test_date, section, floor, section_size, section_score, section_hit_rate, section_rank, section_delta_pp

**2. hall_summary.csv** (ホール×top_k 別サマリー)
列: hall, top_k, eval_days, section_rho, section_p, section_baseline_rate, section_top_rate, section_lift, machine_baseline_rate, selected_machine_rate, selected_machine_lift, global_hist_rate, global_hist_lift

**3. mini_section_audit.csv** (section_size ≤ 4 のセクション一覧)
列: hall, section, section_min, section_max, section_size, floor, section_score_mean, section_score_std, n_eval_days

### レポート (report.md)

```markdown
# セクション予測 横展開検証レポート

## 1. データ概要
| ホール | 台数 | セクション数 | 評価日数 | フロア構成 |
(各ホールの実データから集計)

## 2. ミニセクション監査
(section_size ≤ 4 のセクションについてスコア安定性を報告)
- 各ミニセクションの score_std と出現日数
- ミニセクションを含めた場合 vs 除外した場合の rho 比較

## 3. ホール別評価サマリー
(hall_summary.csv をMarkdownテーブルで表示。蒲田7を先頭行=ベースライン)

## 4. Spearman相関の比較
(各ホールの section_rho を比較)

## 5. セクション順位の安定性
(各ホールで「60日間にTop5セクションが何回入れ替わったか」を集計)
- みとやは「Top3が100%固定」だった
- 蒲田1・楽園で同じ現象が起きていないか確認

## 6. 楽園のフロア別分析
(楽園のみ: フロア別にSpearman rho / section_lift を計算。全フロア統合 vs フロア別の比較)

## 7. 結論と推奨
- 各ホールでセクション予測に付加価値があるか（section_lift > 1.0 かつ section_rho > 0 有意）
- ミニセクションの影響度
- 楽園はフロア統合 vs フロア別どちらが良いか
- 次のステップの推奨
```

## DBデフォルト

各ホールのDBパスは以下の固定値を使うこと:
```python
HALL_CONFIGS = {
    "kamata7": {
        "db": PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db",
        "coords": [
            PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv",
            PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv",
        ],
        "exclude_machine": 2026,
        "exclude_mmdd": "0707",
        "event_dds": frozenset({1, 7, 11, 17, 21, 22, 27, 31}),
    },
    "kamata1": {
        "db": PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db",
        "coords": [
            PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv",
        ],
        "exclude_machine": None,
        "exclude_mmdd": None,
        "event_dds": frozenset({1, 7, 11, 17, 21, 22, 27, 31}),
    },
    "rakuen": {
        "db": PROJECT_ROOT / "db" / "楽園蒲田店.db",
        "coords": [
            PROJECT_ROOT / "Heatmap" / "honkan1F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "honkan2F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "honkan3F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "shinkan1F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "shinkan2F_floor_coordinates_rakuen.csv",
        ],
        "exclude_machine": None,
        "exclude_mmdd": None,
        "event_dds": frozenset({1, 4, 7, 14, 17, 24, 27, 30}),
    },
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # eda/ の1つ上 = 2026project
```

## 出力制約

- テーブル出力は `to_markdown()` を使わず、自前の簡易Markdown生成で行う
- 空セグメントやデータなし日は NaN にせずスキップする
- classify_seg のスモークテスト（各ホールの A/N value_counts 出力）を実行の冒頭に入れる
- 日付は YYYYMMDD 形式（YYYY-MM-DD ではない）。DBの date 列は TEXT型で YYYYMMDD

## 実行確認

1. `python eda/section_lateral_expansion.py --hall kamata7` でエラーなく完走すること
2. `python eda/section_lateral_expansion.py --hall kamata1` でエラーなく完走すること
3. `python eda/section_lateral_expansion.py --hall rakuen` でエラーなく完走すること
4. `python eda/section_lateral_expansion.py` で全ホール処理＋比較レポート生成されること
5. `eda/results/section_lateral_expansion/report.md` が生成され、各セクションに行が埋まっていること
6. `mini_section_audit.csv` にミニセクションが正しくリストアップされていること

## 検証したい仮説

1. **蒲田1はセクション予測が効くか**: 蒲田7と同じマルハン系列だが、2F onlyで規模が小さい。セクション間の差が蒲田7ほど出るか
2. **楽園はフロア統合で効くか**: 5フロアに分散しているため、全体でのセクションランキングは意味をなさない可能性。フロア別の方が良いか
3. **ミニセクションの影響**: section_size ≤ 4 のセクションはスコアが不安定（分散が大きい）で、ランキングを歪める可能性
4. **みとや的な固定効果**: 蒲田1や楽園でもTop3が100%固定になる「予測不要」状態が発生するか
