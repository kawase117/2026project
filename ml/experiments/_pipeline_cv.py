"""Time-series cross-validation splitters for pipeline."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from ml.experiments._pipeline_config import FoldWindow


class ExpandingWindowSplitter:
    def __init__(self, n_splits: int = 5, valid_window_size: int | None = None) -> None:
        self.n_splits = n_splits
        self.valid_window_size = valid_window_size

    def split(self, df: pd.DataFrame, date_column: str = "date") -> Iterable[FoldWindow]:
        df_sorted = df.sort_values(date_column).reset_index(drop=True)
        dates = pd.to_datetime(df_sorted[date_column])
        unique_dates = pd.Index(np.sort(dates.unique()))
        if len(unique_dates) < self.n_splits + 2:
            raise ValueError("Not enough unique dates for expanding-window split")

        valid_size = self.valid_window_size or max(1, len(unique_dates) // (self.n_splits + 1))
        train_size = len(unique_dates) - (valid_size * self.n_splits)
        if train_size < 1:
            raise ValueError("Initial expanding-window train size is too small")

        for fold_index in range(self.n_splits):
            train_dates = unique_dates[: train_size + (fold_index * valid_size)]
            valid_start = train_size + (fold_index * valid_size)
            valid_end = valid_start + valid_size
            valid_dates = unique_dates[valid_start:valid_end]
            train_mask = dates.isin(train_dates)
            valid_mask = dates.isin(valid_dates)
            yield FoldWindow(
                fold_index=fold_index,
                train_indices=np.flatnonzero(train_mask.to_numpy()),
                valid_indices=np.flatnonzero(valid_mask.to_numpy()),
                train_start_date=pd.Timestamp(train_dates.min()),
                train_end_date=pd.Timestamp(train_dates.max()),
                valid_start_date=pd.Timestamp(valid_dates.min()),
                valid_end_date=pd.Timestamp(valid_dates.max()),
            )


class SlidingWindowSplitter:
    def __init__(
        self,
        n_splits: int = 5,
        train_window_size: int | None = None,
        valid_window_size: int | None = None,
    ) -> None:
        self.n_splits = n_splits
        self.train_window_size = train_window_size
        self.valid_window_size = valid_window_size

    def split(self, df: pd.DataFrame, date_column: str = "date") -> Iterable[FoldWindow]:
        df_sorted = df.sort_values(date_column).reset_index(drop=True)
        dates = pd.to_datetime(df_sorted[date_column])
        unique_dates = pd.Index(np.sort(dates.unique()))
        if len(unique_dates) < self.n_splits + 2:
            raise ValueError("Not enough unique dates for sliding-window split")

        valid_size = self.valid_window_size or max(1, len(unique_dates) // (self.n_splits + 2))
        train_size = self.train_window_size or max(valid_size + 1, len(unique_dates) - (valid_size * self.n_splits))
        total_required = train_size + (valid_size * self.n_splits)
        if total_required > len(unique_dates):
            raise ValueError("Sliding-window train/valid sizes exceed available dates")

        for fold_index in range(self.n_splits):
            train_start = fold_index * valid_size
            train_end = train_start + train_size
            valid_end = train_end + valid_size
            train_dates = unique_dates[train_start:train_end]
            valid_dates = unique_dates[train_end:valid_end]
            train_mask = dates.isin(train_dates)
            valid_mask = dates.isin(valid_dates)
            yield FoldWindow(
                fold_index=fold_index,
                train_indices=np.flatnonzero(train_mask.to_numpy()),
                valid_indices=np.flatnonzero(valid_mask.to_numpy()),
                train_start_date=pd.Timestamp(train_dates.min()),
                train_end_date=pd.Timestamp(train_dates.max()),
                valid_start_date=pd.Timestamp(valid_dates.min()),
                valid_end_date=pd.Timestamp(valid_dates.max()),
            )
