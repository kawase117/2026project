# Codex プロンプト: 予測粒度シフト実験

## 背景

蒲田7・みとやのキャリブレーション検証で以下が判明した:

1. **compositeスコア（c1-c6加重合計）は104%超えを予測しない**（全9バリアントでSpearman rho≈0、p>0.27）
2. **hist_metric（台個別の過去104%超え率）が唯一の有効シグナル**（蒲田7: rho=+0.038, +6.0pp / みとや: rho=+0.042, +7.4pp）
3. **c1-c6を束ねるとhist_metricの信号が破壊される**（hist_only Top50: 35.4% vs composite Top50: 32.1%）
4. **台×日の粒度ではノイズが大きすぎて構造シグナルが成立しない**（AT機の1日出力率は分散が巨大）

hist_metricが機能する理由は「複数日の平均でノイズを縮小している」から。
この原理に基づき、予測対象の粒度を「台×日」から変えることで、ノイズを根本的に回避する2つの実験を行う。

## 固定前提

以下はユーザー確認済みで変更しない:
- **セクション定義**: `ml/experiments/walkforward_scoring/config.py` の SECTION_RANGES_2F, SECTION_RANGES_3F をそのまま使用
- **フィルタ**: `games_normalized >= 1500`、日付`0707`除外、台番号`2026`除外
- **週境界**: `W-MON`（月曜始まり）固定

## 共通の実装ルール

- DBデフォルトパスは `db/マルハンメガシティ2000-蒲田7.db`（`--db-path`引数で変更可能にする）
- `to_markdown()` は使わない（文字化けする）。print文で出力する
- 空セグメント/セクションがある場合はNaN処理する
- **リーク防止**: 特徴量の計算窓は `date_dt < target_date` を厳密に適用する。ターゲット当日のデータは絶対に特徴量に含めない。`hist_section_hot_rate`や`hist_metric`の集計もtarget_date未満のデータのみで計算すること

## 実験A: セクション×日 予測（「今日どのセクションが熱いか」）

### 目的
台単位ではなくセクション単位で「今日このセクションに高設定が入っているか」を予測する。
セクション内の全台の出力を平均すればノイズが√N倍（N=セクション台数）縮小する。

### ターゲット定義
セクション×日ごとに以下を計算:
- `section_avg_payout`: セクション内全台の平均出玉率
- `section_hit_rate`: セクション内の104%超え台の割合

**閾値は固定しない。** `section_hit_rate` を連続値のままSpearman相関で評価する。
加えて、参考として複数の閾値（30%, 35%, 40%, 45%）でsection_hotを二値化し、各閾値でのliftとベースラインを併記する。

### 特徴量候補
- `hist_section_hit_rate`: 過去90日間（target_date未満）でこのセクションのsection_hit_rateの平均
- `dd`: 日付の日（1-31）
- `dow`: 曜日（0-6）
- `is_event`: イベント日フラグ（蒲田7: EVENT_DDS={1,7,11,17,21,22,27,31}）
- `section_debut_ratio`: セクション内のdebut台（導入14日以内）の割合（target_date未満のデータで算出）
- `section_avg_hist`: セクション内全台のhist_metricの平均（target_date未満のデータで算出）
- `prev_day_section_hot`: 前日のsection_hit_rate（連続値）

### 実装

```
ファイル: eda/section_daily_prediction.py
DB: db/マルハンメガシティ2000-蒲田7.db
```

1. machine_detailed_resultsからセクション×日の集計テーブルを作成

2. 60日walk-forwardで評価（window=90日）
   - 各日付でtarget_date未満のデータのみから特徴量を計算
   - セクションごとにsection_hit_rateを算出

3. 出力
   - 特徴量別のSpearman rho（section_hit_rateとの相関）、p値
   - 各特徴量のD0→D9のsection_hit_rate分離幅（十分位で分割）
   - liftテーブル: 閾値30/35/40/45%ごとに「特徴量上位N個のセクションの実際のhit率 vs ベースライン」
   - ベースライン: 全セクションの平均section_hit_rate

## 実験B: 台×週 予測（「この台は今週設定が入っている」）

### 目的
1日の出力率では設定を判別できないが、複数日の累積なら判別精度が上がるか検証する。
ターゲットを「台×日の104%超え」から「台×週の累積パフォーマンス」に変える。

### ターゲット定義
台×週（月曜始まり7日間）ごとに:
- `week_avg_payout`: その週の平均出玉率
- `week_positive_days`: 差枚プラスだった日数

**閾値は固定しない。** `week_avg_payout` を連続値のままSpearman相関で評価する。
加えて、参考として複数の閾値（100%, 101%, 102%, 103%）でweek_hotを二値化し、各閾値でのliftとベースラインを併記する。

### 特徴量候補
- `hist_metric`: 過去90日間（target_week開始日未満）の104%超え率
- `prev_week_avg_payout`: 前週の平均出玉率
- `prev_week_positive_days`: 前週の差枚プラス日数
- `section`: セクション（固定効果として）
- `debut_phase`: 導入からの経過日数カテゴリ
- `segment`: セグメント（蒲田7: フロア×LR×A/N）

### 実装

```
ファイル: eda/weekly_machine_prediction.py
DB: db/マルハンメガシティ2000-蒲田7.db
```

1. machine_detailed_resultsを台×週に集約
   - 週の定義: `pd.Grouper(key="date_dt", freq="W-MON")`
   - 週内の稼働日数が3日未満の台-週はスキップ

2. 12週walk-forwardで評価（window=12週）
   - 各週でtarget_week開始日未満のデータのみから特徴量を計算
   - 特徴量とweek_avg_payoutのSpearman相関

3. 出力
   - 特徴量別のSpearman rho、p値
   - 各特徴量のD0→D9のweek_avg_payout分離幅
   - liftテーブル: 閾値100/101/102/103%ごとに「特徴量上位N台の実際のhit率 vs ベースライン」
   - hist_metricの日次キャリブレーション（rho=+0.038）との比較
   - 週次に変えたことで信号が強まるか弱まるかの判定

## 評価基準

- 成功判定に固定閾値は使わない
- **主指標**: Spearman rhoの符号・大きさ・p値
- **副指標**: D0→D9の分離幅（pp）、Top-Nのlift（ベースライン比）
- **ベンチマーク**: 台×日のhist_metric（Spearman rho=+0.038, D0→D9=+6.0pp）を上回るかどうか
- rhoが同等でもD0→D9の分離幅が大きければ、実用上の改善として評価する
- p値は参考として記載するが、単体での成否判定には使わない
