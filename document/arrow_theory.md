# ARROW（ARROW池上店） 台選び理論ドキュメント

> **目的**: ARROW池上店のEDAで判明した知見を「台選びの理論」として体系化する。
> **対象読者**: 毎日通い、最良の台を選ぶプレイヤー。
> **最終更新**: 2026-07-02（機種別DD/曜日横断スキャンで初版作成）
> **ステータス**: 探索初期 — 機種別DD/曜日パターンのスキャンのみ完了。セグメント構造・角番・末尾・イベント日との交互作用・経過日数（3フェーズモデル）は未着手。

---

## 1. 機種別DD/曜日パターン（全機種横断スキャン）

**結論**: 全機種×DD(1-31)/曜日(7水準)の横断的統計スキャン（`eda/machine_axis_pattern_scan.py`、2026-07-02）の結果、ARROWはDD軸で6件、曜日軸で3件がp<0.05かつ効果量≥0.1をクリアした。

### DD軸で法則性が確認された機種（全期間, 効果量降順, スパース警告なしのみ）

| 機種 | outcome | p値 | 効果量 | n |
|------|---------|-----|--------|---|
| ゴーゴージャグラー3 | plus | 6.72e-12 | 0.141 | 4284 |
| 化物語 | hit104 | 4.54e-02 | 0.131 | 827 |
| ゴーゴージャグラー3 | hit104 | 1.82e-08 | 0.122 | 4284 |
| ハッピージャグラーVIII | plus | 7.77e-04 | 0.107 | 2685 |
| 戦国乙女4 戦乱に閃く炯眼の軍師 | plus | 2.15e-02 | 0.105 | 1590 |
| ハッピージャグラーVIII | hit104 | 1.03e-03 | 0.105 | 2685 |

ゴーゴージャグラー3(n=4284, p=6.7e-12)がARROWで最も統計的に強いDD軸シグナル。ハッピージャグラーVIIIもplus/hit104両方でクリアしており一貫性が高い。

参考: ウルトラミラクルジャグラー(hit104, effect=0.224)は数値上さらに大きいがn=537で期待セル<5警告付きのため信頼度は低い。

### 曜日軸で法則性が確認された機種（全期間）

| 機種 | outcome | p値 | 効果量 | n |
|------|---------|-----|--------|---|
| ニューパルサーDX3 | plus | 3.77e-03 | 0.157 | 537 |
| アズールレーン THE ANIMATION | hit104 | 4.24e-02 | 0.155 | 292 |
| ヨルムンガンド | hit104 | 4.58e-02 | 0.152 | 295 |

### 90日ウィンドウ検証（直近90日 vs その前90日）

**DD軸**:
- スマスロ北斗の拳(hit104): 直近90日 p=2.65e-2 効果量0.118（トップ24日）、その前90日 p=5.27e-3 効果量0.117（トップ29日）。両ウィンドウ独立に有意で、ピーク日が近接した範囲で移動する「構造持続型」
- ネオアイムジャグラーEX・ゴッドイーター リザレクションは直近90日のみ有意。今期限定の可能性があり要継続観察

**曜日軸**:
- **いざ！番長（plus/hit104）**: 直近90日 p=2.8e-4/7.0e-3（トップ土曜）、その前90日 p=1.1e-2/2.4e-3（トップ水曜）と**両ウィンドウとも独立に有意**。ピーク曜日は土曜⇔水曜で一致しないが、DD軸の北斗の拳・ファンキージャグラー2と同じ「構造は持続、狙う対象（この場合は曜日）が移動する」パターン。ARROWのいざ！番長はこの傾向がARROW固有で確認された唯一の曜日軸「構造持続型」の例
- かぐや様は告らせたい(plus)は直近90日のみ有意

### 解釈上の注意

1. ハッピージャグラーVIII・ゴーゴージャグラー3はARROW以外の複数の無関係チェーンでも頻出する機種であり、ARROW固有の戦略というよりジャグラー系機種自体の特性（RB確率が設定に直結）の可能性が高い
2. 「直近90日だけ有意」の機種は次回スキャンでの再現性を確認してから採用する
3. 出典CSV: `eda/results/machine_axis_pattern_scan/all_hall_dd_significant.csv`, `all_hall_weekday_significant.csv`, `eda/results/machine_dd_recent_window/ARROW_recent_window.csv`, `eda/results/machine_weekday_recent_window/ARROW_recent_window.csv`

---

## 2. 機種横断一致度スキャン（ホール一致度＋機種単体検定、2026-07-02）

**結論**: `eda/machine_dd_cross_agreement_scan.py`/`machine_weekday_cross_agreement_scan.py`（「その日、何機種が自分自身の平均を上回ったか」をホール横断で二項検定）を実行した結果、ARROWはDD軸1件のみ有意（dd11、既知イベント日、プラス方向、一致率66%）、曜日軸は有意ゼロだった。

機種単体でone-vs-rest検定+FDR補正を通過した機種はゼロ。現存フィルタを適用した候補（ウルトラミラクルジャグラー等）も個体としては非有意で、ホール横断の一致は見られるが機種名を特定できるレベルの強いシグナルはまだ確認できていない。

**DD Bin軸（1-7,8-14,15-21,22-28,29-31、2026-07-03追加）**: `machine_axis_pattern_scan.py`にdd軸の週単位版として追加済み。ARROWではhit104=1件・plus=1件のみが効果量≥0.1をクリア（dd軸のhit104=7件・plus=9件と比べて大幅に少ない）（→`document/instincts/2026-07-02-dd-bin-axis-double-edged-sword-insights.yaml`）。

**出典**: `eda/results/machine_dd_cross_agreement/`, `eda/results/machine_weekday_cross_agreement/`

> 関連instinct: `document/instincts/2026-07-02-machine-dd-cross-agreement-insights.yaml`, `document/instincts/2026-07-02-machine-weekday-cross-agreement-and-power-limits-insights.yaml`

---

## 3. 未探索ロードマップ

1. **セグメント構造** — フロア×左右×機種タイプ分割
2. **角番の効果**
3. **台番号末尾**
4. **イベント日との交互作用** — 公式イベント日は`HALL_EVENT_DIGITS`で[8, 18, 28, 11, 22]
5. **経過日数（3フェーズモデル）** — 全9ホール検証（2026-06-26）でARROWは好設定ホール側（61-180日でプラス圏到達）に分類済みだが、ARROW固有の詳細分析は未実施
6. **ゾロ目効果**

## 4. Instinct参照マップ

- `document/instincts/2026-07-02-recent-window-trend-analysis-insights.yaml`
- `document/instincts/2026-07-02-machine-axis-pattern-scan-insights.yaml`
- `document/instincts/2026-07-02-machine-dd-cross-agreement-insights.yaml`
- `document/instincts/2026-07-02-machine-weekday-cross-agreement-and-power-limits-insights.yaml`
