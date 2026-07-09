# Daily Report Visual Test Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate visual test page for the daily hall report that keeps the current page intact while validating which graphical elements should later be promoted into the existing page.

**Architecture:** Keep `dashboard/pages/page_18_daily_report.py` as the stable baseline and add a new sibling page dedicated to comparison. Reuse the current data-loading, filtering, JST date handling, payout approximation, and heatmap flow, while adding narrowly scoped helper functions for chart-ready aggregation, textual summary generation, and date navigation.

**Tech Stack:** Streamlit, Plotly Express, Pandas, existing dashboard helpers and tests.

---

## File Structure

- Create: `dashboard/pages/page_19_daily_report_visual_test.py`
  - Test-only comparison page with chart-first layout, quick filters, date navigation, summary text, charts, and the existing all-machine/heatmap detail views.
- Modify: `dashboard/utils/daily_report.py`
  - Add shared helper functions that prepare chart-ready frames and natural-language summary strings without duplicating aggregation logic from `page_18`.
- Modify: `dashboard/pages/__init__.py`
  - Export the new page module.
- Modify: `dashboard/config/constants.py`
  - Add the new page to `PAGES`.
- Modify: `dashboard/main.py`
  - Register the new page route.
- Modify: `main_app.py`
  - Register the new page route in the duplicated entrypoint.
- Create: `test/test_daily_report_visual_test.py`
  - Focused tests for helper output, date navigation behavior, chart-preparation branches, and page registration.

## Constraints To Preserve

- `page_18_daily_report.py` remains available and behaviorally unchanged except for shared helper extraction that does not alter current output.
- New page is explicitly a **test version** for evaluating future adoption into the old page.
- Keep JST-based default date behavior.
- Keep the documented `3枚/G` payout approximation and show it in the new page as a visible note.
- Reuse `load_machine_detailed_by_date`, existing filter helpers, and existing heatmap multi-floor behavior.
- Do not add novelty charts that compress multiple metrics into one hard-to-read graphic.

### Task 1: Lock The Comparison-Page Contract In Tests

**Files:**
- Create: `test/test_daily_report_visual_test.py`
- Test: `test/test_daily_report_visual_test.py`

- [ ] **Step 1: Write the failing tests for the new page contract**

```python
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest


def test_prev_next_date_navigation_updates_selected_day(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_19_daily_report_visual_test as page

    state = {"target": date(2026, 7, 1)}

    class _Col:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _button(label: str, **_: object) -> bool:
        return label == "前日へ"

    monkeypatch.setattr(
        page,
        "st",
        SimpleNamespace(
            columns=lambda n: [_Col() for _ in range(n)],
            button=_button,
            session_state=state,
        ),
    )

    result = page._step_target_date("target")

    assert result == date(2026, 6, 30)


def test_build_visual_group_frames_returns_expected_metric_columns() -> None:
    import dashboard.utils.daily_report as report

    daily = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "machine_name": ["A", "A", "B", "B"],
            "last_digit": ["1", "2", "1", "2"],
            "games_normalized": [2000, 1800, 2100, 1900],
            "diff_coins_normalized": [300, 150, -50, 400],
        }
    )
    layout = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "rank_from_min": [1, 2, 1, 2],
            "section": ["S1", "S1", "S2", "S2"],
        }
    )

    frames = report.build_visual_group_frames(daily, layout_frame=layout, master_frame=pd.DataFrame())

    assert set(frames) >= {"machine_name", "last_digit", "rank_from_min", "section"}
    assert list(frames["machine_name"].columns) == [
        "machine_name",
        "n",
        "avg_diff",
        "avg_games",
        "avg_payout_rate",
        "win_rate",
        "hit104_count",
        "hit104_rate",
    ]


def test_build_scatter_frame_keeps_numeric_axes() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "machine_number": [101, 102],
            "machine_name": ["A", "B"],
            "games_normalized": [2000, 1500],
            "diff_coins_normalized": [300, -100],
        }
    )

    scatter = report.build_daily_scatter_frame(frame)

    assert list(scatter.columns) == [
        "machine_number",
        "machine_name",
        "games_normalized",
        "diff_coins_normalized",
        "payout_rate",
        "hit104",
    ]
    assert scatter["games_normalized"].dtype.kind in "if"
    assert scatter["diff_coins_normalized"].dtype.kind in "if"


def test_page_registration_includes_visual_test_page() -> None:
    from dashboard.config.constants import PAGES
    from dashboard.pages import __all__ as page_exports

    assert any(page["key"] == "daily_report_visual_test" for page in PAGES)
    assert "page_19_daily_report_visual_test" in page_exports
```

