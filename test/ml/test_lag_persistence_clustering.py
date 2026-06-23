from __future__ import annotations

import pandas as pd

from ml.machine_type.exploratory import run_lag_persistence_clustering as clustering


def _make_group_rows(
    *,
    hall_id: str,
    machine_name: str,
    x_values: list[float],
    y_values: list[float],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx, (x, y) in enumerate(zip(x_values, y_values, strict=True), start=1):
        rows.append(
            {
                "hall_id": hall_id,
                "machine_name": machine_name,
                "lag1_efficiency": float(x),
                "efficiency": float(y),
                "n": idx,
            }
        )
    return rows


def test_build_lag_persistence_table_classifies_positive_negative_and_neutral_groups() -> None:
    x20 = list(range(1, 21))
    neutral_y = [1, 20, 2, 19, 3, 18, 4, 17, 5, 16, 6, 15, 7, 14, 8, 13, 9, 12, 10, 11]
    rows = []
    rows += _make_group_rows(hall_id="hall_a", machine_name="pos", x_values=x20, y_values=x20)
    rows += _make_group_rows(hall_id="hall_a", machine_name="neg", x_values=x20, y_values=list(reversed(x20)))
    rows += _make_group_rows(hall_id="hall_a", machine_name="neu", x_values=x20, y_values=neutral_y)
    rows += _make_group_rows(hall_id="hall_a", machine_name="tiny", x_values=list(range(1, 10)), y_values=list(range(1, 10)))
    frame = pd.DataFrame(rows)

    table = clustering.build_lag_persistence_table(frame, "lag1_efficiency", "efficiency", ["machine_name"])
    annotated = clustering.annotate_persistence_type(table)

    assert set(annotated["machine_name"]) == {"pos", "neg", "neu"}
    assert annotated.loc[annotated["machine_name"] == "pos", "persistence_type"].iloc[0] == "persistence"
    assert annotated.loc[annotated["machine_name"] == "neg", "persistence_type"].iloc[0] == "reversal"
    assert annotated.loc[annotated["machine_name"] == "neu", "persistence_type"].iloc[0] == "neutral"
    assert annotated.loc[annotated["machine_name"] == "pos", "n"].iloc[0] == 20
    assert annotated.loc[annotated["machine_name"] == "pos", "n_rows"].iloc[0] == 20


def test_build_lag_persistence_table_excludes_groups_with_too_few_samples() -> None:
    rows = _make_group_rows(
        hall_id="hall_a",
        machine_name="small",
        x_values=list(range(1, 10)),
        y_values=list(range(1, 10)),
    )
    frame = pd.DataFrame(rows)

    table = clustering.build_lag_persistence_table(frame, "lag1_efficiency", "efficiency", ["machine_name"])

    assert table.empty


def test_build_hall_conflict_table_finds_same_machine_name_with_opposite_signs() -> None:
    x20 = list(range(1, 21))
    rows = []
    rows += _make_group_rows(hall_id="hall_a", machine_name="shared", x_values=x20, y_values=x20)
    rows += _make_group_rows(hall_id="hall_b", machine_name="shared", x_values=x20, y_values=list(reversed(x20)))
    rows += _make_group_rows(hall_id="hall_c", machine_name="solo", x_values=x20, y_values=x20)
    frame = pd.DataFrame(rows)

    table = clustering.build_lag_persistence_table(frame, "lag1_efficiency", "efficiency", ["hall_id", "machine_name"])
    conflict = clustering.build_hall_conflict_table(table)
    summary = clustering.build_hall_conflict_summary(table)

    assert set(conflict["machine_name"]) == {"shared"}
    assert set(conflict["hall_id"]) == {"hall_a", "hall_b"}
    assert set(conflict["rho_sign"]) == {-1, 1}
    assert summary.loc[summary["machine_name"] == "shared", "hall_count"].iloc[0] == 2
    assert summary.loc[summary["machine_name"] == "shared", "positive_halls"].iloc[0] == 1
    assert summary.loc[summary["machine_name"] == "shared", "negative_halls"].iloc[0] == 1

