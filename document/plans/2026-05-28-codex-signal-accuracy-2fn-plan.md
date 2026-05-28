# Codex実装プラン：シグナル精度検証 + 複数末尾フェイク判定（2FN限定）

作成日: 2026-05-28（v2: 予測ソースを testperiod_topk.csv に変更）
対象DB: `db/マルハンメガシティ2000-蒲田7.db`

---

## 前提知識（必読）

### 2FN の定義
2F（2階）スロット台 = `machine_number` が 2000 〜 2999 の範囲。
台番号3000番台は3F扱いのため除外する。

### 信号機種
- **スマスロ北斗の拳**: 末尾ごとに **1台**（台番号2255-2263、末尾4欠番の計9台）
- **モンキーターンV**: 末尾ごとに **2〜4台**

### games_normalized フィルタ
- 個別台レベルで `games_normalized >= 3000` を適用する
- 北斗の場合: 末尾1台なので、その台が3000G未満ならその末尾はシグナル対象外
- モンキーの場合: 末尾に複数台あるため、3000G以上の台のうちの `AVG(diff)` および `AVG(rb_prob)` を使う

### RB確率の向き
`rb_probability_decimal > 1/300`（= 0.003333）が「良い設定」のシグナル。
**不等号は `>` であり `<` ではない**。分母が300以下 = 頻繁にRBが出る = 高設定の直接指標。

### last_digit の型
`machine_detailed_results.last_digit` は **TEXT型**（"0"〜"9"）。
比較時は必ず `str()` に統一すること。

### 予測ソース（重要な変更）
**nextday予測JSONは使わない。**
既存の `ml/last_digit/reports/*_testperiod_topk.csv` を予測履歴として使用する。
推奨ファイル: `nextday_kamata7_20260527_tasks123_verify_xgb_ranker_ndcg_testperiod_topk.csv`
- 期間: 2026-01-01 〜 2026-05-27（最新・全expert収録）
- 対象expert: `2F_N`（2F スロット・ノーマル区分の予測）

### testperiod_topk.csv の主要列
```
date         : YYYY-MM-DD形式
expert       : "2F_A" / "2F_N" / "3F_A" / "3F_N"
top1_tail    : 予測1位の末尾（str）
hit_at_2     : 1.0 = 予測top1が実際top-2内に入った, 0.0 = 入らなかった
hit_at_3     : 1.0 = 予測top1が実際top-3内に入った, 0.0 = 入らなかった
top1_actual_raw_diff : 予測top1末尾の実際の合計差枚
```

### 「予測外れ日」の定義（明示）

| 区分 | 定義 | 列 |
|------|------|-----|
| **hard_miss** | 予測top1が実際top-2に入らなかった日 | `hit_at_2 == 0` |
| **soft_miss** | 予測top1が実際top-2には入ったが、rank1ではなかった日 | `hit_at_2 == 1` かつ 実際rank1 ≠ 予測top1 ※ |
| **exact_hit** | 予測top1 = 実際rank1 | 別途DBから計算 |

**本プランで「予測外れ日」として使う定義: `hard_miss`（`hit_at_2 == 0`）**

`soft_miss` の検出には実際rank1をDBから別途取得する必要がある。
本プランでは `hard_miss` / `not_hard_miss` の2区分を主軸とし、
`soft_miss` は参考値として出力する（混同しないこと）。

---

## Task 1: `ml/experiments/signal_accuracy_2fn.py`

### 目的
1. **全日分析**: 当日の「北斗ベスト末尾」（3000G以上の中で最大diff）が当日「2FN最優秀末尾」と一致する率を算出
2. **外れ日分析**: 2F_Nの予測がhard_missだった日に限定して同じ一致率を算出

→「予測が外れた日でも北斗が正しい末尾を指していたか」を両方同じCSVから継続的に検証できる設計。

### 引数
```
--db-path        必須 SQLite DBパス
--topk-csv       必須 testperiod_topk.csv のパス
                 推奨: ml/last_digit/reports/nextday_kamata7_20260527_tasks123_verify_xgb_ranker_ndcg_testperiod_topk.csv
--min-games      default=3000  個別台のゲーム数フィルタ（北斗: 1台ベース）
--output-dir     default="db/experiments/signal_accuracy_2fn"
--log-level      default="INFO"
```

### 処理フロー

#### Step 1: データ取得

