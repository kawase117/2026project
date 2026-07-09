# ホール分析手順書 — 蒲田7メソッドの一般化

> **目的**: 新しいホールを分析するとき、蒲田7で確立した手順を再現可能な形で適用する。  
> **前提**: ana-slo.comからデータ取得済み、DBに投入済み。最低90日のデータがあること。  
> **最終更新**: 2026-06-27  
> **関連**: `document/kamata7_theory.md`（蒲田7の完成形）

---

## 全体フロー

```
Phase 0: データ基盤の確認
  ↓
Phase 1: 物理レイアウトの取得とセグメント決定  ← 最重要・最初にやる
  ↓
Phase 2: 角番定義の確定
  ↓
Phase 3: 変数スクリーニング（何が効くかの粗探索）
  ↓
Phase 4: 効果の耐久性検証
  ↓
Phase 5: ホール固有の法則仮説の構築
  ↓
Phase 6: MLスコアリングモデルへの組み込み
```

---

## Phase 0: データ基盤の確認

### 0.1 データ量の確認

```sql
SELECT hall_name, COUNT(DISTINCT date) as n_days,
       COUNT(DISTINCT machine_number) as n_machines,
       MIN(date) as first_date, MAX(date) as last_date
FROM machine_detailed_results
WHERE hall_name = '{ホール名}'
GROUP BY hall_name;
```

| 条件 | 最低要件 | 推奨 |
|------|---------|------|
| 日数 | 90日 | 180日+ |
| 台数 | 50台+ | 100台+ |

90日未満では季節効果とレジーム変化を分離できない。

### 0.2 hall_config.json の確認

`config/hall_config.json` に対象ホールが登録されていることを確認:
- `event_settings.event_digits`: イベント日DD（ホール固有）
- `event_settings.anniversary_date`: 周年記念日
- `layout_settings.reversed_sections`: 逆順セクション（Phase 2で決定）

**注意**: イベント日定義はホールごとに完全に異なる。蒲田7の「7のつく日+1のつく日」を他ホールに流用しない。ぽこリスト、店のSNS、実地観察から定義する。

### 0.3 min_games フィルタの確認

```python
# ホール全体のG数分布を確認
df.groupby('hall_name')['games_normalized'].describe()
```

蒲田7ではmin_games=1500だが、小規模ホールや低稼働ホールでは500-1000が適切な場合がある。中央値の50%を目安にする。

---

## Phase 1: 物理レイアウトの取得とセグメント決定

### なぜ最初にやるのか

**全ての下流分析はセグメントが間違っていると汚染される。**

蒲田7での教訓:
- 全体集計でA機Top3(d3/d4)とN機Top3(d6/d8)が逆相関 → Simpson's Paradox
- セグメントを先に決めないと、法則性の有無を正しく判定できない

### 1.1 台番号の物理配置を把握する

#### 方法A: 座標CSVがある場合

`Heatmap/{ホール名}_floor_coordinates.csv` があれば、X/Y座標で島の構造がわかる。

```python
import pandas as pd
coords = pd.read_csv(f'Heatmap/{ホール名}_floor_coordinates.csv')
# section列がある場合、それが物理的な島単位
coords.groupby('section').agg({
    'machine_number': ['min', 'max', 'count'],
    'X': 'nunique',
    'Y': 'nunique'
})
```

#### 方法B: 座標CSVがない場合（大半のホール）

台番号の連続性から島を推定する:

```python
# 1. 台番号の連続ブロックを検出
machines = sorted(df['machine_number'].unique())
sections = []
current = [machines[0]]
for i in range(1, len(machines)):
    if machines[i] - machines[i-1] <= 2:  # 1-2番の飛びは同一島内
        current.append(machines[i])
    else:
        sections.append(current)
        current = [machines[i]]
sections.append(current)

# 2. 各セクションのサイズと番号範囲を確認
for i, sec in enumerate(sections):
    print(f"Section {i}: {sec[0]}-{sec[-1]} ({len(sec)}台)")
```

**注意**: 台番号が飛ぶ基準（gap=2 or 3 or 10）はホールの台番号付番ルールに依存。必ず実際のデータで確認する。

