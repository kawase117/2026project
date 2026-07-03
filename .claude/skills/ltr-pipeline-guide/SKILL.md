---
name: ltr-pipeline-guide
description: tail_ltr_split_rule_nextday_gpu.py の実行・引数・モジュール実行方法を自動チェックするスキル。パイプライン実行前に適用。
evolved_from:
  - window-name-vs-feature-name-confusion
  - python-module-vs-script-execution
  - is-top2-must-be-within-expert
  - 2fa-exclusion-is-hardcoded-default-not-data-driven
  - bottom3-does-not-require-new-model
  - top3-output-already-implemented-per-expert
  - ltr-replaces-binary-classifier-for-ranking
  - cross-sectional-normalization-for-machine-ranking
  - machine-type-f1-structural-limit
confidence: 0.93
---

# LTR Pipeline Guide Skill

## トリガー
- `tail_ltr_split_rule_nextday_gpu.py` を実行しようとするとき
- `--windows-wed` / `--windows-nonwed` 引数を指定するとき
- LTRのランクターゲット（is_top2等）を定義しようとするとき
- 新しいセグメントや出力を実装しようとするとき
- パイプラインコマンドがエラーになったとき

## 実行前チェックリスト

### 1. 実行形式（最重要）
```
誤: python ml/last_digit/tail_ltr_split_rule_nextday_gpu.py
正: python -m ml.last_digit.tail_ltr_split_rule_nextday_gpu

理由: ml/ はパッケージ（__init__.py あり）。
      直接実行では相対インポートが解決できずModuleNotFoundError。
```

### 2. `--windows-*` 引数の正しい値
```
--windows-wed と --windows-nonwed に指定するのは「training期間名」であり、
特徴量のroll幅（roll28等）ではない。

有効な値:
  - "full_2025"      → regime1開始〜regime2終了
  - "recent_60d"     → テスト開始60日前〜前日
  - "recent_90d"     → テスト開始90日前〜前日
  - "opening_early"  → 開店初期データ
  - "regime1_full"   → regime1全体

誤: --windows-wed "roll28"  → 全候補がunavailableになる
正: --windows-wed "full_2025"
```

### 3. LTRターゲット定義
```
is_top2 は必ず within-expert（エキスパート内上位2）として定義する。
  → グローバルtop2ではなく、セグメント内相対ランク
  → 2F_N, 3F_A, 3F_N の各エキスパートで独立して計算

2F_A は訓練・テスト双方から除外（ハードコードされたデフォルト）。
  → テスト出力に2F_Aが含まれない場合は正常
```

### 4. 出力の確認
```
既に実装済みの出力（再実装不要）:
  - latest_test_top3.csv → 各エキスパートのTOP3推薦（実装済み）
  - BOTTOM3は新規モデル不要 → スコア下位を逆順で取るだけ
```

### 5. 機種タイプ予測の限界
```
machine_type の F1スコアが 0.10以下 → 構造的な学習不可能性。
  → LTR（ランキング）に切り替える。
  → binary classifierを使い続けない。
```

## 進化の背景
9件のインスティンクトから抽出。
ml-pipeline-configuration(3) + ltr-pipeline(3) + ml-machine-type(3)。
