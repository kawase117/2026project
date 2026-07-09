# DD候補台ハイライト付きヒートマップ エクスポートスクリプト

## 目的

指定したDD（日付の日, 例: DD30）の過去実績に基づいて、各ホールの候補台を「平均差枚（背景色）」×「勝率（枠線）」の二軸でフロアマップ上にハイライト表示するスタンドアロンスクリプトを作成する。毎日の実戦前に実行して、候補台を視覚的に確認するために使う。

## 出力先

`Heatmap/export_dd_candidates.py`

## 使い方

```bash
python Heatmap/export_dd_candidates.py --dd 30
python Heatmap/export_dd_candidates.py --dd 30 --halls kamata7 kamata1 mitoya
python Heatmap/export_dd_candidates.py --dd 30 --halls kamata7 --output-dir tmp/
```

- `--dd` (必須): 対象のDD番号 (1-31)
- `--halls`: 対象ホール（デフォルト: kamata7, kamata1, mitoya の全3ホール）
- `--output-dir`: 出力先ディレクトリ（デフォルト: `Heatmap/exports/`）

## ホール定義

| キー | hall_name | DB パス | 座標CSV |
|------|-----------|---------|---------|
| kamata7 | マルハンメガシティ2000-蒲田7 | db/マルハンメガシティ2000-蒲田7.db | Heatmap/2F_floor_coordinates_kamata7.csv, Heatmap/3F_floor_coordinates_kamata7.csv |
| kamata1 | マルハンメガシティ2000-蒲田1 | db/マルハンメガシティ2000-蒲田1.db | Heatmap/2F_floor_coordinates_kamata1.csv |
| mitoya | みとや大森町店 | db/みとや大森町店.db | Heatmap/mitoya_omorimachi_floor_coordinates.csv |

## 処理フロー

### 1. データ集計

既存の `Heatmap/generate_kamata7_cardmap_html.py` の関数を再利用する:
- `load_machine_stats(db_path, day_of_months=[dd])` で DD指定日のみの台別統計を取得
- 戻り値の DataFrame に `avg_diff`, `win_rate`, `sample_days` 等が含まれる

### 2. 二軸カラーリング

#### 背景色 = 平均差枚（期待値の大きさ）

`avg_diff` の値に基づいて背景色を決定する。既存の decile ベース `classify_metric` / `build_tone_thresholds` は使わず、**絶対値ベースの固定閾値**を使う（DD横断で比較可能にするため）。

```
avg_diff <= -1000  → 濃い赤    (#D32F2F)
avg_diff <= -500   → 薄い赤    (#EF9A9A)
avg_diff <= 0      → グレー    (#BDBDBD)
avg_diff <= +500   → 薄い緑    (#A5D6A7)
avg_diff <= +1000  → 緑        (#4CAF50)
avg_diff <= +2000  → 濃い緑    (#2E7D32)
avg_diff >  +2000  → 金        (#FFD700)
```

#### 枠線 = 勝率（信頼度）

`win_rate` の値に基づいて枠線スタイルを決定する。

```
win_rate >= 70%  → 太い金枠   (3px solid #FFD700)
win_rate >= 50%  → 緑枠       (2px solid #4CAF50)
win_rate >= 30%  → 枠なし     (1px solid #E0E0E0)
win_rate <  30%  → 赤点線枠   (2px dashed #D32F2F)
```

### 3. カード描画

既存の `render_machine_card` をベースにするが、tone-class / games-class の代わりに上記の二軸スタイルを適用する。

各カードの表示内容:
- 台番号（メイン表示）
- 機種略称（abbreviate_machine_name で4文字に短縮）
- ツールチップ: 台番号 / 機種名 / 平均差枚 / 勝率 / 出現日数 / 平均G数

### 4. HTML生成

既存の `build_html_document` / `render_floor_section` の構造を参考に、以下を含むスタンドアロンHTMLを生成:
- タイトル: 「DD{dd} 候補台マップ — {hall_name}」
- 凡例: 背景色（差枚）と枠線（勝率）の意味
- フロアマップ: 各フロアのカードマップ
- 画像エクスポートボタン: 既存の html2canvas を使った PNG 保存機能（`Heatmap/static/html2canvas.min.js` を利用）

### 5. ファイル出力

ホール×フロアごとに1つのHTMLファイルを出力:
```
Heatmap/exports/dd30_kamata7_2F.html
Heatmap/exports/dd30_kamata7_3F.html
Heatmap/exports/dd30_kamata1_2F.html
Heatmap/exports/dd30_mitoya.html
```

## 既存コードの再利用ポイント

以下の関数・定数は `Heatmap/generate_kamata7_cardmap_html.py` からそのまま import して使う:

- `load_machine_stats(db_path, day_of_months=...)` — DD指定での集計
- `build_machine_stats(raw)` — 台別統計集計
- `filter_machine_records(raw, day_of_months=...)` — DDフィルタリング
- `load_floor_coordinates(coords_path)` — 座標CSV読み込み
- `build_floor_frame(coords_path, stats_df)` — 座標と統計のマージ
- `abbreviate_machine_name(name, max_length=4)` — 機種名短縮
- `format_filter_label(day_of_months=...)` — フィルタラベル生成
- `sanitize_filename(value)` — ファイル名のサニタイズ
- `HTML2CANVAS_PATH` — html2canvas.min.js のパス
- `HALL_CARD_CONFIG` in `heatmap_common.py` — slot_x/slot_y/pad 等のレイアウト設定
- `coordinate_utils.get_display_columns(columns)` — X/Y列名解決
- `coordinate_utils.find_floor_csvs(hall_name, project_root)` — 座標CSVの自動検出

## みとやの座標CSVについて

みとやの座標CSVは `Heatmap/mitoya_omorimachi_floor_coordinates.csv` に1ファイルのみ。`find_floor_csvs` で自動検出される。hall_name でフィルタしてから使うこと。フロア分割はない（1フロアのみ）。

## 蒲田1の除外台番号

`HALL_CARD_CONFIG` に定義済み: `exclude_machine_numbers: tuple(range(2331, 2341))`（5円スロット島）

## 実装上の注意

1. **新規ファイルは `Heatmap/export_dd_candidates.py` の1ファイルのみ**。既存ファイルは変更しない。
2. 日付フォーマットは `YYYYMMDD`（例: `20260630`）。DB内の date 列はこの形式。
3. `load_machine_stats` の `day_of_months` 引数はリストで渡す: `day_of_months=[30]`
4. `sample_days` が少ない台（例: 機種入替で3日しかない台）は信頼度が低いので、カード上に `n={sample_days}` を小さく表示するとよい。ただし除外はしない。
5. 出力ディレクトリが存在しない場合は自動作成する。
6. HTML内のCSSは既存の `build_html_document` のスタイルをベースに、二軸カラーリング用のクラスを追加する形で実装する。

## テスト

`test/heatmap/test_export_dd_candidates.py` に以下のテストを書く:
- 背景色分類関数のテスト（閾値境界値）
- 枠線分類関数のテスト（閾値境界値）
- HTML生成が例外なく完了するスモークテスト（実DBを使う）
