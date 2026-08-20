"""Dataset parsing and schema profiling.

Runs in the worker, never in the API process. Uploaded bytes are untrusted
input (threat model T2): parse failures and resource-limit breaches produce a
terminal `invalid` version with a stable reason — they never raise into the
job runner or get "fixed" by relaxing a limit.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import polars as pl

from crucible.domain import (
    MAX_COLUMNS,
    MAX_ROWS,
    ColumnProfile,
    DatasetProfile,
)

_MAX_SAMPLE_CHARS = 64


@dataclass(frozen=True, slots=True)
class ProfileFailure:
    reason: str  # short, stable, user-safe
    detail: str  # bounded diagnostic, safe to store


def profile_bytes(data: bytes, *, content_type: str) -> DatasetProfile | ProfileFailure:
    try:
        frame = _read(data, content_type)
    except Exception as exc:
        return ProfileFailure(
            reason="dataset_parse_error",
            detail=f"{type(exc).__name__}: {str(exc)[:200]}",
        )

    n_rows, n_cols = frame.height, frame.width
    if n_cols == 0 or n_rows == 0:
        return ProfileFailure(reason="dataset_empty", detail="File contains no rows or columns.")
    if n_cols > MAX_COLUMNS:
        return ProfileFailure(
            reason="too_many_columns", detail=f"{n_cols} columns exceeds limit of {MAX_COLUMNS}."
        )
    if n_rows > MAX_ROWS:
        # Guards decompression bombs: a small Parquet file can expand to
        # hundreds of millions of rows.
        return ProfileFailure(
            reason="too_many_rows", detail=f"{n_rows} rows exceeds limit of {MAX_ROWS}."
        )

    columns = tuple(_column_profile(frame, name) for name in frame.columns)
    return DatasetProfile(row_count=n_rows, column_count=n_cols, columns=columns)


def _read(data: bytes, content_type: str) -> pl.DataFrame:
    buf = io.BytesIO(data)
    if content_type == "application/vnd.apache.parquet":
        return pl.read_parquet(buf)
    return pl.read_csv(buf, infer_schema_length=10_000, try_parse_dates=True)


def _column_profile(frame: pl.DataFrame, name: str) -> ColumnProfile:
    series = frame.get_column(name)
    min_value = max_value = None
    try:
        raw_min, raw_max = series.min(), series.max()
        min_value = _clip(raw_min)
        max_value = _clip(raw_max)
    except Exception:
        pass
    return ColumnProfile(
        name=name,
        dtype=str(series.dtype),
        null_count=int(series.null_count()),
        distinct_count=int(series.n_unique()),
        min_value=min_value,
        max_value=max_value,
    )


def _clip(value: object) -> str | None:
    if value is None:
        return None
    return str(value)[:_MAX_SAMPLE_CHARS]
