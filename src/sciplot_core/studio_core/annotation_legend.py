"""Closed ordinary native legend visibility contract, retaining series identity."""

from typing import Any

from sciplot_core.studio_core.annotation_axes import require_scope
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.document_edit_policy import ordinary_curve_paths


def require_native_legend(spec: dict[str, Any]) -> dict[str, Any]:
    require_scope(spec)
    legend = spec.get("legend")
    if (not isinstance(legend, dict) or not isinstance(legend.get("show"), bool)
            or not ordinary_curve_paths(spec) or legend.get("native_key") is False
            or legend.get("presentation_kind") in {"factorized_curve", "segmented_component"}):
        raise AnnotationOperationError("unsupported_legend_scope", "Visibility requires an ordinary native legend.")
    return legend


def change_legend_visibility(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    if (set(operation) != {"op", "expected_visible", "visible"}
            or any(not isinstance(operation[key], bool) for key in ("expected_visible", "visible"))):
        raise AnnotationOperationError("invalid_legend_visibility", "Use explicit boolean legend visibility fields.")
    legend = require_native_legend(spec)
    if legend["show"] != operation["expected_visible"]:
        raise AnnotationOperationError("stale_legend_visibility", "The legend visibility differs from the reviewed baseline.")
    before = legend["show"]
    legend["show"] = operation["visible"]
    return {"op": "set_legend_visibility", "before": before, "after": legend["show"]}
