"""Project byte-bound current native geometry, preserving generated diagnostics."""

import math
from pathlib import Path
from typing import Any, cast

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.policy.frame_export import DEFAULT_LEGEND_CURVE_CLEARANCE_MM


LEGEND_ISSUE = "legend_curve_clearance_below_target"


def current_legend_issues(issues: list[dict[str, Any]], document: Path,
                          audit: dict[str, Any], *, geometry_key: str = "legend_geometry",
                          expected_paths: set[str] | None = None) -> list[dict[str, Any]]:
    geometry = audit.get(geometry_key, {})
    verified = (Path(str(audit.get("path", ""))).resolve() == document.resolve()
                and audit.get("sha256") == file_sha256(document)
                and isinstance(geometry, dict) and geometry.get("coverage_complete") is True)
    legends = geometry.get("legends") if isinstance(geometry, dict) else None
    hidden = geometry.get("hidden_legends", []) if isinstance(geometry, dict) else []
    explicitly_hidden = (legends == [] and isinstance(hidden, list)
                         and any(isinstance(item, dict) and item.get("hidden") is True
                                 and item.get("graph_path") == "/page1/graph1"
                                 and item.get("path") == "/page1/graph1/key1" for item in hidden))
    distances = [item.get("minimum_curve_clearance_mm") for item in legends
                 if isinstance(item, dict)] if isinstance(legends, list) else []
    expected_visible = (isinstance(legends, list) and any(isinstance(item, dict)
                        and item.get("path") == "/page1/graph1/key1"
                        and item.get("graph_path") == "/page1/graph1" for item in legends))
    if expected_paths is not None:
        explicitly_hidden = False
        actual = [str(item.get("path")) for item in legends if isinstance(item, dict)] if isinstance(legends, list) else []
        expected_visible = (bool(expected_paths) and len(actual) == len(expected_paths) and set(actual) == expected_paths
            and all(isinstance(item, dict) and item.get("graph_path") == "/page1/graph1" for item in (legends or [])))
    verified = (verified and (explicitly_hidden or (bool(distances) and expected_visible))
                and len(distances) == len(legends or [])
                and all(isinstance(value, int | float) and not isinstance(value, bool)
                        and math.isfinite(value) and value >= 0 for value in distances))
    if not verified:
        # Absence of an old diagnostic is not evidence that a newly edited key is clear.
        return [*issues, {"id": "current_legend_geometry_unavailable", "severity": "critical",
                          "message": "Exact-current native legend clearance could not be established.",
                          "measurement_scope": "unverified_current_native"}]
    minimum = min((float(cast(float, value)) for value in distances), default=math.inf)
    originals = [item for item in issues if item.get("id") == LEGEND_ISSUE]
    candidates = originals or [{"id": LEGEND_ISSUE,
                               "required_clearance_mm": DEFAULT_LEGEND_CURVE_CLEARANCE_MM}]
    result = [dict(item) for item in issues if item.get("id") != LEGEND_ISSUE]
    for original in candidates:
        target = original.get("required_clearance_mm")
        if not isinstance(target, int | float) or isinstance(target, bool) or not math.isfinite(target) or target <= 0:
            result.append(dict(original))  # Unknown historical contracts cannot be superseded.
            result.append({"id": "current_legend_clearance_contract_unavailable", "severity": "critical",
                           "message": "The generated legend clearance target is not a valid positive distance."})
            continue
        item = dict(original)
        if originals:
            item["generated_issue"] = dict(original)
        item.update(measurement_scope="exact_current_native", document_sha256=audit["sha256"],
                    measured_clearance_mm=minimum if math.isfinite(minimum) else None,
                    severity="critical" if minimum <= 0 else "warning" if minimum < target else "info",
                    message=("The current native legend overlaps plotted data." if minimum <= 0
                             else "The current native legend is below the requested curve clearance." if minimum < target
                             else "The current native legend satisfies the requested curve clearance."))
        if explicitly_hidden:
            item.update(native_legend_hidden=True, message="The current native legend is explicitly hidden.")
        result.append(item)
    return result


def current_segmented_legend_issues(issues: list[dict[str, Any]], spec: dict[str, Any],
                                   document_path: Path | None, native_audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Consume only source-bound ordinary grouped summaries and exact native marks."""
    legend = spec.get("legend")
    source_request = spec.get("source_request", {})
    if not isinstance(source_request, dict):
        return issues
    binding = source_request.get("categorical_binding")
    if (document_path is not None and isinstance(binding, dict) and spec.get("template") == "bar"
            and binding.get("mode") in {"mean_sample_sd", "mean_sample_sd_n"}
            and isinstance(legend, dict) and legend.get("show") is True
            and legend.get("presentation_kind") == "segmented_component"):
        from sciplot_core.mapping_contract.categorical import validate_categorical_context
        from sciplot_core.studio_core.guide_contracts import categorical_line_contracts
        from sciplot_core.studio_core.legend_contracts import (
            categorical_component_legend_label_contracts, categorical_component_legend_rect_contracts,
            categorical_grouped_bar_fill_rect_contracts,
        )

        validate_categorical_context(source_request)
        expected = {"/page1/graph1/" + item["name"] for item in
            categorical_component_legend_label_contracts(spec) + categorical_component_legend_rect_contracts(spec)}
        data_paths = {"/page1/graph1/" + item["name"] for item in
            categorical_grouped_bar_fill_rect_contracts(spec) + categorical_line_contracts(spec)}
        audited = dict(native_audit or {})
        slot = audited.get("segmented_legend_geometry")
        geometry = dict(slot) if isinstance(slot, dict) else {}
        reported = geometry.get("data_paths")
        geometry["coverage_complete"] = (geometry.get("coverage_complete") is True
            and isinstance(reported, list) and all(isinstance(path, str) for path in reported)
            and len(reported) == len(data_paths) and set(reported) == data_paths)
        audited["segmented_legend_geometry"] = geometry
        issues = current_legend_issues(issues, document_path, audited,
            geometry_key="segmented_legend_geometry", expected_paths=expected)
        outside = geometry.get("outside_plot_paths", [])
        if (not isinstance(outside, list) or not all(isinstance(path, str) and path in expected for path in outside)
                or outside):
            issues.append({"id": "segmented_legend_outside_fixed_frame", "severity": "critical",
                "message": "The current native component legend cannot fit inside its fixed graph frame.",
                "measurement_scope": "exact_current_native", "paths": outside})
    return issues
