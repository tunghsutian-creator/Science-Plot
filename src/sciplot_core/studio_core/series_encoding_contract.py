"""Build and parse one versioned visual-encoding contract per XY series."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sciplot_core.studio_core.models import MARKER_MAP
from sciplot_core.studio_core.series_request import _marker_thin_factor
from sciplot_core.studio_render.models import (
    CATEGORICAL_SERIES_KINDS,
    IMPACT_POINT_LINE_MARKER_KIND,
    IMPACT_POINT_LINE_RAW_KIND,
    StudioSeries,
    _VeuszStyleContract,
)


SERIES_ENCODING_KIND = "sciplot_series_encoding"
SERIES_ENCODING_VERSION = 1
SERIES_ENCODING_CONTRACT_KIND = "sciplot_series_encoding_contract"
SERIES_ENCODING_CONTRACT_VERSION = 1

REQUEST_BOUND_ENCODING_FIELDS = frozenset(
    {
        "line.color",
        "line.style",
        "marker.shape",
        "marker.fill_color",
        "marker.line_color",
    }
)


def build_series_encoding_resolution(
    item: StudioSeries,
    *,
    template_id: str,
    categorical_visual_style: Mapping[str, Any],
    style: _VeuszStyleContract,
    raw_points_visible: bool,
) -> dict[str, Any]:
    """Freeze the final renderer-facing channels selected for one series."""

    marker = str(MARKER_MAP.get(item.marker, item.marker or "none"))
    plot_line_visible = item.presentation_kind not in (
        CATEGORICAL_SERIES_KINDS
        | {
            IMPACT_POINT_LINE_MARKER_KIND,
            IMPACT_POINT_LINE_RAW_KIND,
        }
    )
    marker_fill_visible = marker != "none" and raw_points_visible
    marker_line_visible = (
        marker != "none"
        and raw_points_visible
        and item.presentation_kind
        not in (CATEGORICAL_SERIES_KINDS | {IMPACT_POINT_LINE_RAW_KIND})
    )
    marker_alpha = _resolved_marker_alpha(
        item,
        categorical_visual_style=categorical_visual_style,
        style=style,
    )
    provenance = item.encoding_provenance
    request_bound_fields = list(provenance.request_bound_fields)
    unsupported = set(request_bound_fields) - REQUEST_BOUND_ENCODING_FIELDS
    if unsupported:
        raise ValueError(
            "Series encoding contains unsupported request-bound fields: "
            + ", ".join(sorted(unsupported))
        )
    return {
        "kind": SERIES_ENCODING_KIND,
        "version": SERIES_ENCODING_VERSION,
        "line": {
            "visible": plot_line_visible,
            "color": item.color,
            "style": item.line_style,
            "width_pt": (
                float(item.line_width)
                if item.line_width is not None
                else float(style.line_width_pt)
            ),
            "alpha": float(style.line_alpha),
        },
        "marker": {
            "shape": marker,
            "size_pt": (
                float(item.marker_size)
                if item.marker_size is not None
                else float(style.marker_size_pt)
            ),
            "thin_factor": _marker_thin_factor(item, template_id=template_id),
            "fill_visible": marker_fill_visible,
            "fill_color": item.marker_fill_color or item.color,
            "fill_alpha": marker_alpha,
            "line_visible": marker_line_visible,
            "line_color": item.marker_line_color or item.color,
            "line_width_pt": (
                float(item.marker_line_width)
                if item.marker_line_width is not None
                else float(style.marker_line_width_pt)
            ),
            "line_alpha": marker_alpha,
        },
        "sources": {
            "line.color": provenance.color_source,
            "line.style": provenance.line_style_source,
            "marker.shape": provenance.marker_source,
            "marker.fill_color": provenance.marker_fill_source,
            "marker.line_color": provenance.marker_line_source,
        },
        "request_bound_fields": request_bound_fields,
        "audit_policy": "request_bound_fields_must_match_exact_current_vsz",
    }


def series_encoding_from_spec(
    series_spec: Mapping[str, Any],
    *,
    style: Mapping[str, Any],
) -> dict[str, Any]:
    """Read a current encoding or project a legacy flat series spec."""

    encoding = series_spec.get("encoding")
    if isinstance(encoding, dict):
        return _validated_encoding_payload(encoding)
    return _legacy_encoding_payload(series_spec, style=style)


def series_encoding_contract_payload(
    series_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe the closed per-series contract carried by a Veusz spec."""

    return {
        "kind": SERIES_ENCODING_CONTRACT_KIND,
        "version": SERIES_ENCODING_CONTRACT_VERSION,
        "series_count": len(series_specs),
        "series_names": [str(item.get("name") or "") for item in series_specs],
        "audit_policy": "request_bound_fields_must_match_exact_current_vsz",
        "supported_request_bound_fields": sorted(REQUEST_BOUND_ENCODING_FIELDS),
    }


def validate_series_encoding_contract(spec: Mapping[str, Any]) -> None:
    """Validate a current top-level contract while accepting fully legacy specs."""

    raw_series = spec.get("series")
    if not isinstance(raw_series, list):
        raise ValueError("Veusz specification has no series list.")
    series_specs = [item for item in raw_series if isinstance(item, dict)]
    if len(series_specs) != len(raw_series):
        raise ValueError("Veusz specification contains an invalid series.")
    contract = spec.get("series_encoding_contract")
    encoded_count = sum(isinstance(item.get("encoding"), dict) for item in series_specs)
    if contract is None:
        if encoded_count:
            raise ValueError(
                "Veusz specification has series encodings without a top-level contract."
            )
        return
    if not isinstance(contract, dict) or encoded_count != len(series_specs):
        raise ValueError(
            "Veusz specification has an incomplete series encoding contract."
        )
    expected = series_encoding_contract_payload(series_specs)
    if contract != expected:
        raise ValueError(
            "Veusz specification series encoding contract is not canonical."
        )


