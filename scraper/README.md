# scraper/ - Phase 1 データ収集

ana-slo.com からパチスロホールのデータをスクレイピングし、JSONとして保存するフェーズ。

## 対象ファイル

| ファイル | 役割 |
|---------|------|
| `anaslo-scraper_multi.py` | メインスクレイパー（マルチホール対応） |
| `extract_and_batch_tables.py` | 旧固定URLリスト用の補助ツール（通常の機種マスター更新では使用しない） |
| `machine_master_research_url_mapper.py` | 1geki のページ索引を作り、URLと解決根拠を`machine_master.csv`へ保存する |
| `machine_master_normalizer.py` | 既知の表記揺れを正規名へ対応付け、別機種へ向いたURLを修正する |
| `fetch_rtp_via_llm.py` | マスター内のURLを読み、スペック表取得、決定的抽出、未解決項目のLLM抽出、検証、CSV更新を一括実行 |

## データフロー

```
hall_config.json       ← ホール設定（URL・名前）
        ↓
anaslo-scraper_multi.py
  1. ana-slo.com にアクセス
  2. 日付別ページを取得
  3. HTMLテーブルをパース（BeautifulSoup）
  4. 辞書形式に変換
        ↓
data/{hall_name}/{date}_{hall_name}_data.json
```

## hall_config.json の構造

```json
{
  "halls": [
    {
      "name": "ホール名",
      "url": "https://ana-slo.com/...",
      "enabled": true
    }
  ]
}
```

## 出力JSONの構造

```json
{
  "date": "2026-01-15",
  "hall_name": "ホール名",
  "all_data": [
    {"台番号": "101", "機種名": "ハナハナ", "G数": "3500", ...}
  ],
  "last_digit_data": [
    {"末尾": "1", "台数": "10", "勝率": "60.0", ...}
  ]
}
```

## 注意事項

- スクレイピング対象：`all_data_table`（個別台）と`last_digit_data_table`（末尾別集計）の2テーブル
- 機種名の正規化・フラグ判定はPhase 2で行う（Phase 1ではやらない）
- 出力先の`data/`フォルダはgitignore対象
- 1geki 系の補助バッチ出力は `scratch/1geki_batches/` に置き、root には出さない

## 機種マスターの1geki更新

標準実行では、メーカー・導入日・機種タイプ・機械割、およびノーマル/BT機のBB/RBに不足がある行を対象にする。1gekiの表を設定番号で決定的に抽出した後、残った項目と対象URL・表HTMLをLLM依頼ファイルへ出力する。

```powershell
venv\Scripts\python.exe scraper\fetch_rtp_via_llm.py --dry-run
```

出力は `scratch/machine_master_research_scrape_report.json` と `scratch/machine_master_research_llm_requests.json`。確認後に `--dry-run` を外すと、検証を通った場合だけCSVを原子的に更新する。

URL索引からマスター内の`source_url`と解決根拠も更新する場合は次を使う。

```powershell
venv\Scripts\python.exe scraper\fetch_rtp_via_llm.py --refresh-source-urls --dry-run
```

候補URLの詳細監査が必要なときだけ、次で一時JSONを明示的に出力する。通常運用ではURLマップCSV/JSONは作らない。

```powershell
venv\Scripts\python.exe scraper\machine_master_research_url_mapper.py --audit-json scratch\url_resolution_audit.json
```

1gekiのサイトマップ自体を再取得する場合は `--refresh-page-index` を指定する。Claude APIをこのコマンドから直接呼ぶ場合のみ `--llm-mode anthropic` を指定し、依存パッケージとAPIキーを用意する。通常の既定値 `batch` は外部APIなしでLLM依頼ファイルを作る。

AT初当りや汎用の「ボーナス初当り・合算」はBB/RB列へ入れず、`at_initial_setting*`、
`bonus_initial_setting*`、`bonus_combined_setting*`、`combined_initial_setting*`へ保存する。
完全攻略時の出玉率も通常出玉率と混ぜず`rtp_complete_setting*`へ保存する。4段階設定
（1/2/5/6など）は表に明記された設定番号の列だけ更新し、未搭載設定は空欄のまま保持する。

ホール由来の表記は`machine_name`に保持し、分析・結合には`canonical_machine_name`を使う。
`notes`は説明専用であり、正規名やURLの正本として扱わない。

## 自動版の実行

```powershell
venv\Scripts\python.exe scraper\anaslo_scraper_auto.py
```

開始日・終了日を省略した場合は、一覧ページから実在する最新日付を自動選択する。
明示的な期間を取得する場合は `--start-date YYYYMMDD --end-date YYYYMMDD` を指定する。

Cloudflareのチャレンジ画面が表示された場合に、画面上での手動解決を待つには次を指定する。

```powershell
venv\Scripts\python.exe scraper\anaslo_scraper_auto.py --manual-challenge
```

自動版は403、チャレンジ、空ページをデータ抽出失敗と混同せず停止する。
チャレンジの自動突破やプロキシローテーションは行わず、現行安定版と同じnodriverの同一タブを再利用する。
