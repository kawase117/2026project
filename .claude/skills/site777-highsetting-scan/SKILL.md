---
name: site777-highsetting-scan
description: site777のリアルタイム収集から高設定台を割り出すまでの一連の運用手順。「スクレイピングして」「分析して」「設定計算して」「今日は弱い?」「予告に適合する台は?」と言われたら毎回この順序で回す。収集の罠(cmd即返し・線色変更・閾値未達)と設定推定の罠(一様事前での順位づけ・合算推定の誤用・誤警報率)を防ぐ。
---

# site777 高設定捜索スキル

## トリガー

- 「スクレイピングして」「再度スクレイピング」（当日のホールデータ収集）
- 「分析して」（収集済みデータからの高設定捜索）
- 「設定計算して」「RBから設定を出して」
- 「今日は弱い？」（当日水準の他日比較）
- 「予告に適合する台は？」（予告と実測の突合）

対象ホールは既定で **楽園蒲田店**。他ホールなら明示される。

## 背景

2026-08-30 のセッションで、この一連の流れをユーザーが5回に分けて個別指示していた。
毎回同じ手順・同じ罠・同じ訂正が発生したため手順書化する。特に「線色変更で差枚が
全件取れない」事象は当日発見・修正しており、放置すると分析が丸ごと成立しない。

## 手順

### 1. 収集（毎回この形で起動する）

```bash
cd C:/Users/apto117/Documents/pachinko-analyzer/src/2026project
scraper/site777/run_site777_complete.cmd -MinGames 2000 -Force
```

- **必ず `run_in_background: true` で起動し、Monitor を張る。** `.cmd` は非対話ツール経由だと
  exit 0 で即返ることがあり、前景実行では進捗が取れない（instinct: site777の.cmdラッパー）。
- `-Force` は更新ゲート（前回から更新が無ければスキップ）の迂回。同日中の再取得では必須。
- ログは **cp932**。`cat` すると "stream did not contain valid UTF-8" で読めない。
  Monitor では `iconv -f CP932 -t UTF-8`、Python では `open(p,'rb').read().decode('cp932')`。
- Monitor の grep は成功系だけでなく失敗系も必ず含める:
  `full_batch=|graph_batch=|graph_complete|failures=[1-9]|restrictions=[1-9]|Traceback|rror|failed|elapsedMinutes|diff_ok|stopped_at=[a-z]`
- 所要は Full 約26分 + Graph 約20分。合計45〜50分。
- フル収集だけ先に使いたいときは `site777_full_run_latest.json` の mtime を
  `until` ループで監視して1回だけ通知させる（Monitor ではなく Bash background）。

**閾値の考え方**: `-MinGames` はグラフ（差枚）収集の足切り。既定2000。
昼前など全台が2000G未満だと **graph targets=0** になる。このとき
「開店前だから」と結論してはいけない。**サイトの updateTime と実際のG数分布を見る**こと。
G数が足りないだけなら時間を置くか閾値を下げる。

### 2. 収集の健全性チェック（分析前に必ず）

```python
# ※ 出力JSONはすべてBOM付き。encoding='utf-8' だと JSONDecodeError になる
d = json.load(open('scraper/site777/output/site777_full_data.json', encoding='utf-8-sig'))
```

- `updateTime`（`"YYYY/MM/DD HH:MM"`）で、いつ時点のデータかを必ず確認して報告に書く
- `site777_graph_summary_filtered.json` の `status` 内訳を見る
- **`trace_unreadable` が全件 or 大半なら、サイト側が推移線の色を変えている**。
  過去4回発生（青紫→橙→水色→緑）。対処は次節。
- `missing_collected_graph` は未収集分。収集進行中なら正常。

### 3. 線色変更の検出と修正（trace_unreadable 多発時）

1. 実画像を **Read ツールで直接見る**（色ヒストグラムの上位N色だけ見ると、細線+
   アンチエイリアスで分散するため見落とす。2026-08-30 に実際に見落とした）
2. 線色を実測する:
   ```python
   a = np.array(Image.open(f).convert('RGB')).astype(int)
   r,g,b = a[:,:,0],a[:,:,1],a[:,:,2]
   mask = (g-r>=25)&(g-b>=25)   # ← 目視した色に応じて条件を変える
   ```
3. `scraper/site777/site777_graph_analyze.py` の `trace_masks()` に新色マスクを追加。
   背景(245,236,231)と灰の軸(153,153,153)を拾わないこと、既存マスクと衝突しないことを確認。
4. **`inputSignature` のバージョンを必ず上げる**（`v8:` → `v9:` など）。
   上げないと既存画像に再適用されず `processedThisRun=0` で何も変わらない。
   再スクレイピングは不要で、バージョンを上げて再解析すればよい（`scraper/site777/INSTINCTS.md`）。
5. 修正後、`trace_masks()` を直接呼んで検出ピクセル数（1枚400〜520が目安）を確認してから本番へ。

### 4. 設定推定（自前で書かない）

