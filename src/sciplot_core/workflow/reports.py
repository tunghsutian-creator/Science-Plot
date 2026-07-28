"""Write run reports and summarize renderer layout quality."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe


def _write_render_report(
    output_dir: Path, *, request: dict[str, Any], result: dict[str, Any]
) -> None:
    lines = [
        "# SciPlot Run",
        "",
        "- Route: `render`",
        f"- Template: `{result['template']}`",
        f"- Figures: {len(result.get('outputs', []))}",
        "",
        "## Review Notes",
        "",
    ]
    notes = request.get("review_notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_auto_report(
    output_dir: Path,
    *,
    request: dict[str, Any],
    result: dict[str, Any],
    semantic: dict[str, Any],
    final_recipe: str | None,
) -> None:
    lines = [
        "# SciPlot Run",
        "",
        "- Route: `auto`",
        f"- Semantic family: `{semantic['semantic_family']}`",
        f"- Final recipe: `{final_recipe or 'direct_render'}`",
        f"- Template: `{result['template']}`",
        f"- Figures: {len(result.get('outputs', []))}",
        "",
        "## Semantic Reason",
        "",
        f"- {semantic.get('reason', 'No semantic reason recorded.')}",
        "",
        "## Review Notes",
        "",
    ]
    notes = request.get("review_notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_review_html(output_dir: Path, *, manifest: dict[str, Any]) -> None:
    figures = [Path(path) for path in manifest.get("figures", [])]
    notes = manifest.get("request", {}).get("review_notes") or []
    revision_brief = manifest.get("revision_brief")
    figure_items = []
    for figure in figures:
        rel = (
            figure.relative_to(output_dir)
            if figure.is_relative_to(output_dir)
            else figure
        )
        label = escape(str(rel))
        if figure.suffix.lower() == ".png":
            figure_items.append(
                f'<li><a href="{label}">{label}</a><br><img src="{label}" alt="{label}"></li>'
            )
        else:
            figure_items.append(f'<li><a href="{label}">{label}</a></li>')
    note_items = [f"<li>{escape(str(note))}</li>" for note in notes] or [
        "<li>No review notes supplied.</li>"
    ]
    html = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>SciPlot Review</title>",
            "<style>",
            "body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}",
            "img{max-width:720px;border:1px solid #ddd}",
            "</style>",
            "</head>",
            "<body>",
            "<h1>SciPlot Review</h1>",
            f"<p>Route: <code>{escape(str(manifest.get('route')))}</code></p>",
            "<h2>Review Notes</h2>",
            "<ul>",
            *note_items,
            "</ul>",
            "<h2>Figures</h2>",
            "<ul>",
            *figure_items,
            "</ul>",
            "<h2>Revision</h2>",
            "<ul>",
            (
                f'<li><a href="{escape(str(revision_brief))}">Revision brief for assisted repair</a></li>'
                if isinstance(revision_brief, str) and revision_brief
                else "<li>No revision brief was generated.</li>"
            ),
            "</ul>",
            "</body>",
            "</html>",
        ]
    )
    (output_dir / "review.html").write_text(html + "\n", encoding="utf-8")


def _layout_quality_from_result(result: dict[str, Any]) -> dict[str, Any]:
    reports = result.get("qa_reports") if isinstance(result, dict) else None
    summaries: list[dict[str, Any]] = []
    issue_ids: list[str] = []
    autofixes: list[str] = []
    needs_ai_intervention = False
    if isinstance(reports, list):
        for report in reports:
            if not isinstance(report, dict):
                continue
            for issue in report.get("issues", []):
                if isinstance(issue, dict) and isinstance(issue.get("id"), str):
                    issue_ids.append(str(issue["id"]))
                    if issue.get("severity") == "critical":
                        needs_ai_intervention = True
            for item in report.get("autofixes_applied", []):
                if isinstance(item, str):
                    autofixes.append(item)
            summary = report.get("layout_summary")
            if isinstance(summary, dict):
                summaries.append(summary)
                if summary.get("needs_ai_intervention") is True:
                    needs_ai_intervention = True
    payload = {
        "review_mode": "structured_qa_only",
        "needs_ai_intervention": needs_ai_intervention,
        "issue_ids": sorted(set(issue_ids)),
        "autofixes_applied": sorted(set(autofixes)),
        "summaries": summaries,
    }
    split_plan = result.get("split_plan")
    if isinstance(split_plan, dict):
        payload["split_plan"] = json_safe(split_plan)
    auto_split = result.get("auto_split")
    if isinstance(auto_split, dict):
        payload["auto_split"] = json_safe(auto_split)
        if auto_split.get("applied") is True:
            payload["autofixes_applied"] = sorted(
                set([*payload["autofixes_applied"], "split_stacked_figure_auto"])
            )
    return payload


def _layout_summary_height_mm(layout_quality: dict[str, Any]) -> float | None:
    heights: list[float] = []
    summaries = (
        layout_quality.get("summaries")
        if isinstance(layout_quality.get("summaries"), list)
        else []
    )
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        for key in ("requested_size_mm", "figure_size_mm"):
            value = summary.get(key)
            if not isinstance(value, list | tuple) or len(value) < 2:
                continue
            try:
                heights.append(float(value[1]))
            except (TypeError, ValueError):
                continue
    return max(heights) if heights else None
