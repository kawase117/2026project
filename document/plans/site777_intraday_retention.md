# site777 途中経過の保管計画（統合は後回し、保管だけ先に）

対象: 楽園蒲田店（site777 = d-deltanet, `pmc=22021006` / `urt=2173`）のみ。

## この計画がやらないこと

- 予測モデルへの統合。当日中データを特徴量に入れる設計は本計画の範囲外とする。
- グラフ画像・OCR経路（587台=920アクセス・約94分）への変更。コストが桁違いなので触らない。
- 収集頻度・巡回設計の変更。**書き出し先を増やすだけの片側変更**にする。

## なぜ今やるか

統合を後回しにしてよい理由（データ量・実装コスト）と、保管を後回しにできない理由は別である。

- 途中経過は**後から取り直せない**。今日の 14:00 時点の RB 回数は、明日には存在しない。
- 統合を半年後に決めた場合、保管していれば半年分の履歴が既にある。していなければゼロから半年待つ。
- 追加の取得アクセスはゼロ。既に取得済みの `site777_full_data.json` を捨てずに書くだけ。

## 既に取れているもの（調査結果 2026-09-09）

`scraper/site777/output/site777_full_data.json`（286KB, version 5）の構造:

```
{ version, priorSnapshotId, startedAt, updatedAt, completedAt, complete,
  expectedModelCount: 119, expectedMachineCount: 587,
  models: { <mdc>: {
      name, machineCount, mdc, href,
      jackpot: { updateTime: "2026/08/30 18:55",
                 pages: [ { rows: [["台番","累計ゲーム","BB回数","RB回数","ART回数"],
                                   ["3193","1728","0","3","11"], ... ] } ] },
      highest: { updateTime, pages: [ { rows: [["台番","当日","前日","2日前","3日前"], ...] } ] }
  } },
  accessLog: [...], restrictionEvents: [], failures: [] }
```

**`BB回数` / `RB回数` / `累計ゲーム` が時点付きで取れている。** これは本プロジェクトが
「差枚ではなくボーナス確率で設定を判定する」（`backtest/bonus_rate.py`）としている指標そのものを、
確定値ではなく当日の途中で観測したものにあたる。

さらに `output/history/` に **57スナップショットが現存**（`20260814-233026` 〜 `20260830-184351`、計17MB）。
これは `-before-parallel-run` のバックアップとして偶発的に残ったもので、
**バックフィル可能な既存資産**である。

## 保管先

新規ファイル `db/site777_intraday.db` を作る。既存のホールDBには**書かない**。

理由: 統合しないと決めた以上、既存DBに列やテーブルが増えると、
`machine_layout` を60ファイルが単純結合していたときと同種の事故（意図しない参照・二重計上）を招く。
分離しておけば、統合しないと判断した場合に**ファイルごと捨てられる**。

### スキーマ

```sql
CREATE TABLE site777_snapshots (
    snapshot_id    TEXT PRIMARY KEY,   -- ソースの updateTime を正規化した "YYYYMMDDHHMM"
    hall_name      TEXT NOT NULL,      -- '楽園蒲田店'
    business_date  TEXT NOT NULL,      -- YYYYMMDD（下記の営業日規則）
    update_time    TEXT NOT NULL,      -- サイト側の "2026/08/30 18:55" 原文
    collected_at   TEXT NOT NULL,      -- こちらの取得時刻（ISO8601 JST）
    source_file    TEXT NOT NULL,      -- 由来した json のパス
    model_count    INTEGER,
    machine_count  INTEGER,
    complete       INTEGER NOT NULL,   -- 元 json の complete
    failures       INTEGER NOT NULL    -- len(failures)
);

CREATE TABLE site777_machine_snapshots (
    snapshot_id     TEXT NOT NULL REFERENCES site777_snapshots(snapshot_id),
    machine_number  INTEGER NOT NULL,
    machine_name    TEXT,
    mdc             TEXT,
    games           INTEGER,   -- 累計ゲーム
    bb              INTEGER,   -- BB回数
    rb              INTEGER,   -- RB回数
    art             INTEGER,   -- ART回数
    highest_today   INTEGER,   -- highest表の「当日」
    PRIMARY KEY (snapshot_id, machine_number)
);

CREATE INDEX idx_s777_machine_date
    ON site777_machine_snapshots(machine_number, snapshot_id);
```

