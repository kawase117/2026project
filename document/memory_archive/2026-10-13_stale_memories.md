# 古くなった記憶のアーカイブ(2026-10-13)

メモリ整理(2026-10-13)で、現役の索引から外した記憶7件をそのまま保存する。削除はしていない。
各節の見出しは元のファイル名。コードブロックの中が元ファイルの全文(frontmatter込み)。
戻すときは、コードブロックの中身を元のファイル名で記憶フォルダに書き戻し、`MEMORY.md` にリンクを足す。


## project_current_focus.md

````markdown
---
name: project-current-focus
description: 現在の作業フォーカス — 蒲田7特化の深堀り分析。全ホール汎化から方針転換（2026-06-26）
metadata: 
  node_type: memory
  type: project
  originSessionId: 81387052-2d9b-4169-bab7-048f614c7432
---

## 現在の方針（2026-06-26 更新）

**蒲田7を重点的に掘り下げる。** 汎化性のある法則よりもホール固有の構造解明を優先。

**Why:** 全9ホール横断EDA（2026-06-26）で、ホールごとに戦略が大きく異なることが実証された。
debut_phaseの単調パターンは共通だが、プラス圏到達の有無・凹型パターン・看板台優遇の有無が
ホールによって全く異なる。汎化法則を追っても「ホールによる」で終わるため非効率。

**How to apply:**
- 新グルーピング軸・特徴量の検証は蒲田7で先行実施
- 全ホール横断は「蒲田7で有効だった知見の再現確認」目的のみ
- 他ホール（みとや等）は蒲田7の知見を転用する際に個別調整

## 蒲田7で確認済みの知見（2026-06-26時点）

- 経過日数×稼働率: 3フェーズモデル成立（best-worst 576枚）
- 設置台数: 凹型（U字型）パターン（蒲田7固有、汎化性低い）
- 区間差枚×稼働率: 新台汚染の再検出。独立した知見ではない
````

## project_ml_segment_strategy.md

````markdown
---
name: ml-segment-specific-strategy
description: 2F vs 3F 機械学習セグメント別戦略。baseline6 が 2F に最適、rich_all が 3F に有効。確率分布分析で検証済み。
metadata: 
  node_type: memory
  type: project
  originSessionId: 6a97b409-78dd-45ff-bfc1-11026db85934
---

# 機械学習セグメント別特徴量戦略（2026-05-27）

## 根本的な違い: 2F vs 3F

### 2F (Second Floor - メイン機種フロア)
- **設定パターン**: シンプルで一貫性がある
- **最適特徴量**: `baseline6`（単純な履歴特徴量）
- **理由**: prior_top1_rate, weekday_prior_top1_rate などの単純特徴量で既に十分な順序付けができている
- **エンジニアリング特徴量の効果**: **逆効果**（AUC 悪化 -0.0012）
- **確率分布**: 中程度の集中（dispersion_ratio=1.27）→ 少数機種に確信

### 3F (Third Floor - 補助機種フロア)
- **設定パターン**: 複雑で非線形
- **最適特徴量**: `rich_all`（エンジニアリング特徴量を含む）
- **理由**: same_weekday_top3_rate, prior_segment_top1_rate などの相対的・クロス参照パターンが必要
- **エンジニアリング特徴量の効果**: **大幅改善**（AUC 改善 +0.0711）
- **確率分布**: より分散（dispersion_ratio=1.69）→ 複数機種に分散

## 確率分布分析の発見（2026-05-27）

### ユーザー仮説の検証: ✅ 正確

**仮説**: 「2F は多くの機種にランダムに近い確率で分散」

**検証結果**:
- baseline6 時点で 2F の確率は「少数機種に中程度集中」（dispersion=1.27）
- rich_all で 2F の確率が「複数機種に大幅分散」（dispersion=3.21）
  - ranking_quality=8.38 → ランキング精度は高い（AUC 0.5434）が、絶対値の確信が低い（hit@1=22.5%）
  - つまり「モデルはどの機種が上かは分かるが、どれが最高か不確実」という状態

### AUC と確率値分布の関係

**重要**: AUC が同じでも、確率値分布は全く異なる
- **High AUC, Low hit@1**: ランキングは正確だが、トップ1 の確信度が低い
- **High AUC, High hit@1**: 両方優れている

**2F の場合**:
- baseline6: AUC 0.5380, hit@1 25.0% → バランス型
- rich_all: AUC 0.5434, hit@1 22.5% → ランキング精度は上がったが確信度は下がった（逆効果）

## 試行錯誤の履歴

### ❌ 失敗: 統合モデル（全セグメント統一）
- baseline6 で 2F と 3F を混在
- 結果: 2F は baseline6 で十分、3F は改善の余地あり
- **学習**: 異なるパターンの機種を統一モデルで学習するのは非効率

