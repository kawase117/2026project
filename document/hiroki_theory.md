# ヒロキ（ヒロキ東口店） 台選び理論ドキュメント

> **目的**: ヒロキ東口店のEDAで判明した知見を「台選びの理論」として体系化する。
> **対象読者**: 毎日通い、最良の台を選ぶプレイヤー。
> **最終更新**: 2026-07-02（機種別DD/曜日横断スキャンで初版作成）
> **ステータス**: 探索初期 — 機種別DD/曜日パターンのスキャンのみ完了。セグメント構造・角番・末尾・イベント日との交互作用・経過日数（3フェーズモデル）は未着手。

---

## 1. 機種別DD/曜日パターン（全機種横断スキャン）

**結論**: 全機種×DD(1-31)/曜日(7水準)の横断的統計スキャン（`eda/machine_axis_pattern_scan.py`、2026-07-02）の結果、ヒロキはDD軸で4件、曜日軸で1件のみがp<0.05かつ効果量≥0.1をクリアした。9ホール中でも有意な機種数が少ない部類。

### DD軸で法則性が確認された機種（全期間, 効果量降順, スパース警告なしのみ）

| 機種 | outcome | p値 | 効果量 | n |
|------|---------|-----|--------|---|
| 甲鉄城のカバネリ 海門(うなと)決戦 | plus | 5.99e-03 | 0.227 | 445 |
| ハッピージャグラーVIII | plus | 7.22e-03 | 0.115 | 1685 |
| 新鬼武者3 | plus | 2.52e-02 | 0.106 | 1494 |
| ファンキージャグラー2 | plus | 9.76e-03 | 0.104 | 1949 |

甲鉄城のカバネリ 海門(うなと)決戦は効果量最大だがn=445とやや小規模。ハッピージャグラーVIII・ファンキージャグラー2はn=1500〜2000でより安定。

参考: 麻雀格闘倶楽部 覚醒(hit104, effect=0.186)は数値上さらに大きいがn=431で期待セル<5警告付きのため信頼度は低い。

### 曜日軸で法則性が確認された機種（全期間）

| 機種 | outcome | p値 | 効果量 | n |
|------|---------|-----|--------|---|
| アズールレーン THE ANIMATION | plus | 4.57e-02 | 0.163 | 259 |

境界的な有意水準(p=0.046)でn=259も小規模。単独の弱いシグナルとして扱う。

### 90日ウィンドウ検証（直近90日 vs その前90日）

**DD軸**:
- マイジャグラーV(plus): 直近90日 p=2.5e-3 効果量0.105（トップ31日）、その前90日も p=4.5e-2 で有意（効果量0.068、トップ22日）。両ウィンドウ有意で構造持続、ピーク日は移動
- 北斗の拳 転生の章2(plus/hit104)・マギアレコードは直近90日のみ有意。今期限定の可能性があり要継続観察

**曜日軸**:
- ジャグラーガールズ(plus)は直近90日のみ有意（その前90日は効果量ゼロ）

### 解釈上の注意

1. ヒロキは有意な機種数自体が少なく、まだ結論を強く主張できる段階ではない
2. 甲鉄城のカバネリ 海門(うなと)決戦はみとやでもDD軸(hit104)で有意 — 前作の甲鉄城のカバネリ(オリジナル)は蒲田1/蒲田7で有意だったのに対し、後継機は別のホール群(みとや/ヒロキ)で有意になっており、DD深堀りセッション(2026-07-02前半)の`successor-machine-dd-divergence-may-be-sample-noise-not-strategy-shift`instinctの通り解釈には注意が必要
3. 「直近90日だけ有意」の機種は次回スキャンでの再現性を確認してから採用する
4. 出典CSV: `eda/results/machine_axis_pattern_scan/all_hall_dd_significant.csv`, `all_hall_weekday_significant.csv`, `eda/results/machine_dd_recent_window/ヒロキ_recent_window.csv`, `eda/results/machine_weekday_recent_window/ヒロキ_recent_window.csv`

---

## 2. 機種横断一致度スキャン（ホール一致度＋機種単体検定、2026-07-02）

**結論**: `eda/machine_dd_cross_agreement_scan.py`/`machine_weekday_cross_agreement_scan.py`（「その日、何機種が自分自身の平均を上回ったか」をホール横断で二項検定）を実行した結果、ヒロキはDD軸・曜日軸ともに**有意な日がゼロ**だった。機種数不足ではない（DD区分あたり平均101機種、`insufficient`扱い0件）ため、ヒロキは機種横断で揃って動く投入日パターン自体を持たない、または今回の残差ベース設計では検出できない別方式（機種を絞った個別投入等）を使っている可能性がある。9ホール中、DD軸で有意ゼロだったのは楽園・ヒロキ・ザシティの3ホール、曜日軸も含めて完全にゼロだったのはヒロキ・ザシティ・蒲田1・レイトギャップ・ARROW・金時。

**DD Bin軸（1-7,8-14,15-21,22-28,29-31、2026-07-03追加）**: `machine_axis_pattern_scan.py`にdd軸の週単位版として追加済み。ヒロキではhit104=4件・plus=6件が効果量≥0.1をクリア（dd軸のhit104=12件・plus=11件よりは少ないが、9ホール中では比較的多い部類）。「SHAKE BONUS TRIGGER」(plus, 効果量0.162, n=218)はdd軸の上位10件には入らずdd_bin軸で初めて浮上しており、週スケールの傾向を持つ候補として要継続観察（→`document/instincts/2026-07-02-dd-bin-axis-double-edged-sword-insights.yaml`）。

**出典**: `eda/results/machine_dd_cross_agreement/`, `eda/results/machine_weekday_cross_agreement/`

> 関連instinct: `document/instincts/2026-07-02-machine-dd-cross-agreement-insights.yaml`, `document/instincts/2026-07-02-machine-weekday-cross-agreement-and-power-limits-insights.yaml`

---

## 3. 未探索ロードマップ

1. **セグメント構造** — フロア×左右×機種タイプ分割
2. **角番の効果**
3. **台番号末尾**
4. **イベント日との交互作用** — 公式イベント日は`HALL_EVENT_DIGITS`で[6, 16, 26]
5. **経過日数（3フェーズモデル）** — 全9ホール検証（2026-06-26）でヒロキは渋いホール側（単調改善するが全フェーズマイナスのまま）に分類済みだが、ヒロキ固有の詳細分析は未実施
6. **ゾロ目効果**

## 4. Instinct参照マップ

- `document/instincts/2026-07-02-recent-window-trend-analysis-insights.yaml`
- `document/instincts/2026-07-02-machine-axis-pattern-scan-insights.yaml`
- `document/instincts/2026-07-02-machine-dd-deepdive-kabaneri-juggler-clair-insights.yaml`（甲鉄城のカバネリ後継機のホール別分岐に関する知見）
- `document/instincts/2026-07-02-machine-dd-cross-agreement-insights.yaml`
- `document/instincts/2026-07-02-machine-weekday-cross-agreement-and-power-limits-insights.yaml`
