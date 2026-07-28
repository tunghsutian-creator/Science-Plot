"""Audit spectral coverage, semantic series contracts, and visual transforms."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.studio_render.models import (
    STACKED_TEMPLATE_IDS,
    StudioSeries,
    _VeuszAxisContract,
)
from sciplot_core.studio_render.template_resolution import (
    _looks_like_wavenumber_axis,
)


def _spectral_x_coverage_issue(
    series: list[StudioSeries],
    *,
    template_id: str,
    axis_info: dict[str, Any],
    axis_contract: _VeuszAxisContract,
) -> dict[str, Any] | None:
    if template_id not in STACKED_TEMPLATE_IDS or not _looks_like_wavenumber_axis(
        axis_info
    ):
        return None
    if axis_contract.x_min is None or axis_contract.x_max is None:
        return None
    axis_low, axis_high = sorted(
        (float(axis_contract.x_min), float(axis_contract.x_max))
    )
    axis_span = axis_high - axis_low
    values = [
        float(value)
        for item in series
        for value in item.x_values
        if math.isfinite(float(value)) and axis_low <= float(value) <= axis_high
    ]
    if axis_span <= 0.0 or len(values) < 2:
        return None
    data_low = min(values)
    data_high = max(values)
    coverage = (data_high - data_low) / axis_span
    if coverage >= 0.25:
        return None
    severity = "critical" if coverage < 0.08 else "warning"
    return {
        "id": "spectral_axis_data_coverage_low",
        "severity": severity,
        "message": (
            "Spectral data occupy too little of the requested wavenumber axis; the curve is visually collapsed."
            if severity == "critical"
            else "Spectral data occupy less than one quarter of the requested wavenumber axis."
        ),
        "axis_domain": [axis_low, axis_high],
        "data_domain": [data_low, data_high],
        "coverage_fraction": round(coverage, 6),
        "critical_threshold": 0.08,
        "warning_threshold": 0.25,
    }


def _semantic_series_contract_issues(
    series: list[StudioSeries],
    *,
    request: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reject same-axis series that contradict the selected rule's metric contract."""

    rule_id = str(request.get("rule_id") or "").strip()
    labels = [str(item.label or "").casefold() for item in series]
    issues: list[dict[str, Any]] = []
    forbidden_by_rule = {
        "saxs_profile": ("azimuth", "angle"),
        "swelling_curve": ("gel fraction", "gel content"),
    }
    forbidden = forbidden_by_rule.get(rule_id, ())
    incompatible_labels = [
        item.label
        for item, label in zip(series, labels, strict=True)
        if any(token in label for token in forbidden)
    ]
    if incompatible_labels:
        issues.append(
            {
                "id": "incompatible_series_for_axis_metric",
                "severity": "critical",
                "message": "A same-table metric incompatible with the selected y-axis was included as a curve.",
                "rule_id": rule_id,
                "incompatible_series": incompatible_labels,
            }
        )
    if rule_id == "gpc_sec_chromatogram" and len(series) > 1:
        domains: list[tuple[float, float]] = []
        for item in series:
            values = [
                float(value) for value in item.x_values if math.isfinite(float(value))
            ]
            if len(values) >= 2 and max(values) > min(values):
                domains.append((min(values), max(values)))
        if len(domains) == len(series):
            overlap = max(
                0.0,
                min(high for _low, high in domains)
                - max(low for low, _high in domains),
            )
            minimum_span = min(high - low for low, high in domains)
            overlap_fraction = overlap / minimum_span if minimum_span > 0.0 else 0.0
            if overlap_fraction < 0.25:
                issues.append(
                    {
                        "id": "gpc_detector_time_domains_misaligned",
                        "severity": "critical"
                        if overlap_fraction < 0.05
                        else "warning",
                        "message": (
                            "GPC detector traces share too little elution-time domain for a common-axis overlay."
                        ),
                        "series_domains": [[low, high] for low, high in domains],
                        "minimum_span_overlap_fraction": round(overlap_fraction, 6),
                        "critical_threshold": 0.05,
                        "warning_threshold": 0.25,
                    }
                )
    return issues


def _visual_data_transforms(
    *,
    template_id: str,
    render_options: dict[str, Any],
    series_count: int,
) -> list[dict[str, Any]]:
    transforms: list[dict[str, Any]] = []
    baseline_mode = str(render_options.get("baseline") or "none").strip().casefold()
    if baseline_mode != "none":
        transforms.append(
            {
                "id": "baseline_correction",
                "mode": baseline_mode,
                "implementation": "mean of up to 30 points at each endpoint with linear interpolation",
                "scientific_values_changed_in_visual_document": True,
            }
        )
    if template_id in STACKED_TEMPLATE_IDS and series_count > 1:
        transforms.append(
            {
                "id": "vertical_offset_stack",
                "mode": "q01_shift_and_auto_spacing",
                "series_count": series_count,
                "scientific_values_changed_in_visual_document": True,
                "purpose": "visual separation only; processed source table retains the unshifted values",
            }
        )
    return transforms