### ❌ 失敗: 無分別に rich_all 導入
- 全セグメントに rich_all を適用
- 結果: 2F は悪化（AUC -0.0012）、3F も想定より改善なし
- **学習**: エンジニアリング特徴量が常に有益とは限らない

### ✅ 成功: セグメント別特徴量戦略の提案
- baseline6: 2F に最適（シンプルさを保つ）
- rich_all: 3F に最適（複雑パターンを捉える）
- **根拠**: 確率分布分析で理論的に検証

## 関連ファイル

**分析スクリプト**:
- `ml/machine_type/analyze_baseline6_vs_rich_all.py` — feature importance 比較
- `ml/machine_type/analyze_probability_distribution.py` — 確率分布分析（hit@1, dispersion_ratio 等）

**評価結果**:
- `ml/machine_type/v2/output/auto_explore_20260526_100706/baseline_tune/` — baseline6 結果
- `ml/machine_type/v2/output/auto_explore_20260526_100706/task1_tune_rich_all/` — rich_all 結果
- `ml/machine_type/v2/comparison_baseline6_vs_rich_all.txt` — 90日 walk-forward 評価結果

**パイプライン**:
- `ml/machine_type/v2/run_machine_type_v2.py` — メインパイプライン（--feature-profile 指定可）
````

## feedback_exploration_strategy.md

````markdown
---
name: exploration-coarse-to-fine
description: ML探索は「粗く網羅的→細かく限定的」の段階的絞り込みを原則とする
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3d2d44ee-c73a-45de-b228-ac251c033b9a
---

新しい探索（モデル選択・特徴量・ハイパーパラメータ・eval幅など）を始めるときは、最初は荒く網羅的に、段階を踏んでだんだん細かく限定的に絞り込む。

**Why:** 早期に限定的な探索をすると有望な領域を見落とすリスクがある。最初に全体像を把握してから深堀りする方が効率的。

**How to apply:**
- モデル比較: 最初は全モデル x 粗い設定 → 勝者だけ詳細チューニング
- iterations: eval3（疎通）→ eval20-30（比較）→ eval60（最終確認）の段階制と同じ思想
- ハイパーパラメータ: 粗いグリッド全探索 → 有望領域を絞って細かいグリッド
- 特徴量: 多めに候補を入れて Ablation で削る（最初から限定しない）
- 新モデル導入時のiterations: まず既存モデルと同条件で比較し、精度が出たら増やす
````

## project_3fn_model_failure_20260527.md

````markdown
---
name: 3fn-model-failure-20260527
description: "蒲田七2026-05-27：3F_N（イベント日無敗）モデルが初敗北。末尾9を強く推したが-20,900。ホール戦略の予測不可能性が浮き彫り。"
metadata: 
  node_type: memory
  type: project
  originSessionId: a79c0947-53fc-4ae3-bbd1-a0b06e23e3de
---

## 事実：3F_N モデルの初敗北（2026-05-27）

**日付**: 2026-05-27（水曜日）  
**ホール**: マルハンメガシティ2000-蒲田7  
**イベント日**: event_digits=[1,11,31,7,17,27] に該当（27日）

### 3F_N の予測 vs 実績

| 指標 | 予測 | 実績 | 乖離 |
|------|------|------|------|
| **末尾9 順位** | **1位**（最強推奨） | **最下位（10位）** | 9位乖離 |
| **全台合計差枚** | （プラス推奨） | **-20,900** | 最悪 |
| **信頼度ステータス** | "イベント日無敗" | **初敗北** | 仮説破綻 |

### 具体的な損害：末尾9 ゾロ目台の分析

- 3299（ハッピージャグラーVIII）: +1,300 ← 数台のプラスあり
- 3199（新ハナビ）: **-600**
- 2199（カバネリ）: +1,000
- 2299（スーパーブラックジャック）: +1,200

**→ ゾロ目台単体ではプラス台が複数存在するが、非ゾロ目台含め全体では大損。ホール側の分散戦略か。**

---

## 根本原因の推測

1. **ホール側が末尾9に設定投入しなかった**
   - 3F_N は「イベント日パターン（27日など）に高設定を投入」という学習仮説
   - しかし実際には末尾9は避けられた可能性
   - ホール側が「既知の末尾パターンを避ける」戦略を採用している可能性がある

2. **イベント日の定義がホール主観と異なる**
   - event_digitsに27が含まれていても、実際のイベント投入パターンが27日の末尾9とは無関係
   - または、27日というイベント日自体が他の日と異なる戦略（特定末尾を避ける）を採用