#### 方法C: 実地確認（最も確実）

可能であれば実際にホールに行き、以下を確認:
- 何フロアあるか
- 各フロアの島の数と配置
- 各島の台数
- 通路の位置（角番の起点）
- A機（ジャグラー/ハナハナ）とN機（AT系）の配置

### 1.2 セグメント分割の決定

#### 分割軸の候補（優先度順）

| 軸 | 判断基準 | 蒲田7での実績 |
|----|---------|-------------|
| **フロア** | 複数フロアなら必ず分割 | 2F/3F分割で効果が劇的に異なった |
| **A機/N機** | 機種名でジャグラー/ハナハナを判定 | A/Nで最適末尾が完全逆転 |
| **物理的な左右** | X座標の中央値で分割 | F値はLR=0.03で無効だった |
| **島サイズ** | small/medium/large | F値=32.41で最も有効 |

#### 分割の手順

```
Step 1: フロア分割
  → 複数フロアなら必ず分ける

Step 2: A/N分割
  → 機種名に「ジャグラー」「ハナハナ」を含む台 = A機
  → それ以外 = N機
  → A機が全体の10%未満なら分割しない（検定力不足）

Step 3: セクションサイズの確認
  → 島ごとの台数を集計
  → small(≤8), medium(9-14), large(15+) のバランスを確認

Step 4: LR分割の必要性を判定
  → 蒲田7ではLR分割のF値が0.03で無効だった
  → 他ホールでも安易にLR分割しない
  → LR分割を入れるなら、F値でsection_sizeと比較して判断
```

#### セグメント数の目安

| ホール規模 | 推奨セグメント数 | 注意 |
|-----------|---------------|------|
| 小規模（100台未満） | 2-3 | A/N分割のみ、またはフロア分割のみ |
| 中規模（100-300台） | 3-4 | フロア×A/N |
| 大規模（300台+、蒲田7級） | 4-6 | フロア×LR×A/N（LRが有効な場合のみ） |

**1セグメント50台未満は統計的に危険**。検定力が不足し、少数台依存の偽シグナルを生む。

### 1.3 セグメント分割の検証

分割が正しいかを検証する:

```python
# セグメント間でavg_diffの分布が異なることを確認
from scipy.stats import kruskal
for seg in segments:
    data = df[df['segment'] == seg]['diff_coins_normalized']
    print(f"{seg}: n={len(data)}, mean={data.mean():.0f}, std={data.std():.0f}")

# セグメント間のKruskal-Wallis
stat, p = kruskal(*[df[df['segment']==s]['diff_coins_normalized'] for s in segments])
print(f"KW p={p:.6f}")
```

p<0.05 でないなら、その分割は意味がない。

---

## Phase 2: 角番定義の確定

### 2.1 角番の3つの定義

| 定義 | 説明 | いつ使うか |
|------|------|----------|
| **rank_from_min** | 台番号最小からの順位 | 台番号が通路→奥に昇順のホール |
| **rank_from_max** | 台番号最大からの順位 | 台番号が通路→奥に降順のホール |
| **rank_from_aisle** | 通路からの物理距離 | 交互配置のホール（みとやなど） |

### 2.2 どの定義を使うかの判定手順

```
Step 1: 台番号の並び方向を確認
  → 島ごとに台番号の最小と最大を調べる
  → 通路側がmin? max? 島ごとに異なる?

Step 2: 島ごとの並び方向が統一されているか確認
  → 統一: rank_from_min または rank_from_max を使う
  → 交互（島ごとに逆転）: rank_from_aisle が必要

Step 3: 交互配置の場合、reversed_sections を特定する
  → hall_config.json の layout_settings.reversed_sections に登録
  → DBの rank_from_aisle が自動計算される
```

#### 交互配置の検出方法

座標CSVがある場合:
```python
# 各セクション内で台番号とX座標の相関を見る
for section in coords['section'].unique():
    sec = coords[coords['section'] == section]
    corr = sec['machine_number'].corr(sec['X'])
    print(f"{section}: corr={corr:.3f} {'→reversed' if corr < 0 else '→normal'}")
```

