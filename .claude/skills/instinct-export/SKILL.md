---
name: instinct-export
description: セッションの発見のうち「将来の判断を変えるもの」だけをdocument/instincts/にYAMLで書き出す。セッション終盤に使用。読み込みはinstinct-importを使うこと。
---

# Instinct Export Skill

## まず: 書く基準

**instinct は「将来の判断を変える知識」だけ。セッションの記録ではない。**

3つすべてに Yes でなければ書かない。

1. **再来するか** — 同じ状況が今後も起きるか（1日限りの観察・特定日の答え合わせは No）
2. **判断が変わるか** — これを知らない自分と知っている自分で、取る行動が違うか
3. **他に置き場所がないか** — theory 文書・セッションログ・コードのコメントで足りないか

目安は **1セッションあたり1〜3件**。5件を超えたら基準を満たさないものが混ざっている。

2026-05〜07 の3ヶ月で1476件が書かれたが、相互参照は35件(2.4%)、
`/evolve` による自動クラスタリングは460件から0クラスタしか検出できなかった。
書きすぎると検索も蒸留も効かなくなる。

### 書かずに済ませる先

| 内容 | 置き場所 |
|---|---|
| ホール固有の運用ルール・数値 | `document/<hall>_theory.md` |
| その日やったこと・経緯 | セッションログ（`/save`） |
| 実装上の注意・落とし穴 | 該当コードのコメント、または該当スキル |
| 一過性の観察・単日の結果 | どこにも書かない（再現したら書く） |

## trigger の書き方（最重要）

**trigger は検索キーになった。** `instinct-import` は trigger を検索して
「今からやること」に該当する instinct を返す。trigger が悪いと**二度と発見されない**。

- 「**いつ**参照すべきか」を書く。何を発見したかではない
- 実際に口に出す言葉を使う。「効果なしと結論したくなったとき」「角番をDDと組み合わせるとき」
- ホール固有なら**ホール名を必ず入れる**（ホール名で絞り込みが効く）
- 固有名詞・専門語を入れる。「分析するとき」だけでは頻出語として減点される

```yaml
# 良い
trigger: "検定が帰無を棄却しなかったとき。『効果なし』『レジームなし』と結論したくなったとき"
trigger: "蒲田7のX角番（奥行き方向ランク）をDD軸と組み合わせた戦略を立案するとき"

# 悪い（検索に引っかからない）
trigger: "統計分析をするとき"
trigger: "データを確認するとき"
```

## 古い instinct を訂正するとき

**必ず `supersedes` / `invalidates` で対象を名指しする。** 書かないと古い主張は
永久に生き続ける。`compile_instincts.py` が自動で対象を閉じる。

```yaml
supersedes:
  - id: kamata7-7kei-monday-strongest-signal
    reason: data_bug
    note: 7/7周年（全台高設定日）未除外で算出された値だった
```

判定基準は `document/instincts/INSTINCT_TEMPLATE.md` の `invalidates` Rules。
「名前に rejected / corrected と付いている」だけで閉じないこと
（後続仮説の棄却であって元の主張は生きている、という例が実際にある）。

## confidence の意味

**主張の確からしさ**であって、重要度でも優先度でもない。検証途上なら低く書く。

高く盛らないこと。ACTIVE の選定は日付枠で行われるので盛っても優先されない。
むしろ自己申告 confidence は肯定的な発見に高く、それを訂正する反証に低く付きやすいため、
confidence で並べると訂正が埋もれる。

## 使い方

```
/instinct-export [filename] [--merge]
```

```
/instinct-export 2026-07-31-instinct-system-redesign
/instinct-export                     # 既定は YYYY-MM-DD-instincts.yaml
/instinct-export 2026-07-31 --merge  # 既存ファイルにマージ（id で重複検出）
```

書き出し後、注入チャンネルへ反映するには:

```bash
venv\Scripts\python.exe scripts/compile_instincts.py --sync-homunculus --force
```

## Files

- **Skill**: `instinct-export.py`
- **Output**: `document/instincts/<filename>.yaml`
- **Schema**: `references/schema.md`（instinct-import と共通の契約）
- **Template**: `document/instincts/INSTINCT_TEMPLATE.md`

---

**Created**: 2026-05-19 / **Updated**: 2026-07-31（書く基準と trigger 規約を追加）
