from __future__ import annotations

import pandas as pd


def compute_is_a_type_flag(df: pd.DataFrame) -> pd.Series:
    return (
        (pd.to_numeric(df.get("jug_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df.get("hana_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df.get("oki_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df.get("bt_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
    )


def add_floor_atype4_columns(
    df: pd.DataFrame,
    *,
    machine_number_col: str = "machine_number",
) -> pd.DataFrame:
    work = df.copy()
    work[machine_number_col] = pd.to_numeric(work[machine_number_col], errors="coerce")
    work = work[work[machine_number_col].notna()].copy()
    work[machine_number_col] = work[machine_number_col].astype(int)
    work["floor_head"] = work[machine_number_col].astype(str).str[0]
    work = work[work["floor_head"].isin(["2", "3"])].copy()
    work["floor_bucket"] = work["floor_head"] + "F"
    work["is_a_type"] = compute_is_a_type_flag(work).astype(int)
    work["atype_bucket"] = work["is_a_type"].map({1: "A", 0: "N"})
    work["expert"] = work["floor_bucket"] + "_" + work["atype_bucket"]
    return work
