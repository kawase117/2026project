# GOGO3イベント日投資戦略 深堀り — Codex連絡ログ

背景: `document/superpowers/2026-07-06-jug-rb-prediction-final-report.md` の副次的発見
（GOGO3系統だけ全9ホールでe_payoutが実現値よりプラスに乖離）の原因調査中、
イベント日(is_any_event)別にGOGO3の実現機械割を見たところ、ホールによって
真逆の挙動が見つかった（蒲田7・ザシティはGOGO3がイベント日に相対的に厚遇、
レイトギャップ・ヒロキはGOGO3がイベント日に相対的に冷遇＝ホール全体はイベント日に
上がっているのにGOGO3だけ下がる）。この4ホールを深堀りする。

運用: Claude が指示をこのファイルに追記し、Codex は毎回**このセクションだけで
完結する指示**を実行する（過去のセクションを読む必要はない。読まなくても
再現できるよう、前提から全て記載する）。

---

## [2026-07-06] タスク#1: 4ホールのGOGO3イベント日効果を統計的に検証（全文自己完結）

### 背景となる記述統計（参考、Claudeが事前に計算済み）

| ホール | GOGO3 event−非event差 | 全機種平均 event−非event差 |
|---|---|---|
| 蒲田7(kamata7) | +0.26pp | −0.61pp |
| ザシティ(zashiti) | +0.51pp | +0.73pp |
| レイトギャップ(lategap) | −0.83pp | +0.42pp |
| ヒロキ(hiroki) | −0.96pp | +0.21pp |

これはブートストラップ等の検定をしていない単純な記述統計。今回はこれを
統計的に検証する。

### 対象・データ
- 対象4ホール: 蒲田7(db/マルハンメガシティ2000-蒲田7.db)、
  ザシティ(db/ザ-シティ-ベルシティ雑色店.db)、
  レイトギャップ(db/レイトギャップ平和島.db)、
  ヒロキ(db/ヒロキ東口店.db)
- 対象機種: `machine_name = 'ゴーゴージャグラー3'`（完全一致、部分一致ではない）
- フィルタ: `games_normalized >= 500`。蒲田7のみ追加で `date` が `0707` で終わる行、
  および `machine_number = 2026` を除外（既存プロジェクト規約）
- テーブル: `machine_detailed_results`（date, machine_number, games_normalized,
  diff_coins_normalized）と `daily_hall_summary`（date, is_any_event, is_zorome,
  is_strong_zorome, is_month_start, is_month_end, is_weekend, is_holiday,
  hall_anniversary, is_x_day）を date で結合
- 機械割の定義: `payout% = (1 + Σdiff_coins_normalized / (3 * Σgames_normalized)) * 100`
  （G加重、日付グループ内で合算してから比率を取る）

### 計算内容

各ホールについて、日付を単位とした2つの系列を作る:
1. `gogo3_daily_payout(date)`: その日のGOGO3全台合算のG加重機械割
2. `all_daily_payout(date)`: その日の全機種合算のG加重機械割（ゾロ目・イベント等
   の判定はdaily_hall_summary由来、機種を問わない）

その上で、日付を `is_any_event==1` か `0` かで2群に分け、以下2つの量を
moving block bootstrap（block=7日、n_bootstrap=2000、シードは42固定）で
95%CI付きで推定する:

1. **単純差**: mean(gogo3_daily_payout | event) − mean(gogo3_daily_payout | non-event)
2. **DiD（差分の差）**: 上記1 − [mean(all_daily_payout | event) − mean(all_daily_payout | non-event)]
   ※DiDの方が理論的に重要。「イベント日は日全体が高くなりがち」という交絡を除去し、
   「GOGO3だけがイベント日にホール平均以上に動いているか」を直接測る指標

ブートストラップの実装は既存の `ml/experiments/jug_rb_setting_prediction/stage4_real_money.py`
内の `_moving_block_bootstrap_ci` 関数と同じロジックを流用してよい（同一ファイルから
importするか、同等のロジックを新規スクリプトに実装する）。

### 追加分析: どのイベントカテゴリが効いているか

`is_any_event` は複数のフラグ（is_zorome, is_strong_zorome, is_month_start,
is_month_end, is_holiday, hall_anniversary, is_x_day）のORで構成されている。
4ホールについて、`is_zorome`・`is_month_end`・`is_holiday`（+可能なら`is_x_day`）
それぞれ単独でも同じDiD計算を行い、どのカテゴリが最も大きく効いているかを
確認すること（サンプル数が少なすぎるカテゴリ(<20日)は計算せずスキップしてよい）。

