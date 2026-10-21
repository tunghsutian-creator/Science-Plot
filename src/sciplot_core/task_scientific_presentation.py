"""Validate requested scientific presentation without substituting its meaning."""

from __future__ import annotations

from typing import Any

from sciplot_core.task_errors import TaskControlError


CURVE_DISPLAYS = ("raw_overlay", "stacked_offset")
SUMMARY_STATISTICS = ("raw_only", "median_iqr", "mean_sample_sd", "mean_sample_sd_n")


def presentation_requirement_properties() -> dict[str, Any]:
    """Optional requirements constrain existing execution; they never select an algorithm."""
    return {
        "curve_display": {
            "enum": list(CURVE_DISPLAYS),
            "description": "Required unshifted overlay or explicitly offset curves; reject incompatible execution rather than changing measured display values.",
        },
        "summary_statistic": {
            "enum": list(SUMMARY_STATISTICS),
            "description": "Required replicate summary. mean_sample_sd uses sample SD (ddof=1); mean_sample_sd_n also requires delivered valid n. The selected executor's fixed method and source contract must satisfy the requirement.",
        },
    }


def validate_presentation_requirements(request: dict[str, Any]) -> None:
    for field, allowed in (("curve_display", CURVE_DISPLAYS), ("summary_statistic", SUMMARY_STATISTICS)):
        if field in request and request[field] not in allowed:
            error = TaskControlError("invalid_scientific_presentation", f"{field} must use an advertised scientific presentation requirement.")
            error.issues = [{"path": "/" + field, "constraint": "enum", "expected": list(allowed)}]
            raise error


def scientific_presentation(
    request: dict[str, Any], *, rule_id: str | None = None, template: str | None = None,
) -> dict[str, Any]:
    """Describe the actual existing task route, independently of visual mark names."""
    if "intent" in request:
        return {"route": "semantic_xy", "curve_display": "raw_overlay", "summary_statistic": "raw_only",
                "rule_id": request["intent"].get("rule_id", "ordinary_xy"), "summary_calculation": "none"}
    from sciplot_core.materials_rules.catalog import get_rule, resolve_rule_template

    rule = get_rule(str(rule_id))
    selected = resolve_rule_template(rule, template)
    summary = rule.render_options.get("summary_statistic", "raw_only")
    statistics: dict[str, Any] = {}
    if rule.rule_id == "impact_metric":
        from sciplot_core.materials_rules.impact_presentation import impact_presentation_statistics

        statistics = impact_presentation_statistics(selected, summary_statistic=request.get("summary_statistic"))
        summary = statistics["summary_statistic"]
    if rule.figure_plan_adapter == "mechanical":
        # The current mechanical plan always includes its descriptive children.
        summary = "median_iqr"
    display = ("stacked_offset" if selected == "stacked_curve" else
               "raw_overlay" if rule.presentation_data_shape != "categorical_replicates" and selected in {"curve", "point_line"} else None)
    return {"route": "ordinary_rule", "rule_id": rule.rule_id, "template": selected,
            "supported_templates": list(rule.presentation_templates),
            "curve_display": display, "summary_statistic": summary,
            **({"statistics_contract": statistics} if statistics else {})}


def presentation_blocker(request: dict[str, Any], effective: dict[str, Any]) -> dict[str, Any] | None:
    """Reject a semantic mismatch before source preparation or native creation."""
    required = {key: request[key] for key in ("curve_display", "summary_statistic") if key in request}
    issues = [{"path": "/" + key, "constraint": "supported_scientific_presentation",
               "required": value, "effective": effective.get(key)}
              for key, value in required.items() if value != effective.get(key)]
    intent = request.get("intent")
    if isinstance(intent, dict) and str(intent["x"]["quantity"]).strip().casefold() in {"sample", "category", "categorical", "metric"}:
        issues.append({"path": "/intent/x/quantity", "constraint": "numeric_xy_only",
                       "required": intent["x"]["quantity"], "effective": "numeric_coordinate"})
    if not issues:
        return None
    messages = []
    for issue in issues:
        if issue["path"] == "/intent/x/quantity":
            messages.append("Numeric XY creation uses numeric coordinates. Use the source-bound categorical task contract for original categorical values or repeated Sample/Condition measurements; arbitrary pivot and row- or Metric-scoped unit inference remain unsupported.")
        elif issue["path"] == "/summary_statistic":
            messages.append(f"Required replicate statistics {issue['required']!r} are unavailable; this executor uses {issue['effective']!r}. Its fixed method must satisfy the request; raw points underneath a summary are not raw-only. Internal n tables are not delivered valid-n disclosure.")
        else:
            messages.append(f"Required curve display {issue['required']!r} is unavailable; this route uses {issue['effective']!r}.")
    return {
        "reason_code": "scientific_presentation_unsupported",
        "message": " ".join(messages),
        "required": required, "effective": effective, "issues": issues,
        "recovery_action": "resolve_scientific_intent",
        "continuation": "Retain the original source and requested meaning. Report this unsupported requirement; change it only with explicit user intent. Do not select another experiment, offset measurements, replace mean/SD with median/IQR, invent units, or rewrite input cells.",
    }


def sample_sd_source_blocker(request: dict[str, Any], effective: dict[str, Any], source: Any) -> dict[str, Any] | None:
    """Use the existing source owner's counts; do not call a singleton error an SD."""
    if request.get("summary_statistic") != "mean_sample_sd" or effective.get("rule_id") != "impact_metric":
        return None
    from sciplot_core.semantic_sources.impact_sources import _read_impact_source

    payload = _read_impact_source(source)
    missing = {sample: count for sample, count in zip(payload.samples, payload.replicate_counts, strict=True) if count < 2}
    if not missing:
        return None
    return {
        "reason_code": "scientific_presentation_unsupported", "required": {"summary_statistic": "mean_sample_sd"},
        "effective": effective,
        "message": "Sample SD requires at least two valid observations per group; the executor's singleton zero-error fallback is not a sample SD estimate.",
        "issues": [{"path": "/summary_statistic", "constraint": "minimum_valid_replicates", "minimum": 2, "groups": missing}],
        "recovery_action": "resolve_scientific_intent",
        "continuation": "Preserve the original observations. Report the undefined sample SD; do not invent observations or present the singleton zero-error fallback as measured certainty.",
    }


__all__ = ["CURVE_DISPLAYS", "SUMMARY_STATISTICS", "presentation_requirement_properties",
           "validate_presentation_requirements", "scientific_presentation", "presentation_blocker", "sample_sd_source_blocker"]
