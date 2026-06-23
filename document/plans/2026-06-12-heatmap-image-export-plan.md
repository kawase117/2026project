# ヒートマップ／末尾ハイライト 画像エクスポート 実装計画

- 日付: 2026-06-12
- 対象: `dashboard/pages/page_17_heatmap.py`（「ヒートマップ」「末尾ハイライト」両タブ）
- 実装担当: Codex（本ドキュメントはプランニングのみ）

## 1. 目的

カード型フロアマップ（`build_html_document` が生成するHTML）の表示内容を、PNG画像としてダウンロードできるようにする。
- 対象は2タブ：①メトリクスのカード型ヒートマップ、②台末尾ハイライト
- 蒲田7（2F/3F）・蒲田1（2F）どちらも対象。フロアが複数ある場合はフロアごとにボタンを用意。

## 2. 方式の選定

| 案 | 概要 | 評価 |
|---|---|---|
| A. **html2canvas（クライアントサイド）** | 生成済みHTML内のDOMをJSでcanvasに描画し、PNGとしてダウンロード | ✅ 採用。追加のPythonライブラリ不要、既存の `components_html` 構成と相性が良い |
| B. Playwright等でサーバー側スクリーンショット | サーバー側でheadless browserを起動しHTMLをレンダリング→PNG化 | ❌ 重い依存追加・Streamlit Cloudでの実行コストが高い。却下 |
| C. Plotly再導入 | Plotly図に戻して `fig.write_image`（kaleido）でPNG化 | ❌ 今回の意図（カード型デザイン採用）と逆行。却下 |

→ **A. html2canvas** を採用。

### CDN vs ローカル同梱
- `components.html` はiframe（sandbox属性付き）でレンダリングされるため、外部CDNスクリプトの読み込みが環境によってブロックされる可能性がある。
- **推奨**: `html2canvas.min.js` をリポジトリに同梱（例: `Heatmap/static/html2canvas.min.js`）し、`build_html_document` がファイル内容を読み込んで `<script>` タグにインライン埋め込みする。
  - オフライン環境・社内ネットワークでも確実に動作する
  - sandbox の `allow-scripts` のみで動作（外部リソース読み込み許可が不要）
- CDN方式は最終手段（ネットワーク到達性に依存するため非推奨）。

## 3. 実装箇所

### 3.1 `Heatmap/generate_kamata7_cardmap_html.py`

#### (1) html2canvas の同梱・埋め込み
- `Heatmap/static/html2canvas.min.js`（MIT, 公式リリースから取得）を追加
- `build_html_document` 冒頭で読み込み、`<head>` 内に `<script>{html2canvas_js}</script>` として埋め込むヘルパー関数 `_load_html2canvas_js()` を追加
  - ファイル読み込み失敗時はエクスポートボタンを無効化（`disabled` + ツールチップ "画像エクスポート機能が利用できません"）するフォールバックも検討

#### (2) エクスポートボタンのマークアップ追加
- `render_floor_section`（ヒートマップ用）と `render_last_digit_floor_section`（ハイライト用）それぞれの `floor-head` 内に、エクスポートボタンを追加：

```html
<button class="export-png-btn" type="button"
        data-export-target="floor-map"
        data-export-filename="{escape(export_filename)}">
  📷 画像として保存
</button>
```

