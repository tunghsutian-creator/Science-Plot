"""Pure reproducible observed-peak evidence over audited series values."""

from __future__ import annotations

import math
from typing import Any

from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.annotation_axes import axis_unit, require_scope
from sciplot_core.studio_core.document_edit_state import value_digest
from sciplot_core.studio_core.series_presentation import selected_series_order


def peak_candidates_for_spec(
    spec: dict[str, Any], *, object_path: str, window: dict[str, Any], polarity: str,
) -> list[dict[str, Any]]:
    require_scope(spec)
    if polarity not in {"maximum", "minimum"}:
        raise AnnotationOperationError("invalid_peak_polarity", "Choose maximum or minimum.")
    if not isinstance(window, dict) or set(window) != {"min", "max", "unit"}:
        raise AnnotationOperationError("invalid_peak_window", "Window needs min, max and unit.")
    if window["unit"] != axis_unit(spec, "x"):
        raise AnnotationOperationError("unit_mismatch", "Use the exact inspected x-axis unit.")
    lo, hi = window["min"], window["max"]
    if any(isinstance(v, bool) or not isinstance(v, int | float)
           or not math.isfinite(v) for v in (lo, hi)) or lo >= hi:
        raise AnnotationOperationError("invalid_peak_window", "Window bounds must be finite and increasing.")
    matches = [item for item in spec["series"]
               if object_path == f"/page1/graph1/{item['name']}"]
    if len(matches) != 1 or matches[0].get("presentation_kind") != "curve":
        raise AnnotationOperationError("ambiguous_anchor", "Select one uniquely bound ordinary curve.")
    item = matches[0]
    if item["label"] not in selected_series_order(spec):
        raise AnnotationOperationError("anchor_not_visible", "The selected source series is excluded from this figure.")
    x, y = item["x_values"], item["y_values"]
    if len(x) != len(y):
        raise AnnotationOperationError("invalid_peak_data", "Paired curve lengths differ.")
    finite = [i for i, (a, b) in enumerate(zip(x, y, strict=True))
              if isinstance(a, int | float) and isinstance(b, int | float)
              and math.isfinite(a) and math.isfinite(b)]
    finite_indices = set(finite)
    finite_x = [x[i] for i in finite]
    if len(set(finite_x)) != len(finite_x):
        raise AnnotationOperationError("ambiguous_anchor", "Duplicate x coordinates require an explicit scientific selection.")
    ordered = sorted(finite_x)
    if finite_x not in (ordered, list(reversed(ordered))):
        raise AnnotationOperationError("invalid_peak_data", "Peak detection requires a monotonic observed x trace.")
    signature = value_digest({key: item[key] for key in
                              ("name", "label", "x_name", "y_name", "x_values", "y_values", "source_artifacts")})
    candidates = []
    sign = 1 if polarity == "maximum" else -1
    for i in range(1, len(x) - 1):
        if not all(j in finite_indices for j in (i - 1, i, i + 1)) or not lo <= x[i] <= hi:
            continue
        if sign * y[i] <= sign * y[i - 1] or sign * y[i] <= sign * y[i + 1]:
            continue
        if any(not min(spec["axes"][axis]["min"], spec["axes"][axis]["max"]) <= value <=
               max(spec["axes"][axis]["min"], spec["axes"][axis]["max"])
               for axis, value in (("x", x[i]), ("y", y[i]))):
            continue
        candidate = {
            "kind": "sciplot_observed_peak", "version": 1,
            "object_path": object_path, "sample": item["label"],
            "series_signature": signature, "window": window, "polarity": polarity,
            "method": "strict_discrete_interior_extremum_v1", "point_index": i,
            "x": float(x[i]), "y": float(y[i]),
            "x_unit": axis_unit(spec, "x"), "y_unit": axis_unit(spec, "y"),
        }
        candidate["candidate_id"] = value_digest(candidate)
        candidates.append(candidate)
    return candidates


def validate_peak_candidate(spec: dict[str, Any], candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise AnnotationOperationError("invalid_peak_candidate", "Use a candidate returned by peak inspection.")
    try:
        candidates = peak_candidates_for_spec(
            spec, object_path=candidate["object_path"], window=candidate["window"],
            polarity=candidate["polarity"],
        )
    except KeyError as exc:
        raise AnnotationOperationError("invalid_peak_candidate", "Peak evidence is incomplete.") from exc
    evidence = {k: v for k, v in candidate.items() if k not in {"document_sha256", "figure_id"}}
    if evidence not in candidates:
        raise AnnotationOperationError("anchor_missing", "Observed peak evidence no longer matches this exact source series.")
    return evidence

