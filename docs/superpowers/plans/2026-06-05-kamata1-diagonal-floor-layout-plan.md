# Kamata1 Diagonal Floor Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Kamata1 2F coordinate CSV so diagonal, horizontal, and vertical machine rows match the supplied floor map and render correctly in Streamlit.

**Architecture:** Store integer logical coordinates in `X/Y` and integer drawing coordinates in `display_x/display_y`. Generate the CSV from explicit row definitions so the layout can be corrected without manually editing hundreds of rows, and update the shared renderer to prefer both display axes when present.

**Tech Stack:** Python 3, pandas, Plotly, Streamlit, pytest

---

### Task 1: Add coordinate validation tests

**Files:**
- Create: `test/heatmap/test_floor_coordinates.py`
- Read: `Heatmap/2F_floor_coordinates.csv`

- [x] **Step 1: Write tests for the CSV contract**

Create tests that assert:

```python
REQUIRED_COLUMNS = {
    "hall_name",
    "machine_number",
    "X",
    "Y",
    "display_x",
    "display_y",
    "section",
    "section_min",
    "section_max",
    "rank_from_min",
    "rank_from_max",
}
```

The tests must also assert unique machine numbers, unique display coordinate pairs,
the absence of `2341-2398`, and continuous section ranks.

- [x] **Step 2: Add representative diagonal assertions**

For `2001-2020`, sort by machine number and assert that consecutive
`display_x` differences are `1` and consecutive `display_y` differences are `-1`.

- [x] **Step 3: Run the tests and verify the current CSV fails**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/heatmap/test_floor_coordinates.py -q
```

Expected: failure because `display_x` is absent and `2001-2020` is horizontal.

### Task 2: Build a declarative coordinate generator

**Files:**
- Create: `Heatmap/generate_kamata1_coordinates.py`
- Modify: `Heatmap/2F_floor_coordinates.csv`

- [x] **Step 1: Define row primitives**

Implement helpers for horizontal, vertical, and diagonal machine sequences:

```python
def add_run(
    rows: list[dict[str, object]],
    machines: list[int],
    start_x: int,
    start_y: int,
    step_x: int,
    step_y: int,
) -> None:
    ...
```

Each machine receives `display_x = start_x + index * step_x` and
`display_y = start_y + index * step_y`.

- [x] **Step 2: Define sections from the supplied map**

Split broad numeric ranges whenever the floor map changes direction or row:

```text
2001-2020: diagonal
2021-2031: horizontal
2032-2042: horizontal
2043-2059: diagonal
2060-2076: diagonal
2077-2087: horizontal
2088-2098: horizontal
2099-2109: diagonal
2110-2120: diagonal
2121-2131: horizontal
2132-2142: horizontal
```

Continue the same process for every included machine through `2415`, excluding
`2341-2398`.

- [x] **Step 3: Derive section metadata**

For each physical run, calculate:

```python
section_min = min(machines)
section_max = max(machines)
section = f"{section_min}-{section_max}"
rank_from_min = machine_number - section_min + 1
rank_from_max = section_max - machine_number + 1
```

- [x] **Step 4: Generate the CSV**

Run:

```powershell
venv\Scripts\python.exe Heatmap/generate_kamata1_coordinates.py
```

Expected: `Heatmap/2F_floor_coordinates.csv` is regenerated with integer
`display_x/display_y` coordinates.

- [x] **Step 5: Run coordinate tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/heatmap/test_floor_coordinates.py -q
```

Expected: all coordinate contract tests pass.

### Task 3: Support display X coordinates in the renderer

**Files:**
- Modify: `Heatmap/heatmap_common.py`
- Create: `test/heatmap/test_heatmap_coordinates.py`

- [x] **Step 1: Write a failing axis-selection test**

Extract a small helper:

```python
def get_display_columns(columns: Collection[str]) -> tuple[str, str]:
    x_column = "display_x" if "display_x" in columns else "X"
    y_column = "display_y" if "display_y" in columns else "Y"
    return x_column, y_column
```

Test that both display columns are selected when present and legacy `X/Y` are
selected otherwise.

- [x] **Step 2: Run the test and verify it fails**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/heatmap/test_heatmap_coordinates.py -q
```

Expected: failure because `get_display_columns` does not exist.

- [x] **Step 3: Implement display-axis selection**

Parse `display_x` numerically when present, use the selected X column for matrix
width, matrix indexing, and hover coordinates, and preserve the existing fallback.

- [x] **Step 4: Run renderer tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/heatmap/test_heatmap_coordinates.py -q
```

Expected: all tests pass.

### Task 4: Verify the Streamlit page

**Files:**
- Verify: `Heatmap/HeatmapKamata1.py`
- Verify: `Heatmap/2F_floor_coordinates.csv`
- Verify: `Heatmap/heatmap_common.py`

- [x] **Step 1: Run all heatmap tests**

```powershell
venv\Scripts\python.exe -m pytest test/heatmap -q
```

- [x] **Step 2: Run syntax checks**

```powershell
venv\Scripts\python.exe -m py_compile Heatmap/heatmap_common.py Heatmap/HeatmapKamata1.py Heatmap/generate_kamata1_coordinates.py
```

- [x] **Step 3: Start the page**

```powershell
streamlit run Heatmap/HeatmapKamata1.py
```

- [x] **Step 4: Inspect the rendered layout**

Confirm the top-left `2001-2020` row is diagonal, rectangular islands remain
horizontal, `2399-2415` is vertical, passages remain visible, and excluded
machines do not appear.