- `export_filename` は呼び出し側（`render_heatmap_page` / `render_last_digit_highlight`）から渡す。命名規則:
  ```
  {hall_name}_{floor}_{タブ種別}_{metric_or_filter}_{date_range}.png
  例: マルハンメガシティ2000-蒲田7_2F_heatmap_avg_diff_20260101-20260531.png
      マルハンメガシティ2000-蒲田1_2F_digit_highlight_20260101-20260531.png
  ```
  - 日本語ホール名はファイル名に使えない文字（`/` `\` `:` 等）が無いため概ね安全だが、念のため `re.sub(r'[\\/:*?"<>|]', "_", ...)` でサニタイズする関数 `sanitize_filename()` を追加

#### (3) JS: キャプチャ＆ダウンロード処理
- 既存の `<script>` IIFE（フロア切替・fitMap処理）に追記する形で実装
- 処理フロー（ボタンクリック時）:
  1. ボタンを `disabled`化 + テキストを「生成中…」に変更
  2. 対象の `.floor-map`（スケール変換前のDOM要素、固定の `width/height` を持つ）を **複製** し、画面外（`position: fixed; left: -99999px; top: 0; transform: none;`）に配置
     - 複製する理由: 表示中の `.floor-map` には `transform: scale(...)` が適用されており、html2canvasがスケールを誤って二重適用する可能性があるため、スケール1の複製をオフスクリーンでレンダリングする
  3. `document.fonts.ready` を待つ（フォント読み込み完了前のキャプチャによるレイアウト崩れを防止）
  4. `html2canvas(clone, { scale: 2, backgroundColor: '#f8fafc', useCORS: true })` を実行（`scale: 2` で高解像度PNGにする）
  5. 完了後、複製要素をDOMから削除
  6. `canvas.toBlob(blob => { ... }, 'image/png')`
  7. `URL.createObjectURL(blob)` → 一時的な `<a download="{filename}">` をクリックしてダウンロード
  8. `URL.revokeObjectURL(...)` でメモリ解放
  9. ボタンを元の状態に戻す
- ダウンロードがブロックされる場合のフォールバック:
  - try/catch で失敗した場合、`window.open(dataURL, '_blank')` で新規タブに画像を開く（ユーザーが手動保存できる）

#### (4) CSS
- `.export-png-btn`: 既存のボタン系スタイル（`.floor-tab` 等）に準拠したシンプルなボタンスタイルを追加
- 生成中表示用に `.export-png-btn.is-loading` クラス（カーソル変更・透過度など）

### 3.2 `Heatmap/heatmap_common.py`

- `render_heatmap_page`:
  - `render_floor_section` 呼び出し時に `export_filename` を生成して渡す
    - 例: `f"{hall_name}_{floor}_heatmap_{metric}_{date_start_key}-{date_end_key}.png"`
- `render_last_digit_highlight`:
  - `render_last_digit_floor_section` 呼び出し時に同様に `export_filename` を生成
    - 例: `f"{hall_name}_{floor}_digit_highlight_{date_start_key}-{date_end_key}.png"`
- `sanitize_filename()` ヘルパーを `generate_kamata7_cardmap_html.py` からimportして使用

### 3.3 `dashboard/pages/page_17_heatmap.py`

- 変更不要（ボタンはHTML内に埋め込まれるため、Streamlit側のUI追加は無し）
- ただし `components_html(html, height=1800, scrolling=True)` の `height` がボタン分のレイアウト変化に耐えるか確認（ボタンは既存の `floor-head` 内に収まる前提なので、高さへの影響は軽微）

## 4. テスト方針

ブラウザでの実画像生成はpytestでは検証できないため、**マークアップ・配線の検証**に留める。

- `test/test_kamata7_cardmap_html.py` / `test/test_kamata1_cardmap_html.py`:
  - `build_html_document` の出力に以下が含まれることを確認
    - `html2canvas` のスクリプト本体（先頭数十文字など）が埋め込まれている
    - `class="export-png-btn"` が各フロアパネルに存在する
    - `data-export-filename` 属性が想定通りの値になっている（サニタイズ後の文字列）
- `test/heatmap/test_heatmap_common_filters.py`:
  - `render_heatmap_page` / `render_last_digit_highlight` が生成するHTMLに `export-png-btn` と正しい `data-export-filename` が含まれることを確認

## 5. 既知のリスク・留意点

1. **大量カードのキャプチャ性能**: 蒲田7 3Fは366カード。`scale: 2` でのhtml2canvas実行に数秒かかる可能性あり → ローディング表示で対応。必要なら `scale: 1` にフォールバックするオプションを検討。
2. **iframeのsandbox属性**: Streamlitの `components.html` が付与する `sandbox` 属性に `allow-downloads` が含まれない場合、`<a download>` クリックが機能しない可能性がある。検証して機能しない場合は「新規タブで画像表示→右クリック保存」をデフォルト動作にする。
3. **html2canvasの日本語フォント描画**: Webフォント（Noto Sans JP等）を使っている場合、フォント読み込み完了前にキャプチャするとレイアウト崩れの可能性 → `document.fonts.ready` を待ってからキャプチャする。
4. **ライブラリの同梱・ライセンス**: html2canvas は MIT ライセンス。バイナリではなく単一JSファイルなのでリポジトリに同梱して問題なし。バージョン固定し、`Heatmap/static/` 配下に配置。

## 6. 実装ステップ（Codex向けタスク分割）

1. `Heatmap/static/html2canvas.min.js` を追加（公式リリースから取得・コミット）
2. `generate_kamata7_cardmap_html.py`:
   - `_load_html2canvas_js()`, `sanitize_filename()` 追加
   - `render_floor_section` / `render_last_digit_floor_section` に `export_filename` 引数追加 + ボタンマークアップ
   - `build_html_document` に html2canvas埋め込み + キャプチャ用JS + CSS追加
3. `heatmap_common.py`:
   - `render_heatmap_page` / `render_last_digit_highlight` で `export_filename` を生成して渡す
4. テスト追加・更新（`test/test_kamata7_cardmap_html.py`, `test/test_kamata1_cardmap_html.py`, `test/heatmap/test_heatmap_common_filters.py`）
5. Streamlitプレビューで両ホール・両タブ・複数フロアでボタン動作を目視確認
   - ダウンロードが機能するか、ファイル名が正しいか、画像内容が表示内容と一致するか