def _validated_encoding_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("kind") != SERIES_ENCODING_KIND:
        raise ValueError("Series encoding kind is not supported.")
    if payload.get("version") != SERIES_ENCODING_VERSION:
        raise ValueError("Series encoding version is not supported.")
    line = payload.get("line")
    marker = payload.get("marker")
    sources = payload.get("sources")
    request_bound = payload.get("request_bound_fields")
    if not isinstance(line, dict) or not isinstance(marker, dict):
        raise ValueError("Series encoding has no closed line/marker channels.")
    if not isinstance(sources, dict) or not isinstance(request_bound, list):
        raise ValueError("Series encoding has no source and audit provenance.")
    if set(sources) != REQUEST_BOUND_ENCODING_FIELDS:
        raise ValueError("Series encoding source fields are not closed.")
    normalized_request_bound = [str(value) for value in request_bound]
    if len(set(normalized_request_bound)) != len(normalized_request_bound):
        raise ValueError("Series encoding request-bound fields must be unique.")
    unsupported = set(normalized_request_bound) - REQUEST_BOUND_ENCODING_FIELDS
    if unsupported:
        raise ValueError(
            "Series encoding contains unsupported request-bound fields: "
            + ", ".join(sorted(unsupported))
        )
    required_line = {"visible", "color", "style", "width_pt", "alpha"}
    required_marker = {
        "shape",
        "size_pt",
        "thin_factor",
        "fill_visible",
        "fill_color",
        "fill_alpha",
        "line_visible",
        "line_color",
        "line_width_pt",
        "line_alpha",
    }
    if set(line) != required_line or set(marker) != required_marker:
        raise ValueError("Series encoding line/marker fields are not closed.")
    return {
        "kind": SERIES_ENCODING_KIND,
        "version": SERIES_ENCODING_VERSION,
        "line": dict(line),
        "marker": dict(marker),
        "sources": {str(key): str(value) for key, value in sources.items()},
        "request_bound_fields": normalized_request_bound,
        "audit_policy": str(payload.get("audit_policy") or ""),
    }


def _legacy_encoding_payload(
    series_spec: Mapping[str, Any],
    *,
    style: Mapping[str, Any],
) -> dict[str, Any]:
    marker = str(series_spec.get("marker") or "none")
    raw_points_visible = series_spec.get("raw_points_visible") is not False
    return {
        "kind": SERIES_ENCODING_KIND,
        "version": SERIES_ENCODING_VERSION,
        "line": {
            "visible": series_spec.get("plot_line_hide") is not True,
            "color": str(series_spec.get("color") or ""),
            "style": str(series_spec.get("line_style") or "solid"),
            "width_pt": float(
                series_spec.get("line_width_pt") or style.get("line_width_pt") or 0.0
            ),
            "alpha": float(style.get("line_alpha") or 1.0),
        },
        "marker": {
            "shape": marker,
            "size_pt": float(
                series_spec.get("marker_size_pt") or style.get("marker_size_pt") or 0.0
            ),
            "thin_factor": int(series_spec.get("marker_thin_factor") or 1),
            "fill_visible": marker != "none" and raw_points_visible,
            "fill_color": str(
                series_spec.get("marker_fill_color") or series_spec.get("color") or ""
            ),
            "fill_alpha": float(
                series_spec.get("marker_alpha") or style.get("marker_alpha") or 1.0
            ),
            "line_visible": (
                marker != "none"
                and raw_points_visible
                and series_spec.get("marker_line_hide") is not True
            ),
            "line_color": str(
                series_spec.get("marker_line_color") or series_spec.get("color") or ""
            ),
            "line_width_pt": float(
                series_spec.get("marker_line_width_pt")
                or style.get("marker_line_width_pt")
                or 0.0
            ),
            "line_alpha": float(
                series_spec.get("marker_alpha") or style.get("marker_alpha") or 1.0
            ),
        },
        "sources": {
            field: "legacy_flat_spec" for field in REQUEST_BOUND_ENCODING_FIELDS
        },
        "request_bound_fields": [],
        "audit_policy": "legacy_flat_spec_has_no_request_binding",
    }


def _resolved_marker_alpha(
    item: StudioSeries,
    *,
    categorical_visual_style: Mapping[str, Any],
    style: _VeuszStyleContract,
) -> float:
    if item.marker_alpha is not None:
        return float(item.marker_alpha)
    if item.presentation_kind == "categorical_replicates":
        return float(
            categorical_visual_style.get("raw_point_alpha", style.marker_alpha)
        )
    return float(style.marker_alpha)


__all__ = [
    "REQUEST_BOUND_ENCODING_FIELDS",
    "SERIES_ENCODING_CONTRACT_KIND",
    "SERIES_ENCODING_CONTRACT_VERSION",
    "SERIES_ENCODING_KIND",
    "SERIES_ENCODING_VERSION",
    "build_series_encoding_resolution",
    "series_encoding_contract_payload",
    "series_encoding_from_spec",
    "validate_series_encoding_contract",
]