**必ず `scraper/site777/setting_estimator.py` を使う。** スペック表は
`ml/experiments/jug_rb_setting_prediction/config.py:JUGGLER_FAMILY_SPECS`。

```python
spec = importlib.util.spec_from_file_location('se','scraper/site777/setting_estimator.py')
se = importlib.util.module_from_spec(spec); spec.loader.exec_module(se)
FS = se.load_family_specs()
summary = se.annotate_setting_estimates(machines, FS)
# machines は [{'model_name','machine_number','games','bb_count','rb_count'}, ...]
```

このモジュールが持つ知見を自前実装で失わないこと:

- `MIN_GAMES_FOR_SETTING = 2000` — 未満は誤警報2〜3割
- **順位づけは `high_low_ratio`（高設定側尤度÷低設定側尤度）で行う。**
  `p_high_setting_uniform_prior` は一様事前なので過大に出る。順位に使わない
- **`setting_band_label`（否定できない設定の幅）を必ず併記する。** 高低比が高くても
  「絞れず」なら情報は薄い。2026-08-30 に高低比だけで3148を最上位に推し、幅が
  4〜6まで絞れていた1138を下に置いて外した
- `FALSE_HIGH_RATE_AT_3000G` — 真が設定1でも最尤が5-6になる割合。
  **ゴーゴージャグラー3は22.7%** と突出（アイム8.2%/マイジャグ11.4%/ハッピー12.9%）。
  この機種の単独推しは割り引く
- `indistinguishable` — **アイムEX系は設定5と6のRB確率が同一**で、RBでは区別不能。
  「最尤6」を6と断定しない
- 機種名マッチは `build_family_matcher`（長いキーワード優先）を使う。素朴な先頭一致
  ループは誤割当のリスクがある

**機種グループ合算の扱い**: `estimate_setting` にグループ合算値を渡すのは
「全台同一設定」を仮定した推定。混在ホールでは意味を持たず、アイム62台のように
設定1比 p=0.00000 なのに合算最尤が設定3で「低設定寄り」と出る。
**混在の検出には設定1を帰無とした二項検定の p 値**を、台の選定には台別推定を使う。

**機種の取り違えに注意**: 新ハナビ と スマスロハナビ は別機種で別スペック
（設定1 RB 1/356 vs 1/395）。同じ「1/300」でも意味が違う。機種をまたいで
実測RB確率を直接比較しない。必ず自機種の設定1基準に対する位置で見る。

### 5. 分析メニュー（毎回この順で出す）

1. **全体水準** — 差枚の平均/中央/勝率、平均G数、updateTime
2. **差枚TOP** と **機種別平均**（3台以上）
3. **並びブロック** — 台番号連続でプラスが続く塊。4台以上を強調。
   予告の「N台並び」条件の判定に直結する
4. **ニブイチ判定** — 機種の上位半数平均 vs ホール上位1/2分位平均（当該機種を除く）。
   `backtest/announce.py:_judge_model_named_ratio` と同じ式
5. **設定推定**（手順4）— 高低比降順、幅・信用度・差枚を併記
6. **予告との突合**（登録済み announce があれば）— ①てっぺん ②各1以上 ③全台系
   ④並び の各条件を実測で判定

### 6. やってはいけないこと

- **差枚で設定を判定しない**（instinct: feedback-scoring-must-separate-setting-from-pnl）。
  差枚は「予告の主張パターンへの適合」を見る材料であって設定の証拠ではない
- **G数上位N台の比較を時刻をまたいで行わない**。フルデイの「G数上位」は1日かけて
  勝った台が濃縮されるが、昼の「2000G到達組」は朝から回されただけで勝者選抜が
  効いていない。2026-08-30 に「過去88日中下から2番目」という誤った弱さを出した
- **「今日は弱い？」には時刻非依存の指標で答える**。ジャグラー系のホール合算RB確率を
  過去90日の同指標と比べるのが正しい。差枚ベースの比較は上記の理由で歪む
- **末尾別は多重比較補正を書く**。10末尾を検定するので Bonferroni α=0.005。
  p=0.011 程度では「末尾5が冷遇」と言わない。加えて2000G足切りの選択バイアスを明示する
- **稼働はセグメント補正する**。AT/液晶機とノーマル機で平均G数が1.5倍違う
  （2026-08-30: 1,168G vs 766G）。ホール平均との比は誤解を生む
- **`回転数がホール平均の2倍以上`のシグナル**（instinct）は、昼の段階では
  ほぼ該当しない。時間帯を明記して判定する

## 関連スキル・資産

- `announce-prep` — 予告の事前登録と答え合わせ。本スキルの手順6の入力を作る
- `mojibake-debug` — cp932まわりで詰まったとき
- `env-check` — `venv\Scripts\python.exe` を使う。裸の `python` は使わない
- `scraper/site777/INSTINCTS.md` — 収集側の詳細な既知事項
- `scraper/site777/setting_estimator.py` — 設定推定の唯一の実装
