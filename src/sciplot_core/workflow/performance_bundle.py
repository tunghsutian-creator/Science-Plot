"""Render performance-comparison figure bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.materials_rules import (
    resolve_rule_template,
)
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
)
from sciplot_core.render import render_to_dir


def _render_veusz_performance_bundle(
    source_input: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    if str(request.get("rule_id") or "").strip() != "performance_comparison":
        return None
    requested_template = request.get("template")
    templates = (
        [
            resolve_rule_template(
                "performance_comparison",
                requested_template if isinstance(requested_template, str) else None,
            )
        ]
        if request.get("explicit_template_selection") is True
        else ["scatter", "polar_curve"]
    )
    combined: dict[str, list[Any]] = {
        "outputs": [],
        "exports": [],
        "qa_reports": [],
        "veusz_documents": [],
        "veusz_specs": [],
        "terminal_render_requests": [],
        "transform_steps": [],
    }
    figures_dir = output_dir / "figures"
    for template_id in templates:
        result = render_to_dir(
            source_input,
            template=template_id,
            output_dir=figures_dir / template_id,
            options=options,
            export_formats=export_formats,
            request_context={
                **request,
                "template": template_id,
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            },
        )
        for key in combined:
            values = result.get(key)
            if isinstance(values, list):
                combined[key].extend(values)
    return {
        "kind": "sciplot_veusz_render",
        "render_engine": "veusz",
        "template": "performance_comparison_figure_set",
        "export_formats": list(export_formats or DEFAULT_EXPORT_FORMATS_POLICY),
        **combined,
        "multi_metric_bundle": {
            "kind": "performance_comparison_figure_set",
            "templates": templates,
            "document_policy": "independent_single_page_vsz",
        },
    }
