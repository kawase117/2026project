# Instinct自動注入の仕組み調査（2026-07-27）

## 背景

2026-07-27のセッションで `document/instincts/` に3本のInstinctを新規作成したが、
セッション開始時に自動注入される6件のリストには反映されなかった。
「なぜ反映されないのか」を調査した記録。

> **2026-07-31 追記: 対応済み。**
> `compile_instincts.py` v1.3.0 に `--sync-homunculus` を実装し、下記の
> 「未解決のまま残した論点」1・3 を解消した。調査時点で未発見だった
> **注入内容そのものの破損**（末尾の追記節）も併せて修正済み。
> 本文の記述は調査当時の状態を残してある。

## 分かったこと：注入の実際の仕組み

`document/instincts/` に書いたファイルは、セッション開始時に自動で読まれる
Instinctとは**別の倉庫**にある。両者は同期していない。

```
このプロジェクトのInstinct蓄積（人が書く場所）
  document/instincts/*.yaml            … 336ファイル・1,450レコード
  → scripts/compile_instincts.py が集約
  → document/instincts/ACTIVE_INSTINCTS.md / .jsonl （人が読む一覧・上位120件）
  ★ ここまでは自動注入とは無関係。誰も自動で読んでいない。

セッション開始時に自動注入される場所（Claude Codeプラグインが読む場所）
  ~/.claude/homunculus/
  ├─ projects.json                     … リポジトリパス → プロジェクトID の対応表
  │     "257beeaeb232" = 2026project (このリポジトリ)
  ├─ instincts/personal/               … グローバル(全プロジェクト共通)・個人用。12件
  ├─ instincts/inherited/              … グローバル・空
  └─ projects/257beeaeb232/instincts/
     ├─ personal/                      … このプロジェクト専用。1件のみ
     └─ inherited/                     … このプロジェクト専用。約190件（本体）
```

注入元のコード： `everything-claude-code` プラグインの
`scripts/hooks/session-start.js` 内 `summarizeActiveInstincts()`。
以下4ディレクトリを読み、`confidence >= 0.7` のものを confidence 降順で
最大6件（`DEFAULT_MAX_INJECTED_INSTINCTS`）まで注入する。

```js
const projectDirs = observerContext.isGlobal ? [] : [
  { dir: path.join(observerContext.projectDir, 'instincts', 'personal'), scope: 'project' },
  { dir: path.join(observerContext.projectDir, 'instincts', 'inherited'), scope: 'project' },
];
const globalDirs = [
  { dir: path.join(homunculusDir, 'instincts', 'personal'), scope: 'global' },
  { dir: path.join(homunculusDir, 'instincts', 'inherited'), scope: 'global' },
];
```

- `observerContext.projectDir` は **リポジトリのパスではなく**
  `homunculus/projects/<プロジェクトID>` を指す（誤読しやすい）。
- `getHomunculusDir()` は `~/.claude/homunculus`（キャッシュ側プラグインの実装）。
  マーケットプレイス側コピー（`~/.claude/plugins/marketplaces/...`）は
  `~/.local/share/ecc-homunculus` を指すコードになっており**存在しないパス**。
  実際に動くのはキャッシュ側（`~/.claude/plugins/cache/.../2.0.0-rc.1/`）。
  調査時、最初にマーケットプレイス側を読んで誤った結論を出した。

## 分かったこと：`inherited/` は6週間前のスナップショットで止まっている

`projects/257beeaeb232/instincts/inherited/` の約190ファイルは、
ファイル名末尾に `-20260618-0807xx` 〜 `-20260618-0808xx` という
タイムスタンプが付いている。これは **2026-06-18 08:07〜08:08 に
`document/instincts/` から一括コピーされた1回きりのスナップショット**であることを示す。

その後（2026-06-18〜2026-07-27の約6週間分）に `document/instincts/` へ
追加されたInstinctは、この`inherited/`に一切反映されていない。
今回作成した3本もこのままでは注入対象にならない。

`personal/`（このプロジェクト専用）は1件のみ
（`experiment-results-structure.yaml`）で、ほぼ未使用。

## 分かったこと：confidenceが「確からしさ」と「今の関連度」を兼用している

注入の選定基準は `confidence >= 0.7` を満たすものを confidence 降順で
上位6件、という単純なものだった。

`inherited/` の190件はconfidenceが0.95〜1.00に集中しており、内容は
「daily_hall_summaryの日付列がNULL」「カバネリにS/L版がある」等の
**事実として確実だが、個別セッションの当日判断には無関係**なものが多い。

一方、今回新規作成した3本（みとやのレジーム変化・楽園の機種粒度分析の罠・
ホール推薦前の外部情報確認）はconfidence 0.75〜0.90で、事実としての確度は
高いが検証途上のものも含む。**「今日の判断に直結するが検証途上の知見」が
「確実だが無関係な古い事実」に押しのけられる**構造になっている。

confidenceを単純に上げる対応は、確実な事実と見分けがつかなくなるため
悪化させるだけで解決にならない。「確からしさ」と「鮮度・関連度」は
別軸として持つ必要があるが、テンプレート・注入ロジック両方への変更を
伴うため今回は着手していない。