- [ ] **Step 2: Run the new focused test file and verify it fails**

Run: `venv\Scripts\python.exe -m pytest test/test_daily_report_visual_test.py -q`

Expected: FAIL because `page_19_daily_report_visual_test` and the new helper functions do not exist yet.

- [ ] **Step 3: Commit the failing-test checkpoint**

```bash
git add test/test_daily_report_visual_test.py
git commit -m "test: define daily report visual test page contract"
```

### Task 2: Add Shared Helper Functions For Visual Aggregation

**Files:**
- Modify: `dashboard/utils/daily_report.py`
- Test: `test/test_daily_report_visual_test.py`

- [ ] **Step 1: Add a failing test for summary text generation**

```python
def test_build_daily_highlight_summary_mentions_top_signals() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "machine_name": ["A", "A", "B", "B"],
            "games_normalized": [2200, 2000, 1800, 1700],
            "diff_coins_normalized": [450, 300, -50, 80],
        }
    )

    summary = report.build_daily_highlight_summary(frame, machine_label="機種別")

    assert "機種別" in summary
    assert "A" in summary
    assert "差枚" in summary
```

- [ ] **Step 2: Run the single test and verify it fails**

Run: `venv\Scripts\python.exe -m pytest test/test_daily_report_visual_test.py::test_build_daily_highlight_summary_mentions_top_signals -q`

Expected: FAIL because `build_daily_highlight_summary` is undefined.

- [ ] **Step 3: Implement the shared helper functions with minimal surface area**

```python
def build_visual_group_frames(
    daily_frame: pd.DataFrame,
    *,
    layout_frame: pd.DataFrame,
    master_frame: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {
        "machine_name": summarize_group_performance(daily_frame, "machine_name"),
        "last_digit": summarize_group_performance(daily_frame, "last_digit"),
    }
    if not layout_frame.empty:
        if "rank_from_min" in layout_frame.columns:
            frames["rank_from_min"] = build_layout_summary(daily_frame, layout_frame, group_column="rank_from_min")
        if "section" in layout_frame.columns:
            frames["section"] = build_layout_summary(daily_frame, layout_frame, group_column="section")
    if not master_frame.empty:
        segment = build_segment_summary(daily_frame, master_frame)
        if not segment.empty:
            frames["segment"] = segment
    return {key: value for key, value in frames.items() if not value.empty}


def build_daily_scatter_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = add_hit104_flag(frame)
    columns = [
        "machine_number",
        "machine_name",
        "games_normalized",
        "diff_coins_normalized",
        "payout_rate",
        "hit104",
    ]
    available = [column for column in columns if column in work.columns]
    return work.loc[:, available].reset_index(drop=True)


def build_daily_highlight_summary(frame: pd.DataFrame, *, machine_label: str) -> str:
    grouped = summarize_group_performance(frame, "machine_name")
    if grouped.empty:
        return f"{machine_label}の目立った傾向は抽出できませんでした。"
    top = grouped.iloc[0]
    return (
        f"{machine_label}では {top['machine_name']} が最上位で、"
        f"平均差枚 {top['avg_diff']:.0f}、勝率 {top['win_rate'] * 100:.1f}% が目立ちます。"
    )
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run: `venv\Scripts\python.exe -m pytest test/test_daily_report_visual_test.py -q`

Expected: PASS for helper-focused tests, with registration/page-import tests still failing until later tasks land.

- [ ] **Step 5: Commit the helper checkpoint**

```bash
git add dashboard/utils/daily_report.py test/test_daily_report_visual_test.py
git commit -m "feat: add visual daily report helper functions"
```

### Task 3: Build The New Visual Test Page

**Files:**
- Create: `dashboard/pages/page_19_daily_report_visual_test.py`
- Test: `test/test_daily_report_visual_test.py`

- [ ] **Step 1: Add a failing test for the visible note and chart-ready layout entrypoints**

```python
def test_visual_test_page_shows_test_version_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_19_daily_report_visual_test as page

    captions: list[str] = []

    monkeypatch.setattr(
        page,
        "st",
        SimpleNamespace(
            session_state={"hall_name": None, "db_path": None},
            warning=lambda message: captions.append(message),
            markdown=lambda message: captions.append(message),
            caption=lambda message: captions.append(message),
        ),
    )

    page.render()

    assert any("テスト版" in str(message) for message in captions)
