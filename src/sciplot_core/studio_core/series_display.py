"""Source-bound display aliases and membership; scientific identities stay intact."""

from copy import deepcopy
from typing import Any

from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.document_edit_policy import ordinary_curve_paths
from sciplot_core.studio_core.series_presentation import (
    persist_series_selection, selected_series_order, spec_source_series_order,
)


def require_series_display(spec: dict[str, Any]) -> list[dict[str, Any]]:
    series = spec.get("series", [])
    if not isinstance(series, list) or any(not isinstance(item, dict) for item in series):
        raise AnnotationOperationError("series_display_unsupported", "An exact source series inventory is required.")
    if (spec.get("template") != "curve" or spec.get("direct_labels")
            or len(ordinary_curve_paths(spec)) != len(series) or not series):
        raise AnnotationOperationError("series_display_unsupported", "Display aliases and membership require source-bound ordinary curves with a native legend.")
    spec_source_series_order(spec)
    return [dict(item) for item in series]


def compile_series_display(spec: dict[str, Any], operation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retain the complete source inventory and record the explicit display delta."""
    series = require_series_display(spec)
    result = deepcopy(spec)
    if operation["op"] == "set_series_selection":
        before_order = selected_series_order(spec)
        if operation["expected_order"] != before_order:
            raise AnnotationOperationError("stale_series_selection", "Use the current visible source order.")
        try:
            result = persist_series_selection(result, source_order=spec_source_series_order(spec), active_order=operation["active_order"])
        except ValueError as exc:
            raise AnnotationOperationError("invalid_series_selection", str(exc)) from exc
        after = selected_series_order(result)
        return result, {"op": operation["op"], "before": before_order, "after": after,
                        "authorization": "explicit_source_member_selection", "source_order": spec_source_series_order(spec)}
    source = operation["sample"]
    matches = [item for item in series if item["label"] == source]
    if len(matches) != 1:
        raise AnnotationOperationError("unknown_series", "Choose an exact source series identity.")
    before = str(matches[0].get("legend_key", source))
    if operation["expected_label"] != before:
        raise AnnotationOperationError("stale_series_label", "Use the current display alias.")
    label = operation["label"]
    if not isinstance(label, str) or not label.strip() or len(label) > 500 or any(ord(char) < 32 for char in label):
        raise AnnotationOperationError("invalid_series_label", "Use a non-blank display alias of at most 500 characters.")
    next(item for item in result["series"] if item["label"] == source)["legend_key"] = label
    return result, {"op": operation["op"], "sample": source, "before": before, "after": label,
                    "authorization": "explicit_display_alias", "source_identity_preserved": True}


def audit_source_series(document: Any, spec: dict[str, Any]) -> None:
    """Check every source array, including excluded members and duplicate points."""
    import numpy as np

    for item in require_series_display(spec):
        for axis in ("x", "y"):
            dataset = document.data.get(item[axis + "_name"])
            if dataset is None or not np.array_equal(np.asarray(dataset.data), np.asarray(item[axis + "_values"]), equal_nan=True):
                raise ValueError("A retained source series dataset differs from its exact source inventory.")