3. **セグメント別データの乖離**
   - 2F_N と 3F_N の差異が大きい（末尾9： 3F_N=1位、 2F_N=4位）
   - セグメント別（2F vs 3F）での学習データまたはホール別データの分布に乖離がある可能性

---

## Why（実装者への背景）

### 3F_N が優秀と思われていた理由
- Prior sessions での「イベント日無敗」という成績（0% top1 miss rate）
- イベント日フラグが明確に定義されている（date_info_calculator.py で自動計算）
- 特に arrow 池上店などでは高精度との報告

### なぜ今日破綻したのか
- ホール固有の戦略が予測モデルより一段階上（「既知パターンを避ける」という二次的戦略）
- セグメント別の特徴量が全ホール統合モデルと乖離している
- 蒲田7固有の設定投入パターンが未知の可能性

---

## How to apply（今後の対応）

1. **3F_N の信頼度を一時的に低下させる**
   - 「イベント日無敗」という仮定は、このホール・この日付の組み合わせでは破綻
   - イベント日でも他モデル（3F_A, 2F_N）と同等の信頼度に再評価すべき
   - ホール別・日付別に3F_Nの精度を再検証する必要あり

2. **3F_A（Adaptive）の信頼度を相対的に上昇**
   - 末尾4,6を的確に予測（実績1位, 2位）
   - ホール適応学習能力が高い可能性

3. **「ホール側の回避戦略」を検証**
   - 既知の高設定パターン（末尾7,9など）を意図的に避ける傾向がないか
   - 過去30日間の複数ホールで同様の「予測とは逆」のパターン（予測1位 → 実績最下位）を検索
   - もし複数ホールで見られたら、ML パイプラインに「逆転リスク」フィルタを追加

4. **セグメント別モデルの再検証**
   - 2F_N vs 3F_N の乖離原因を特定（database/など で 2F/3F データ分布を確認）
   - ホール別・セグメント別に分割学習する妥当性を再確認

5. **イベント日定義の見直し**
   - 27日が event_digits に含まれていても、蒲田7では異なる戦略を採用している可能性
   - ホール別の event_digits を再調整する検討

---

## 関連メモリ

[[ml-segment-specific-strategy]] — 2F vs 3F セグメント別特徴量戦略。baseline6⇒2F最適、rich_all⇒3F最適。確率分布検証済み（2026-05-27）

[[project-current-focus]] — 機種別ML継続中。セグメント別戦略実装検討中（2026-05-27）
````

## project_mitoya_theory_rebuild_pending.md

````markdown
---
name: project-mitoya-theory-rebuild-pending
description: mitoya_theory.md手動再構築は完了済み（2026-07-02）。kamata7相当の構成で再編済み
metadata: 
  node_type: memory
  type: project
  originSessionId: fc4b1044-7cdb-4cfc-9910-2b2788ef332f
---

`document/mitoya_theory.md` を2026-07-02に手動再構築完了。旧版はPhase3〜8（自動生成、`eda/mitoya_phase5b_theory.py`製）とPhase10以降（既に手作業品質だった否定仮説カタログ・アンチパターン7類型・蒲田7比較・実運用フロー）が同居していた。新版はPhase3〜8を切り離し、Phase10〜12の内容とInstinct全件（Exploreエージェント2件で収集、約150件＋Phase9-11詳細統計）をkamata7_theory.md構成（用語定義→セグメント構造→変数別効果→否定仮説→ホール比較→統合フロー→ML運用知見→ロードマップ→Instinct参照マップ）に再編した。詳細は [[feedback-theory-docs-must-be-hand-authored]]。

`eda/mitoya_phase5b_theory.py` の `OUTPUT_PATH` は `document/mitoya_evidence_bundle.md` に変更済み（次回スクリプト実行時に手動版を上書きしないため）。ただしevidence bundle自体の再生成はまだ実行していない（スクリプトは書き換えたが未実行）。

**Why**: みとやは分析セッション数が多く（`eda/mitoya_*.py` が70本以上、Phase3〜12まで存在）、素材となる検証結果自体は豊富だった。不足していたのは合成作業のみで、実際にはPhase10以降に既にその合成の大部分が存在していた（当初の想定より作業量は少なかった）。

