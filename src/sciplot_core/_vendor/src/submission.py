from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from src import plot_style
from src.plot_contract import template_contract, validation_rule
from src.rendering.models import QAReport, RenderOptions, SubmissionCheck, SubmissionReport

_SAFE_PALETTES = {
    "jama_editorial",
    "npg_modern",
    "tol_bright",
}
_CURVE_TEMPLATES = {"curve", "point_line", "scatter", "bubble_scatter"}
_PDF_SUFFIXES = {".pdf"}
_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}


def _dedupe_text(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        ordered.append(item)
        seen.add(item)
    return tuple(ordered)


def _status_rank(status: str) -> int:
    return {
        "critical": 4,
        "warning": 3,
        "advisory": 2,
        "pending": 1,
        "pass": 0,
    }.get(status, 0)


def _severity_to_status(severity: str) -> str:
    if severity == "critical":
        return "critical"
    if severity == "warning":
        return "warning"
    return "advisory"


def _report_readiness(
    checks: Sequence[SubmissionCheck],
    blockers: Sequence[str],
) -> str:
    if blockers:
        return "blocked"
    if any(check.status in {"critical", "warning", "advisory", "pending"} for check in checks):
        return "review"
    return "ready"


def _report_summary(
    context: str,
    readiness: str,
    blockers: Sequence[str],
    checks: Sequence[SubmissionCheck],
) -> str:
    if readiness == "blocked":
        return f"{context.title()} is blocked by {len(blockers)} hard validation issue(s)."
    review_count = sum(check.status in {"critical", "warning", "advisory"} for check in checks)
    pending_count = sum(check.status == "pending" for check in checks)
    if readiness == "review":
        if review_count and pending_count:
            return (
                f"{context.title()} can proceed, with {review_count} editorial signal(s) "
                f"and {pending_count} follow-up check(s) still worth reviewing."
            )
        if review_count:
            return f"{context.title()} can proceed, with {review_count} editorial signal(s) worth reviewing."
        return f"{context.title()} can proceed, but a few checks only finalize after rendering/export."
    return f"{context.title()} is submission-ready under the current contract and style preset."


def _style_checks(style_preset: str | None) -> list[SubmissionCheck]:
    if not style_preset:
        return []
    style_spec = plot_style.get_style_spec(style_preset)
    minimum_font = min(style_spec.typography.font_size_pt, style_spec.typography.legend_font_size_pt)
    checks = [
        SubmissionCheck(
            id="style_preset",
            status="pass",
            message=style_spec.preset_note,
            metric_value=style_preset,
            target="public_style",
            source="style",
        )
    ]
    checks.append(
        SubmissionCheck(
            id="font_floor",
            status="pass" if minimum_font >= 5.0 else "warning",
            message=(
                "Base text sizes stay above the 5 pt submission floor."
                if minimum_font >= 5.0
                else "One of the configured text sizes fell below the 5 pt submission floor."
            ),
            metric_value=round(minimum_font, 2),
            target=5.0,
            source="style",
        )
    )
    return checks


def _palette_check(palette_preset: str | None) -> SubmissionCheck | None:
    if not palette_preset:
        return None
    return SubmissionCheck(
        id="palette_accessibility",
        status="pass" if palette_preset in _SAFE_PALETTES else "advisory",
        message=(
            "Selected palette stays inside the current accessibility-safe preset list."
            if palette_preset in _SAFE_PALETTES
            else "Selected palette should be checked for accessibility before submission."
        ),
        metric_value=palette_preset,
        target="safe_palette",
        source="palette",
    )


def _axis_frame_check(template: str) -> SubmissionCheck | None:
    hard_rules = set(template_contract(template).hard_rules)
    if "single_panel_axis_frame" in hard_rules:
        rule = validation_rule("single_panel_axis_frame")
        return SubmissionCheck(
            id="axis_frame_contract",
            status="pass",
            message=rule.description,
            target=rule.label,
            source="contract",
        )
    if "heatmap_main_frame" in hard_rules:
        rule = validation_rule("heatmap_main_frame")
        return SubmissionCheck(
            id="axis_frame_contract",
            status="pass",
            message=rule.description,
            target=rule.label,
            source="contract",
        )
    if "wide_nmr_horizontal_alignment" in hard_rules:
        rule = validation_rule("wide_nmr_horizontal_alignment")
        return SubmissionCheck(
            id="axis_frame_contract",
            status="pass",
            message=rule.description,
            target=rule.label,
            source="contract",
        )
    return None


def _multi_output_check(output_filenames: Sequence[str]) -> SubmissionCheck:
    count = len(output_filenames)
    if count > 1:
        return SubmissionCheck(
            id="multi_output_bundle",
            status="advisory",
            message=f"This run exports {count} coordinated PDF files.",
            metric_value=count,
            target=1,
            source="export",
        )
    return SubmissionCheck(
        id="multi_output_bundle",
        status="pass",
        message="This run exports a single PDF figure.",
        metric_value=count,
        target=1,
        source="export",
    )


def _vector_pdf_check() -> SubmissionCheck:
    return SubmissionCheck(
        id="vector_output",
        status="pass",
        message="The render/export path stays on vector PDF output by default.",
        metric_value="pdf",
        target="vector_pdf",
        source="export",
    )


def _find_worst_issue(
    qa_reports: Sequence[QAReport | None],
    issue_ids: set[str],
):
    worst_issue = None
    for report in qa_reports:
        if report is None:
            continue
        for issue in report.issues:
            if issue.id not in issue_ids:
                continue
            if worst_issue is None or _status_rank(_severity_to_status(issue.severity)) > _status_rank(
                _severity_to_status(worst_issue.severity)
            ):
                worst_issue = issue
    return worst_issue


def _qa_issue_check(
    *,
    check_id: str,
    qa_reports: Sequence[QAReport | None],
    issue_ids: set[str],
    pass_message: str,
    pending_message: str,
) -> SubmissionCheck:
    issue = _find_worst_issue(qa_reports, issue_ids)
    if issue is not None:
        return SubmissionCheck(
            id=check_id,
            status=_severity_to_status(issue.severity),
            message=issue.message,
            metric_value=issue.metric_value,
            target=issue.target,
            source="qa",
        )
    if any(report is not None for report in qa_reports):
        return SubmissionCheck(
            id=check_id,
            status="pass",
            message=pass_message,
            source="qa",
        )
    return SubmissionCheck(
        id=check_id,
        status="pending",
        message=pending_message,
        source="qa",
    )


def build_render_submission_report(
    *,
    context: str,
    template: str,
    options: RenderOptions,
    output_filenames: Sequence[str] = (),
    qa_reports: Sequence[QAReport | None] = (),
    blockers: Sequence[str] = (),
    warnings: Sequence[str] = (),
) -> SubmissionReport:
    checks: list[SubmissionCheck] = []
    checks.extend(_style_checks(options.style_preset))
    palette_check = _palette_check(options.palette_preset)
    if palette_check is not None:
        checks.append(palette_check)
    axis_frame_check = _axis_frame_check(template)
    if axis_frame_check is not None:
        checks.append(axis_frame_check)
    checks.append(_multi_output_check(output_filenames))
    checks.append(_vector_pdf_check())

    if template in _CURVE_TEMPLATES:
        checks.append(
            _qa_issue_check(
                check_id="legend_footprint",
                qa_reports=qa_reports,
                issue_ids={"legend_footprint"},
                pass_message="Legend footprint stays inside the compact panel target.",
                pending_message="Legend footprint finalizes after preview/export renders the figure.",
            )
        )
        checks.append(
            _qa_issue_check(
                check_id="stroke_hierarchy",
                qa_reports=qa_reports,
                issue_ids={"stroke_hierarchy"},
                pass_message="Line and tick hierarchy stays separated enough for a compact panel.",
                pending_message="Stroke hierarchy finalizes after preview/export renders the figure.",
            )
        )
    if template == "heatmap":
        checks.append(
            _qa_issue_check(
                check_id="palette_uniformity",
                qa_reports=qa_reports,
                issue_ids={"palette_uniformity"},
                pass_message="Heatmap palette stays inside the approved perceptual-uniform list.",
                pending_message="Heatmap palette checks finalize after preview/export renders the figure.",
            )
        )

    for index, warning in enumerate(_dedupe_text(warnings), start=1):
        checks.append(
            SubmissionCheck(
                id=f"preflight_warning_{index}",
                status="advisory",
                message=warning,
                source="preflight",
            )
        )

    deduped_blockers = _dedupe_text(blockers)
    readiness = _report_readiness(checks, deduped_blockers)
    return SubmissionReport(
        context=context,
        readiness=readiness,
        summary=_report_summary(context, readiness, deduped_blockers, checks),
        template=template,
        style_preset=options.style_preset,
        palette_preset=options.palette_preset,
        output_count=len(output_filenames),
        output_filenames=tuple(output_filenames),
        blockers=deduped_blockers,
        checks=tuple(checks),
    )


__all__ = [
    "build_render_submission_report",
]
