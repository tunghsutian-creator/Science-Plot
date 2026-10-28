"""The new persisted automatic label contract consumes exact-current native QA."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.policy.frame_export import DEFAULT_LEGEND_CURVE_CLEARANCE_MM
from sciplot_core.studio_render.direct_label_layout import DIRECT_LABEL_LAYOUT_KEY, active_direct_label_layout


def current_direct_label_issues(issues: list[dict[str, Any]], spec: dict[str, Any],
                                document_path: Path | None, audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    request = spec.get("source_request")
    if not isinstance(request, dict) or DIRECT_LABEL_LAYOUT_KEY not in request:
        return issues
    try:
        active = active_direct_label_layout(request)
    except ValueError:
        active = "unknown"
    if active is None:
        return issues  # Explicit placement remains user owned.
    def unavailable(message: str) -> list[dict[str, Any]]:
        return [*issues, {"id": "current_direct_label_geometry_unavailable", "severity": "critical",
                          "message": message, "measurement_scope": "unverified_current_native"}]
    if active == "unknown":
        return unavailable("Unknown persisted automatic direct-label layout version.")
    labels = spec.get("direct_labels", [])
    if not labels:
        return issues  # A recorded legend/hidden-label choice has no inline footprint.
    if document_path is None or not isinstance(audit, dict):
        return unavailable("Automatic direct labels require exact-current native geometry.")
    geometry = audit.get("direct_label_geometry")
    expected = {"/page1/graph1/"+item["name"] for item in labels if isinstance(item, dict) and isinstance(item.get("name"), str)}
    curves = {"/page1/graph1/"+item["name"] for item in spec.get("series", [])
              if isinstance(item, dict) and isinstance(item.get("name"), str)}
    if (Path(str(audit.get("path", ""))).resolve() != document_path.resolve()
            or audit.get("sha256") != file_sha256(document_path)
            or not isinstance(geometry, dict) or geometry.get("coverage_complete") is not True
            or geometry.get("kind") != "sciplot_native_direct_label_geometry" or geometry.get("version") != 1):
        return unavailable("The exact-current native inline-label geometry is incomplete or stale.")
    records, hidden = geometry.get("labels"), geometry.get("hidden_labels")
    paths, hidden_curves = geometry.get("data_paths"), geometry.get("hidden_data_paths")
    if (not isinstance(records, list) or not isinstance(hidden, list)
            or not isinstance(paths, list) or not isinstance(hidden_curves, list)):
        return unavailable("The complete visible/hidden label and curve inventories are required.")
    if (not all(isinstance(record, dict) and isinstance(record.get("path"), str) for record in records)
            or not all(isinstance(path, str) for path in hidden+paths+hidden_curves)
            or len(expected) != len(labels) or not curves):
        return unavailable("The complete visible/hidden label and curve inventories are required.")
    actual = [record.get("path") for record in records if isinstance(record, dict)]
    if (len(actual) != len(records) or len(actual)+len(hidden) != len(expected)
            or set(actual+hidden) != expected or set(actual).intersection(hidden)
            or len(paths)+len(hidden_curves) != len(curves) or set(paths+hidden_curves) != curves
            or set(paths).intersection(hidden_curves)):
        return unavailable("The native inline-label/visible-curve inventory does not match its recorded contract.")
    outside = geometry.get("outside_plot_paths")
    if not isinstance(outside, list) or any(path not in expected for path in outside):
        return unavailable("The exact-current inline-label frame measurement is incomplete.")
    minimum = math.inf
    for record in records:
        if record.get("graph_path") != "/page1/graph1":
            return unavailable("The automatic label belongs to an unverified graph frame.")
        distances = [record.get("minimum_curve_clearance_mm")]
        if len(records) > 1:
            distances.append(record.get("minimum_label_clearance_mm"))
        if not all(isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 for value in distances):
            return unavailable("Every painted inline label needs finite full-geometry clearance.")
        minimum = min(minimum, *distances)
    target = DEFAULT_LEGEND_CURVE_CLEARANCE_MM
    failed = bool(outside) or minimum < target
    return [*issues, {"id": "current_direct_label_clearance", "severity": "critical" if failed else "info",
        "message": ("No inline label is currently visible; no visible-text clearance is claimed." if not records
                    else "Automatic inline labels violate the recorded frame/curve clearance." if failed
                    else "Automatic inline labels satisfy actual native frame/curve clearance."),
        "measurement_scope": "exact_current_native", "document_sha256": audit["sha256"],
        "required_clearance_mm": target, "measured_clearance_mm": minimum if math.isfinite(minimum) else None,
        "outside_plot_paths": outside, "native_labels_hidden": not records}]
