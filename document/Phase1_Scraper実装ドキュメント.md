---
source: raw/notes/PHASE_1_SCRAPER_ACTUAL_IMPLEMENTATION.md
compiled: 2026-04-06
tags: [pachinko, scraper, phase-1, web-automation, data-collection]
---

# Phase 1 (Scraper) 実装ドキュメント

**対象ファイル**: `anaslo-scraper_multi.py`
**作成日**: 2026-04-06
**目的**: Phase 1 の実装内容を正確に説明

---

## 📋 概要

Phase 1（Scraper）は、https://ana-slo.com から各パチンコホールのデータを自動で取得し、**JSON ファイルとして保存する**プロセスです。

**重要**: Phase 1 は**データの取得と HTML テーブル解析**のみを行います。機種名の正規化や機種フラグの判定は行われません。

---

## 🔄 Phase 1 のデータフロー

```
【入力】
├─ hall_config.json（ホール設定）
└─ ana-slo.com（Web サイト）

【処理】
1. ana-slo.com にアクセス
2. 日付別のホールリストページを取得
3. 各ホールのデータページを取得
4. HTML テーブルをパース
5. テーブルを辞書形式に変換

【出力】
data/{hall_name}/{date}_{hall_name}_data.json
```

---

## 🎯 主要な処理フロー

### 1. ホール名の取得と URL 正規化

**関数**: `extract_hall_name_from_url()`, `normalize_hall_name()`

URL から `hall_name` を抽出し、ファイルシステム用に正規化します。

```
例：
URL: https://ana-slo.com/2025-07-01-ザ-シティ-ベルシティ雑色店-data/

処理：
1. URL から hall_name_encoded を抽出
2. URL デコード
3. スペース → ハイフン
4. スラッシュ → ハイフン

結果: "ザ-シティ-ベルシティ雑色店"
```

### 2. HTML テーブル抽出

**関数**: `process_target_page_html()`

データページから以下の 2 つのテーブルを抽出します：

| テーブル | ID | 内容 |
|---------|-----|------|
| 全機械データ | `all_data_table` | 個別台の詳細データ |
| 末尾別集計 | `last_digit_data_table` | 末尾別の集計統計 |

### 3. テーブルのパース処理

BeautifulSoup で HTML テーブルを解析し、ヘッダーとセルを辞書形式に変換

### 4. JSON 保存

```python
json_filename = f"{date_str}_{hall_name}_data.json"
json_filepath = os.path.join(save_dir, json_filename)

with open(json_filepath, 'w', encoding='utf-8') as f:
    json.dump(extracted_data, f, ensure_ascii=False, indent=2)
```

**保存先**: `data/{hall_name}/{date}_{hall_name}_data.json`

---

## 📊 JSON に含まれるデータ構造

### JSON ファイルの形式

```json
{
  "date": "20250701",
  "hall_name": "マルハンメガシティ2000-蒲田7",
  "all_data": [
    {
      "機種名": "ジャグラーV",
      "台番号": "101",
      "G数": "5500",
      "差枚": "2500",
      "BB": "8",
      "RB": "12",
      "合成確率": "1/180.5",
      "BB確率": "1/290.2",
      "RB確率": "1/520.8"
    }
  ],
  "last_digit_data": []
}
```

**重要**: すべてのカラムが**TEXT 型**です。型変換は行われません。

---

## ✅ Phase 1 で実装されていること / いないこと

### 実装されている処理

| 処理 | 詳細 |
|------|------|
| Web スクレイピング | nodriver + BeautifulSoup で HTML 取得・解析 |
| ホール名の抽出 | URL から hall_name を抽出 |
| ホール名の正規化 | スペース / スラッシュをハイフンに変換 |
| HTML テーブルパース | ID で特定して抽出 |
| 辞書形式への変換 | ヘッダーとセルから key-value に変換 |
| JSON 保存 | `data/{hall_name}/` に保存 |

### 実装されていない処理

| 処理 | 理由 |
|------|------|
| 機種名の正規化 | スクレイピングしたそのままの値を使用 |
| 機種フラグの判定 | jug_flag, hana_flag などは付与されない |
| 型の変換 | すべて TEXT/STRING 型のまま保存 |
| 数値のパース | "5500" のまま（int に変換されない） |

---

## 📝 重要な注意点

### データの生のままの形式

JSON に保存されるデータはスクレイピング結果そのままです。

- 機種名：スクレイパーで取得したそのままの文字列
- 数値（G数、差枚）：文字列形式（カンマ付きの可能性もあり）
- 確率：分数形式の文字列

### Phase 2 での処理待ち

以下の処理は [[Phase2_Database全体アーキテクチャ]] で行われます：

- 機種名の正規化
- 機種フラグの判定（jug, hana, oki, bt）
- 数値型への変換
- データベース投入と集計

---

## 📂 出力ディレクトリ構造

```
data/
├── マルハンメガシティ2000-蒲田7/
│   ├── 20250701_マルハンメガシティ2000-蒲田7_data.json
│   ├── 20250702_マルハンメガシティ2000-蒲田7_data.json
│   └── ...（日付別に保存）
└── ...（各ホール）
```

**ファイル命名規則**: `{YYYYMMDD}_{hall_name}_data.json`

---

## 🎯 Phase 1 の責務

### Phase 1（Scraper）が行うこと
✅ Web からのデータ取得
✅ HTML テーブル抽出
✅ JSON への構造化保存

### Phase 1（Scraper）が行わないこと
❌ 機種名の正規化
❌ 機種フラグの判定
❌ 数値型への変換
❌ データベースへの本格的な投入と集計

