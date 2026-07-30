---
name: instinct-import
description: これから着手する作業の内容でinstinctを検索して読み込む。分析・実装の着手前、結論を書く前、過去の知見を参照したい時に使用。書き込みはinstinct-exportを使うこと。
---

# Instinct Import (trigger 検索)

**やろうとしていることを一言で伝えると、それに該当する instinct を返す。**

instinct の `trigger` は「〜するとき」という形で「いつ適用されるか」を書いた
フィールドで、1475件すべてに入っている唯一のフィールド。これを検索する。

## 使い方

```bash
venv\Scripts\python.exe scripts/query_instincts.py "楽園のセクション分析"
venv\Scripts\python.exe scripts/query_instincts.py --top 15 "蒲田7の角番をDDと組み合わせる"
venv\Scripts\python.exe scripts/query_instincts.py --json "効果なしと結論したくなった"
```

| オプション | 用途 |
|---|---|
| `--top N` | 件数（既定10） |
| `--hall <name>` | ホールを明示。省略時はクエリから自動判定 |
| `--no-hall-filter` | 他ホールのレコードを減点しない |
| `--min-confidence X` | confidence 下限 |
| `--include-retired` | superseded/refuted も検索（監査用） |
| `--json` | JSON 出力 |

## クエリの書き方

**やろうとしていることを、自分の言葉で書く。** キーワードの羅列より効く。

- 良い: `"効果なしと結論したくなった"` → `null-result-requires-power-measurement` が1位
- 良い: `"バックテストの結果を確証として扱う"` → `preregistration-breaks-in-sample-self-reference` が1位
- 悪い: `"統計"` `"分析"` — 頻出語はIDFで減点されるので絞り込めない

該当が無ければ語を減らすか、trigger 側の語彙（「棄却」「帰無」「答え合わせ」など）に
寄せて言い換える。

## 使いどころ

- **分析・実装の着手前**（最も効く）。「これから何をするか」が決まった時点で引く
- **結論を書く前**。特に「効果なし」「シグナルなし」と書きそうなとき
- 他ホールの知見を流用しそうになったとき

ホール横断の共通法則はほぼ存在しないので、クエリにホール名が入っていると
他ホールのレコードは自動的に減点される。方法論・統計などホールに紐づかない
レコードは減点されない。

## セッション開始時の自動注入との違い

セッション開始時に注入される6件は**日付順**で選ばれ、その日の作業とは無関係に
決まる（仕組みは `document/instinct_injection_investigation_20260727.md`）。
関連度で引けるのはこのスキルだけなので、**着手前に必ず引くこと。**

## 全体像を俯瞰したいとき

検索ではなく一覧が要る場合は `document/instincts/ACTIVE_INSTINCTS.jsonl`（正本）
または `ACTIVE_INSTINCTS.md`（ビュー）を読む。直近枠60件＋定番枠60件の構成。
生成は `scripts/compile_instincts.py`。

## 参照

- 実装: `scripts/query_instincts.py`
- フィールド定義: `.claude/skills/instinct-export/references/schema.md`
- 書き込み: `instinct-export` スキル