```python
# 北斗データ（2FNのみ）
df_hokuto = pd.read_sql("""
    SELECT date, machine_number, last_digit,
           diff_coins_normalized, games_normalized
    FROM machine_detailed_results
    WHERE machine_name = 'スマスロ北斗の拳'
      AND CAST(machine_number AS INTEGER) BETWEEN 2000 AND 2999
""", conn)

# 2FN他機種データ（北斗・モンキー除く）
df_other = pd.read_sql("""
    SELECT date, last_digit, diff_coins_normalized
    FROM machine_detailed_results
    WHERE CAST(machine_number AS INTEGER) BETWEEN 2000 AND 2999
      AND machine_name NOT IN ('スマスロ北斗の拳', 'モンキーターンV')
""", conn)

# 曜日情報
df_weekday = pd.read_sql("SELECT date, day_of_week FROM daily_hall_summary", conn)

# 予測履歴（2F_Nのみ抽出）
df_topk = pd.read_csv(args.topk_csv)
df_pred = df_topk[df_topk["expert"] == "2F_N"].copy()
df_pred["date"] = df_pred["date"].astype(str).str.replace("-", "")  # YYYY-MM-DD → YYYYMMDD
# hard_miss フラグ
df_pred["hard_miss"] = df_pred["hit_at_2"] == 0
pred_map = df_pred.set_index("date")[["top1_tail", "hit_at_2", "hard_miss"]].to_dict("index")
```

#### Step 2: 北斗ベスト末尾の計算（日単位）

```python
def compute_hokuto_best(df_day: pd.DataFrame, min_games: int) -> dict:
    """
    戻り値:
        best_digit: str | None   (Noneなら3000G以上の台なし)
        best_diff: float | None
        n_valid: int             (min_games以上の台数)
        top2_digits: list[str]   (上位2末尾)
    """
    valid = df_day[df_day["games_normalized"] >= min_games]
    if valid.empty:
        return {"best_digit": None, "best_diff": None, "n_valid": 0, "top2_digits": []}
    sorted_v = valid.sort_values("diff_coins_normalized", ascending=False)
    top2 = sorted_v["last_digit"].astype(str).head(2).tolist()
    return {
        "best_digit": str(sorted_v.iloc[0]["last_digit"]),
        "best_diff": float(sorted_v.iloc[0]["diff_coins_normalized"]),
        "n_valid": len(valid),
        "top2_digits": top2,
    }
```

#### Step 3: 2FN最優秀末尾の計算（日単位）

```python
def compute_2fn_best_digit(df_day: pd.DataFrame) -> str | None:
    """2FN他機種を last_digit 別に集計し avg_diff が最大の末尾を返す。"""
    if df_day.empty:
        return None
    agg = df_day.groupby("last_digit")["diff_coins_normalized"].mean()
    return str(agg.idxmax())
```

#### Step 4: 日単位ループ（DB全日 + 予測情報を付加）

```python
rows = []
for date in sorted(all_dates):
    hokuto = compute_hokuto_best(df_hokuto[df_hokuto["date"] == date], min_games)
    best_2fn = compute_2fn_best_digit(df_other[df_other["date"] == date])
    weekday = weekday_map.get(date, "")

    # 予測情報（testperiod_topk.csv から。なければ None）
    pred_info = pred_map.get(date, {})
    pred_top1 = str(pred_info.get("top1_tail", "")) if pred_info else None
    hit_at_2 = pred_info.get("hit_at_2", None) if pred_info else None
    hard_miss = bool(pred_info.get("hard_miss", False)) if pred_info else None
    has_pred = pred_info != {}

    is_match = (
        hokuto["best_digit"] is not None
        and best_2fn is not None
        and hokuto["best_digit"] == best_2fn
    )
    is_top2_match = (
        best_2fn is not None
        and best_2fn in hokuto.get("top2_digits", [])
    )

    rows.append({
        "date": date,
        "day_of_week": weekday,
        "hokuto_best_digit": hokuto["best_digit"],
        "hokuto_best_diff": hokuto["best_diff"],
        "hokuto_n_valid": hokuto["n_valid"],
        "best_2fn_digit": best_2fn,
        "is_match": is_match,
        "is_top2_match": is_top2_match,
        # 予測情報（CSV期間外の日はNaN）
        "pred_top1_tail": pred_top1,
        "hit_at_2": hit_at_2,
        "hard_miss": hard_miss,
        "has_pred": has_pred,
    })
```

#### Step 5: 集計（全日 + 外れ日分離）