```

- [ ] **Step 2: Run the single test and verify it fails**

Run: `venv\Scripts\python.exe -m pytest test/test_daily_report_visual_test.py::test_visual_test_page_shows_test_version_caption -q`

Expected: FAIL because the new page file does not exist yet.

- [ ] **Step 3: Implement the visual test page with the comparison-first layout**

```python
st.markdown("## 前日レポート 可視化テスト版")
st.caption("旧ページに導入する要素を比較確認するためのテスト版です。集計条件は既存ページと揃えます。")
st.info("機械割は 3枚/G の近似値です。機種ごとの正確な投入枚数は反映していません。")

target_date = _step_target_date(f"daily_report_visual_test_date_{hall_name}")
daily_df = load_machine_detailed_by_date(str(db_path), _format_date_key(target_date))
daily_df = apply_machine_filters(daily_df, None, min_games, show_low_confidence)
daily_df = add_hit104_flag(daily_df)

frames = build_visual_group_frames(daily_df, layout_frame=layout_frame, master_frame=master_frame)
scatter = build_daily_scatter_frame(daily_df)

st.markdown("### サマリー")
st.write(build_daily_highlight_summary(daily_df, machine_label="機種別"))

st.markdown("### カテゴリ別グラフ")
_render_metric_bar_tabs(frames, metric="avg_diff", title="差枚比較")
_render_metric_bar_tabs(frames, metric="win_rate", title="勝率比較")
_render_metric_bar_tabs(frames, metric="hit104_rate", title="104%超え比率比較")

st.markdown("### 全台散布図")
_render_diff_games_scatter(scatter)

st.markdown("### TOP5 / ワースト5")
_render_rank_sections(...)

st.markdown("### 全台テーブル")
_render_table("台番号順", filter_search_query(_prepare_all_table(daily_df), search_query))

st.markdown("### フロアヒートマップ")
_render_heatmap_views(...)
```

- [ ] **Step 4: Include the local page helpers needed for readability**

```python
def _step_target_date(key: str) -> date:
    current = st.session_state.get(key, _default_target_date())
    prev_col, next_col, picker_col = st.columns([1, 1, 3])
    with prev_col:
        if st.button("前日へ", key=f"{key}_prev"):
            current = current - timedelta(days=1)
    with next_col:
        if st.button("翌日へ", key=f"{key}_next"):
            current = current + timedelta(days=1)
    st.session_state[key] = current
    with picker_col:
        picked = st.date_input("対象日", value=current, key=f"{key}_picker")
    st.session_state[key] = picked
    return picked


def _render_metric_bar_tabs(frames: dict[str, pd.DataFrame], *, metric: str, title: str) -> None:
    if not frames:
        st.info("グラフ化できる集計がありません")
        return
    tabs = st.tabs(list(frames.keys()))
    for tab, (label, frame) in zip(tabs, frames.items()):
        with tab:
            chart = px.bar(frame.head(10), x=metric, y=frame.columns[0], orientation="h")
            st.plotly_chart(chart, use_container_width=True)
```

- [ ] **Step 5: Run the new page test file and verify the page imports and branch tests pass**

Run: `venv\Scripts\python.exe -m pytest test/test_daily_report_visual_test.py -q`

Expected: PASS for helper and page tests, with registration tests still failing until Task 4 is complete.

- [ ] **Step 6: Commit the page implementation checkpoint**

```bash
git add dashboard/pages/page_19_daily_report_visual_test.py test/test_daily_report_visual_test.py
git commit -m "feat: add visual test version of daily report page"
```

### Task 4: Register The Comparison Page Alongside The Existing Page

**Files:**
- Modify: `dashboard/pages/__init__.py`
- Modify: `dashboard/config/constants.py`
- Modify: `dashboard/main.py`
- Modify: `main_app.py`
- Test: `test/test_daily_report_visual_test.py`

- [ ] **Step 1: Add the new page import/export in the package index**

```python
from . import page_18_daily_report, page_19_daily_report_visual_test

