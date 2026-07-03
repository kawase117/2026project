---
name: prediction-evaluation
description: 末尾予測・ゾロ目補正の精度を正しく評価するスキル。評価レポートを書く前・比較分析の前に適用。
evolved_from:
  - segment-specific-top3-comparison
  - zorome-correction-value-definition
  - prediction-accuracy-two-layer-structure
  - tail-vs-zorome-machine-separate-evaluation
  - retroactive-prediction-comparison-equal-denominator
  - single-day-accuracy-high-variance
  - hit3-outperforms-hit2-in-live-evaluation
  - tail-ranking-outlier-noise-detection
  - tail9-systematic-underestimation-2fn
confidence: 0.91
---

# Prediction Evaluation Skill

## トリガー
- 末尾予測の精度レポートを作成するとき
- ゾロ目台推奨の的中率を評価するとき
- 旧予測と新予測を比較するとき
- 「今日のモデルは当たったか？」を分析するとき

## 評価の基本原則

### 1. セグメント別に比較する（混在禁止）
```python
# 2F_N予測 → 2F実績のみと比較（3F実績と混ぜない）
df['floor'] = ['2F' if int(n) < 3000 else '3F'
               for n in df['machine_number'].astype(str)]
for floor in ['2F', '3F']:
    df_floor = df[df['floor'] == floor]
    summary = df_floor.groupby('last_digit')['diff_coins_normalized'].sum()
    actual_top3 = summary.nlargest(3).index.tolist()
    actual_bottom3 = summary.nsmallest(3).index.tolist()

# ゾロ目意見はゾロ目台実績（is_zorome=1）のみと比較
```

### 2. 末尾精度とゾロ目精度は分離して報告（必須）
```
2軸を常に分離:
  1. tail hit@3: セグメント別末尾合計差枚によるTop3一致度
  2. XX台実績: 当日のゾロ目台（XX番台）の差枚を個別記載

「末尾当たり・XX台外れ」は頻繁に発生する。
混在させると見えなくなる。

例（2026-05-27 3F_N）:
  tail hit: セグメント1位 +13,300円 (一致)
  3077台実績: -2,900円 (外れ)
  原因: 非ゾロ目の末尾7台が+16,200円を稼いでいた
```

### 3. ゾロ目補正値の正しい定義
```python
# 補正値 = ゾロ目台平均差枚 - 非ゾロ目台平均差枚（同末尾・同セグメント）
for ld in [str(i) for i in range(10)]:
    df_ld = df_floor[df_floor['last_digit'] == ld]
    z_avg = df_ld[df_ld['is_zorome']==1]['diff_coins_normalized'].mean()
    nz_avg = df_ld[df_ld['is_zorome']==0]['diff_coins_normalized'].mean()
    correction = z_avg - nz_avg  # 実績補正値
# 予測補正値（例: +170）と実績補正値を比較して精度評価
```

### 4. 遡及比較は分母を揃えてから
```
手順:
1. 旧予測と新予測で使用セグメント数が同じか確認
2. 異なる場合は「共通セグメントのみ」で比較
3. 除外理由を明記
4. 分母が異なる比較は「参考値」として別扱い

例: 旧(9分母) vs 新(12分母) → 公平でない
    共通3セグメントで揃えてから比較する
```

### 5. 末尾精度が高くてもゾロ目補正精度は保証されない
```
末尾別Top3一致度: 3/3（完全的中）でも
ゾロ目補正Top3一致度: 1/3 のケースが実在する。

「モデルが優秀」と言うときは、どの評価軸の話かを明確にする。
```

### 6. 単日評価は分散が大きすぎる（2026-05-29 追加）
```
モデル評価に単日結果を使ってはいけない。

根拠: 同じモデルで2026-05-28=50%、2026-05-29=25% と1日で2倍の差が出た。
末尾Top3の試行数は4セグメント=4回のみ → 信頼区間が非常に広い。

ルール:
  - モデル評価は 20〜30日以上の蓄積で行う
  - 単日結果は「現象の記録」に留め、評価に使わない
  - 30日移動Hit@3が40%超を継続できるかが評価閾値
  - 「当たった日・外れた日」ではなく「月次平均」で語る
```

### 7. 実運用ではhit@3 > hit@2（2026-05-29 追加）
```
モデルはhit@2でテスト（内部精度が高い）だが、実運用では逆の傾向がある。

3日間実績:
  Hit@2: 6/24 (25%) — ランダム+5%
  Hit@3: 14/36 (39%) — ランダム+9%（有意に上回る）

実運用への含意:
  - Top3を参照する（Top2に絞ると機会損失）
  - モデル1位末尾を絶対視しない
  - 2・3位も同等の候補として扱う
```

### 8. 末尾ランキングのアウトライア検出（2026-05-29 追加）
```
特定末尾が突出して1位になったとき → 少数台のノイズかを確認する。

手順:
1. その末尾のTop2〜3台の差枚を個別確認
2. 上位台の直近15日履歴を確認（通常マイナス→今日だけプラス → 分散ノイズ）
3. 上位台を除外した場合の末尾合計を計算
4. 2台以下が合計の大半を占める → 「ノイズ末尾」として扱う

例（2026-05-29 2F_N末尾9）:
  合計+15,900（1位に見える）
  実態: 台2309(+12,600) + 台2059(+8,300)の2台で大半
  除外後: -5,000（実質最下位圏）
  → ノイズ末尾と判断
```

## 進化の背景
9件のインスティンクトから抽出(2026-07-04 再構成: ゾロ目補正の検証単位・3F_A信頼度の2件は
ホール戦略解釈の文脈が強いため pachinko-live-analysis に移動)。
prediction-evaluation(9)。平均信頼度: 91%。