```python
_WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]

# 全日（北斗シグナルあり）
all_valid = [r for r in rows if r["hokuto_best_digit"] is not None]
# 外れ日（hard_miss + 北斗シグナルあり）
miss_valid = [r for r in all_valid if r["hard_miss"] is True]
# soft_miss: hit_at_2==1 だが実際rank1は別（参考値のみ）
soft_miss_valid = [r for r in all_valid if r["hit_at_2"] == 1.0 and r["has_pred"]]

n_digits = df_other["last_digit"].nunique()  # 通常9
baseline = 1 / n_digits if n_digits > 0 else float("nan")

def calc_stats(day_list: list[dict]) -> dict:
    if not day_list:
        return {"n": 0, "hit_rate": float("nan"), "top2_hit_rate": float("nan")}
    return {
        "n": len(day_list),
        "hit_rate": sum(r["is_match"] for r in day_list) / len(day_list),
        "top2_hit_rate": sum(r["is_top2_match"] for r in day_list) / len(day_list),
    }

def weekday_breakdown(day_list: list[dict]) -> dict:
    return {
        wd: calc_stats([r for r in day_list if r["day_of_week"] == wd])
        for wd in _WEEKDAY_ORDER
    }
```

### 出力ファイル

**`signal_accuracy_2fn_daily.csv`**
```
date,day_of_week,hokuto_best_digit,hokuto_best_diff,hokuto_n_valid,
best_2fn_digit,is_match,is_top2_match,pred_top1_tail,hit_at_2,hard_miss,has_pred
```
例（値はサンプル）:
```
20260526,月,0,5111.0,3,2,False,False,5,1.0,False,True
20260524,土,6,3277.0,5,6,True,True,7,0.0,True,True
20260101,木,8,4200.0,2,8,True,True,,,, False
```

**`signal_accuracy_2fn_summary.json`**
```json
{
  "topk_csv_used": "nextday_kamata7_20260527_tasks123_verify_...topk.csv",
  "expert": "2F_N",
  "miss_definition": "hard_miss (hit_at_2 == 0)",
  "min_games_threshold": 3000,
  "n_digits": 9,
  "baseline_random": 0.111,

  "all_days": {
    "n_total": 323,
    "n_with_signal": 280,
    "n_no_signal": 43,
    "hit_rate": 0.XX,
    "top2_hit_rate": 0.XX,
    "lift_over_baseline": 0.XX,
    "weekday": {
      "月": {"n": 45, "hit_rate": 0.XX, "top2_hit_rate": 0.XX},
      "火": {...}, "水": {...}, "木": {...}, "金": {...}, "土": {...}, "日": {...}
    }
  },

  "hard_miss_days": {
    "n_total": 60,
    "n_with_signal": 52,
    "hit_rate": 0.XX,
    "top2_hit_rate": 0.XX,
    "lift_over_baseline": 0.XX,
    "note": "予測top1がactual top-2に入らなかった日（外れ日）",
    "weekday": { ... }
  },

  "soft_miss_reference": {
    "n": 70,
    "hit_rate": 0.XX,
    "note": "hit_at_2==1（top-2には入った）日。top1外れかどうかは未検証。参考値のみ。"
  }
}
```
※ 上記の数値はサンプル値。実際の値とは異なる。

---

## Task 2: `ml/experiments/signal_multi_tail_2fn.py`

### 目的
北斗・モンキーが **複数末尾** でシグナルを出した日に、どの末尾が「真正」（2FN他機種も高い）かを判定する。
「末尾1も末尾5も好調に見える日、どちらを信じるべきか」への答えを統計的に検証する。

### 引数
```
--db-path         必須
--diff-threshold  default=200.0
--rb-threshold    default=0.003333  (= 1/300)
--min-games       default=3000 (個別台ベース)
--output-dir      default="db/experiments/signal_multi_tail_2fn"
--log-level       default="INFO"
```

### 信号判定ロジック

#### 北斗（1台/末尾）
```python
def get_hokuto_signal_tails(df_hokuto_day, min_games, diff_threshold, rb_threshold) -> set[str]:
    valid = df_hokuto_day[df_hokuto_day["games_normalized"] >= min_games].copy()
    signal = valid[
        (valid["diff_coins_normalized"] > diff_threshold) |
        (valid["rb_probability_decimal"] > rb_threshold)
    ]
    return set(signal["last_digit"].astype(str).tolist())
```

#### モンキー（複数台/末尾 → 末尾別AVG）
```python
def get_monkey_signal_tails(df_monkey_day, min_games, diff_threshold, rb_threshold) -> set[str]:
    valid = df_monkey_day[df_monkey_day["games_normalized"] >= min_games].copy()
    if valid.empty:
        return set()
    agg = valid.groupby("last_digit").agg(
        avg_diff=("diff_coins_normalized", "mean"),
        avg_rb=("rb_probability_decimal", "mean"),
    )
    signal = agg[
        (agg["avg_diff"] > diff_threshold) |
        (agg["avg_rb"] > rb_threshold)
    ]
    return set(signal.index.astype(str).tolist())
```

#### 合算シグナル末尾
```python
signal_tails = get_hokuto_signal_tails(...) | get_monkey_signal_tails(...)
```

