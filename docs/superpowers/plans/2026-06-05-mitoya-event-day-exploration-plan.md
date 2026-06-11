# Mitoya Event Day Exploration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate whether Mitoya Omorimachi `last_digit` behavior is better explained by `4/14/24` event days than by Wednesday, using the existing Mitoya segmentation and walk-forward outputs first, then the raw base rows.

**Architecture:** Reuse the current Mitoya artifacts and DB-backed row builder rather than changing training code immediately. Split the work into two passes: output-level attribution on the saved walk-forward days, then row-level and segment-level checks on `N/A/BT` aggregates with event-day flags.

**Tech Stack:** Python, pandas, sqlite3-backed project helpers, existing Mitoya scripts/artifacts.

---

### Task 1: Check whether the saved walk-forward results are really weekday-driven

**Files:**
- Read: `db/experiments/tail_ltr_mitoya_wf.json`
- Read: `db/experiments/tail_ltr_mitoya_wf_atype3_focus_days.csv`
- Read: `db/experiments/tail_ltr_mitoya_wf_atype3_raw_days.csv`

- [ ] **Step 1: Confirm the saved runner is splitting on Wednesday**

Run: `venv\Scripts\python.exe - <<'PY'`
```python
from pathlib import Path
import json

data = json.loads(Path("db/experiments/tail_ltr_mitoya_wf.json").read_text(encoding="utf-8"))
print(data["modes"]["atype3"]["focus_nonA"]["wednesday_only"]["n_days"])
print(data["modes"]["atype3"]["focus_nonA"]["non_wednesday"]["n_days"])
PY
```
Expected: nonzero counts for both `wednesday_only` and `non_wednesday`.

- [ ] **Step 2: Add 4/14/24 event-day flags to the saved daily outputs**

Run: `venv\Scripts\python.exe - <<'PY'`
```python
import pandas as pd
from pathlib import Path

for name in ["focus", "raw"]:
    path = Path(f"db/experiments/tail_ltr_mitoya_wf_atype3_{name}_days.csv")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df["day"] = df["date"].dt.day
    df["is_4day"] = df["day"].isin([4, 14, 24])
    df["is_wed"] = df["date"].dt.weekday.eq(2)
    out = path.with_name(path.stem + "_event_flags.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(out, len(df))
PY
```
Expected: two new `_event_flags.csv` files are written.

- [ ] **Step 3: Compare event-day vs non-event-day and Wednesday vs non-Wednesday means**

Run: `venv\Scripts\python.exe - <<'PY'`
```python
import pandas as pd
from pathlib import Path

def summarize(path: str) -> None:
    df = pd.read_csv(path, parse_dates=["date"])
    print(path)
    print("overall_mean", round(df["excess"].mean(), 4))
    print("4day_mean", round(df.loc[df["is_4day"], "excess"].mean(), 4), "n", int(df["is_4day"].sum()))
    print("non4day_mean", round(df.loc[~df["is_4day"], "excess"].mean(), 4), "n", int((~df["is_4day"]).sum()))
    print("wed_mean", round(df.loc[df["is_wed"], "excess"].mean(), 4), "n", int(df["is_wed"].sum()))
    print("nonwed_mean", round(df.loc[~df["is_wed"], "excess"].mean(), 4), "n", int((~df["is_wed"]).sum()))
    print()

summarize("db/experiments/tail_ltr_mitoya_wf_atype3_focus_days_event_flags.csv")
summarize("db/experiments/tail_ltr_mitoya_wf_atype3_raw_days_event_flags.csv")
PY
```
Expected: a first-pass attribution table showing whether `4/14/24` has stronger explanatory power than Wednesday.

### Task 2: Check segment-level behavior on the Mitoya base rows

**Files:**
- Read: `ml/last_digit/mitoya_segmentation.py`
- Read: `db/みとや大森町店.db`

- [ ] **Step 1: Build the Mitoya base rows with current weights**

