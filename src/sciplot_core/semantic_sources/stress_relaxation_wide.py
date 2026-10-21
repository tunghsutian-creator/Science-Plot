"""Exact compact time/normalized-stress pairs, with closed source row evidence."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.semantic_sources.models import CurveSeriesPayload


class StressSourceBindingError(ValueError):
    """A recoverable stress-source mismatch, never a different experiment."""

    def __init__(self, source_id: str, column: int, expected: str, observed: object,
                 *, row: int | None = None) -> None:
        self.issues: list[dict[str, Any]] = [{
            "source_id": source_id, "column": column, "row": row,
            "expected": expected, "observed": str(observed)[:400],
            "continuation": {"action": "correct_source_mapping", "field": "mapping",
                             "preserve_raw": True, "same_task": True},
        }]
        super().__init__(f"{source_id}, column {column}, row {row}: expected {expected}; observed {observed!s}.")


def normalized_header_identity(header: object) -> tuple[str, str, str] | None:
    """Interpret only the explicit compact schema; no modulus or unit guesses."""
    value = str(header).strip()
    sample, separator, metric = value.rpartition("|")
    if not separator:
        metric, sample = value, ""
    identities = {"t_s": ("Time", "s"),
                  "sigma_over_sigma0": ("Normalized stress", "sigma/sigma0")}
    identity = identities.get(metric)
    return (sample, *identity) if identity is not None else None


def read_normalized_wide(source: Path, raw: pd.DataFrame) -> list[CurveSeriesPayload] | None:
    """Read independently ragged pairs; interior holes and partial pairs fail closed."""
    if raw.empty:
        return None
    headers = [str(value).strip() for value in raw.iloc[0]]
    identities = [normalized_header_identity(value) for value in headers]
    if not any(identity is not None for identity in identities):
        return None
    if len(headers) % 2:
        raise StressSourceBindingError(source.name, len(headers) - 1,
                                       "adjacent t_s/sigma_over_sigma0 pair", headers[-1])
    result = []
    for column in range(0, len(headers), 2):
        x, y = identities[column:column + 2]
        if x is None or y is None or x[1] != "Time" or y[1] != "Normalized stress" or x[0] != y[0]:
            raise StressSourceBindingError(source.name, column,
                                           "same-sample adjacent t_s/sigma_over_sigma0", headers[column:column + 2])
        sample = x[0] or source.stem
        if any(series.sample == sample for series in result):
            raise StressSourceBindingError(sample, column, "unique original pair identity", sample)
        points, rows = [], []
        ended = False
        for row in range(1, len(raw)):
            cells = [raw.iat[row, index] for index in (column, column + 1)]
            empty = [pd.isna(value) or not str(value).strip() for value in cells]
            if all(empty):
                ended = True
                continue
            if ended or any(empty):
                bad_column = column + (1 if empty[1] and not empty[0] else 0)
                raise StressSourceBindingError(sample, bad_column,
                    "contiguous complete finite pairs followed only by empty trailing cells", cells, row=row)
            try:
                pair = (float(cells[0]), float(cells[1]))
            except (ValueError, TypeError) as exc:
                raise StressSourceBindingError(sample, column, "finite time/normalized stress", cells, row=row) from exc
            if not all(math.isfinite(value) for value in pair):
                raise StressSourceBindingError(sample, column, "finite time/normalized stress", cells, row=row)
            points.append(pair)
            rows.append(row)
        if len(points) < 2:
            raise StressSourceBindingError(sample, column, "at least two original paired points", len(points))
        result.append(CurveSeriesPayload(
            sample=sample, x_label="Time", x_unit="s", y_label="Normalized stress",
            y_unit="sigma/sigma0", points=tuple(points), diagnostics={
                "source_id": sample, "source_file": str(source), "source_header_row_index": 0,
                "source_x_column_index": column, "source_y_column_index": column + 1,
                "source_x_header": headers[column], "source_y_header": headers[column + 1],
                "source_x_unit": "s", "source_y_unit": "sigma/sigma0",
                "source_sample_detection": "explicit_compact_pair_header",
                "source_point_count": len(points), "source_paired_row_indices": rows,
                "source_first_point": list(points[0]),
                "normalization_applied": False,
                "normalization_fallback": "already_normalized_source_preserved",
                "normalization_definition": "source already reports sigma_over_sigma0; preserve every supplied value",
                "time_reset_definition": "preserve source time unchanged",
            }))
    return result
