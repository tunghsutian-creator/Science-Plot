"""Summarize terminal Veusz layout and QA evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.split import (
    SUPPORTED_SPLIT_TEMPLATES,
)


def _veusz_layout_report(
    *,
    template: str,
    spec: dict[str, Any],
    document: Path,
    outputs: list[Path],
    split_panel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    size = spec.get("size_mm") if isinstance(spec.get("size_mm"), list) else []
    series = spec.get("series") if isinstance(spec.get("series"), list) else []
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
    y_axis = axes.get("y") if isinstance(axes.get("y"), dict) else {}
    summary: dict[str, Any] = {
        "kind": "sciplot_veusz_layout_summary",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "template": template,
        "document": str(document),
        "outputs": [str(path) for path in outputs],
        "series_count": len(series),
        "requested_size_mm": size,
        "figure_size_mm": size,
        "axes": [
            {
                "x_label": x_axis.get("label"),
                "y_label": y_axis.get("label"),
                "x_bounds": [x_axis.get("min"), x_axis.get("max")],
                "y_bounds": [y_axis.get("min"), y_axis.get("max")],
                "x_ticks": x_axis.get("ticks") or [],
                "y_ticks": y_axis.get("ticks") or [],
                "legend": spec.get("legend", {}),
            }
        ],
    }
    categorical = (
        spec.get("categorical") if isinstance(spec.get("categorical"), dict) else None
    )
    if categorical is not None:
        categorical_kind = str(categorical.get("presentation_kind") or "")
        summary_key = (
            "categorical_components"
            if categorical_kind == "stacked_components"
            else "categorical_replicates"
        )
        summary[summary_key] = {
            "presentation_kind": categorical.get("presentation_kind"),
            "summary_statistic": categorical.get("summary_statistic"),
            "native_veusz_boxplot": categorical.get("native_veusz_boxplot"),
            "raw_values_preserved": categorical.get("raw_values_preserved"),
            "raw_replicate_count": categorical.get("raw_replicate_count"),
            "component_labels": categorical.get("component_labels") or [],
            "component_value_count": categorical.get("component_value_count"),
            "group_count": len(categorical.get("groups") or []),
            "insufficient_replicate_groups": categorical.get(
                "insufficient_replicate_groups"
            )
            or [],
        }
    if split_panel is not None:
        summary["split_panel"] = split_panel
    issues: list[dict[str, Any]] = [
        item for item in spec.get("layout_issues", []) if isinstance(item, dict)
    ]
    try:
        from sciplot_core.contract import load_plot_contract, qa_profile

        contract = load_plot_contract()
        alignment_profile = qa_profile("alignment")
        tolerance_mm = float(alignment_profile.get("frame_tolerance_mm", 0.05))
        performance = (
            spec.get("performance_comparison")
            if isinstance(spec.get("performance_comparison"), dict)
            else None
        )
        performance_frame = (
            spec.get("frame_alignment")
            if performance is not None and isinstance(spec.get("frame_alignment"), dict)
            else {}
        )
        performance_margins = (
            performance_frame.get("margins_mm")
            if isinstance(performance_frame.get("margins_mm"), dict)
            else {}
        )
        expected_margins = (
            {
                side: float(performance_margins[side])
                for side in ("left", "right", "bottom", "top")
            }
            if all(
                side in performance_margins
                for side in ("left", "right", "bottom", "top")
            )
            else {
                "left": float(contract.global_frame.left_margin_mm),
                "right": float(contract.global_frame.right_margin_mm),
                "bottom": float(contract.global_frame.bottom_margin_mm),
                "top": float(contract.global_frame.top_margin_mm),
            }
        )
        style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
        actual_margins = (
            style.get("margins_mm") if isinstance(style.get("margins_mm"), dict) else {}
        )
        margin_errors = {
            side: abs(float(actual_margins.get(side, float("inf"))) - expected)
            for side, expected in expected_margins.items()
        }
        frame_alignment = {
            "mode": "fixed_mm",
            "status": (
                "aligned"
                if all(error <= tolerance_mm for error in margin_errors.values())
                else "misaligned"
            ),
            "expected_margins_mm": expected_margins,
            "actual_margins_mm": actual_margins,
            "margin_error_mm": margin_errors,
            "tolerance_mm": tolerance_mm,
            "outside_legend_allowed": False,
        }
        summary["frame_alignment"] = frame_alignment
        if performance is not None:
            summary["performance_comparison"] = {
                "layout": performance.get("layout"),
                "normalization": performance.get("normalization"),
                "sample_count": performance.get("sample_count"),
                "reference_count": performance.get("reference_count"),
            }
        if frame_alignment["status"] != "aligned":
            issues.append(
                {
                    "id": "fixed_publication_frame_misaligned",
                    "severity": "critical",
                    "message": "The Veusz graph margins drifted from the fixed publication frame.",
                    "margin_error_mm": margin_errors,
                    "tolerance_mm": tolerance_mm,
                }
            )
        legend = spec.get("legend") if isinstance(spec.get("legend"), dict) else {}
        if str(legend.get("mode") or "").strip().casefold() in {
            "outside",
            "outside_right",
        }:
            issues.append(
                {
                    "id": "outside_legend_forbidden",
                    "severity": "critical",
                    "message": "Outside legends are disabled because they break the fixed publication frame.",
                }
            )
    except (TypeError, ValueError):
        issues.append(
            {
                "id": "fixed_publication_frame_unverifiable",
                "severity": "critical",
                "message": "The generated Veusz spec did not expose verifiable physical graph margins.",
            }
        )
    if (
        split_panel is None
        and template in SUPPORTED_SPLIT_TEMPLATES
        and len(series) >= 24
        and len(size) >= 2
        and float(size[1]) >= 100.0
    ):
        issues.append(
            {
                "id": "stack_peak_too_small",
                "severity": "warning",
                "message": "Dense stacked Veusz output should be split into readable panels.",
            }
        )
    return {
        "kind": "sciplot_veusz_qa_report",
        "engine": "veusz",
        "issues": issues,
        "autofixes_applied": [
            str(item)
            for item in spec.get("autofixes_applied", [])
            if isinstance(item, str)
        ],
        "layout_summary": summary,
    }