__all__ = [
    ...
    "page_18_daily_report",
    "page_19_daily_report_visual_test",
]
```

- [ ] **Step 2: Register the page in both router entrypoints**

```python
from dashboard.pages import page_18_daily_report, page_19_daily_report_visual_test

PAGE_ROUTER = {
    ...
    "daily_report": page_18_daily_report.render,
    "daily_report_visual_test": page_19_daily_report_visual_test.render,
}
```

- [ ] **Step 3: Add the page metadata entry to the visible navigation list**

```python
{
    "key": "daily_report_visual_test",
    "label": "前日レポート(可視化テスト版)",
    "icon": "📈",
}
```

- [ ] **Step 4: Run the focused registration tests and verify they pass**

Run: `venv\Scripts\python.exe -m pytest test/test_daily_report_visual_test.py::test_page_registration_includes_visual_test_page -q`

Expected: PASS

- [ ] **Step 5: Commit the registration checkpoint**

```bash
git add dashboard/pages/__init__.py dashboard/config/constants.py dashboard/main.py main_app.py test/test_daily_report_visual_test.py
git commit -m "feat: register daily report visual test page"
```

### Task 5: Full Verification And Comparison Readiness Check

**Files:**
- Modify: `dashboard/pages/page_19_daily_report_visual_test.py`
- Modify: `dashboard/utils/daily_report.py`
- Test: `test/test_daily_report.py`
- Test: `test/test_daily_report_visual_test.py`
- Test: `test/heatmap/test_page_17_heatmap.py`
- Test: `test/test_filters.py`

- [ ] **Step 1: Run compile checks on the touched files**

Run: `venv\Scripts\python.exe -m py_compile dashboard/utils/daily_report.py dashboard/pages/page_18_daily_report.py dashboard/pages/page_19_daily_report_visual_test.py test/test_daily_report.py test/test_daily_report_visual_test.py`

Expected: no output

- [ ] **Step 2: Run the targeted regression suite**

Run: `venv\Scripts\python.exe -m pytest test/test_daily_report.py test/test_daily_report_visual_test.py test/heatmap/test_page_17_heatmap.py test/test_filters.py -q`

Expected: PASS

- [ ] **Step 3: Do one manual smoke pass in Streamlit**

Run: `venv\Scripts\python.exe -m streamlit run main_app.py`

Expected:
- Both `前日レポート` and `前日レポート(可視化テスト版)` appear in navigation
- New page shows the test-version caption and payout-approximation note
- Date stepping works
- Bar charts render for available groupings
- Scatter plot renders with numeric axes
- Existing page still opens and behaves the same as before

- [ ] **Step 4: Record comparison criteria in the PR or handoff note**

```text
Compare page_18 vs visual test page on:
1. 初見で全体像を把握しやすいか
2. 末尾・角番・Sectionの強弱を拾いやすいか
3. 全台の高稼働/高差枚/低稼働一発台を見分けやすいか
4. 動作の重さが許容範囲か
```

- [ ] **Step 5: Commit the verified final checkpoint**

```bash
git add dashboard/utils/daily_report.py dashboard/pages/page_19_daily_report_visual_test.py dashboard/pages/__init__.py dashboard/config/constants.py dashboard/main.py main_app.py test/test_daily_report_visual_test.py
git commit -m "feat: add visual test variant of daily report page"
```

## Self-Review

- Spec coverage: The plan covers the separate test page, reuse of current logic, graph-first additions, quick date navigation, visible approximation note, unchanged old page, registration, and targeted verification.
- Placeholder scan: No `TODO` or deferred implementation markers remain. Each task includes exact files, commands, and concrete code shapes.
- Type consistency: The plan uses `pd.DataFrame`, `dict[str, pd.DataFrame]`, `date`, and the same router key `daily_report_visual_test` throughout.