Run: `venv\Scripts\python.exe - <<'PY'`
```python
from pathlib import Path
from ml.last_digit.mitoya_segmentation import build_base_rows_mitoya

df = build_base_rows_mitoya(
    db_path=Path("db/みとや大森町店.db"),
    a_weight=0.4,
    non_a_weight=1.3,
)
print(df.shape)
print(sorted(df["expert"].dropna().unique().tolist()))
PY
```
Expected: rows load successfully and experts are `['A', 'BT', 'N']`.

- [ ] **Step 2: Aggregate by date and expert with 4/14/24 flags**

Run: `venv\Scripts\python.exe - <<'PY'`
```python
from pathlib import Path
import pandas as pd
from ml.last_digit.mitoya_segmentation import build_base_rows_mitoya

df = build_base_rows_mitoya(
    db_path=Path("db/みとや大森町店.db"),
    a_weight=0.4,
    non_a_weight=1.3,
)
daily = (
    df.groupby(["date", "expert"], as_index=False)
    .agg(
        machine_count=("machine_number", "count"),
        total_diff=("diff_coins_normalized", "sum"),
        focus_diff=("diff_focus", "sum"),
        win_rate=("win_flag", "mean"),
    )
)
daily["day"] = pd.to_datetime(daily["date"]).dt.day
daily["is_4day"] = daily["day"].isin([4, 14, 24])
daily["is_wed"] = pd.to_datetime(daily["date"]).dt.weekday.eq(2)
out = Path("db/experiments/mitoya_event_day_daily_segment_summary.csv")
daily.to_csv(out, index=False, encoding="utf-8-sig")
print(out, len(daily))
PY
```
Expected: segment-by-day artifact is written for inspection.

- [ ] **Step 3: Measure which segment benefits on 4/14/24**

Run: `venv\Scripts\python.exe - <<'PY'`
import pandas as pd

df = pd.read_csv("db/experiments/mitoya_event_day_daily_segment_summary.csv", parse_dates=["date"])
summary = (
    df.groupby(["expert", "is_4day"], as_index=False)
    .agg(
        n_days=("date", "nunique"),
        mean_total_diff=("total_diff", "mean"),
        mean_focus_diff=("focus_diff", "mean"),
        mean_win_rate=("win_rate", "mean"),
    )
)
print(summary.to_string(index=False))
PY
```
Expected: a compact segment table showing whether `BT`, `A`, or `N` carries the 4-day effect.

### Task 3: Decide whether the runner should be changed

**Files:**
- Read: `db/experiments/tail_ltr_mitoya_wf_atype3_focus_days_event_flags.csv`
- Read: `db/experiments/tail_ltr_mitoya_wf_atype3_raw_days_event_flags.csv`
- Read: `db/experiments/mitoya_event_day_daily_segment_summary.csv`

- [ ] **Step 1: Compare four buckets to isolate the true driver**

Run: `venv\Scripts\python.exe - <<'PY'`
```python
import pandas as pd

df = pd.read_csv("db/experiments/tail_ltr_mitoya_wf_atype3_focus_days_event_flags.csv", parse_dates=["date"])
labels = {
    (True, True): "4day_wed",
    (True, False): "4day_nonwed",
    (False, True): "non4day_wed",
    (False, False): "non4day_nonwed",
}
df["bucket"] = [labels[(a, b)] for a, b in zip(df["is_4day"], df["is_wed"])]
summary = df.groupby("bucket", as_index=False).agg(
    n_days=("date", "count"),
    mean_excess=("excess", "mean"),
    median_excess=("excess", "median"),
)
print(summary.to_string(index=False))
PY
```
Expected: one of the buckets stands out enough to justify keeping or replacing the Wednesday split.

- [ ] **Step 2: Make the implementation decision**

Expected:
- If `4day` buckets explain the positive/negative spread better than `wed/nonwed`, change the Mitoya runner next.
- If not, keep the runner as-is and treat `4/14/24` as explanatory context only.
