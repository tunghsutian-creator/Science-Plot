"""Read supported tabular sources and normalize frame metadata for plotting."""

from __future__ import annotations

import math
from io import StringIO
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.file_hashing import (
    file_sha256,
)
from sciplot_core.foundation.text_files import decode_text

from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
    StudioSourceFrame,
)

from sciplot_core.studio_render.metric_columns import (
    _is_rheology_sweep_request,
    _is_unit_label,
)


def _read_source_frame_records(
    source: Path,
    *,
    request: dict[str, Any] | None = None,
) -> list[StudioSourceFrame]:
    files: list[Path]
    if source.is_dir():
        files = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        ]
        if _is_rheology_sweep_request(request):
            text_files = [
                path
                for path in files
                if path.suffix.lower() in {".csv", ".tsv", ".txt"}
            ]
            if text_files:
                files = text_files
    elif source.is_file():
        files = [source]
    else:
        raise FileNotFoundError(f"Studio source not found: {source}")
    frames: list[StudioSourceFrame] = []
    read_failures: list[tuple[Path, str]] = []
    for path in files:
        try:
            resolved = path.expanduser().resolve()
            before_sha256 = file_sha256(resolved)
            frame = _read_table(resolved)
            after_sha256 = file_sha256(resolved)
            if after_sha256 != before_sha256:
                raise StudioPreparationBlocked(
                    "source_changed_during_read",
                    f"Studio source changed while it was read: {resolved}",
                )
            frames.append(
                StudioSourceFrame(
                    label=_source_label_from_path(resolved),
                    path=resolved,
                    sha256=before_sha256,
                    frame=frame,
                )
            )
        except StudioPreparationBlocked:
            raise
        except Exception as exc:
            read_failures.append((path, type(exc).__name__))
    if read_failures:
        detail = ", ".join(
            f"{path.name} ({error_type})" for path, error_type in read_failures
        )
        raise StudioPreparationBlocked(
            "source_table_read_failed",
            "Studio refused to omit selected source tables that could not be "
            f"parsed: {detail}. Repair or remove those files explicitly.",
        )
    if not frames:
        raise ValueError(f"Studio could not read any numeric table from {source}.")
    return frames


def _source_label_from_path(path: Path) -> str:
    stem = path.stem
    if "__" in stem:
        left, right = stem.rsplit("__", maxsplit=1)
        if left == right:
            return right
    return stem


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    text = decode_text(path)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "Interval data:" in line:
            header = line.split("Interval data:", maxsplit=1)[1].lstrip("\t, ")
            table_text = "\n".join([header, *lines[index + 1 :]])
            return pd.read_csv(StringIO(table_text), sep="\t", engine="python")
    tab_count = text.count("\t")
    comma_count = text.count(",")
    if suffix == ".tsv" or tab_count > comma_count:
        separator: str | None = "\t"
    elif suffix == ".csv" or comma_count:
        separator = ","
    else:
        separator = None
    return pd.read_csv(StringIO(text), sep=separator, engine="python")


def _coerced_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    metadata_rows = _structured_metadata_prefix_rows(frame)
    numeric = frame.iloc[metadata_rows:].apply(
        pd.to_numeric,
        errors="coerce",
    )
    useful_columns = [
        column for column in numeric.columns if numeric[column].notna().sum() >= 2
    ]
    return numeric[useful_columns].dropna(how="all")


def _structured_metadata_prefix_rows(frame: pd.DataFrame) -> int:
    if frame.shape[0] < 3:
        return 0
    for row_index in range(min(2, frame.shape[0])):
        values = [
            str(value).strip().casefold()
            for value in frame.iloc[row_index].tolist()
            if not pd.isna(value) and str(value).strip()
        ]
        if not values:
            continue
        unit_values = [value for value in values if _is_unit_label(value)]
        nonnumeric_units = [
            value for value in unit_values if not _is_finite_numeric_text(value)
        ]
        if (
            len(unit_values) >= max(1, math.ceil(len(values) * 0.5))
            and nonnumeric_units
        ):
            return min(2, frame.shape[0])
    return 0


def _series_metadata_order(frame: pd.DataFrame) -> str | None:
    """Identify whether two structured metadata rows store unit/sample or sample/unit."""

    if frame.shape[0] < 2 or _structured_metadata_prefix_rows(frame) != 2:
        return None

    def unit_density(row_index: int) -> float:
        values = [
            str(value).strip().casefold()
            for value in frame.iloc[row_index].tolist()
            if not pd.isna(value) and str(value).strip()
        ]
        if not values:
            return 0.0
        return sum(_is_unit_label(value) for value in values) / len(values)

    first_density = unit_density(0)
    second_density = unit_density(1)
    if first_density >= 0.5 and second_density >= 0.5:
        raise StudioPreparationBlocked(
            "ambiguous_metadata_row_roles",
            "The first two metadata rows are both unit-like, so SciPlot "
            "cannot safely determine which row contains sample labels.",
        )
    if first_density >= 0.5 and first_density > second_density:
        return "unit_then_sample"
    if second_density >= 0.5 and second_density > first_density:
        return "sample_then_unit"
    return None


def _is_finite_numeric_text(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except ValueError:
        return False