座標CSVがない場合:
- 実地確認が必要
- または、rank_from_min と rank_from_max の両方でKruskal-Wallis検定を行い、ε²が大きい方を採用

### 2.3 角番定義の検証

**蒲田7での教訓**: 角番の効果はε²で5倍の差がつくことがある（みとやの事例）。定義を間違えると「角番効果なし」と誤判定する。

```python
# 3つの定義でKW検定を比較
for rank_col in ['rank_from_min', 'rank_from_max', 'rank_from_aisle']:
    stat, p = kruskal(*[
        seg_df[seg_df[rank_col] == k]['diff_coins_normalized']
        for k in seg_df[rank_col].unique()
    ])
    epsilon_sq = stat / (len(seg_df) - 1)
    print(f"{rank_col}: ε²={epsilon_sq:.6f}, p={p:.6f}")
```

ε²が最大の定義を採用する。

---

## Phase 3: 変数スクリーニング（粗探索）

### 探索原則

**粗く網羅的 → 細かく限定的**の段階的絞り込み。

蒲田7で検証した全変数を、蒲田7の結論を持ち込まずに各ホールで独立にスクリーニングする。

### 3.1 スクリーニング対象変数

| 変数 | テスト | 蒲田7での結果 | 他ホールで異なる可能性 |
|------|--------|-------------|-------------------|
| 角番 | KW検定 by kakuban | 全セグメントp<0.001 | **方向は同じ可能性高**（物理的な理由） |
| 台番号末尾 | KW検定 by last_digit | セグメント依存 | **完全にホール固有** |
| DD（日付の日） | KW検定 by dd | 単独無効 | ホールのイベント日に強く依存 |
| 曜日 | KW検定 by weekday | AT群×土曜のみ安定 | **ホール間で逆方向**（蒲田7水曜↑/蒲田1水曜↓） |
| イベント日 | MW検定 event vs non-event | A機に集中 | イベント日定義がホール固有 |
| ゾロ目 | MW検定 zorome vs non-zorome | +49差 | 効果の大小はホール次第 |
| 経過日数 | 3フェーズ比較 | 全9ホール単調改善 | **方向のみ移植可能** — 水準はホール次第 |

### 3.2 スクリーニング手順

各変数について、**セグメント別に** Kruskal-Wallis 検定を実行:

```python
from scipy.stats import kruskal, mannwhitneyu

for segment in segments:
    seg_df = df[df['segment'] == segment]
    
    # 角番
    groups = [seg_df[seg_df['kakuban']==k]['diff_coins_normalized']
              for k in sorted(seg_df['kakuban'].unique())]
    stat, p = kruskal(*groups)
    print(f"[{segment}] 角番: p={p:.6f}")
    
    # 末尾
    groups = [seg_df[seg_df['last_digit']==str(d)]['diff_coins_normalized']
              for d in range(10)]
    stat, p = kruskal(*groups)
    print(f"[{segment}] 末尾: p={p:.6f}")
    
    # 以下同様にDD、曜日、イベント日、ゾロ目...
```

**判定基準**:
- p < 0.01: 有望 → Phase 4で耐久性検証へ
- 0.01 ≤ p < 0.05: 要注意 → 効果量(ε²)も確認
- p ≥ 0.05: 脱落

### 3.3 蒲田7との比較で注意すべき点

| 項目 | 蒲田7で確定した事実 | 他ホールへの移植可否 |
|------|-------------------|-------------------|
| 角番中間台優位 | 堅牢（構造シグナル） | **移植可能性高い** — ただし「中間台」の位置は島サイズに依存 |
| A機の末尾無効 | 全粒度でp>0.3 | **移植禁止** — ホール固有の法則がある可能性 |
| 曜日効果 | 蒲田7水曜↑/金曜↓ | **移植禁止** — 蒲田1では完全に逆 |
| イベント日定義 | 7/1系+ゾロ目+月末 | **移植禁止** — ホールごとにevent_digitsが異なる |
| 3フェーズモデル | 方向は全9ホール共通 | **方向のみ移植可能** — 水準はホール次第 |
| DD18-23トラフゾーン | 蒲田7で確認 | **要検証** — 給料日前の行動パターンは共通かもしれない |