### 重複排除の鍵は「サイト側の updateTime」であって取得時刻ではない

サイトの更新は約90分間隔（`site777_update_gate_history.jsonl` より
`16:25 → 17:55 → 翌12:25`）。その間に2回取りに行けば**同一データが2件入る**。
`snapshot_id` をサイト側 `updateTime` から作り `INSERT OR IGNORE` にすれば、
取得回数に関係なく1時点1行になる。

`models[].jackpot.updateTime` は機種ごとに持つが、実測では機種間で一致している。
**一致しない場合はスナップショットを分割せず、最頻値を代表値とし、
ズレた機種の行に `update_time` の実値を別途持たせるのではなく捨てる**
（時点の異なるデータを1スナップショットに混ぜるほうが害が大きいため）。
ズレの発生率は導入後1週間で計測し、無視できなければ設計を見直す。

### 営業日の規則

`resolve_dates.py` の `RULE_CUTOFF_HOUR = 8` に合わせる。
`updateTime` の時刻が 08:00 未満なら前日を `business_date` とし、それ以外は当日とする。
site777 の更新は営業時間中（12:25〜17:55 の実績）なので通常は当日に落ちるが、
規則を他モジュールと揃えておく。

## 実装

### 1. `scraper/site777/site777_snapshot_store.py`（新規）

```
ingest(json_path, db_path) -> (snapshot_id, inserted_rows, skipped_reason|None)
```

- `utf-8-sig` で読む（既存 json に BOM がある。`site777_graph_summary.json` で確認済み）。
- `complete == False` または `failures` が非空のスナップショットは、
  `site777_snapshots` に記録した上で `site777_machine_snapshots` を**入れない**
  （部分取得を全台取得と誤認させない）。
- `rows` の先頭行はヘッダ、末尾の `"平均"` 行は台データではないので除外する。
- 台番は `int()` 変換に失敗したら行ごとスキップし、件数を返り値に含める。

### 2. 収集スクリプトからの呼び出し

`run_site777_full_collect_parallel.ps1` の完走直後（`site777_full_data.json` 書き出し後）に
1行足して `ingest` を呼ぶ。失敗しても収集自体は成功扱いのままにする
（保管は副作用であって、これで収集を落とさない）。

### 3. 既存57スナップショットのバックフィル

```
python scraper/site777/site777_snapshot_store.py backfill --history-dir scraper/site777/output/history
```

`output/history/*/site777_full_data.json` を順に `ingest` する。
`snapshot_id` が重複するものは自然に無視される。
8/14〜8/30 の 57 件から、実際に何時点分が復元できるかを最初に報告する
（同一 `updateTime` の重複が多ければ、実質の時点数は57より少ない）。

### 4. `.gitignore`

`db/site777_intraday.db` を追加する。DBはコミットしない。

## 容量の見積り

587台 × 1日あたり時点数 × 365日。

| 1日の時点数 | 年間行数 | 概算サイズ |
|---|---:|---:|
| 4 | 86万 | 約50MB |
| 8 | 171万 | 約100MB |
| 12 | 257万 | 約150MB |

現行 `pachinko_data.db` が68MB。**同オーダーであり、「莫大」なのはグラフ/OCR経路の側**
（587台=920アクセス・94分・画像1.5MB分のOCR）であって、表データの保管ではない。
本計画は表データのみを対象とする。

## 完了条件

1. `db/site777_intraday.db` が生成され、既存57スナップショットのバックフィルが通る。
2. 通常の収集run 1回で1スナップショットが増える。
3. 同一 `updateTime` に対して2回 `ingest` しても行数が増えない（冪等）。
4. 既存の収集・分析出力（`site777_report.md` 等）が一切変わらない。
5. `test/` に (3) の冪等性と、`complete=False` を取り込まないことのテストを置く。

## 統合を検討する時期の判断材料

保管を始めてから、以下が揃った時点で統合を再検討する。

- 1台あたり1日3時点以上が、60営業日以上たまっている。
- 朝〜昼の時点の RB 確率が、その日の確定 RB 確率をどの程度予測するか
  （＝途中経過に情報があるか）を先に測る。ここが無情報なら統合しない。
- 予告（`backtest/announce/`）の主張と、当日途中の観測が一致する日／しない日の切り分け。
