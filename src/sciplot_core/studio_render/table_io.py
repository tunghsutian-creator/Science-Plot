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
from sciplot_core.source_tables.parsing import coerce_numeric_series

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
    legacy_numeric_parser: bool = False,
    source_artifact_origin: dict[str, str] | None = None,
) -> list[StudioSourceFrame]:
    groups = []
    if request is not None and (request.get("data_mapping_application") or {}).get("source_groups"):
        from sciplot_core.data_mapping.source_projection import verified_mapping_source_groups

        groups = verified_mapping_source_groups(request, replicates=True)
    if groups:
        assert request is not None
        original = Path(source_artifact_origin["path"]).resolve() if source_artifact_origin else source.resolve()
        if original != Path(request["data_mapping_application"]["effective_input"]).resolve():
            groups = [group for group in groups if Path(group["path"]).resolve() == original]
            if not groups:
                raise ValueError("A terminal source is outside the verified raw group correspondence.")
        group_frames = []
        for group in groups:
            path = source if source_artifact_origin else Path(group["path"])
            if source_artifact_origin and source_artifact_origin["sha256"] != group["sha256"]:
                raise ValueError("A captured source snapshot differs from its verified raw group.")
            frame = pd.read_csv(path, float_precision="round_trip")
            if file_sha256(path) != group["sha256"] or len(frame) != group["rows"]:
                raise ValueError("A verified mapped group changed while reading.")
            frame.attrs["sciplot_source_group"] = group
            group_frames.append(StudioSourceFrame(group["display_label"], path, group["sha256"], frame))
        return group_frames
    if request is not None and "categorical_binding" in request:
        from sciplot_core.studio_render.categorical_bindings import read_categorical_frame
        from sciplot_core.mapping_contract.categorical import validate_categorical_context

        validate_categorical_context(request)
        return [read_categorical_frame(source, request["categorical_binding"],
                                       legacy_numeric_parser=legacy_numeric_parser,
                                       source_artifact_origin=source_artifact_origin)]
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
            frame = (
                _read_table(resolved, legacy_numeric_parser=True)
                if legacy_numeric_parser else _read_table(resolved)
            )
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


def _read_table(path: Path, *, legacy_numeric_parser: bool = False) -> pd.DataFrame:
    """Read current cells, or exactly replay an unversioned historical parser.

    The compatibility mode is local to this frame and only used by the exact
    source audit of an existing unversioned specification. It never changes a
    source, saved document or current creation's parsing policy.
    """
    frame = _read_table_cells(path, dtype=None if legacy_numeric_parser else object)
    if legacy_numeric_parser:
        frame.attrs["sciplot_legacy_numeric_parser"] = True
    return frame


def _read_table_cells(path: Path, *, dtype: Any) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=dtype)
    text = decode_text(path)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "Interval data:" in line:
            header = line.split("Interval data:", maxsplit=1)[1].lstrip("\t, ")
            table_text = "\n".join([header, *lines[index + 1 :]])
            return pd.read_csv(StringIO(table_text), sep="\t", engine="python", dtype=dtype)
    tab_count = text.count("\t")
    comma_count = text.count(",")
    if suffix == ".tsv" or tab_count > comma_count:
        separator: str | None = "\t"
    elif suffix == ".csv" or comma_count:
        separator = ","
    else:
        separator = None
    return pd.read_csv(StringIO(text), sep=separator, engine="python", dtype=dtype)


def _coerced_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    metadata_rows = _structured_metadata_prefix_rows(frame)
    if frame.attrs.get("sciplot_legacy_numeric_parser") is True:
        numeric = frame.iloc[metadata_rows:].apply(pd.to_numeric, errors="coerce")
    else:
        numeric = frame.iloc[metadata_rows:].apply(coerce_numeric_series)
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