## 未解決のまま残した論点（次回検討用）

1. `document/instincts/`（人が書く場所）と `homunculus/projects/.../inherited/`
   （自動注入される場所）を、どう・どのくらいの頻度で同期させるか。
   手動コピー、コミットフック、compile_instincts.py の出力先変更、など複数の
   選択肢があるが未検討。
2. confidence（確からしさ）と鮮度・関連度をテンプレート上でどう分離するか。
   `INSTINCT_TEMPLATE.md` の変更を伴う。
3. `personal/` と `inherited/` の使い分け方針が実質決まっていない
   （`personal/`はこのプロジェクトで1件しか使われていない）。
4. ~~グローバル側 `instincts/personal/`（12件、2026-05-18付・別プロジェクトの
   wiki管理知見）が、このプロジェクトの作業時にも注入候補になっている点の
   要否。~~ → **2026-07-28に対応済み**。該当3ファイル・12件
   （`2026-05-18-frontmatter-design.yaml` / `2026-05-18-tag-automation-strategy.yaml` /
   `2026-05-18-wiki-management-learnings.yaml`）を
   `~/.claude/homunculus/instincts/personal/`（グローバル）から
   `~/.claude/homunculus/projects/ea7cd5befaca/instincts/personal/`
   （wikiプロジェクト専用・project_id=ea7cd5befaca）へ移動した。
   グローバル側personalは空になった。同種の「別プロジェクトの知見が
   グローバルに紛れ込む」問題が今後も起きうるため、新規Instinctは
   最初からproject-scopedな場所に書く運用が望ましい。

## 2026-07-31 追記：注入内容そのものが壊れていた

棚卸しの過程で、凍結とは独立した二つ目の故障が見つかった。
`session-start.js` の `parseInstinctFile()` は `---` を単純トグルする状態機械で、
1ファイルに複数レコードを連結した当プロジェクトのフォーマットを読めない。

```
---
id: A          ← ここは frontmatter として読まれる
confidence: 1.0
---            ← frontmatter 終了
id: B          ← 以降すべてが「レコードAの本文」になる
```

結果、`extractInstinctAction()` が拾う「本文の先頭行」は次レコードの `id:` 行になり、
**レコードAの confidence とレコードBの id が組み合わさった行**が注入されていた。
2026-07-31 時点で実際に注入されていた6行は全て `id: <スラッグ>` という文字列で、
行動指針を一切含んでいなかった。

| 注入されていた行 | 実際の frontmatter id |
|---|---|
| `id: weekday-digit-nth-single-dim-all-null` | `daily-hall-summary-date-features-null-bug` |
| `id: juggler-104pct-threshold-meaning-by-model` | `juggler-series-bonus-probability-spec` |
| `id: banchou4-weekday-pattern-not-generalizable` | `kabaneri-s-and-l-version-distinction` |

つまり凍結を解消して同期しても、同じフォーマットで書く限り中身は無意味なままだった。

### 対応

`compile_instincts.py --sync-homunculus` を追加。プラグイン本体は
キャッシュ配下でプラグイン更新時に上書きされるためパッチせず、**書き出す側で制御**する。

- `inherited/` を「アーカイブ」ではなく **6スロットの出力チャンネル**として扱う
  （`MAX_INJECTED_INSTINCTS = 6` が上限なので、189ファイル置いても6件しか届かない）
- **1レコード1ファイル**で書き出す。連結をやめればパーサが正しく読む
- 本文に `## Action` を置く。コーパスは日本語見出し（`アクション` 約1436件 /
  `背景` 約1446件）が実態なので、そこから1行に畳んで書き出す
- ランキングは **confidence 順ではなく日付順**。自己申告 confidence は
  肯定的な発見に高く、それを訂正する反証に低く付くため、confidence でソートすると
  楽観的な主張が残って訂正が落ちる（論点2の別の現れ方）
- `document/instincts/INJECTION_PINS.txt` に id を書けば強制的に枠を確保できる

旧ファイルは削除せず退避した。

- `inherited/` 189ファイル → `inherited_archive_20260730/`
- `personal/` 5レコード（ML実験ログ・ダッシュボード実装の規約）→ `personal_archive_20260731/`
  - 分割して正しい形式に直した上で退避。confidence 0.84〜0.92 と高く、
    6枠のうち2枠を占めて直近の分析知見を押し出していたため。
    実装規約はセッション開始時に毎回想起する種類の知識ではなく、
    該当作業時に `ml-experiment-logger` スキルや CLAUDE.md から参照する方が適切

### 運用

```bash
venv\Scripts\python.exe scripts/compile_instincts.py --sync-homunculus --force
```

`--dry-run` を付けると書き込まずに注入予定の6件を確認できる。
反映は**次のセッション開始時**（`session-start.js` は起動時にしか走らない）。

## 参照

- `~/.claude/plugins/cache/everything-claude-code/everything-claude-code/2.0.0-rc.1/scripts/hooks/session-start.js`
- `~/.claude/plugins/cache/everything-claude-code/everything-claude-code/2.0.0-rc.1/scripts/lib/observer-sessions.js`
- `document/instincts/INSTINCT_TEMPLATE.md`
- `scripts/compile_instincts.py`
