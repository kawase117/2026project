# みとや大森町 台選び理論ドキュメント

> **目的**: みとや大森町のEDA・Instinct（約150件）とPhase9〜12の精密検証で判明した知見を「台選びの理論」として体系化する。
> **対象読者**: 毎日通い、最良の台を選ぶプレイヤー。セグメント単位のスコアリングをベースとした運用を前提とする。
> **最終更新**: 2026-07-02（再構築版)。旧版は`eda/mitoya_phase5b_theory.py`が自動生成するPhase3〜8の生データ羅列と、Phase10以降に手作業で追加された高品質な分析（否定仮説カタログ・アンチパターン7類型・蒲田7比較・実運用フロー）が同居していた。本版はPhase3〜8の生データ羅列を評価bundleへ切り離し、Phase10〜12の内容を骨格として、Instinct全件・kamata7_theory.md相当の構成に再編した。
> **ステータス**: 統合完了。角番・末尾・debut_phaseは4系統の耐久性検証（split-half/regime/machine_dependency/corner制御）が実施済み。DD full spectrum・曜日・ゾロ目はPhase11aで否定的結論が出ている。104%率とavg_diffの評価軸の一致度検証も完了（rho=0.873、詳細は[2.9](#29-104率分析--蒲田7手法の導入検証)）。
> **旧版の扱い**: Phase3〜8の生データ集計（`eda/mitoya_phase5b_theory.py`出力）は評価bundleとして別途保持し、本文では結論の引用のみ行う。

---

## 用語定義（LLM向け契約）

| 用語 | 定義 | コード上の変数名 | 注意 |
|------|------|------------------|------|
| **セクション（島）** | 物理的な18島単位のグループ | `section` | 台番号の連続範囲とは不一致な場合がある |
| **角番（kakuban）** | 通路距離補正済みの位置番号 | `rank_from_aisle` | `rank_from_min`より説明力5倍（epsilon^2: 0.002482 vs 0.000488）。**必ずrank_from_aisleを使う** |
| **corner_bucket** | 角番の4段階粗視化 | `corner_bucket` | 1 / 2-4 / 5-9 / 10+。fine rank（1台単位）は単調減少しないためバケット化が正しい粒度 |
| **reversed セクション** | 台番号の並びと通路方向が逆のセクション | `is_reversed_section` | 523-539, 557-573, 591-607, 624-640, 658-674が該当。reversed=1では corner1 = 台番号が**最大**側の台 |
| **セグメント** | orientation（横列/縦列）× jug_flag（ジャグラー/非ジャグラー）+ mixed_805独立区分 | `h_jug`, `h_nonjug`, `v_jug`, `v_nonjug`, `mixed_805` | ANOVA交互作用 F=26.05, p=3.3e-7 で確定。蒲田7のLR×A/Nとは異なる分割軸 |
| **X_DDS（イベント日）** | DD in {4, 7, 14, 17, 24, 27}（実運用フローでは1,30も含めた拡張版を使用） | `is_x_day`相当 | 一般的に想定される{1,11,22,25,30,31}という定義は**誤り**。実データから逆引きして確定 |
| **strong_zorome** | `ts.month == ts.day` | 計算値 | DBフラグ参照ではなく日付から直接計算 |
| **debut_phase** | 機種投入からの経過フェーズ | `pre_existing` / `debut` / `growth` / `mature` | debut_bin: 0-30/31-60/61-90/91-120/121+日 |
| **bari island** | 変則配置の独立島 | — | **みとやには存在しない**（machine_num最大値815 < 832）。蒲田7等の知見を安易に流用しない |
| **is_zorome（台）** | 台番号下2桁が同一 | `is_zorome` | 蒲田7と同一定義だが、みとやでは正のシグナルにならない |

---

## 目次

1. [セグメント構造 — なぜ全体集計は信用できないか](#1-セグメント構造--なぜ全体集計は信用できないか)
2. [変数の効果と限界](#2-変数の効果と限界)
   - 2.1 [角番（水平限定・最も堅牢）](#21-角番水平限定最も堅牢)
   - 2.2 [台番号末尾（純粋効果なし・全セグメントで否定）](#22-台番号末尾純粋効果なし全セグメントで否定)
   - 2.3 [DD — X_DDS二値で十分（トラフゾーンなし）](#23-dd--x_dds二値で十分トラフゾーンなし)
   - 2.4 [曜日（角番効果の1/7以下、主軸にしない）](#24-曜日角番効果の17以下主軸にしない)
   - 2.5 [X_DDS×角番の交互作用（水平限定）](#25-x_dds角番の交互作用水平限定)
   - 2.6 [ゾロ目（台番号）— v_nonjugの回避強化のみ](#26-ゾロ目台番号--v_nonjugの回避強化のみ)
   - 2.7 [debut_phase（h_nonjugは生存バイアス＋X_DDS限定プレミアムの二重構造）](#27-debut_phaseh_nonjugは生存バイアスx_dds限定プレミアムの二重構造)
   - 2.8 [機種別DD/曜日パターン（全機種横断スキャン）](#28-機種別dd曜日パターン全機種横断スキャン)
   - 2.9 [104%率分析 — 蒲田7手法の導入検証](#29-104率分析--蒲田7手法の導入検証)
3. [否定された仮説と分析の罠](#3-否定された仮説と分析の罠)
4. [蒲田7との構造比較](#4-蒲田7との構造比較)
5. [統合 — 台選びフロー](#5-統合--台選びフロー)
6. [MLモデル構造と運用知見](#6-mlモデル構造と運用知見)
7. [未探索ロードマップ](#7-未探索ロードマップ)
8. [Instinct参照マップ](#8-instinct参照マップ)

---

## 1. セグメント構造 — なぜ全体集計は信用できないか

### ホール概要

| item | value |
|---|---|
| 台数 | 266 |
| 日数 | 538 |
| 期間 | 20250101〜20260625 |
| セクション数 | 18島 |
| レジーム境界 | 2025-07-07（74台が同日に機種変更） |

### 低天井構造 — 評価軸に未解決の齟齬あり

`mitoya-hallwide-low-ceiling-near-zero-hit104`は「median payout 99.3-100.7%、hit_rate_104≈0%」としているが、[2.9](#29-104率分析--蒲田7手法の導入検証)の104%率分析ではDD別rate_104が27〜34%の範囲で観測されている。両者は指標定義（ホール平均payoutの閾値判定 vs 台単位でpayout_rate>=104%となった比率）が異なる可能性が高いが、**現時点では未調整のまま両方を記載する**。実運用では[2.9](#29-104率分析--蒲田7手法の導入検証)のavg_diffとの高相関(rho=0.873)を根拠に、引き続きavg_diffを主指標として使う。

### 5セグメントの構成と根拠

ANOVA検定でorientation×jug_flagの交互作用が有意（F=26.05, p=3.3e-7）と確認され、以下5セグメントが確定した。

| segment | 定義 | セクション | 台数 | n |
|---------|------|-----------|------|---|
| **h_jug** | 水平島×ジャグラー | 641-657, 658-674(reversed), 675-691 | 51 | 28,346 |
| **h_nonjug** | 水平島×非ジャグラー | 501-522, 523-539, 540-556, 557-573(reversed), 574-590, 591-607(reversed), 608-623, 624-640(reversed) | 139 | 63,036 |
| **v_jug** | 縦列×ジャグラー | 712-722, 723-733, 734-744 | 33 | 16,336 |
| **v_nonjug** | 縦列×非ジャグラー | 692-700, 701-711, 745-755 | 30 | 13,307 |
| **mixed_805** | 独立区分 | 805-815 | 19 | 5,154 |

**v_nonjugは全面マイナスの回避セグメント**: avg_diff=-119、全角番帯マイナス（corner1=-282, corner2-4=-107, corner5-9=-115, corner10+=-32）。ゾロ目台はさらに悪化(-264)。推薦リストから常時除外する。

**mixed_805は独立区分**: 角番主効果(p=0.061)・debut主効果(p=0.702)ともに非有意。ただしdebut×X_DDSの交互作用のみ有意（[2.7](#27-debut_phaseh_nonjugは生存バイアスx_dds限定プレミアムの二重構造)参照）。

### セグメント別有効軸まとめ（Phase10e〜h）

| 軸 | h_jug | h_nonjug | v_jug | v_nonjug | mixed_805 |
|---|-------|----------|-------|----------|-----------|
| 角番 | 最強 F=51.3, p<0.001 | 有効 F=10.4, p<0.001 | 無効 p=0.137 | 有効 F=5.26, p=0.001 | 無効 p=0.061 |
| 末尾 | 有意 p<0.001(見かけ上) | 弱い p=0.038(DD混入で消滅) | 無効 p=0.265 | 弱い p=0.149 | 無効 p=0.423 |
| X_DDS | 有効 F=48.4 | 最強 F=172.8 | 有効 F=50.1 | 有効 F=16.7 | 弱い F=3.87 |
| X_DDS×角番 | 有意 p=0.006 | 最強 p<0.001 | 無効 p=0.908 | 無効 p=0.988 | 無効 p=0.145 |
| debut_phase | 弱い p=0.036 | 最強 p<0.001 | 有効 p=0.007 | 最強 p=0.001 | 無効 p=0.770 |
| debut×X_DDS | 弱い p=0.046 | 最強 p<0.001 | 最強 p=0.001 | 無効 p=0.740 | 最強 p<0.001 |

- **h_jug**: 全軸有効。角番が最強シグナルで、非イベント日でも堅牢
- **h_nonjug**: X_DDSとdebutが支配的。角番はX_DDS日限定でのみ機能（非イベント日は罠）
- **v_jug**: X_DDSのみ有効。角番・末尾は使えない（物理配置＝11台構成の縦列で角の意味が薄いことが原因、機種構成の偏りではないと確認済み）
- **v_nonjug**: debut_phaseと角番が有効だが、全体がマイナス圏のため回避が最優先
- **mixed_805**: debut×X_DDSの交互作用のみ。単独軸は弱い

### アンチパターン: セグメント混合ドミナンス

単価（ベース差枚水準）が異なるセグメントを混ぜて「全島横断トップ」を抽出すると、単価の高いセグメントが常に上位を占める。角番効果はホール全体では有意だが、これはh_jug/h_nonjugが引き上げているだけで、v_jug/v_nonjug/mixed_805では非有意。「セクション交替90%」「末尾交替88-92%」という初期仮説はこの混合アーティファクトによる誤検出だったため**撤回**（詳細は[3章](#3-否定された仮説と分析の罠)）。

---

## 2. 変数の効果と限界

### 2.1 角番（水平限定・最も堅牢）

**h_jug（構造的プレミアム、非イベント日でも堅牢）**:

| scope | corner1 avg_diff | plus_rate | n |
|-------|-----------------|-----------|---|
| 全日 | +463 | 59.1% | 1,610 |
| 非イベント日 | +407 | 57.3% | 1,091 |

rank1→4で+463→+259→+135→+6の単調減少。epsilon^2=0.007と効果量自体は小さいが、レジーム分割（境界2025-07-07）でpre/post両方corner1がtop1を維持（Spearman rho=**1.000**）— **唯一のレジーム耐性ありシグナル**。

**h_nonjug（corner1は非イベント日の罠）**:

| scope | corner1 avg_diff | n |
|-------|-----------------|---|
| X_DDS | +639 | 843 |
| 月末 | +729 | 121 |
| 非イベント日 | **-160** | 2,593 |

非イベント日は全バケット中最悪。**角番×イベント日の交互作用項として使う場合のみ有効で、単体使用は逆効果**。レジーム分割ではrho=0.800（corner2-4→corner2-4で維持だがcorner1の位置づけは不安定）。

**v_jug / v_nonjug（角番効果ほぼ無効）**: raw KW p=0.123（v_jug）、残差法（機種効果除去後）でもp=0.551で非有意。原因は物理配置（縦列は11台構成で角の意味が薄い）と確認済み——機種構成の偏りという対立仮説は残差法で棄却済み。レジーム分割でもv_jug rho=0.400、mixed_805 rho=0.400でともに崩壊。

**機種交絡の警告（繰り返し発生したアンチパターン）**:
- AT機角番4の好成績は特定台番号への機種固定配置の交絡
- 角番5のバウンス（rank4より高い）も機種固有の個別特性
- 「カバネリ512の角固有効果」は初代と海門決戦の機種同定ミスで訂正済み
- 主通路側（x=3）の機械割優位も機種名効果の交絡で、機種名除去後は7セクション中6セクションで有意性消失

**Bonferroni補正での注意**: DD個別の角番フラグは作らない。30回のMWU検定（5セグメント×6DD）のうちBonferroni補正後に有意なのはh_jug DD=7とDD=14の2件のみ。各セルn=51-54と薄く、DDごとにセグメント間で挙動が逆転する。`corner1 x is_xdds x jug_flag`の粒度に留める。

**X_DDS日のfine rank（1台単位）は単調減少ではない**: h_jug rank1=+566だがrank4=+83だけ急落（rank5=+370）。h_nonjugでrank2/4がrank1を上回る偶奇パターンが見えたが、セクション別分解でノイズと確定（MWU p=0.258）。**rank_from_aisleの生値ではなくcorner_bucket（1/2-4/5-9/10+）を使う**。

### 2.2 台番号末尾（純粋効果なし・全セグメントで否定）

**結論**: 蒲田7と異なり、みとやには**純粋な末尾効果は存在しない**。全セグメントで機種個体効果またはDD混入と判明している。

**h_jug（機種依存で否定）**: 非イベント日限定でp=6.2e-7と強有意に見えたが、machine_dependencyテストでd4のtop2_share=**96.0%**。台674（658-674の角番1、マイジャグラーV）がd4全体のavg_diffの**87.3%**を担っており、674を除外すると+135→+17に崩壊。d2も台642が55%を占め、除外で+124→+39に低下。**末尾に見えるものは全て角番効果または特定台の個体効果**。

**h_nonjug（DD混入で否定）**: 全日p=0.038→非イベント日限定でp=0.442に消滅。X_DDS日（DD4/14/24）の底上げが末尾4の台番号に統計的に乗っていただけの偽陽性。

**耐久性検証4系統の教訓**: h_jugの末尾はsplit-half（rho=0.891）・regime（Top3重複2/3）でPASSしていたが、machine_dependencyでFAIL。**split-half PASSは「特定台が前半も後半も強い」ことの反映に過ぎず、末尾という変数自体の効果ではない**。耐久性検証はsplit-half・regime・machine_dependency・corner制御の4系統で見る必要がある。

**唯一の限定的シグナル: dd_mod10一致x corner1**: 末尾と日付下1桁の一致（例: DD4かつ末尾4）はcorner1限定で有効（corner1で+446、corner2-4で+281、corner10+で+34まで低下）。末尾単独ではなく角番との交互作用としてのみ機能する。

### 2.3 DD — X_DDS二値で十分（トラフゾーンなし）

**結論**: 蒲田7のDD18-23のような明確なトラフゾーンはみとやに存在しない。DD full spectrumの有意性はX_DDS日（DD4/7/14/17/24/27）が引き上げているだけで、非X_DDS日側だけを取り出すと全セグメントで脱落する（p>0.4）。**DDは個別フラグではなくis_xdds（binary）で十分**。

**X_DDS日のavg_diff**（Phase9由来の参考値）:

| DD | avg_diff | n |
|---|---|---|
| dd4 | +276 | 4,769 |
| dd14 | +232 | 4,764 |
| dd24 | +216 | 4,766 |
| dd7 | +185 | 4,712 |

**耐久性検証（h_jug非イベント日限定）**: split-half rho=**0.891**（前半/後半top3重複2/3）、regime分割（境界2025-09-01）rho=**0.830**（top3重複2/3、フェーズ前1,2,4位→後2,3,4位でシフトあり）。

**ホール全体のKW検定は有意だがepsilon^2≈0** — 31グループに希釈されるため、必ずセグメント別に評価する。

### 2.4 曜日（角番効果の1/7以下、主軸にしない）

**結論**: 全期間検定で曜日軸単独の有意な機種はゼロ（DD軸>>曜日軸が確定済み）。h_jug/h_nonjug/v_jugのセグメント粒度ではKW有意（p<0.01）だが、曜日別avg_diff差は最大72（h_nonjug非イベント日: 金-38 vs 水-110）で、**角番効果の差(483)の1/7しかない**。X_DDS日限定ではh_nonjugのみ境界的有意(p=0.018)、他は脱落。

イベント日×曜日の交互作用はホール全体では非有意(p=0.069)。h_nonjugのみp=0.007だがepsilon^2は小さい。h_nonjug X_DDS曜日別: 火+393, 木+391, 水+348, 土+321, 月+205, **金+188**（他の半分程度）, 日+176。蒲田7の「イベント日×土曜逆効果」に相当するものはみとやでは見えない。

90日ウィンドウ限定ではマギアレコード（直近90日 p=3.0e-2, 効果量0.143, 土曜top）が例外的に検出されたが、その前90日は非有意で今期限定のノイズの可能性が高い。土曜26週の単発集計もsplit-half検証でrho≈-0.1と持続性がなく撤回済み。

### 2.5 X_DDS×角番の交互作用（水平限定）

2-way ANOVA（`diff ~ C(is_xdds_day) + C(corner_bucket) + C(is_xdds_day):C(corner_bucket)`）:

| segment | interaction F | interaction p | corner F | corner p | X_DDS F | X_DDS p |
|---------|-------------|---------------|----------|----------|---------|---------|
| h_jug | 4.16 | 0.006 | 51.3 | <0.001 | 48.4 | <0.001 |
| h_nonjug | **9.09** | **<0.001** | 10.4 | <0.001 | 172.8 | <0.001 |
| v_jug | 0.18 | 0.908 | 1.84 | 0.137 | 50.1 | <0.001 |
| v_nonjug | 0.04 | 0.988 | 5.26 | 0.001 | 16.7 | <0.001 |
| mixed_805 | 1.80 | 0.145 | 2.46 | 0.061 | 3.87 | 0.049 |

X_DDS×角番の交互作用は**水平セグメント（h_jug, h_nonjug）のみ**有意で、h_nonjugが最も強い。X_DDS日に角番勾配が約10倍に拡大する（h_nonjug corner1: X_DDS=+623 vs 非イベント=-164、差=483）。垂直島では交互作用なし。

**セクション内の異質性に注意**: 同一セクション・同一DDでも機種によって選好が正反対になる例がある（574-590のDD=4: 機種X +1720 vs 機種B -2584）。「セクション×DD」ルールは実質「機種×DD」ルールの代理変数であり、機種配置が変わると無効化される。

### 2.6 ゾロ目（台番号）— v_nonjugの回避強化のみ

ホール全体p=0.402で脱落。v_nonjugのみsegment内p<0.001だが、方向は「ゾロ目台がさらに悪い」（ゾロ目=-264 vs 非ゾロ目=-98）。蒲田7のゾロ目（+49、堅牢な正の優位）とは構造が異なり、**みとやではゾロ目に設定を入れる傾向がない**。ジャグラー×ゾロ目日×corner1に限定すると+187まで改善する例外はあるが（非ジャグラーでは-259と逆効果）、単独の狙い目にはならない。

### 2.7 debut_phase（h_nonjugは生存バイアス＋X_DDS限定プレミアムの二重構造）

**h_jug**: debut/growth期にプレミアムが持続し、時間経過で減衰（0-30日+136 → 31-60日+101 → 121日+ -7）。p=0.036で他セグメントより弱いが方向は単調。

**h_nonjug（逆V字、2つの仮説がともに支持）**: debut期avg_diff=-89.9 → mature期+107.9の逆転。3つの対立仮説を検証した結果:

| 仮説 | 検証結果 | 根拠 |
|------|---------|------|
| A: ホール戦略（後から設定UP） | 不明（直接検証不可） | — |
| B: 生存バイアス | **支持** | survived debut=-16.7 vs removed debut=-179.9（MWU p=0.003） |
| C: X_DDS限定プレミアム | **支持** | debut期のX_DDS=+52.2 vs 非イベント=-139.1 |

撤去された機種はdebut期から既に成績が悪く早期撤去されており（生存バイアス）、加えてdebut期の台でもX_DDS日限定なら期待値がプラスに転じる（限定プレミアム）。**両方が同時に成り立つ**——mature期の高成績は「設定変更」ではなく、生き残った機種＋イベント日の恩恵の合成。機種別improvementランキング上位: カバネリ海門(+844), かぐや様(+633), 炎炎2(+444)。

**レジーム分割での不安定性**: h_nonjugのdebut序列自体がレジーム境界（2025-07-07）前後でSpearman rho=**0.400**（崩壊）。matureはpre=-267→post=+134と反転しており、**debut_phaseルールは前提として不安定**。ML特徴量にする場合はwalk-forwardでの再学習が必須。

**mixed_805の交互作用構造**: debut主効果はp=0.702で非有意だが、debut×X_DDS交互作用はF=10.82, p<0.001。

| debut_phase | X_DDS avg_diff | 非イベント avg_diff | contrast |
|------------|---------------|------------------|----------|
| debut | +408.6 | -9.2 | +417.8 |
| growth | -169.2 | +100.5 | -269.8 |
| mature | +213.5 | +12.0 | +201.6 |

debutとgrowthがX_DDS日で正反対に振る舞い相殺するため、主効果としては消えて交互作用だけが残る構造。

### 2.8 機種別DD/曜日パターン（全機種横断スキャン）

`eda/machine_axis_pattern_scan.py`による全ホール横断DD軸スキャンで、みとやでも以下の機種が有意:

| 機種 | outcome | p値 | 効果量 | n |
|---|---|---|---|---|
| 東京喰種 | plus | 3.98e-11 | 0.122 | 5,360 |
| ジャグラーガールズ | plus | 4.79e-7 | 0.130 | 3,211 |

いずれも他ホールでも頻出する機種のため、みとや固有というより機種側の特性の可能性が高い。

**機種横断一致度スキャン（2026-07-02、Phase12）**: 「その日、何機種が自分自身の平均を上回ったか」をホール横断で二項検定した結果、みとやはDD軸3件（dd14=既知X_DDS・プラス、**dd22/dd29=novel・マイナス**）、曜日軸1件（土曜=既知週末・プラス）が有意。

機種単体検定では「クレアの秘宝伝〜はじまりの扉と太陽の石〜 ボーナストリガーver.」のdd27がone-vs-rest二項検定+FDR補正で個体として有意（q=0.0005, +36.6pt, hit104率62.1%）。ただしdd27はホール横断一致度スキャンでは有意になっておらず、**機種固有の反応であってホール全体の投入パターンではない**。曜日軸では「ありふれた職業で世界最強」(+23.6pt)、「スマート沖スロ ニューキングハナハナV」(-14.1pt、逆方向)の2台が個体として有意——同じ土曜でも機種によって方向が割れている。

**DD Bin軸（1-7,8-14,15-21,22-28,29-31）での検証（2026-07-03）**: 「クレアの秘宝伝」のdd27信号は週単位のBinにまとめると**消える**。dd軸ではhit104効果量0.204（p=2.4e-4、有意）だったが、dd_bin軸では22-28日のBinに均されて効果量0.086（p=0.037。p値だけ見ると有意に見えるが、本プロジェクトの実用閾値0.1を下回るため非シグナル扱い）まで低下。理由はdd27単独が62.1%と突出する一方、同じBin内のdd22-26/28は平均25%前後の平凡な値で、これらに埋もれてしまうため。**「クレアの秘宝伝＝週単位の投入」ではなく「dd27という特定の1日の投入」という解釈が正しい**（→`document/instincts/2026-07-02-dd-bin-axis-double-edged-sword-insights.yaml`）。

### 2.9 104%率分析 — 蒲田7手法の導入検証

蒲田7はDDを104%率で分析しDD18-23のトラフゾーンを発見した。同手法をみとやに導入し、既存の差枚ベースの結論を検証した。

**DD×104%率のピーク/トラフ構造**:

| category | Top5 DD | rate_104 | is_xdds |
|----------|---------|----------|---------|
| peak | DD4(33.8%), DD14(33.4%), DD24(32.5%), DD27(32.1%), DD17(32.1%) | 32-34% | 全てX_DDS |
| trough | DD23(28.3%), DD1(28.2%), DD18(27.8%), DD22(27.8%), DD29(27.0%) | 27-28% | 全て非X_DDS |

ピーク/トラフ差=**6.8pp**（蒲田7は4.3pp）。ただし蒲田7のDD18-23のような特定範囲への集中は見えず、DD1/22/29など分散している——[2.3](#23-dd--x_dds二値で十分トラフゾーンなし)の「明確なトラフゾーンはない」という結論と整合。

**差枚と104%率の相関**: ホール全体Spearman rho=**0.873**（p<0.001）。差枚ランキングと104%率ランキングはほぼ一致し、蒲田7で見られた「設定4集中 vs 設定6一点」の乖離は小さい。**みとやの分析は差枚ベースで十分、104%率への切り替えは不要**。

**角番×104%率**: h_jugは差枚・104%率の両方でcorner1→2→3→4の順位が**完全一致**——corner1の構造的プレミアムがさらに補強される。mixed_805は差枚(corner2-4→10+→1→5-9)と104%率(corner10+→5-9→2-4→1)で順位が大きく乖離しており、差枚の高さが少数台の爆発（設定6一点型）に依存している可能性がある。

---

## 3. 否定された仮説と分析の罠

### 3.1 否定された仮説一覧

| # | 仮説 | 否定の根拠 | 参照 |
|---|------|-----------|------|
| 1 | みとやに純粋な末尾効果がある | h_jug d4のtop2_share=96%。台674の個体効果で674除外後+135→+17 | mitoya-no-pure-digit-effect |
| 2 | h_nonjugの末尾有意(p=0.038)は本物 | 非イベント日限定でp=0.442に消滅。DD混入の偽陽性 | mitoya-h-nonjug-digit-dd-contamination |
| 3 | split-half PASSなら末尾効果は堅牢 | h_jug d4はsplit-half PASSでもmachine_dependency FAIL | mitoya-digit-durability-split-half-stable-but-machine-dependent |
| 4 | v_jugに末尾効果がある | 全日p=0.265, 非イベント日p=0.474で非有意 | vjug-no-digit-effect-confirmed |
| 5 | v_jugに角番効果がある | raw p=0.123、残差法p=0.551。物理配置（11台構成）が原因、機種構成の偏りではない | vjug-corner-effect-absent-physical-layout |
| 6 | DD個別(4,7,14,17,24,27)の角番フラグが有効 | 30回検定中Bonferroni補正後有意はh_jug DD=7,14の2件のみ | mitoya-dd-individual-corner-not-reliable |
| 7 | X_DDS日のfine rank(1-5)は単調減少 | rank4だけ急落、偶奇パターンもノイズ(MWU p=0.258) | mitoya-xdds-fine-rank-not-monotonic |
| 8 | X_DDS×角番の交互作用は全セグメントで有効 | v_jug p=0.908, v_nonjug p=0.988, mixed_805 p=0.145。水平限定 | xdds-corner-interaction-horizontal-only |
| 9 | h_nonjugのmature高成績はホールが設定を上げたから | survived debut=-16.7 vs removed debut=-179.9(p=0.003)。生存バイアス | h-nonjug-debut-survival-bias-confirmed |
| 10 | debut_phaseの序列はレジームを跨いで安定 | h_nonjug rho=0.400（崩壊）。matureがpre=-267→post=+134に反転 | mitoya-debut-effect-regime-dependent |
| 11 | DD full spectrumに非X_DDSのトラフゾーンがある | composite分析でX_DDS側は全セグメント脱落。有意性はX_DDS日だけが引き上げ | mitoya-dd-fullspectrum-no-trough-zone |
| 12 | 曜日が台選びの主軸になる | 最大効果量epsilon^2=0.001。曜日差は角番差の1/7 | mitoya-weekday-small-effect-nonevent-only |
| 13 | 台番号末尾ゾロ目が正のシグナルになる | ホール全体p=0.402。v_nonjugのみ有意だが方向は回避強化 | mitoya-zorome-machine-v-nonjug-avoidance-amplifier |
| 14 | v_nonjugセグメントで打つ価値のある条件がある | 全角番帯マイナス。ゾロ目台はさらに悪化(-264) | mitoya-v-nonjug-avoid-segment |
| 15 | 単一戦略が全ウィンドウを支配する | Shortlist/CornerRule/MachineCornerのどれもPeriod間で崩れる窓あり | mitoya-no-single-strategy-dominates-all-windows |
| 16 | セクション交替90%／末尾交替88-92% | 全島混合トップ抽出の方法論的アーティファクト、ランダム期待値と区別不可 | mitoya-dd-group-section/digit-antipattern-RETRACTED |
| 17 | 給料日仮説（5・15・25日にジャグラーが熱い） | 実差0.4ptで誤差範囲 | mitoya-juggler-payday-hypothesis-rejected-by-data |
| 18 | diff_std<medianフィルタでQ5(高設定)を選定 | 実際はQ5"回避"フィルタとして機能。逆効果 | mitoya-rule2-screening-backtest-fails-q5-prediction |
| 19 | 異機序バケットの統合モデル | 個別モデルより性能低下 | positive-combined-mode-degrades-performance |

### 3.2 分析上のアンチパターン（みとや固有 — 7類型）

#### パターン1: 鉄台による偽シグナル（台固有性）
**検出方法**: machine_dependencyテストでtop2_shareを算出し、top2を除外して再検定。50%以上なら個体効果を疑う。
**実例**: h_jug末尾d4のtop2_share=96%。台674（マイジャグラーV）がd4全体の87.3%を担う。

#### パターン2: セグメント未分割の全体集計（Simpson's Paradoxリスク）
**検出方法**: セグメント別にランキングを出し全体集計と比較。二極化していれば全体集計は参考値に留める。
**実例**: 角番効果はホール全体で有意だがv_jug/v_nonjug/mixed_805では非有意。h_jug/h_nonjugが引き上げていただけ。

#### パターン3: 個体効果の交絡（split-half PASSの罠）
**検出方法**: split-half PASSとmachine_dependency FAILの組み合わせを検出。
**実例**: h_jug d4はsplit-half rho=0.891でPASSしたがmachine_dependencyでFAIL（top2_share=96%）。

#### パターン4: レジーム変化混入
**検出方法**: レジーム分割でpre/postのSpearman rhoを比較。0.5未満なら崩壊とみなす。
**実例**: h_nonjugのdebut序列はrho=0.400で崩壊。h_jugの角番のみrho=1.000で安定。

#### パターン5: DD混入偽陽性（みとや固有）
**検出方法**: 全日で有意でも非イベント日限定で再検定。消滅すればDD混入。
**実例**: h_nonjug末尾d4は全日p=0.038→非イベント日p=0.442に消滅。

#### パターン6: 生存バイアス（みとや固有）
**検出方法**: survived（181日以上）とremoved（180日以下で撤去）に分け、debut期のavg_diffを比較。
**実例**: h_nonjugのsurvived debut=-16.7、removed debut=-179.9（p=0.003）。

#### パターン7: 主効果なし交互作用のみ（みとや固有）
**検出方法**: 2-way ANOVAで主効果と交互作用を分離。交互作用のみ有意ならセル分解で駆動セルを特定。
**実例**: mixed_805のdebut主効果はp=0.702だが、debut×X_DDSはF=10.82, p<0.001。

---

## 4. 蒲田7との構造比較

| 項目 | 蒲田7 | みとや |
|------|------|------|
| 生存バイアス | なし（survived debut=-194 vs removed=-124, p=0.60） | **あり**（survived=-17 vs removed=-180, p=0.003） |
| 原因 | 大規模(535台), stability=0%, 定期入替 | 小規模(266台), 成績ベース撤去 |
| 角番の構造性 | A機セグメント(top2_share<7%)で構造シグナル | h_jug（レジームrho=1.000）で構造シグナル |
| 末尾効果 | 3F_L_N d8/d9は台特定シグナル(top2_share=54-76%) | 全セグメントで否定（台674の個体効果、top2_share=96%） |
| DD構造 | DD18-23トラフゾーン、DD full spectrumが有効 | X_DDS引き上げのみ、トラフなし。is_xdds binaryで十分 |
| 差枚 vs 104%率 | 乖離あり（設定4集中 vs 設定6一点の判別に有用） | 高相関(rho=0.873)、切り替え不要 |
| 曜日 | AT×土曜のみ堅牢(top2_share=7.4%) | 全セグメントで効果量が小さい(epsilon^2<=0.001) |
| ゾロ目 | +49で堅牢（桁別・末尾別で差あり） | ホール全体非有意。v_nonjugで回避強化のみ |

**含意**: 両ホールとも「全体集計は信用できない、セグメント分割必須」という大原則は共通するが、具体的にどの変数が効くかは正反対に近い（末尾・ゾロ目はみとやで全否定、生存バイアスは蒲田7でなくみとやで発生）。[[feedback-no-cross-hall-pooling]]の通り、ホール横断の共通法則を前提とした解釈はしない。

---

## 5. 統合 — 台選びフロー

### Step 1: セグメントを判定する

| segment | セクション | 有効軸 | 判定 |
|---------|-----------|--------|------|
| h_jug | 641-657, 658-674(reversed), 675-691 | 角番◎ 末尾◎(見かけ上) X_DDS◎ | **最優先** |
| h_nonjug | 501-522〜608-623, 624-640(reversed) | X_DDS◎ debut◎ 角番○(X_DDS限定) | 主力 |
| v_jug | 712-722, 723-733, 734-744 | X_DDSのみ | 補助 |
| mixed_805 | 805-815 | debut×X_DDS交互作用のみ | 補助 |
| v_nonjug | 692-700, 701-711, 745-755 | — | **常時回避** |

(reversed)=台番号の並びと通路方向が逆のセクション。corner1の物理的な向きに注意。

### Step 2: 当日の日付属性を確認する

- **X_DDS判定**: DD in {4,7,14,17,24,27}か（実運用では1,30も含めた拡張版を使うことがある）
- **曜日は無視してよい**（角番効果の1/7以下）
- **DD個別のトラフゾーンは想定しない**（is_xdds二値で十分）

### Step 3: 角番ルールを適用する

**X_DDS日**:
1. h_jug corner1（641, 658(reversed), 675の角番1台）— avg_diff+463、勝率59.1%
2. h_nonjug corner1-4 — avg_diff+639（corner1）、非イベント日の10倍に拡大
3. v_jug — 角番ルールなし、セクション平均で判断
4. mixed_805 — debut機種を優先（+409）

**非イベント日**:
1. h_jug corner1のみ — avg_diff+407、勝率57.3%（非イベント日でも有効な唯一のルール）
2. h_nonjug corner1は**罠**（-160）— 角番を使わない
3. v_jug / mixed_805 — 期待値が低く、打たない選択肢も検討

### Step 4: セクション内優先度（h_jug）

| 順位 | section | corner1 avg_diff | 特徴 |
|------|---------|-----------------|------|
| 1 | 641-657 | +542 | 全セクション最強、勝率61.9% |
| 2 | 675-691 | +266 | 成熟台ベースで安定 |
| 3 | 658-674 | corner10+=+165 | reversedのため角番を逆方向に数える |

### Step 5: 特殊ルール — DD=24

h_nonjugのcorner1にDD=24限定で高設定投入の再現性が高い（18日中16日プラス、平均+1147）。適用条件: `dd==24 and segment==h_nonjug and rank_from_aisle==1 and section!='523-539'`（523-539のDD=24 corner1は-770で例外）。n=143と薄いためML特徴量ではなくルールベース補正として保持する。

### Step 6: 末尾・ゾロ目・debut_phaseで微調整する（補助的）

- 末尾単独では選ばない（純粋効果なし）。corner1に座れた場合のみdd_mod10一致を追加材料にする
- h_jug×ゾロ目日×corner1の組み合わせでのみ+187の上乗せ（h_nonjugでは-259と逆効果）
- h_jug狙いは新しめの台（debut〜growth期）、h_nonjug狙いはmature台を優先。ただしh_nonjugの逆転パターンはレジーム依存で不安定

### 外れた時の切り分け

1. **v_nonjugを選んでいないか？** — 全条件で回避対象
2. **h_nonjugでcorner1の罠を踏んでいないか？** — 非イベント日にh_nonjug corner1を選んでいたら敗因の筆頭候補
3. **末尾単独で選んでいないか？** — みとやに純粋な末尾効果はない
4. **鉄台依存ではなかったか？** — 台674等、特定台への依存を確認
5. **レジーム変化（機種入替）が起きていないか？** — 266台中204台が入替済みという高い流動性を前提に、直近データで再確認する

---

## 6. MLモデル構造と運用知見

### hist_metricが最強シグナル

セクションレベルの特徴量群の中で、hist_metric（台個別の過去成績）が最も強い予測力を持つ（rho=+0.042, p<0.0001, D0→D9で+7.4pp）。蒲田7の知見（hist_metricのみが実効シグナル）と同じ傾向。

### セクションレベル単体には予測シグナルがない

セクション単位の集計だけでは予測シグナルがほぼ存在しない。角番・セグメント・debut_phaseまで分解して初めて意味のある差が出る。

### 戦略比較 — X_DDS日はCornerRuleが最強、通期はMachineCornerだが不安定

| scope | Target_avg_diff | Shortlist | CornerRule | MachineCorner |
|-------|-----------------|-----------|------------|----------------|
| X_DDS日 | 339.18 | 620.15 (+280.97) | **652.24 (+313.07)** | 605.52 (+266.34) |
| 全体 | 61.371 | 193.03 (+131.66) | 185.48 (+124.11) | **226.64 (+165.27)** |

ウィンドウ別（5期間）ではCornerRuleが3→4期間で-6.42と逆転する窓があり、**単一戦略が全ウィンドウを支配することはない**。複数戦略のアンサンブルが必須。

### X_DDS日ではc_cornerとc_dow_secが反予測的

X_DDS日限定の予測では、角番コンポーネント(c_corner)と曜日×セクション(c_dow_sec)がむしろ逆相関(rho=-0.052/-0.041)。X_DDS日は通常日と別モデル・別重みで扱うべき。

### 学習範囲・特徴量設計

- **x_day限定学習が全期間学習より優秀**: Spearman 0.2916 vs 0.2786
- **機種名の正規化（全履歴書き換え）は逆効果**: 266台中204台(76%)が機種名変更済み。walk-forward集約特徴量（machine_avg_diff_wf等）の方が優秀（Spearman 0.2936）
- **位置特徴量はトレードオフ**: hit@1をわずかに悪化(-1.4pp)させるが、mean_diffは+288%改善——単発の的中率より期待値重視の設計と整合
- 新店長期間へのsample_weight増強は効果なし（データ量不足）
- 高分散戦略（diff_std>=median & payout>=100%）はQ5到達率を1.5倍に高め、split-halfで再現性も確認済み（信頼度0.55→0.7）——ハイリスク・ハイリターン狙いの補助戦略として有効

---

## 7. 未探索ロードマップ

### 優先度: 高

| # | 項目 | 現状 | 必要な作業 |
|---|------|------|-----------|
| 1 | **104%率とavg_diffの評価軸の齟齬解消** | rate_104(27-34%)とhit_rate_104≈0%が同時に主張されている | 両指標の定義差分を確認し、[1章](#1-セグメント構造--なぜ全体集計は信用できないか)の未解決注記を解消する |
| 2 | **鉄台の系統的抽出** | 台674等、個別発見のみ | 蒲田7の機種入替台帳に相当する入替台帳の構築、pos_rate>=60%台の一覧化 |
| 3 | **曜日運営仮説の直接検証** | 統計的にはほぼ無効と判定済み | ぽこリスト等の外部情報源との突合が未実施 |

### 優先度: 中

| # | 項目 | 期待される価値 |
|---|------|---------------|
| 4 | mixed_805専用ルールの探索 | 「既存ルール非適用」で終わっているが、独自軸が眠っている可能性 |
| 5 | h_nonjug debut_phase逆転の安定化条件の特定 | regime依存で不安定なため、反転を引き起こす条件（機種構成比の変化等）の特定 |
| 6 | OKF形式への段階的移行 | [[project-okf-migration-decision]]で合意した個別台信号レジストリを、みとやの鉄台リスト（台674等）から試験導入する |

### 優先度: 低（将来検討）

| # | 項目 |
|---|------|
| 7 | 機種横断DD/曜日スキャン（東京喰種等）のみとや固有性の切り分け |
| 8 | 時系列的なパターン変化の追跡（月次・四半期単位の監視） |

---

## 8. Instinct参照マップ

**用語・定義**: `mitoya-section-numeric-range-pitfall`, `aisle-corrected-rank-5x-epsilon-improvement`, `mitoya-event-day-definition-and-selection-bias-in-min-games-filter`, `mitoya-bari-island-nonexistent`, `mitoya-5segment-definition-validated`

**角番**: `mitoya-h-jug-corner1-structural-premium`, `mitoya-h-nonjug-corner1-event-only-trap`, `mitoya-corner-effect-orientation-dependent`, `mitoya-dd24-h-nonjug-corner1-rule-based`, `mitoya-dd-individual-corner-not-reliable`, `mitoya-xdds-fine-rank-not-monotonic`, `vjug-corner-effect-absent-physical-layout`, `xdds-corner-interaction-horizontal-only`, `at-corner4-confound-by-machine-placement`, `corner5-bounce-is-machine-specific-not-structural`, `mitoya-kabaneri-corner-effect-was-wrong-machine-correction`

**末尾**: `mitoya-no-pure-digit-effect`, `mitoya-h-nonjug-digit-dd-contamination`, `mitoya-digit-durability-split-half-stable-but-machine-dependent`, `vjug-no-digit-effect-confirmed`

**DD/曜日**: `mitoya-dd-axis-dominates-weekday-axis-confirmed`, `mitoya-dd-fullspectrum-no-trough-zone`, `mitoya-weekday-small-effect-nonevent-only`, `mitoya-event-weekday-interaction-h-nonjug-friday-weak`, `mitoya-104pct-confirms-diff-based-analysis`

**セクション/セグメント**: `mitoya-section-dd-effect-is-machine-dd-effect`, `mitoya-within-section-dd-heterogeneity`, `mitoya-segment-is-section-not-lr-an`, `mitoya-v-nonjug-avoid-segment`

**debut_phase**: `h-nonjug-debut-survival-bias-confirmed`, `mitoya-debut-effect-regime-dependent`, `mixed-805-debut-xdds-interaction-driver`

**ゾロ目**: `mitoya-zorome-machine-v-nonjug-avoidance-amplifier`

**機種**: `machine-name-contamination-in-ml-training`, `machine-name-normalization-hurts-accuracy`, `machine-name-walkforward-agg-features-b-plan`, `cross-hall-machine-name-persistence-generalizes`

**ML/キャリブレーション**: `mitoya-hist-metric-strongest-signal`, `mitoya-section-level-no-signal`, `mitoya-corner-rule-xdds-strongest`, `mitoya-machine-corner-best-overall-but-unstable`, `mitoya-no-single-strategy-dominates-all-windows`, `xday-scope-training-beats-full-period`

**否定された仮説・方法論**: `mitoya-dd-group-section-antipattern-RETRACTED`, `mitoya-dd-group-digit-antipattern-RETRACTED`, `mitoya-juggler-payday-hypothesis-rejected-by-data`, `mitoya-saturday-screening-retracted-no-persistence`, `cross-segment-aggregation-creates-dominance-artifact`, `mitoya-island-mixing-artifact-warning`, `mitoya-period-sum-diff-overstates-magnitude-by-ndays`, `mitoya-daily-hall-summary-null-flags`

**横断スキャン(2026-07-02)**: `document/instincts/2026-07-02-machine-dd-cross-agreement-insights.yaml`, `document/instincts/2026-07-02-machine-weekday-cross-agreement-and-power-limits-insights.yaml`
