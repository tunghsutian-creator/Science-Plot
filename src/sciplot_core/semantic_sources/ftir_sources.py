"""Read FTIR spectra without inferring response identity from magnitudes."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text as _clean_text
from sciplot_core.foundation.text_values import token as _token
from sciplot_core.semantic_sources.ftir_transform_contract import (
    FTIR_X_LABEL,
    FTIR_X_UNIT,
    FTIR_Y_LABELS,
    build_ftir_transform_contract,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic_sources.series_labels import _source_display_sample
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
)
from sciplot_core.semantic_sources.table_scanning import (
    _float,
    _scan_curve_series_table,
)
from sciplot_core.source_tables import read_raw_table


_SUFFIXES = frozenset({".csv", ".tsv", ".txt"})
_X_ALIASES = ("wavenumber", "cm-1", "cm^-1")
_Y_ALIASES = (
    "transmittance",
    "%t",
    "absorbance",
    "spectral response",
    "ftir response",
    "infrared intensity",
)


def resolve_ftir_scientific_transform(
    source: Path,
    *,
    series_order: object = None,
) -> ResolvedScientificTransform:
    """Resolve source-bound FTIR traces while preserving every finite pair."""

    paths = _ftir_source_files(source.expanduser().resolve())
    if not paths:
        raise ValueError(f"No supported FTIR source files found under {source}.")
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for path in paths:
        try:
            series_list.extend(_read_ftir_series(path))
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
    if errors:
        raise ValueError(
            "FTIR transform rejected one or more in-scope source files; "
            f"silent partial datasets are not allowed ({'; '.join(errors[:3])})."
        )
    _validate_series_set(series_list)
    explicit_order = bool(_series_order_map(series_order))
    if explicit_order:
        series_list = _order_curve_series(series_list, series_order)
    selected_sources = tuple(
        dict.fromkeys(
            Path(str((series.diagnostics or {})["source_file"])).resolve()
            for series in series_list
        )
    )
    return ResolvedScientificTransform(
        series=tuple(series_list),
        contract=build_ftir_transform_contract(
            series_list,
            selected_sources=selected_sources,
            explicit_series_order_applied=explicit_order,
        ),
        selected_sources=selected_sources,
    )


def _ftir_source_files(source: Path) -> list[Path]:
    if source.is_file() and source.suffix.lower() in _SUFFIXES:
        return [source.resolve()]
    if not source.is_dir():
        return []
    return sorted(
        (
            path.resolve()
            for path in source.iterdir()
            if path.is_file() and path.suffix.lower() in _SUFFIXES
        ),
        key=lambda path: path.name.casefold(),
    )


def _read_ftir_series(source: Path) -> list[CurveSeriesPayload]:
    """Read one structured or headerless source through one shared boundary."""

    source = source.expanduser().resolve()
    raw = read_raw_table(source, preserve_na_tokens=True)
    structured = _scan_curve_series_table(
        raw,
        x_aliases=_X_ALIASES,
        y_aliases=_Y_ALIASES,
        x_label=FTIR_X_LABEL,
        y_label=FTIR_Y_LABELS["unknown"],
        default_x_unit="",
        default_y_unit="",
        sample_prefix=_source_display_sample(source),
    )
    if structured:
        return [
            _project_structured_series(series, source=source, raw=raw)
            for series in structured
        ]
    return [_read_headerless_series(source, raw=raw)]


def _project_structured_series(
    series: CurveSeriesPayload,
    *,
    source: Path,
    raw: pd.DataFrame,
) -> CurveSeriesPayload:
    diagnostics = dict(series.diagnostics or {})
    data_start = _structured_data_start(diagnostics)
    _reject_metadata_partial(raw, diagnostics=diagnostics, data_start=data_start)
    mode = _response_mode(str(diagnostics.get("source_y_header") or ""))
    source_x_unit = _explicit_x_unit(diagnostics)
    if source_x_unit and _token(source_x_unit) != _token(FTIR_X_UNIT):
        raise ValueError(
            f"Unsupported FTIR wavenumber unit {source_x_unit!r} in {source}."
        )
    source_y_unit = _explicit_y_unit(diagnostics)
    _validate_row_evidence(series, diagnostics)
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=FTIR_X_LABEL,
        x_unit=FTIR_X_UNIT,
        y_label=FTIR_Y_LABELS[mode],
        y_unit=source_y_unit,
        points=series.points,
        diagnostics={
            **diagnostics,
            "source_file": str(source),
            "source_table": source.stem,
            "source_x_unit": source_x_unit,
            "source_y_unit": source_y_unit,
            "source_x_unit_detection_value": source_x_unit,
            "source_y_unit_detection_value": source_y_unit,
            "source_x_unit_authority": "selected_rule_axis_contract",
            "source_data_start_row_index": data_start,
            "ftir_response_mode": mode,
            "ftir_response_mode_detection": (
                "detected_from_explicit_response_header"
                if mode != "unknown"
                else "not_declared_in_response_header"
            ),
        },
    )


def _read_headerless_series(
    source: Path,
    *,
    raw: pd.DataFrame,
) -> CurveSeriesPayload:
    if raw.empty or raw.shape[1] < 2:
        raise ValueError("No adjacent numeric column pair was found.")
    candidates = [
        (column, _row_evidence(raw, x_column=column, y_column=column + 1))
        for column in range(raw.shape[1] - 1)
    ]
    candidates = [item for item in candidates if item[1][0]]
    if not candidates:
        raise ValueError("No adjacent numeric column pair was found.")
    maximum = max(len(item[1][0]) for item in candidates)
    selected = [item for item in candidates if len(item[1][0]) == maximum]
    if len(selected) != 1:
        columns = ", ".join(f"{index}/{index + 1}" for index, _ in selected)
        raise ValueError(f"Ambiguous adjacent numeric pairs at columns {columns}.")
    x_column, evidence = selected[0]
    points, candidate, empty, partial, nonfinite = evidence
    if partial:
        raise ValueError("Selected columns contain partial or nonnumeric rows.")
    if nonfinite:
        raise ValueError("Selected columns contain nonfinite rows.")
    diagnostics = {
        "source_file": str(source),
        "source_table": source.stem,
        "source_sample_detection": "derived_from_source_filename",
        "source_sample_row_index": None,
        "source_sample_value": _source_display_sample(source),
        "source_header_row_index": None,
        "source_data_start_row_index": 0,
        "source_x_column_index": x_column,
        "source_y_column_index": x_column + 1,
        "source_x_header": "",
        "source_y_header": "",
        "source_x_unit": "",
        "source_y_unit": "",
        "source_x_unit_detection": "not_declared_in_headerless_source",
        "source_y_unit_detection": "not_declared_in_headerless_source",
        "source_x_unit_detection_row_index": None,
        "source_y_unit_detection_row_index": None,
        "source_x_unit_detection_value": "",
        "source_y_unit_detection_value": "",
        "source_x_unit_authority": "selected_rule_axis_contract",
        "ftir_response_mode": "unknown",
        "ftir_response_mode_detection": "not_declared_in_headerless_source",
        "candidate_row_count": candidate,
        "retained_point_count": len(points),
        "excluded_empty_pair_count": empty,
        "excluded_partial_or_nonnumeric_pair_count": partial,
        "excluded_nonfinite_pair_count": nonfinite,
    }
    return CurveSeriesPayload(
        sample=_source_display_sample(source),
        x_label=FTIR_X_LABEL,
        x_unit=FTIR_X_UNIT,
        y_label=FTIR_Y_LABELS["unknown"],
        y_unit="",
        points=points,
        diagnostics=diagnostics,
    )


def _row_evidence(
    raw: pd.DataFrame,
    *,
    x_column: int,
    y_column: int,
) -> tuple[tuple[tuple[float, float], ...], int, int, int, int]:
    points: list[tuple[float, float]] = []
    empty = partial = nonfinite = 0
    for row in range(raw.shape[0]):
        x_cell, y_cell = raw.iat[row, x_column], raw.iat[row, y_column]
        if not _clean_text(x_cell) and not _clean_text(y_cell):
            empty += 1
            continue
        x_value, y_value = _float(x_cell), _float(y_cell)
        if x_value is None or y_value is None:
            partial += 1
        elif not (math.isfinite(x_value) and math.isfinite(y_value)):
            nonfinite += 1
        else:
            points.append((x_value, y_value))
    return tuple(points), raw.shape[0], empty, partial, nonfinite


def _explicit_x_unit(diagnostics: dict[str, Any]) -> str:
    value = str(diagnostics.get("source_x_unit_detection_value") or "")
    header = str(diagnostics.get("source_x_header") or "")
    if not value and _token(header) == _token(FTIR_X_UNIT):
        diagnostics["source_x_unit_detection"] = "detected_from_header"
        diagnostics["source_x_unit_detection_row_index"] = diagnostics.get(
            "source_header_row_index"
        )
        return FTIR_X_UNIT
    return value


def _explicit_y_unit(diagnostics: dict[str, Any]) -> str:
    value = str(diagnostics.get("source_y_unit_detection_value") or "")
    header = str(diagnostics.get("source_y_header") or "")
    if not value and header.replace(" ", "").casefold() == "%t":
        diagnostics["source_y_unit_detection"] = "detected_from_header"
        diagnostics["source_y_unit_detection_row_index"] = diagnostics.get(
            "source_header_row_index"
        )
        return "%"
    return value


def _response_mode(header: str) -> str:
    text = _clean_text(header).casefold()
    absorbance = "absorbance" in text or _token(header) == "abs"
    transmittance = "transmittance" in text or "%t" in text.replace(" ", "")
    if absorbance and transmittance:
        raise ValueError(f"Conflicting FTIR response header {header!r}.")
    return (
        "absorbance" if absorbance else "transmittance" if transmittance else "unknown"
    )


def _structured_data_start(diagnostics: dict[str, Any]) -> int:
    header_row = int(diagnostics["source_header_row_index"])
    metadata_rows = [header_row]
    for axis in ("x", "y"):
        if diagnostics.get(f"source_{axis}_unit_detection") == (
            "detected_from_adjacent_unit_row"
        ):
            metadata_rows.append(
                int(diagnostics[f"source_{axis}_unit_detection_row_index"])
            )
    sample_row = diagnostics.get("source_sample_row_index")
    if sample_row is not None:
        metadata_rows.append(int(sample_row))
    return max(metadata_rows) + 1


def _reject_metadata_partial(
    raw: pd.DataFrame,
    *,
    diagnostics: dict[str, Any],
    data_start: int,
) -> None:
    header_row = int(diagnostics["source_header_row_index"])
    x_column = int(diagnostics["source_x_column_index"])
    y_column = int(diagnostics["source_y_column_index"])
    for row in range(header_row + 1, data_start):
        x_value = _float(raw.iat[row, x_column])
        y_value = _float(raw.iat[row, y_column])
        if (x_value is None) != (y_value is None):
            raise ValueError("A pre-data metadata row contains a partial numeric pair.")


def _validate_row_evidence(
    series: CurveSeriesPayload,
    diagnostics: dict[str, Any],
) -> None:
    candidate = int(diagnostics.get("candidate_row_count") or 0)
    retained = int(diagnostics.get("retained_point_count") or 0)
    empty = int(diagnostics.get("excluded_empty_pair_count") or 0)
    partial = int(diagnostics.get("excluded_partial_or_nonnumeric_pair_count") or 0)
    nonfinite = int(diagnostics.get("excluded_nonfinite_pair_count") or 0)
    if partial:
        raise ValueError(f"FTIR series {series.sample!r} contains partial rows.")
    if nonfinite:
        raise ValueError(f"FTIR series {series.sample!r} contains nonfinite rows.")
    if retained != len(series.points) or candidate != retained + empty:
        raise ValueError(f"FTIR row evidence is incomplete for {series.sample!r}.")


def _validate_series_set(series_list: list[CurveSeriesPayload]) -> None:
    samples = [series.sample for series in series_list]
    if (
        not samples
        or any(not sample for sample in samples)
        or len(samples) != len(set(samples))
    ):
        raise ValueError("FTIR series need non-empty unique source sample labels.")
    modes = {
        str((series.diagnostics or {}).get("ftir_response_mode") or "unknown")
        for series in series_list
    }
    if len(modes) != 1:
        raise ValueError(
            "FTIR response modes cannot share one figure when identities are mixed "
            f"or incomplete: {sorted(modes)}."
        )
    y_units = {series.y_unit for series in series_list}
    if len(y_units) != 1:
        raise ValueError(
            "FTIR response units cannot share one figure when declarations differ: "
            f"{sorted(y_units)}."
        )


def _read_ftir_series_list(source: Path) -> list[CurveSeriesPayload]:
    """Compatibility reader backed by the typed transform."""

    return list(resolve_ftir_scientific_transform(source).series)


__all__ = [
    "_read_ftir_series",
    "_read_ftir_series_list",
    "resolve_ftir_scientific_transform",
]
