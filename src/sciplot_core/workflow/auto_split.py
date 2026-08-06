"""Dispatch one workflow render family and apply automatic split policy."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Literal
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import get_rule
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.render import render_to_dir
from sciplot_core.split import (
    DEFAULT_STACK_SPLIT_POLICY,
    STACKED_TALL_FIGURE_HEIGHT_MM,
    SUPPORTED_SPLIT_TEMPLATES,
)

from sciplot_core.workflow.reports import (
    _layout_quality_from_result,
    _layout_summary_height_mm,
)

from sciplot_core.workflow.rheology_bundle import (
    _render_veusz_sweep_bundle,
)

from sciplot_core.workflow.mechanical_bundle import (
    _render_veusz_mechanical_bundle,
)

from sciplot_core.workflow.impact_bundle import (
    _render_veusz_impact_bundle,
)

from sciplot_core.workflow.dsc_bundle import (
    _render_veusz_dsc_bundle,
)

from sciplot_core.workflow.performance_bundle import (
    _render_veusz_performance_bundle,
)

WorkflowRenderFamily = Literal[
    "performance",
    "impact",
    "mechanical",
    "dsc",
    "rheology",
    "generic",
]

_SPECIALIZED_RENDER_FAMILY_BY_RULE: dict[str, WorkflowRenderFamily] = {
    "performance_comparison": "performance",
    "impact_metric": "impact",
    "tensile_curve": "mechanical",
    "compression_curve": "mechanical",
    "flexural_curve": "mechanical",
    "dsc_curve": "dsc",
    "rheology_frequency_sweep": "rheology",
    "rheology_temperature_sweep": "rheology",
}


def _resolve_workflow_render_family(rule_id: object) -> WorkflowRenderFamily:
    """Resolve one specialized family or the generic renderer from a rule."""

    if rule_id is None:
        return "generic"
    if not isinstance(rule_id, str):
        raise ValueError("Workflow render `rule_id` must be text or null.")
    normalized = rule_id.strip()
    if not normalized:
        return "generic"
    if normalized != rule_id:
        raise ValueError(
            "Workflow render `rule_id` cannot contain surrounding whitespace."
        )
    get_rule(normalized)
    return _SPECIALIZED_RENDER_FAMILY_BY_RULE.get(normalized, "generic")


def _auto_split_policy_for_result(
    *,
    request: dict[str, Any],
    template: str,
    layout_quality: dict[str, Any],
) -> dict[str, Any] | None:
    if isinstance(request.get("split_policy"), dict):
        return None
    if template not in SUPPORTED_SPLIT_TEMPLATES:
        return None
    issue_ids = (
        layout_quality.get("issue_ids")
        if isinstance(layout_quality.get("issue_ids"), list)
        else []
    )
    if "stack_peak_too_small" not in {str(item) for item in issue_ids}:
        return None
    height_mm = _layout_summary_height_mm(layout_quality)
    if height_mm is None or height_mm < STACKED_TALL_FIGURE_HEIGHT_MM:
        return None
    return dict(DEFAULT_STACK_SPLIT_POLICY)


def _render_with_auto_split(
    input_path: Path,
    *,
    source_input: Path | None = None,
    source_attestation: PreparationSourceAttestation | None = None,
    template: str,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any]:
    figures_dir = output_dir / "figures"
    family = _resolve_workflow_render_family(request.get("rule_id"))
    bundle = _render_resolved_bundle(
        family,
        input_path=input_path,
        source_input=source_input,
        source_attestation=source_attestation,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if bundle is not None:
        return bundle
    if request.get("resolved_figure_plan") is not None:
        raise ValueError(
            "workflow_planned_bundle_unavailable: the selected FigurePlan "
            "cannot fall back to generic rendering."
        )
    result = render_to_dir(
        input_path,
        template=template,
        output_dir=figures_dir,
        options=options,
        export_formats=export_formats,
        split_policy=request.get("split_policy"),
        request_context={
            **request,
            "explicit_render_option_keys": request.get(
                "explicit_render_option_keys", []
            ),
        },
    )
    layout_quality = _layout_quality_from_result(result)
    policy = _auto_split_policy_for_result(
        request=request, template=template, layout_quality=layout_quality
    )
    if policy is None:
        return result

    if figures_dir.exists():
        shutil.rmtree(figures_dir)
    split_options = _compact_auto_split_options(options)
    split_result = render_to_dir(
        input_path,
        template=template,
        output_dir=figures_dir,
        options=split_options,
        export_formats=export_formats,
        split_policy=policy,
        request_context={
            **request,
            "explicit_render_option_keys": request.get(
                "explicit_render_option_keys", []
            ),
        },
    )
    split_result["auto_split"] = {
        "applied": True,
        "trigger_issue": "stack_peak_too_small",
        "reason": "tall_stacked_peak_too_small",
        "policy": json_safe(policy),
        "original_layout_quality": json_safe(layout_quality),
    }
    return split_result


def _render_resolved_bundle(
    family: WorkflowRenderFamily,
    *,
    input_path: Path,
    source_input: Path | None,
    source_attestation: PreparationSourceAttestation | None,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    """Call at most one specialized adapter for the resolved render family."""

    if family == "performance":
        return _render_veusz_performance_bundle(
            source_input or input_path,
            output_dir=output_dir,
            options=options,
            export_formats=export_formats,
            request=request,
        )
    if family == "impact":
        return _render_veusz_impact_bundle(
            source_input or input_path,
            output_dir=output_dir,
            options=options,
            export_formats=export_formats,
            request=request,
        )
    if family == "mechanical":
        return _render_veusz_mechanical_bundle(
            input_path,
            output_dir=output_dir,
            options=options,
            export_formats=export_formats,
            request=request,
        )
    if family == "dsc":
        return _render_veusz_dsc_bundle(
            input_path,
            output_dir=output_dir,
            options=options,
            export_formats=export_formats,
            request=request,
        )
    if family == "rheology":
        return _render_veusz_sweep_bundle(
            input_path,
            source_input=source_input,
            source_attestation=source_attestation,
            output_dir=output_dir,
            options=options,
            export_formats=export_formats,
            request=request,
        )
    return None


def _compact_auto_split_options(options: dict[str, Any]) -> dict[str, Any]:
    updated = dict(options)
    size = str(updated.get("size") or "").strip().lower()
    if size.endswith("x110"):
        updated["size"] = f"{size.removesuffix('x110')}x55"
    return updated
