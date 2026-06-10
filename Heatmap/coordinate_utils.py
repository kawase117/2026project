"""Coordinate column selection shared by heatmap renderers."""

from __future__ import annotations

import os
from collections.abc import Collection

import pandas as pd


def get_display_columns(columns: Collection[str]) -> tuple[str, str]:
    """Return preferred drawing columns with legacy X/Y fallback."""

    x_column = "display_x" if "display_x" in columns else "X"
    y_column = "display_y" if "display_y" in columns else "Y"
    return x_column, y_column


def find_floor_csvs(hall_name: str, project_root: str) -> list[dict[str, str]]:
    """Find floor coordinate CSVs for a hall under ``project_root/Heatmap``."""

    heatmap_dir = os.path.join(project_root, "Heatmap")
    results: list[dict[str, str]] = []

    if not os.path.exists(heatmap_dir):
        return results

    for fname in sorted(os.listdir(heatmap_dir)):
        if "floor_coordinates" not in fname or not fname.endswith(".csv"):
            continue

        csv_path = os.path.join(heatmap_dir, fname)

        try:
            hall_df = pd.read_csv(csv_path, dtype=str, usecols=["hall_name"])
        except (ValueError, KeyError):
            continue
        except Exception:
            continue

        if not (hall_df["hall_name"] == hall_name).any():
            continue

        try:
            floor_df = pd.read_csv(csv_path, dtype=str, usecols=["hall_name", "floor"])
            floors = (
                floor_df.loc[floor_df["hall_name"] == hall_name, "floor"]
                .dropna()
                .unique()
                .tolist()
            )
        except (ValueError, KeyError):
            floors = ["フロア"]
        except Exception:
            continue

        if not floors:
            floors = ["フロア"]

        for floor in floors:
            results.append({"path": csv_path, "floor": str(floor)})

    return sorted(results, key=lambda item: (item["floor"], item["path"]))
