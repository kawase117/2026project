# scraper/ - Phase 1 データ収集

ana-slo.com からパチスロホールのデータをスクレイピングし、JSONとして保存するフェーズ。

## 対象ファイル

| ファイル | 役割 |
|---------|------|
| `anaslo-scraper_multi.py` | メインスクレイパー（マルチホール対応） |

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