### 出力先
新規ディレクトリ `ml/analysis/results/gogo3_event_day_strategy/` に:
- `{hall_slug}_gogo3_event_bootstrap.json`
  （キー: simple_diff{mean,ci_lower,ci_upper,n_event,n_non_event},
  did{mean,ci_lower,ci_upper}, by_category{カテゴリ名: {mean,ci_lower,ci_upper,n}}）
  hall_slugは kamata7/zashiti/lategap/hiroki
- `gogo3_event_strategy_summary.csv`（全4ホール横並び、列: hall, simple_diff_mean,
  simple_diff_ci_lower, simple_diff_ci_upper, did_mean, did_ci_lower, did_ci_upper）
- `gogo3_event_strategy_summary.md`（上記を表にしたもの、各ホールの判定
  ["positive_divergence"(DiDのCIが0より上)/"negative_divergence"(CIが0より下)/
  "no_significant_divergence"(CIが0を跨ぐ)]を付記）

### スクリプト・テスト
- 新規スクリプト: `ml/analysis/gogo3_event_day_strategy.py`
  （CLI引数で対象ホールを指定できるようにし、上記出力を生成する関数を持つこと）
- テスト: `ml/tests/test_gogo3_event_day_strategy.py` に、小さな合成データで
  simple_diffとDiDの計算が正しいことを検証するユニットテストを追加
- `py_compile` と `pytest` を通すこと

### 報告フォーマット
1. `gogo3_event_strategy_summary.md` の全文
2. 4ホール中、DiDのCIが0を跨がなかったホールとその方向（正/負）
3. カテゴリ別内訳で最も寄与が大きかったカテゴリ（ホールごとに1つずつ）
4. py_compile / pytest の結果

「完了しました」だけの報告は受理しない。上記1〜4を実データで提示すること。

---

## [2026-07-06] Codex報告: 事前チェック完了。`is_any_event`が11〜15日しかなく、
下位カテゴリ(is_zorome等)も全て<20日でスキップ対象になる見込み

## [2026-07-06] 裁定#1: `daily_hall_summary`のDBフラグではなくカレンダー計算式に切替（全文自己完結）

### 原因
`daily_hall_summary.is_any_event`等のDB列は、本セッションで一貫して使ってきた
「イベント日」（7のつく日・1のつく日・ゾロ目・強ゾロ目・月末、全日数の約3割）
とは**別の、もっと狭い定義**になっている（hall_anniversary等の稀な特別日のみを
指している可能性が高い）。Codexの事前チェックが正しく、このままではタスク#1の
カテゴリ別分析が全滅する。

### 修正: イベント日をDBフラグからではなく`date`列から直接計算する

`daily_hall_summary`のフラグ列は**使用しない**。代わりに、既存の
`ml/experiments/jug_rb_setting_prediction/stage3_features.py` の `_add_event_flag`
関数と同じロジックをこの新規スクリプト内に実装する（date列 "YYYYMMDD" から）:
```python
day = date.day
month_end = (dateがその月の最終日か)
is_event_day = (
    day in [1, 7, 11, 17, 21, 27, 30]
    or day == 22
    or day == date.month  # 強ゾロ目(月=日)
    or day == month_end   # 月末
)
```
これを4ホール全てで `is_any_event` の代わりに使う（タスク#1の「対象・データ」
セクションの`daily_hall_summary`結合は不要になる。dateから直接計算するため）。

### カテゴリ別分析も同じ計算式のサブセットで再定義

DBの`is_zorome`等ではなく、以下5カテゴリを`date`から直接計算する
（互いに重複しうる。1台の日が複数カテゴリに属してよい）:
- `is_7suffix`: day in [7, 17, 27]
- `is_1suffix`: day in [1, 11, 21, 31]
- `is_zorome`: day in [11, 22]
- `is_strong_zorome`: day == date.month
- `is_month_end`: day == その月の最終日

各カテゴリについて、そのカテゴリ=1の日数が20日以上あればDiDを計算、
未満ならスキップ（タスク#1の元の判定基準どおり）。7のつく日・1のつく日は
月3日×約18ヶ月分≈50日超えるはずなので、この定義なら大半のカテゴリで
計算可能になる見込み。

### その他はタスク#1の指示のまま変更なし
- ブートストラップ手法（block=7, n=2000, seed=42）、出力先、ファイル名、
  スクリプト名・テストファイル名、報告フォーマットは全て元の指示を踏襲
- 出力JSONの`by_category`キーは上記5カテゴリ名（is_7suffix等）を使うこと

この条件で実装に進んでください。
