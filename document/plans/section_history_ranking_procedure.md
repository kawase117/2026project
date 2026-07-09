# セクション履歴ランキング手順書 v1.0

**作成日**: 2026-06-29
**ステータス**: 蒲田1で検証完了、他ホール展開可能
**前提**: 他ホール検証手順書 v1.0 の Step 1-2 完了後に実施

---

## 概要

セクション（島）単位の過去hit率履歴を使い、当日のTOP-Kセクションを予測する。
イベント日と非イベント日で訓練データを分割する「splitモデル」が基本。

**蒲田1での検証結果**:
- splitモデル top_k=5: lift=1.191, precision=39.9%, 差枚優位+310/日
- baselineモデル（全日混合）: lift=1.135, precision=36.5%, 差枚優位+176/日

---

## デフォルトパラメータ

| # | パラメータ | デフォルト | 備考 |
|---|-----------|-----------|------|
| 1 | window_days | 90 | 訓練ウィンドウ。感度低（60-180で安定） |
| 2 | min_games | 2000 | 対象台の最低G数。感度高（上げると改善するがデータ減少） |
| 3 | top_k | 5 | 推薦セクション数。K=7以上でlift急落 |
| 4 | eval_days | 120 | バックテスト評価期間 |
| 5 | hit_threshold | 104% | A機種。N機種は106% |

---

## 手順

### S-1. 前提確認

以下が完了していること：
- セクション定義（座標CSV）
- イベント日定義（EVENT_DDS）
- min_gamesフィルタ値

これらは他ホール検証手順書 Step 1-2 の出力。

### S-2. ベースライン評価（全日混合）

全日の訓練データを使った素朴なセクション履歴ランキングを評価する。

```
for 評価日 in 直近eval_days日:
    train = 過去window_days日の全データ
    section_score = train.groupby('section')['hit'].mean()
    top_sections = section_score.sort_values(desc).head(top_k)
    当日実績と照合 → lift, precision, 差枚優位を記録
```

**出力**: 全体のlift@K, precision@K, Spearman rho

### S-3. イベント/非イベント分割評価

訓練データを当日のイベント種別に合わせて分割する。

```
for 評価日 in 直近eval_days日:
    is_event = (評価日のDD ∈ EVENT_DDS)
    train = 過去window_days日のデータ
    if is_event:
        train = train[train.is_event == 1]  # イベント日のみで訓練
    else:
        train = train[train.is_event == 0]  # 非イベント日のみで訓練

    if len(train) < 50:  # サンプル不足時はフォールバック
        train = 全データ

    section_score = train.groupby('section')['hit'].mean()
    top_sections = section_score.sort_values(desc).head(top_k)
    当日実績と照合
```

**5つの構成を比較する**:

| 構成 | 訓練データ | 評価日 | 目的 |
|------|-----------|--------|------|
| all→all | 全日 | 全日 | ベースライン |
| event→event | イベント日のみ | イベント日のみ | イベント日の予測力 |
| nonevent→nonevent | 非イベント日のみ | 非イベント日のみ | 非イベント日の予測力 |
| all→event | 全日 | イベント日のみ | 混合訓練のイベント日性能 |
| all→nonevent | 全日 | 非イベント日のみ | 混合訓練の非イベント日性能 |

**判定基準**:
- nonevent→nonevent が all→all を上回る → split有効
- all→event の lift < 1.0 → イベント日は全日混合では予測不可
- event→event の改善が小さい → イベント日のサンプル不足または構造不安定

### S-4. パラメータ感度分析

1変数ずつ感度を確認する。**グリッドサーチ禁止。**

| # | パラメータ | 探索範囲 | 注意 |
|---|-----------|---------|------|
| 1 | window_days | 30, 60, 90, 120, 180 | 30日で急落するホールがある |
| 2 | min_games | 1000, 1500, 2000, 3000 | 上げると改善するが候補台が減る |
| 3 | top_k | 1, 3, 5, 7, 10, 15, 20 | lift急落点を検出 |

### S-5. 最終パラメータ確定

感度分析結果を見て、以下の基準で調整：
- min_games: lift改善と候補台数のバランス。20台/日を下回ると実用上リスク
- top_k: lift急落点の1段手前。蒲田1ではK=5→7で急落
- window_days: 感度が低ければデフォルト90を維持

---

## 出力物

| ファイル | 内容 |
|---------|------|
| `hall_summary.csv` | ホール×top_k のlift/precision/rho |
| `event_split_comparison.csv` | 5構成の比較結果 |
| `parameter_sensitivity.csv` | 感度分析結果 |
| `daily_results.csv` | 日次のlift/precision/差枚（splitモデル最終パラメータ） |

---

## ホール別の予想パターン

蒲田1・蒲田7・みとや・楽園の知見から、以下のパターンが想定される：

| パターン | 特徴 | 例 |
|---------|------|-----|
| **安定固定型** | top3セクションが不変。split不要 | みとや（rho=0.20, 5 unique sets） |
| **イベント入替型** | イベント/非イベントで順位が入れ替わる。split有効 | 蒲田1（all rho≈0, split rho=0.18） |
| **常時分散型** | どの日もセクション順位が不安定。予測困難 | （楽園の一部フロア） |

split有効性はホールの戦略に依存する。全ホールで5構成を比較してから判断すること。

---

## 注意事項

- **新台は高回転するため、games_normalizedフィルタの信号を汚染する**。
  可能であれば導入初週の台を除外して計算する方が正確
- **hit_threshold**: A機種=104%、N機種=106%。classify_seg()で判定。
  ホール別にA/N比率が異なるため、ホールをまたぐ比較はhit率ではなくliftで行う
- **サンプル不足のフォールバック**: イベント日の訓練データが50レコード未満の場合、
  全日データにフォールバックする。小規模ホール（<150台）で発生しやすい
- **既存スクリプト**: `eda/section_lateral_expansion.py` が全日混合版を実装済み。
  split版は未統合のため、各ホール個別にスクリプト実行するか、統合を検討する
