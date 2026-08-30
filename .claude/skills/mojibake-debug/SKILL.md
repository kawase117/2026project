---
name: mojibake-debug
description: Windows/PowerShell環境で日本語(機種名・ホール名)が文字化けした際の切り分け手順を定型化する。PowerShellの表示崩れをPython側のバグと誤診しないための最短ルート。
---

# Mojibake Debug Skill

## トリガー
- PowerShellやコンソール出力で日本語(機種名、ホール名)が「?」や意味不明な文字列になったとき
- 文字列比較(`==`)が見た目は同じ日本語なのに一致しないとき
- CSVやJSONの日本語列が読み込み後に別の文字に化けているとき

## 背景
2026-08-25のmirror-review(`document/mirror_evidence_2026-08-25.md`セクション4-C)で、同種のmojibakeデバッグが5セッション以上で独立に再発していることが判明した(コードギアス検索alias、report.md表示崩れ、「蒲」vs「蒼」のUnicodeコードポイント取り違え、ホール名文字列比較、spec文字列抽出)。毎回「PowerShellでmojibake発生→Pythonで直接UTF-8読み→unicode_escapeで比較→コードポイント特定→修正」という同一手順を再発明していた。

## やること(切り分けの最短ルート)

1. **まずPowerShellの表示自体を疑う**(Python/DB側のバグと決めつけない)。
   ```powershell
   chcp
   ```
   出力が`932`(Shift-JIS系)なら、コンソール表示だけが化けている可能性が高い。この場合、実データは正常な可能性がある。

2. **Pythonから直接UTF-8で読み、文字列の実体を確認する**(コンソール表示を経由しない)。
   ```python
   with open(path, encoding="utf-8") as f:
       text = f.read()
   print(repr(text[:200]))  # printでなくreprで見る。コンソール変換をバイパスできる
   ```

3. **見た目が同じ日本語が一致しない場合はコードポイントを比較する**。
   ```python
   a = "蒲田"
   b = get_value_from_db()
   print([hex(ord(c)) for c in a])
   print([hex(ord(c)) for c in b])
   ```
   「蒲」(U+8712)と「蒼」(U+84BC)のように見た目が近い異なる文字、または全角/半角・NFC/NFD正規化差異(`unicodedata.normalize("NFKC", s)`で解消できる場合が多い)を特定する。

4. **原因を特定したら、表示側(コンソール/PowerShell)の問題か、データ側(実際に別の文字が格納されている)の問題かを明記してから修正する**。表示側の問題ならコード側は修正不要(`sys.stdout.reconfigure(encoding="utf-8")`で足りることが多い)。データ側の問題ならDB/スクレイパー側の正規化ロジックを直す。

## やらないこと
- 表示が化けているだけなのに、DB/スクレイパー側のロジックを推測で書き換えない(ステップ2でPython側の実体を確認してから判断する)。
- `.ps1`スクリプトに日本語リテラルを埋め込む形での回避(プロジェクト方針として`.ps1`には日本語を書かず、Python側の定数解決やJSON設定ファイル経由で渡す。既存instinct参照)。

## 実装メモ
このスキルはコードを生成しない。切り分け手順の順序(表示疑う→実体確認→コードポイント比較→原因の層を特定)を固定化することで、毎回の再発明を防ぐための手順書として機能する。
