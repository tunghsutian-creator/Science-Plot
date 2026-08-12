"""Explicit PANalytical Data Collector scan-block evidence."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from sciplot_core.foundation.text_values import clean_text, token


_UNIT_DETECTION = "detected_from_instrument_export_schema"


@dataclass(frozen=True)
class PanalyticalScanMetadata:
    """Validated metadata bound to one exact scan-point block."""

    header_index: int
    declared_point_count: int
    sample: str
    sample_row_index: int | None
    scan_axis: str

    @property
    def x_unit_evidence(self) -> tuple[str, str, int, str]:
        return ("degree", _UNIT_DETECTION, self.header_index, "degree")

    @property
    def y_unit_evidence(self) -> tuple[str, str, int, str]:
        return ("counts", _UNIT_DETECTION, self.header_index, "counts")

    def sample_evidence(self, fallback: str) -> tuple[str, str, int | None]:
        if self.sample:
            return (
                self.sample,
                "detected_from_instrument_metadata",
                self.sample_row_index,
            )
        return (fallback, "fallback_from_source_table", None)

    def diagnostics(self) -> dict[str, object]:
        return {
            "source_instrument_format": "panalytical_data_collector_scan_points",
            "source_declared_point_count": self.declared_point_count,
            "source_scan_axis": self.scan_axis,
            "source_point_count_match": True,
        }


def _metadata_rows(
    raw: pd.DataFrame,
    *,
    header_index: int,
) -> tuple[dict[str, str], dict[str, int]]:
    values: dict[str, str] = {}
    row_indices: dict[str, int] = {}
    for row_index in range(header_index):
        key = token(raw.iat[row_index, 0])
        if not key:
            continue
        values[key] = next(
            (
                clean_text(raw.iat[row_index, column])
                for column in range(1, raw.shape[1])
                if clean_text(raw.iat[row_index, column])
            ),
            "",
        )
        row_indices[key] = row_index
    return values, row_indices


def _declared_point_count(value: str) -> int:
    try:
        numeric = float(clean_text(value))
    except ValueError as exc:
        raise ValueError(
            "PANalytical scan metadata needs a positive integer `No. of points`."
        ) from exc
    if numeric < 1 or not numeric.is_integer():
        raise ValueError(
            "PANalytical scan metadata needs a positive integer `No. of points`."
        )
    return int(numeric)


def resolve_panalytical_scan_metadata(
    raw: pd.DataFrame,
    *,
    header_index: int,
    x_index: int,
    y_index: int,
    data_start: int,
    finite_point_count: int,
) -> PanalyticalScanMetadata | None:
    """Recognize and close one PANalytical Gonio scan-point block."""

    if header_index <= 0 or (x_index, y_index) != (0, 2):
        return None
    headers = tuple(
        token(raw.iat[header_index, column])
        for column in range(min(4, raw.shape[1]))
    )
    if headers != ("angle", "timeperstep", "intensity", "esd"):
        return None
    if token(raw.iat[header_index - 1, 0]) != "scanpoints":
        return None

    metadata, row_indices = _metadata_rows(raw, header_index=header_index)
    if "measurementconditions" not in metadata:
        return None
    if token(metadata.get("scanaxis", "")) != "gonio":
        return None
    declared = _declared_point_count(metadata.get("noofpoints", ""))
    data_row_count = raw.shape[0] - data_start
    if data_row_count != declared or finite_point_count != declared:
        raise ValueError(
            "PANalytical scan-point count does not match its declared "
            f"`No. of points`: declared {declared}, found {data_row_count} "
            f"rows and {finite_point_count} finite pairs."
        )
    sample = metadata.get("sampleidentification", "").strip()
    return PanalyticalScanMetadata(
        header_index=header_index,
        declared_point_count=declared,
        sample=sample,
        sample_row_index=row_indices.get("sampleidentification") if sample else None,
        scan_axis=metadata["scanaxis"],
    )


__all__ = ["PanalyticalScanMetadata", "resolve_panalytical_scan_metadata"]
