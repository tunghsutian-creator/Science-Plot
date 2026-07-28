"""Evaluate series accessibility from exact-current visual evidence."""

from __future__ import annotations

from itertools import combinations
from typing import Any

from sciplot_core.qa.color_math import (
    _CVD_MATRICES,
    _simulate_cvd,
    _delta_e,
    _relative_luminance,
    _rgb_matches,
    _sample_color_scale,
    _turn_count,
)


def _series_accessibility_report(
    audit: dict[str, Any] | None,
    pdfs: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    documents = audit.get("documents", []) if isinstance(audit, dict) else []
    series = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("series", [])
        if isinstance(item, dict)
        and (item.get("plot_line_visible") or item.get("marker_visible"))
    ]
    color_scales = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("color_scales", [])
        if isinstance(item, dict)
    ]
    if not documents:
        return {
            "available": False,
            "coverage_complete": False,
            "passed": False,
            "reason": "exact_current_vsz_audit_unavailable",
            "series": [],
            "pairs": [],
        }
    active_color_entries = [
        {
            "path": item.get("path"),
            "role": entry.get("role"),
            "color": entry.get("color"),
        }
        for item in series
        for entry in item.get("rendered_colors", [])
        if isinstance(entry, dict)
    ]
    unresolved = [
        {"path": item.get("path"), "role": item.get("role")}
        for item in active_color_entries
        if not isinstance(item.get("color"), dict)
    ]
    unresolved.extend(
        {"path": item.get("path"), "role": "primary_series_color"}
        for item in series
        if not isinstance(item.get("color"), dict)
        and not any(entry.get("path") == item.get("path") for entry in unresolved)
    )
    pdf_colors = [
        color
        for pdf in pdfs
        for color in pdf.get("vector_colors", {}).get("unique_rgb", [])
        if isinstance(color, list) and len(color) == 3
    ]
    unrendered = [
        {"path": item.get("path"), "role": item.get("role"), "color": item.get("color")}
        for item in active_color_entries
        if isinstance(item.get("color"), dict)
        and not any(
            _rgb_matches(item["color"]["rgb"], candidate) for candidate in pdf_colors
        )
    ]
    accessibility = (
        profile.get("accessibility")
        if isinstance(profile.get("accessibility"), dict)
        else {}
    )
    minimum_delta_e = float(accessibility.get("minimum_simulated_delta_e") or 10.0)
    minimum_luminance_delta = float(
        accessibility.get("minimum_grayscale_luminance_delta") or 0.08
    )
    minimum_colormap_step = float(
        accessibility.get("minimum_colormap_step_delta_e") or 2.0
    )
    minimum_colormap_range = float(
        accessibility.get("minimum_colormap_luminance_range") or 0.3
    )
    maximum_colormap_turns = int(
        accessibility.get("maximum_colormap_luminance_turns") or 1
    )
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for item in series:
        key = (
            str(item.get("document")),
            str(item.get("graph_path")),
            int(item.get("page") or 0),
        )
        groups.setdefault(key, []).append(item)
    categorical_graph_keys = {
        (
            str(document.get("path")),
            str(graph.get("graph_path")),
            int(graph.get("page") or 0),
        )
        for document in documents
        if isinstance(document, dict)
        for graph in document.get("categorical_graphs", [])
        if isinstance(graph, dict) and graph.get("spatial_identity_explicit") is True
    }
    pair_reports: list[dict[str, Any]] = []
    for group_key, group in groups.items():
        for left, right in combinations(group, 2):
            left_signature = (
                left.get("line_style") if left.get("plot_line_visible") else None,
                left.get("marker") if left.get("marker_visible") else None,
            )
            right_signature = (
                right.get("line_style") if right.get("plot_line_visible") else None,
                right.get("marker") if right.get("marker_visible") else None,
            )
            categorical_position_distinct = group_key in categorical_graph_keys
            non_color_distinct = bool(
                (left.get("direct_labelled") and right.get("direct_labelled"))
                or left_signature != right_signature
                or categorical_position_distinct
            )
            left_rgb = (
                left.get("color", {}).get("rgb")
                if isinstance(left.get("color"), dict)
                else None
            )
            right_rgb = (
                right.get("color", {}).get("rgb")
                if isinstance(right.get("color"), dict)
                else None
            )
            simulations = {}
            if isinstance(left_rgb, list) and isinstance(right_rgb, list):
                for name, matrix in _CVD_MATRICES.items():
                    simulations[name] = round(
                        _delta_e(
                            _simulate_cvd(left_rgb, matrix),
                            _simulate_cvd(right_rgb, matrix),
                        ),
                        3,
                    )
                luminance_delta = round(
                    abs(_relative_luminance(left_rgb) - _relative_luminance(right_rgb)),
                    6,
                )
            else:
                luminance_delta = None
            pair_reports.append(
                {
                    "group": list(group_key),
                    "left": {
                        "path": left.get("path"),
                        "label": left.get("label"),
                        "signature": left_signature,
                    },
                    "right": {
                        "path": right.get("path"),
                        "label": right.get("label"),
                        "signature": right_signature,
                    },
                    "categorical_position_distinct": categorical_position_distinct,
                    "distinction_basis": (
                        "categorical_axis_position_and_label"
                        if categorical_position_distinct
                        else "direct_labels"
                        if left.get("direct_labelled") and right.get("direct_labelled")
                        else "line_or_marker_signature"
                        if left_signature != right_signature
                        else "none"
                    ),
                    "non_color_distinct": non_color_distinct,
                    "cvd_delta_e": simulations,
                    "grayscale_luminance_delta": luminance_delta,
                    "cvd_accessible": bool(simulations)
                    and (
                        min(simulations.values()) >= minimum_delta_e
                        or non_color_distinct
                    ),
                    "grayscale_accessible": luminance_delta is not None
                    and (
                        luminance_delta >= minimum_luminance_delta or non_color_distinct
                    ),
                }
            )
    non_color_required = accessibility.get("non_color_distinction_required") is True
    non_color_passed = not non_color_required or all(
        item["non_color_distinct"] for item in pair_reports
    )
    cvd_passed = all(item["cvd_accessible"] for item in pair_reports)
    grayscale_passed = all(item["grayscale_accessible"] for item in pair_reports)
    embedded_raster_present = any(pdf.get("embedded_rasters") for pdf in pdfs)
    color_scale_reports: list[dict[str, Any]] = []
    forbidden_names = {
        "spectrum",
        "spectrum2",
        "spectrum2-step",
        "rainbow",
        "jet",
        "hsv",
    }
    for scale in color_scales:
        samples = _sample_color_scale(scale.get("control_colors", []))
        binding_samples = _sample_color_scale(
            scale.get("control_colors", []), count=256
        )
        matched_pdf_colors = [
            color
            for color in pdf_colors
            if binding_samples
            and min(_delta_e(color, sample) for sample in binding_samples) <= 2.5
        ]
        rendered_output_confirmed = (
            embedded_raster_present or len(matched_pdf_colors) >= 3
        )
        rendered_output_method = (
            "embedded_pdf_raster"
            if embedded_raster_present
            else "pdf_vector_palette_matches"
            if rendered_output_confirmed
            else "unconfirmed"
        )
        luminances = [_relative_luminance(rgb) for rgb in samples]
        cvd_steps = {
            name: [
                _delta_e(_simulate_cvd(left, matrix), _simulate_cvd(right, matrix))
                for left, right in zip(samples, samples[1:], strict=False)
            ]
            for name, matrix in _CVD_MATRICES.items()
        }
        minimum_steps = {
            name: round(min(values), 3) if values else None
            for name, values in cvd_steps.items()
        }
        luminance_range = max(luminances) - min(luminances) if luminances else 0.0
        turns = _turn_count(luminances)
        cvd_scale_passed = bool(samples) and all(
            value is not None and float(value) >= minimum_colormap_step
            for value in minimum_steps.values()
        )
        grayscale_scale_passed = (
            bool(samples)
            and luminance_range >= minimum_colormap_range
            and turns <= maximum_colormap_turns
        )
        rainbow_passed = not (
            accessibility.get("avoid_rainbow_palette") is True
            and str(scale.get("name") or "").strip().casefold() in forbidden_names
        )
        color_scale_reports.append(
            {
                "path": scale.get("path"),
                "name": scale.get("name"),
                "sample_count": len(samples),
                "minimum_adjacent_cvd_delta_e": minimum_steps,
                "luminance_range": round(luminance_range, 6),
                "luminance_turns": turns,
                "cvd_accessible": cvd_scale_passed,
                "grayscale_accessible": grayscale_scale_passed,
                "rainbow_avoidance_passed": rainbow_passed,
                "rendered_raster_confirmed": embedded_raster_present,
                "rendered_output_confirmed": rendered_output_confirmed,
                "rendered_output_method": rendered_output_method,
                "matched_pdf_colors": matched_pdf_colors,
                "passed": (
                    cvd_scale_passed
                    and grayscale_scale_passed
                    and rainbow_passed
                    and rendered_output_confirmed
                ),
            }
        )
    colormap_passed = all(item["passed"] for item in color_scale_reports)
    cvd_passed = cvd_passed and all(
        item["cvd_accessible"] for item in color_scale_reports
    )
    grayscale_passed = grayscale_passed and all(
        item["grayscale_accessible"] for item in color_scale_reports
    )
    scale_coverage = all(
        item["sample_count"] > 0 and item["rendered_output_confirmed"]
        for item in color_scale_reports
    )
    coverage_complete = not unresolved and not unrendered and scale_coverage
    return {
        "available": True,
        "coverage_complete": coverage_complete,
        "passed": coverage_complete
        and non_color_passed
        and cvd_passed
        and grayscale_passed
        and colormap_passed,
        "series": series,
        "categorical_graphs": [
            {**graph, "document": document.get("path")}
            for document in documents
            if isinstance(document, dict)
            for graph in document.get("categorical_graphs", [])
            if isinstance(graph, dict)
        ],
        "color_scales": color_scale_reports,
        "pairs": pair_reports,
        "unresolved_color_paths": unresolved,
        "colors_not_confirmed_in_pdf": unrendered,
        "non_color_required": non_color_required,
        "non_color_passed": non_color_passed,
        "colour_vision_passed": cvd_passed,
        "grayscale_passed": grayscale_passed,
        "colormap_passed": colormap_passed,
        "thresholds": {
            "minimum_simulated_delta_e": minimum_delta_e,
            "minimum_grayscale_luminance_delta": minimum_luminance_delta,
            "minimum_colormap_step_delta_e": minimum_colormap_step,
            "minimum_colormap_luminance_range": minimum_colormap_range,
            "maximum_colormap_luminance_turns": maximum_colormap_turns,
            "authority": accessibility.get("threshold_authority")
            or "sciplot_internal_operational_gate",
        },
    }