**How to apply**: 新版で見つかった未解決事項が2つ残っている。①104%率(rate_104=27-34%)とhit_rate_104≈0%という2つのInstinctの数値が矛盾しており定義の突き合わせが必要（[7章未探索ロードマップ#1]）。②`eda/mitoya_phase5b_theory.py`実行で`document/mitoya_evidence_bundle.md`を一度生成しておくと、Phase3〜8の生データ参照が復元される。次にみとやのtheory更新をする際は、この新版をベースに追記する（ゼロから再構築しない）。
````

## project_quoted_image_refetch_pending.md

````markdown
---
name: project-quoted-image-refetch-pending
description: 引用ツイート画像の混入890件は2026-09-24に解消済み。ハッシュ一致計測→取り直し→再抽出まで完了、残suspect(5枚以上)は0件。
metadata:
  node_type: memory
  type: project
  originSessionId: db561cb2-f0d7-400e-ae4a-7c24f2284f54
  modified: 2026-09-24T14:23:48.833Z
---

**2026-09-24 完了。** [[feedback-scraper-image-tweet-misbinding]] で保留にしていた2作業を実施した。

1. **ハッシュ一致による特定**（`scraper/twitter_monitor/measure_quote_image_hashes.py`、新規・読み取り専用）:
   実行時点で「5枚以上」のsuspectは11件のみだった（メモ記載の890件から、同日進行中だった別の
   絵文字誤スキップ修正バッチで大半が並行して解消済みだったため）。ハッシュ一致率100%（11/11）、
   一致画像36枚（5枚目以降21枚・1〜4枚目15枚）。暫定ルール「5枚目以降を除外」が見落としていた
   4枚目以内の引用画像も実際に存在することを確認。

2. **取り直し**: `repair_tweet_images.py --apply --tweet-id ...` で11件（999999Q9Q 8, kawasakislot 2,
   sloneko222 1）すべて成功。ただし実行中に `strip_emoji` の欠陥3種を発見・修正した
   （詳細は [[feedback-scraper-image-tweet-misbinding]] に追記予定、コミット済み）。
   修正前は11件中10件が「本文が一致しないので触らない」と誤スキップされていた。

3. **再抽出**: `prefilter.py`（新規画像37枚→32枚が対象、実行後 image_features 反映）→
   `extract_answers.py --tweet-ids ...` で9件successを確認。残り2件（2094382077475266855,
   2097709452887744862）は画像が写真判定（prefilter is_candidate=0）で対象外、これは正しい挙動。

**確認**: `tweet_images` を tweet_id ごとに数えて5枚以上のsuspectは現在0件。

**Why:** 作業2（取り直し）の過程で `repair_tweet_images.py` の本文突き合わせ（same_tweet_text/
strip_emoji）が想定以上に壊れていた。FE0F付きBMP内記号（‼️⬇️等）・キーキャップ絵文字（7️⃣）・
FE0Fなし単体絵文字（✨等、Misc Symbols+Dingbats/Misc Symbols and Arrows帯）が除去されず、
DB本文とページ表示のずれで「本文不一致」誤判定が起きていた。今回の11件のうち10件がこれで
最初は弾かれた。今後このスクリプトで新たな「本文が一致しない」多発が出たら、まず絵文字漏れを疑う。

**How to apply:** 画像由来のラベルは全期間で信頼してよい（混入対象は解消済み）。今後
scrape_tweets/repair_tweet_images が新規に取りこぼした場合は、このメモの手順（ハッシュ一致計測→
--tweet-id明示でrepair→prefilter→extract_answers）をそのまま再利用する。
````

## project_ml_20260602_learnings_archive.md

````markdown
---
name: ml-20260602-learnings-archive
description: 2026-06-02のML関連メモ5件の退避(元ファイルは消失し索引の1行説明だけが残っていたものを2026-10-13に復元)。DB拡張計画・ランキング知見・検証規律・全ホール方針転換・ホール偏りペナルティ。
metadata:
  node_type: memory
  type: project
  originSessionId: f7ec292d-a0d6-4861-a94b-4774715861fd
  modified: 2026-10-12T16:39:49.545Z
---

元の記憶ファイルは存在せず、索引(MEMORY.md)に残っていた1行説明をそのまま退避した。詳細は失われている。

- **DB拡張計画**: 現在1年半データでは長期パターン検出不可。追加データ投入後に再モデリング。
- **ランキング知見**: Oracle統計・hit@2の価値・multi-threshold確率・anti-concentration制御の実装済み知見。
- **検証規律**: Walk-forward厳密性・tuning期間ポリシー最適化・holdout固定適用の実装ガイドライン。
- **全ホール方針転換**: 「強いホール当て」から「スパイク日(弱ホール爆発)当て」へ。全ホール毎日スコアリング。
- **ホール偏りペナルティ**: 実証として蒲田7の選択率70%に対し実績1位は24%。ホール偏りペナルティが必須で、Top2運用で回避。

**Why:** 索引だけが情報源で、リンク先が無い状態だったため。
**How to apply:** これらの方針を使う前に、現在の `ml/` と `document/` の実装で裏取りする。
````
