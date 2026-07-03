# Instinct YAML スキーマ(export/import共通)

`document/instincts/*.yaml`の各insightは以下のフィールドを持つ。instinct-exportが書き込み、instinct-importが読み込む、共通のデータ契約。

| フィールド | 説明 |
|---|---|
| `id` | 一意識別子(kebab-case) |
| `trigger` | この洞察が適用される場面 |
| `confidence` | 確信度スコア(0.0-1.0) |
| `domain` | 洞察のカテゴリ |
| `source` | 洞察の取得経緯 |
| `project_id` / `project_name` | プロジェクト文脈 |
| `title` | 洞察タイトル(本文見出し) |
| `background` | 背景・動機(`## 背景`) |
| `action` | トリガー発生時に取るべき行動(`## アクション`) |
| `example` | 洞察を示すコード・シナリオ例(`## 例`) |

## YAML形式例

```yaml
---
id: unique-insight-id
trigger: "when implementing X"
confidence: 0.85
domain: wiki-maintenance
source: session-observation
project_id: wiki
project_name: wiki

# Insight Title

## 背景
Context and motivation for this insight...

## アクション
What to do when this trigger is encountered...

## 例
Code or scenario demonstrating the insight...

---
```

複数のinsightは`---`区切りで1ファイルに連結できる(export側の`--merge`オプションが重複id検出とともにこれを扱う)。
