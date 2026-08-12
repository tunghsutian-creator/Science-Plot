"""Classify input sources and resolve source-shape recommendations into intent."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe as _json_safe
from sciplot_core.foundation.text_files import (
    text_preview as _text_preview,
)
from sciplot_core.foundation.text_values import (
    token as _token,
)
from sciplot_core.materials_rules import (
    get_rule,
    match_rule,
    semantic_payload_from_rule,
)
from sciplot_core.performance_comparison import is_performance_comparison_source
from sciplot_core.policy import (
    DEFAULT_RENDER_OPTIONS as _DEFAULT_RENDER_OPTIONS,
)

from sciplot_core.source_inspection import (
    inspect_input_file,
)

from sciplot_core.semantic_sources.rheology_replicates import (
    is_rheology_temperature_comparison_dir,
)
from sciplot_core.semantic_sources.tensile_export_identity import (
    TENSILE_EXPORT_DIR_SUFFIX as TENSILE_EXPORT_DIR_SUFFIX,
    has_tensile_export_parent,
    is_tensile_export_dir,
    tensile_export_csv_files as tensile_export_csv_files,
    tensile_export_sample_name as tensile_export_sample_name,
)


def _inspect_source_shape(
    input_path: Path, sheet: str | int
) -> tuple[dict[str, Any] | None, str | None]:
    if input_path.is_dir():
        return None, "Source inspection expects a file, not a directory."
    try:
        payload = inspect_input_file(input_path, sheet)
    except Exception as exc:
        return None, str(exc)
    return _json_safe(payload), None


def _top_recommendation(
    inspection: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not inspection:
        return None
    recommendations = inspection.get("recommendations") or []
    top = recommendations[0] if recommendations else None
    return top if isinstance(top, dict) else None


def _template_from_inspection(
    inspection: dict[str, Any] | None, fallback: str = "curve"
) -> str:
    top = _top_recommendation(inspection)
    if top is None:
        return fallback
    return str(top.get("template_id") or fallback)


def _render_options_from_inspection(
    inspection: dict[str, Any] | None,
) -> dict[str, Any]:
    top = _top_recommendation(inspection)
    if top is None:
        return dict(_DEFAULT_RENDER_OPTIONS)
    defaults = top.get("default_render_overrides") or {}
    if not isinstance(defaults, dict):
        return dict(_DEFAULT_RENDER_OPTIONS)
    return {**_DEFAULT_RENDER_OPTIONS, **defaults}


def _classification(
    *,
    semantic_family: str,
    recommended_recipe: str | None,
    template: str,
    render_options: dict[str, Any],
    confidence: float,
    reason: str,
    needs_ai_intervention: bool = False,
    inspection_model: str | None = None,
    inspection_error: str | None = None,
) -> dict[str, Any]:
    return {
        "semantic_family": semantic_family,
        "recommended_recipe": recommended_recipe,
        "template": template,
        "render_options": render_options,
        "confidence": confidence,
        "reason": reason,
        "needs_ai_intervention": needs_ai_intervention,
        # Preserve these established payload keys while their implementation
        # now comes from the first-party source_inspection package.
        "vendor_model": inspection_model,
        "vendor_error": inspection_error,
    }


def classify_source(
    input_path: str | Path,
    *,
    sheet: str | int = 0,
    vendor_inspection: dict[str, Any] | None = None,
    requested_rule_id: str | None = None,
) -> dict[str, Any]:
    path = Path(input_path).expanduser()
    if requested_rule_id is not None:
        requested_rule = get_rule(requested_rule_id)
        return semantic_payload_from_rule(
            requested_rule,
            confidence=100.0,
            reason=(
                f"Explicitly requested material rule `{requested_rule.rule_id}` "
                "is pending fixture-backed acceptance and cannot run in "
                "deterministic mode."
                if requested_rule.fixture_status != "ready"
                else f"Explicit material rule `{requested_rule.rule_id}` selected "
                "by the user or an assistant."
            ),
        )
    performance_rule = get_rule("performance_comparison")
    if (
        requested_rule_id is None
        and performance_rule.fixture_status == "ready"
        and is_performance_comparison_source(path)
    ):
        return semantic_payload_from_rule(
            performance_rule,
            confidence=99.0,
            reason=(
                "Detected the explicit material/role/metric/value/unit tidy "
                "performance-comparison contract."
            ),
        )
    if vendor_inspection is None:
        inspection, inspection_error = _inspect_source_shape(path, sheet)
    else:
        inspection = vendor_inspection
        inspection_error = None

    inspection_model = (
        str(inspection.get("model")) if inspection and inspection.get("model") else None
    )
    top = _top_recommendation(inspection)
    experiment_family = (
        str(top.get("experiment_family"))
        if top and top.get("experiment_family")
        else ""
    )
    text = _text_preview(path)
    evidence = f"{path.as_posix()}\n{text}".casefold()
    compact_evidence = _token(evidence)
    match_inspection_model = inspection_model
    match_experiment_family = experiment_family
    structured_temperature_comparison = bool(
        requested_rule_id is None
        and path.is_dir()
        and is_rheology_temperature_comparison_dir(path)
    )
    explicit_instrument_temperature_sweep = bool(
        inspection_model == "frequency_metric_sheet"
        and (
            "temperaturesweep" in compact_evidence
            or "temperatureramp" in compact_evidence
        )
        and "temperature" in compact_evidence
        and any(
            token in compact_evidence
            for token in ("storagemodulus", "lossmodulus", "complexmodulus")
        )
    )
    if inspection_model == "frequency_metric_sheet" and (
        "temperaturesweep" in compact_evidence
        or "temperatureramp" in compact_evidence
        or structured_temperature_comparison
    ):
        # Generic shape inspection calls any aligned rheology metric
        # sheet a frequency sheet, even when the instrument metadata and X
        # column explicitly identify a temperature sweep. Keep the inspection
        # model for diagnostics, but do not let that structural shortcut
        # override stronger experiment semantics.
        match_inspection_model = None
        match_experiment_family = None
    if requested_rule_id is None and (
        structured_temperature_comparison or explicit_instrument_temperature_sweep
    ):
        return semantic_payload_from_rule(
            get_rule("rheology_temperature_sweep"),
            confidence=94.0,
            reason=(
                "Detected explicit rheology temperature-sweep metadata and a "
                "temperature response column; the declared varying independent "
                "variable takes precedence over logged constant angular-frequency columns."
            ),
            vendor_model=inspection_model,
            vendor_error=inspection_error,
        )
    matched_rule = match_rule(
        evidence=evidence,
        compact_evidence=compact_evidence,
        vendor_model=match_inspection_model,
        experiment_family=match_experiment_family,
        requested_rule_id=requested_rule_id,
    )
    if matched_rule is not None:
        if matched_rule.fixture_status != "ready":
            return semantic_payload_from_rule(
                matched_rule,
                confidence=0.0,
                reason=(
                    f"Explicitly requested material rule `{matched_rule.rule_id}` is pending "
                    "fixture-backed acceptance and cannot run in deterministic mode."
                ),
                vendor_model=inspection_model,
                vendor_error=inspection_error,
            )
        confidence = (
            100.0 if requested_rule_id else max(80.0, 98.0 - matched_rule.priority / 2)
        )
        return semantic_payload_from_rule(
            matched_rule,
            confidence=confidence,
            reason=(
                f"Explicit material rule `{matched_rule.rule_id}` selected by the user or an assistant."
                if requested_rule_id
                else matched_rule.reason
                or f"Matched material rule `{matched_rule.rule_id}`."
            ),
            vendor_model=inspection_model,
            vendor_error=inspection_error,
        )

    if (
        is_tensile_export_dir(path)
        or has_tensile_export_parent(path)
        or "结果表格2" in compact_evidence
    ):
        return _classification(
            semantic_family="tensile_curve",
            recommended_recipe="tensile",
            template="curve",
            render_options=dict(_DEFAULT_RENDER_OPTIONS),
            confidence=95.0,
            reason="Detected Chinese tensile export table or `.is_tens_Exports` directory.",
            inspection_model=inspection_model,
            inspection_error=inspection_error,
        )

    if (
        "stressrelaxation" in compact_evidence
        or "stresssrelaxation" in compact_evidence
        or "relaxationtest" in compact_evidence
        or "relaxationmodulus" in compact_evidence
        or "stepstrain" in compact_evidence
    ):
        return _classification(
            semantic_family="rheology_stress_relaxation",
            recommended_recipe="stress_relaxation",
            template="curve",
            render_options=dict(_DEFAULT_RENDER_OPTIONS),
            confidence=94.0,
            reason="Detected rheology stress-relaxation metadata or relaxation modulus columns.",
            inspection_model=inspection_model,
            inspection_error=inspection_error,
        )

    if (
        "creep" in compact_evidence
        or "creeptest" in compact_evidence
        or "creepcompliance" in compact_evidence
    ):
        return _classification(
            semantic_family="rheology_creep",
            recommended_recipe="rheology_dma",
            template="curve",
            render_options=dict(_DEFAULT_RENDER_OPTIONS),
            confidence=94.0,
            reason="Detected rheology creep metadata or creep compliance columns.",
            inspection_model=inspection_model,
            inspection_error=inspection_error,
        )

    if (
        inspection_model == "frequency_metric_sheet"
        or experiment_family == "rheology"
        or "frequencysweep" in compact_evidence
        or "angularfrequency" in compact_evidence
        or "pinlv" in compact_evidence
        or "流变" in evidence
    ):
        return _classification(
            semantic_family="rheology_frequency",
            recommended_recipe="rheology_dma",
            template=_template_from_inspection(inspection, "point_line"),
            render_options=_render_options_from_inspection(inspection),
            confidence=93.0 if inspection_model == "frequency_metric_sheet" else 80.0,
            reason="Detected rheology frequency-sweep data.",
            inspection_model=inspection_model,
            inspection_error=inspection_error,
        )

    if "impact" in compact_evidence or "冲击" in evidence:
        return semantic_payload_from_rule(
            get_rule("impact_metric"),
            confidence=86.0,
            reason=(
                "Detected impact-strength data; preserve every observation and use the categorical replicate "
                "Veusz contract without fabricating missing replicates."
            ),
            vendor_model=inspection_model,
            vendor_error=inspection_error,
        )

    if (
        inspection_model == "tensile_curve"
        or "tensile" in compact_evidence
        or "拉伸" in evidence
    ):
        return _classification(
            semantic_family="tensile_curve",
            recommended_recipe="tensile",
            template=_template_from_inspection(inspection, "curve"),
            render_options=_render_options_from_inspection(inspection),
            confidence=88.0,
            reason="Detected mechanical tensile-style curve data.",
            inspection_model=inspection_model,
            inspection_error=inspection_error,
        )

    if inspection_model == "replicate_table":
        return _classification(
            semantic_family="generic_replicate",
            recommended_recipe="metrics_swelling",
            template=_template_from_inspection(inspection, "box"),
            render_options=_render_options_from_inspection(inspection),
            confidence=75.0,
            reason="Detected a generic replicate table.",
            inspection_model=inspection_model,
            inspection_error=inspection_error,
        )

    if inspection_model in {"curve_table", "heatmap_table", "table_summary"}:
        return _classification(
            semantic_family="generic_curve",
            recommended_recipe=None,
            template=_template_from_inspection(inspection, "curve"),
            render_options=_render_options_from_inspection(inspection),
            confidence=70.0,
            reason=f"Detected a generic plot-ready table through source model `{inspection_model}`.",
            inspection_model=inspection_model,
            inspection_error=inspection_error,
        )

    return _classification(
        semantic_family="unknown",
        recommended_recipe=None,
        template="curve",
        render_options=dict(_DEFAULT_RENDER_OPTIONS),
        confidence=0.0,
        reason="SciPlot could not map this input to a known experiment semantic family.",
        needs_ai_intervention=True,
        inspection_model=inspection_model,
        inspection_error=inspection_error,
    )
