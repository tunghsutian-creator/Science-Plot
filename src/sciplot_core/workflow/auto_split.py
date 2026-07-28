"""Choose and execute explicit multi-panel rendering policies."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
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
    template: str,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any]:
    figures_dir = output_dir / "figures"
    performance_bundle = _render_veusz_performance_bundle(
        source_input or input_path,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if performance_bundle is not None:
        return performance_bundle
    impact_bundle = _render_veusz_impact_bundle(
        source_input or input_path,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if impact_bundle is not None:
        return impact_bundle
    mechanical_bundle = _render_veusz_mechanical_bundle(
        input_path,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if mechanical_bundle is not None:
        return mechanical_bundle
    dsc_bundle = _render_veusz_dsc_bundle(
        input_path,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if dsc_bundle is not None:
        return dsc_bundle
    bundle = _render_veusz_sweep_bundle(
        input_path,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if bundle is not None:
        return bundle
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


def _compact_auto_split_options(options: dict[str, Any]) -> dict[str, Any]:
    updated = dict(options)
    size = str(updated.get("size") or "").strip().lower()
    if size.endswith("x110"):
        updated["size"] = f"{size.removesuffix('x110')}x55"
    return updated
