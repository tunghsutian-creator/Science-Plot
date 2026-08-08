"""Validate adjacent provenance for publication-digitized DSC curves."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_number,
    require_json_object,
)


DSC_PUBLICATION_DIGITIZED_SOURCE_STATUS = (
    "digitized_from_authorized_publication_figure_not_instrument_raw"
)
_EXPECTED_DOI = "10.1038/s41893-025-01688-5"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL_KEYS = {
    "kind",
    "version",
    "source_pdf_authorized_root_relative",
    "source_pdf_sha256",
    "article_title",
    "doi",
    "source_figures",
    "output_csv",
    "output_csv_sha256",
    "traces",
    "acceptance_gate",
}
_TRACE_KEYS = {
    "sample",
    "source_pdf_page",
    "source_image_xref",
    "source_image_size_px",
    "axis_bounds_px",
    "axis_values",
    "trace_temperature_span_C",
    "trace_point_count",
    "published_peak_temperature_C",
    "digitized_peak_temperature_C",
    "peak_temperature_absolute_error_C",
    "pixel_resolution",
    "digitization_method",
    "source_data_status",
}


@dataclass(frozen=True, slots=True)
class DscDigitizedTraceFacts:
    """CSV-derived facts required to verify one provenance trace."""

    sample: str
    point_count: int
    temperature_min: float
    temperature_max: float
    heat_flow_min: float
    heat_flow_max: float
    heat_flow_peak_temperature: float


def read_dsc_provenance(source: Path) -> dict[str, Any]:
    """Read one adjacent provenance object with stable failure semantics."""

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        return require_json_object(payload, label="DSC digitization provenance")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "dsc_single_curve_provenance_mismatch",
            f"The DSC digitization provenance is invalid: {exc}",
        ) from exc


def validate_dsc_provenance(
    payload: dict[str, Any],
    *,
    csv_name: str | None,
    csv_sha256: str,
    traces: tuple[DscDigitizedTraceFacts, ...],
) -> None:
    """Require the closed provenance object to bind the selected CSV facts."""

    try:
        reject_unknown_keys(payload, _TOP_LEVEL_KEYS, label="DSC provenance")
        if payload.get("kind") != "sciplot_digitized_fixture_provenance":
            raise ValueError("provenance kind is not supported")
        if require_json_int(payload.get("version"), label="provenance.version") != 1:
            raise ValueError("provenance version is not supported")
        source_pdf = _required_text(
            payload.get("source_pdf_authorized_root_relative"),
            label="provenance.source_pdf_authorized_root_relative",
        )
        source_pdf_path = Path(source_pdf)
        if source_pdf_path.is_absolute() or ".." in source_pdf_path.parts:
            raise ValueError("authorized PDF path must be root-relative")
        _require_sha256(payload.get("source_pdf_sha256"), label="source PDF hash")
        _required_text(payload.get("article_title"), label="provenance.article_title")
        if payload.get("doi") != _EXPECTED_DOI:
            raise ValueError("provenance DOI does not identify the registered source")
        source_figures = require_json_list(
            payload.get("source_figures"), label="provenance.source_figures"
        )
        if len(source_figures) != len(traces):
            raise ValueError("provenance source-figure count does not match traces")
        for index, value in enumerate(source_figures):
            _required_text(value, label=f"provenance.source_figures[{index}]")
        output_csv = _required_text(
            payload.get("output_csv"), label="provenance.output_csv"
        )
        if Path(output_csv).name != output_csv or not output_csv.casefold().endswith(
            ".csv"
        ):
            raise ValueError("provenance output filename is not a safe CSV name")
        if csv_name is not None and output_csv != csv_name:
            raise ValueError("provenance output filename does not match the CSV")
        if payload.get("output_csv_sha256") != csv_sha256:
            raise ValueError("provenance output hash does not match the CSV")

        trace_payloads = require_json_list(
            payload.get("traces"), label="provenance.traces"
        )
        if len(trace_payloads) != len(traces):
            raise ValueError("provenance trace count does not match the CSV")
        peak_errors = tuple(
            _validate_trace(value, expected=expected, index=index)
            for index, (value, expected) in enumerate(
                zip(trace_payloads, traces, strict=True)
            )
        )
        acceptance = require_json_object(
            payload.get("acceptance_gate"), label="provenance.acceptance_gate"
        )
        reject_unknown_keys(
            acceptance,
            {"maximum_peak_temperature_absolute_error_C", "passed"},
            label="provenance.acceptance_gate",
        )
        maximum_error = require_json_number(
            acceptance.get("maximum_peak_temperature_absolute_error_C"),
            label="provenance.acceptance_gate.maximum_error",
        )
        if maximum_error <= 0:
            raise ValueError("provenance maximum peak error must be positive")
        if not require_json_bool(
            acceptance.get("passed"), label="provenance.acceptance_gate.passed"
        ):
            raise ValueError("provenance acceptance gate did not pass")
        if any(error > maximum_error for error in peak_errors):
            raise ValueError("a digitized peak exceeds the accepted error")
    except (KeyError, TypeError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "dsc_single_curve_provenance_mismatch",
            f"The DSC digitization provenance does not bind the selected CSV: {exc}",
        ) from exc


def _validate_trace(
    value: Any,
    *,
    expected: DscDigitizedTraceFacts,
    index: int,
) -> float:
    label = f"provenance.traces[{index}]"
    trace = require_json_object(value, label=label)
    reject_unknown_keys(trace, _TRACE_KEYS, label=label)
    if trace.get("sample") != expected.sample:
        raise ValueError(f"{label}.sample does not match the CSV order")
    if require_json_int(trace.get("trace_point_count"), label=f"{label}.count") != (
        expected.point_count
    ):
        raise ValueError(f"{label}.count does not match the CSV")
    if trace.get("source_data_status") != DSC_PUBLICATION_DIGITIZED_SOURCE_STATUS:
        raise ValueError(f"{label}.source_data_status is not publication-digitized")
    _require_positive_int(trace.get("source_pdf_page"), label=f"{label}.page")
    _require_positive_int(trace.get("source_image_xref"), label=f"{label}.xref")
    _require_positive_int_pair(trace.get("source_image_size_px"), label=f"{label}.size")
    _validate_numeric_bounds(
        trace.get("axis_bounds_px"),
        keys=("left", "right", "top", "bottom"),
        label=f"{label}.axis_bounds_px",
    )
    axis_values = _validate_numeric_bounds(
        trace.get("axis_values"),
        keys=("x_min_C", "x_max_C", "y_min_W_g", "y_max_W_g"),
        label=f"{label}.axis_values",
    )
    if not (
        axis_values[0]
        <= expected.temperature_min
        <= expected.temperature_max
        <= axis_values[1]
        and axis_values[2]
        <= expected.heat_flow_min
        <= expected.heat_flow_max
        <= axis_values[3]
    ):
        raise ValueError(f"{label}.axis_values do not contain the digitized trace")
    span = _require_number_pair(
        trace.get("trace_temperature_span_C"),
        label=f"{label}.trace_temperature_span_C",
    )
    if not (
        math.isclose(span[0], expected.temperature_min, abs_tol=1e-6)
        and math.isclose(span[1], expected.temperature_max, abs_tol=1e-6)
    ):
        raise ValueError(f"{label}.temperature span does not match the CSV")
    published_peak = require_json_number(
        trace.get("published_peak_temperature_C"), label=f"{label}.published_peak"
    )
    digitized_peak = require_json_number(
        trace.get("digitized_peak_temperature_C"), label=f"{label}.digitized_peak"
    )
    if not math.isclose(
        digitized_peak,
        expected.heat_flow_peak_temperature,
        abs_tol=1e-6,
    ):
        raise ValueError(f"{label}.digitized peak does not match the CSV")
    peak_error = require_json_number(
        trace.get("peak_temperature_absolute_error_C"), label=f"{label}.peak_error"
    )
    if peak_error < 0 or not math.isclose(
        peak_error, abs(digitized_peak - published_peak), abs_tol=1e-9
    ):
        raise ValueError(f"{label}.peak error is inconsistent")
    pixel_resolution = require_json_object(
        trace.get("pixel_resolution"), label=f"{label}.pixel_resolution"
    )
    reject_unknown_keys(
        pixel_resolution,
        {"temperature_C_per_px", "heat_flow_W_g_per_px"},
        label=f"{label}.pixel_resolution",
    )
    if any(
        require_json_number(pixel_resolution.get(key), label=f"{label}.{key}") <= 0
        for key in ("temperature_C_per_px", "heat_flow_W_g_per_px")
    ):
        raise ValueError(f"{label}.pixel resolution must be positive")
    _required_text(trace.get("digitization_method"), label=f"{label}.method")
    return peak_error


def _validate_numeric_bounds(
    value: Any,
    *,
    keys: tuple[str, str, str, str],
    label: str,
) -> tuple[float, float, float, float]:
    payload = require_json_object(value, label=label)
    reject_unknown_keys(payload, set(keys), label=label)
    values = (
        require_json_number(payload.get(keys[0]), label=f"{label}.{keys[0]}"),
        require_json_number(payload.get(keys[1]), label=f"{label}.{keys[1]}"),
        require_json_number(payload.get(keys[2]), label=f"{label}.{keys[2]}"),
        require_json_number(payload.get(keys[3]), label=f"{label}.{keys[3]}"),
    )
    if values[0] >= values[1] or values[2] >= values[3]:
        raise ValueError(f"{label} does not define increasing bounds")
    return values


def _require_positive_int_pair(value: Any, *, label: str) -> tuple[int, int]:
    values = require_json_list(value, label=label)
    if len(values) != 2:
        raise ValueError(f"{label} must contain two values")
    return (
        _require_positive_int(values[0], label=f"{label}[0]"),
        _require_positive_int(values[1], label=f"{label}[1]"),
    )


def _require_number_pair(value: Any, *, label: str) -> tuple[float, float]:
    values = require_json_list(value, label=label)
    if len(values) != 2:
        raise ValueError(f"{label} must contain two values")
    return (
        require_json_number(values[0], label=f"{label}[0]"),
        require_json_number(values[1], label=f"{label}[1]"),
    )


def _require_positive_int(value: Any, *, label: str) -> int:
    number = require_json_int(value, label=label)
    if number < 1:
        raise ValueError(f"{label} must be positive")
    return number


def _require_sha256(value: Any, *, label: str) -> str:
    text = _required_text(value, label=label)
    if _SHA256_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _required_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


__all__ = [
    "DSC_PUBLICATION_DIGITIZED_SOURCE_STATUS",
    "DscDigitizedTraceFacts",
    "read_dsc_provenance",
    "validate_dsc_provenance",
]