---

## Phase 4: 効果の耐久性検証

Phase 3で有望と判断された変数に対して、**偽シグナルでないことを確認**する。

### 4.1 3テスト検証

| テスト | 方法 | 判定 |
|--------|------|------|
| **Split-half** | 前半/後半で効果の方向が一致するか | 不一致 → レジーム変化の疑い |
| **鉄台除外** | pos_rate>=60% or median>=0 の台を除外して再検定 | 消滅 → 少数台依存 |
| **低稼働日除外** | min_games以下の日を除外 | 大幅変化 → ノイズ依存 |

### 4.2 台固有性の定量化

```python
# 効果量のtop1/top2台への依存度
for seg in segments:
    seg_df = df[df['segment'] == seg]
    machine_effect = seg_df.groupby('machine_number')['diff_coins_normalized'].mean()
    total_effect = machine_effect.sum()
    top1_share = machine_effect.max() / total_effect
    top2_share = machine_effect.nlargest(2).sum() / total_effect
    print(f"[{seg}] top1_share={top1_share:.1%}, top2_share={top2_share:.1%}")
```

| top2_share | 判定 |
|-----------|------|
| <10% | 構造シグナル（安全） |
| 10-30% | 少数台依存（注意） |
| >30% | 特定台効果（危険） |

### 4.3 機種入替の影響確認

```python
# 各台の機種変更回数を確認
machine_changes = df.groupby('machine_number')['machine_name'].nunique()
stability = (machine_changes == 1).mean()
print(f"Stability rate: {stability:.1%}")
```

2Fのstability=0%（蒲田7）のような場合、末尾法則はレジーム変化に脆い。

---

## Phase 5: ホール固有の法則仮説の構築

### 5.1 イベント日の特定

hall_config.jsonの`event_digits`を起点に、実際の104%率でイベント日効果を検証:

```python
for dd in range(1, 32):
    day_df = df[df['dd'] == dd]
    rate104 = (day_df['payout'] >= 104).mean()
    avg_diff = day_df['diff_coins_normalized'].mean()
    print(f"DD{dd:2d}: 104%率={rate104:.1%}, avg_diff={avg_diff:+.0f}, n={len(day_df)}")
```

event_digitsで定義されたDDと、実際にピークが出るDDが一致するか確認。不一致ならイベント日定義を修正する。

### 5.2 曜日パターンの発見

```python
# 曜日別の104%率（ホール全体）
for dow in range(7):
    dow_df = df[df['weekday'] == dow]
    rate104 = (dow_df['payout'] >= 104).mean()
    avg_diff = dow_df['diff_coins_normalized'].mean()
    print(f"曜日{dow}: 104%率={rate104:.1%}, avg_diff={avg_diff:+.0f}")
```

**蒲田7の教訓**: 曜日シグナルはホール間で逆方向になる。蒲田7の「水曜が強い」を他ホールに持ち込まないこと。

### 5.3 ホール固有の変数交互作用

Phase 3で有意だった変数間の交互作用を確認:

```
角番 × DD → 蒲田7で最も有効だった組み合わせ
角番 × 曜日 → ホールごとに「何曜日に角番パターンが出るか」が異なる
末尾 × セグメント → セグメント別に有効な末尾が完全に異なる
イベント日 × セグメント → A機への集中度がホール固有
```

### 5.4 theory.md の作成

蒲田7と同じ構成で、ホール固有のtheory.mdを作成:

```
document/{ホール略称}_theory.md

構成:
1. セグメント構造
2. 変数の効果と限界（角番/末尾/DD/曜日/イベント/ゾロ目/経過日数）
3. 否定された仮説
4. 台選びフロー
5. Instinct参照マップ
```

---

## Phase 6: MLスコアリングモデルへの組み込み

### 6.1 scoring_model.py の汎用性

現在のscoring_model.pyは蒲田7固有の設定がハードコードされている:

| 設定 | 蒲田7固有 | 汎用化に必要な変更 |
|------|----------|-----------------|
| REVERSED_OLD/NEW | 蒲田7のセクション番号 | hall_config.json から読み込み |
| _infer_lr() | X座標の中央値判定 | ホール別に検証が必要 |
| _segment_family() | ジャグラー/ハナハナの文字列マッチ | 共通（機種名は全ホール同一） |
| SEGMENT_WEIGHTS_V11 | 蒲田7の4-fold CVで最適化 | ホール別に再最適化 |
| debut_multiplier | 蒲田7のbase テーブル | ホール別に3フェーズ検証 |

### 6.2 新ホール向けの作業チェックリスト

- [ ] Phase 1: セグメント決定済み
- [ ] Phase 2: 角番定義確定済み（rank_from_min/max/aisle）
- [ ] Phase 3: 有効変数リスト作成済み
- [ ] Phase 4: 耐久性検証済み（堅牢/脆弱の判定）
- [ ] Phase 5: theory.md作成済み
- [ ] hall_config.json にイベント日・reversed_sections登録済み
- [ ] floor_coordinates.csv 作成済み（座標情報がある場合）
- [ ] walk-forward backtestで vs ランダム検定済み

---

## アンチパターン集（蒲田7での地雷）

Phase 1-5の全工程で、以下のアンチパターンに注意:

| # | アンチパターン | 検出方法 | 蒲田7での被害 |
|---|-------------|---------|-------------|
| 1 | **蒲田7の結論を移植** | 結論を使わず手順だけを移植しているか確認 | 曜日パターンがホール間で逆転 |
| 2 | **セグメント未分割で法則主張** | 全体集計の前にセグメント別を見る | Simpson's Paradoxで末尾ランキング逆転 |
| 3 | **角番定義の誤り** | ε²で3定義を比較 | みとやで5倍の差 |
| 4 | **鉄台除外忘れ** | pos_rate>=60%の台を除外して再検定 | 末尾効果の大半が台2026に依存 |
| 5 | **split-half未実施** | 前半/後半で方向一致を確認 | 2F_L_N d6が前半Top3に入らず格下げ |
| 6 | **イベント日定義の流用** | hall_config.jsonのevent_digitsを使う | DD21追加で月曜の符号が反転 |
| 7 | **LR分割の安易な適用** | F値でsection_sizeと比較 | LRはF=0.03で1000倍劣後 |
| 8 | **インサンプルだけで重み最適化** | 4-fold temporal CVを必ず実施 | 2F_R_N p=0.008→CV後に崩壊 |
| 9 | **新台汚染** | debut_phaseで層別化 | 「低差枚×高稼働」の76.6%が新台期 |

---

## ホール別の現状と優先度

| ホール | データ量 | 座標CSV | セグメント | 角番定義 | Phase |
|--------|---------|---------|----------|---------|-------|
| 蒲田7 | 342日 | ✅ | 6セグメント確定 | rank_from_min/max | **Phase 6完了** |
| みとや大森町 | 525日 | ✅ | sectionベース | rank_from_aisle | Phase 5部分完了 |
| 蒲田1 | 342日 | ✅ | 未確定 | 未確定 | Phase 1 |
| 楽園蒲田 | 342日 | ✅（楽園） | 未確定 | 未確定 | Phase 0 |
| 金時京急蒲田 | 342日 | ✗ | 未確定 | 未確定 | Phase 0 |
| レイトギャップ | 342日 | ✗ | 未確定 | 未確定 | Phase 0 |
| ARROW池上 | 342日 | ✗ | 未確定 | 未確定 | Phase 0 |
| ヒロキ東口 | 342日 | ✗ | 未確定 | 未確定 | Phase 0 |
| ザシティ雑色 | 342日 | ✗ | 未確定 | 未確定 | Phase 0 |

### 次に分析すべきホールの推奨

1. **蒲田1** — 蒲田7と同系列（マルハン）、座標CSV済み、同一期間のデータ。蒲田7との比較が容易
2. **みとや大森町** — Phase 5まで進んでいる。rank_from_aisleの実績がある。仕上げに近い
3. **楽園蒲田** — 座標CSV済み。好設定ホール（debut分析で確認済み）