### 処理フロー

```python
rows = []
for date in sorted(all_dates):
    signal_tails = get_combined_signal_tails(date)
    best_2fn = compute_2fn_best_digit(df_other[df_other["date"] == date])

    n = len(signal_tails)
    category = "no_signal" if n == 0 else ("single" if n == 1 else "multi")
    is_match = (best_2fn is not None and best_2fn in signal_tails)

    # 各シグナル末尾の2FN avg_diff（フェイク判定用）
    df_other_day = df_other[df_other["date"] == date]
    signal_tail_2fn_avgs = {}
    for t in signal_tails:
        sub = df_other_day[df_other_day["last_digit"].astype(str) == t]
        signal_tail_2fn_avgs[t] = float(sub["diff_coins_normalized"].mean()) if not sub.empty else float("nan")

    rows.append({
        "date": date,
        "day_of_week": weekday_map.get(date, ""),
        "n_signal_tails": n,
        "signal_tails": ",".join(sorted(signal_tails)),
        "best_2fn_digit": best_2fn,
        "is_match": is_match,
        "category": category,
        "signal_tail_2fn_avgs": json.dumps(signal_tail_2fn_avgs, ensure_ascii=False),
    })
```

### 集計

```python
single = [r for r in rows if r["category"] == "single"]
multi = [r for r in rows if r["category"] == "multi"]

single_hit = sum(r["is_match"] for r in single) / len(single) if single else float("nan")
multi_hit = sum(r["is_match"] for r in multi) / len(multi) if multi else float("nan")

avg_n_signal_when_multi = (
    sum(r["n_signal_tails"] for r in multi) / len(multi) if multi else float("nan")
)
# フェイク率 = multi日のうち2FN最優秀末尾がシグナル末尾に含まれない割合
fake_rate = sum(not r["is_match"] for r in multi) / len(multi) if multi else float("nan")
```

### 出力ファイル

**`signal_multi_tail_daily.csv`**
```
date,day_of_week,n_signal_tails,signal_tails,best_2fn_digit,is_match,category,signal_tail_2fn_avgs
```

**`signal_multi_tail_summary.json`**
```json
{
  "signal_condition": {
    "diff_threshold": 200.0,
    "rb_threshold": 0.003333,
    "min_games": 3000
  },
  "day_counts": {
    "no_signal": 43,
    "single": 105,
    "multi": 175
  },
  "single_signal_hit_rate": 0.XX,
  "multi_signal_hit_rate": 0.XX,
  "baseline_random": 0.111,
  "multi_signal_detail": {
    "avg_n_signal_tails": 2.8,
    "fake_rate": 0.XX
  },
  "weekday_breakdown": {
    "月": {"single_n": ..., "single_hit": ..., "multi_n": ..., "multi_hit": ...},
    "火": {...}, "水": {...}, "木": {...}, "金": {...}, "土": {...}, "日": {...}
  }
}
```
※ 上記の数値はサンプル値。

---

## 実行コマンド

```bash
# Task 1
python -m ml.experiments.signal_accuracy_2fn \
    --db-path db/マルハンメガシティ2000-蒲田7.db \
    --topk-csv ml/last_digit/reports/nextday_kamata7_20260527_tasks123_verify_xgb_ranker_ndcg_testperiod_topk.csv \
    --min-games 3000 \
    --output-dir db/experiments/signal_accuracy_2fn

# Task 2
python -m ml.experiments.signal_multi_tail_2fn \
    --db-path db/マルハンメガシティ2000-蒲田7.db \
    --diff-threshold 200 \
    --rb-threshold 0.003333 \
    --min-games 3000 \
    --output-dir db/experiments/signal_multi_tail_2fn
```

---

## 注意事項

1. `last_digit` 型は `machine_detailed_results` ではTEXT型 → 比較時は必ず `str()` に統一
2. `daily_hall_summary.day_of_week` は日本語（月、火、水、木、金、土、日）
3. 北斗は全期間通じて末尾4が欠番 → 末尾数は最大9
4. `games_normalized >= 3000` を満たす北斗台がない日は `hokuto_best_digit = None` としてスキップ（no_signal）
5. `rb_probability_decimal > 1/300` — 不等号の向きに注意（`>` であり `<` ではない）
6. testperiod_topk.csv の `date` 列は `YYYY-MM-DD`、DBの `date` は `YYYYMMDD` → 結合前に統一する
7. testperiod_topk.csv の期間（2026-01-01〜）外の日は `has_pred=False` としてNaNで記録
8. `soft_miss`（hit_at_2==1 だが予測rank1でない日）は参考値として出力するが、主指標と混同しない
9. `is_zorome` は今回使用しない
