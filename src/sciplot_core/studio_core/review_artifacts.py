"""Run Studio QA and write analysis, review, and revision artifacts."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.qa import run_qa

from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.figure_set_state import (
    _figure_set_export_review_note,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_path,
)


def _run_studio_qa(
    output_dir: Path,
    *,
    publication_profile: dict[str, Any] | None = None,
    strict_publication: bool = False,
    veusz_documents: list[Path] | None = None,
) -> dict[str, Any]:
    try:
        qa = run_qa(
            output_dir,
            publication_profile=publication_profile,
            strict_publication=strict_publication,
            veusz_documents=veusz_documents,
        )
        layout_documents: list[dict[str, Any]] = []
        critical_issues: list[dict[str, Any]] = []
        for document_path in veusz_documents or []:
            spec_path = _veusz_spec_path(document_path)
            spec = _read_json(spec_path) if spec_path.exists() else {}
            issues = [
                item for item in spec.get("layout_issues", []) if isinstance(item, dict)
            ]
            layout_documents.append(
                {
                    "document": str(document_path),
                    "spec": str(spec_path),
                    "issues": json_safe(issues),
                }
            )
            critical_issues.extend(
                {"document": str(document_path), **item}
                for item in issues
                if str(item.get("severity") or "").casefold() == "critical"
            )
        qa["studio_layout"] = {
            "kind": "sciplot_studio_layout_qa",
            "status": "failed" if critical_issues else "passed",
            "documents": layout_documents,
            "critical_issues": json_safe(critical_issues),
        }
        if critical_issues:
            qa["status"] = "failed"
            qa["reason"] = "Critical exact-current Veusz layout issue(s): " + ", ".join(
                sorted({str(item.get("id") or "unknown") for item in critical_issues})
            )
        return qa
    except ValueError as exc:
        return {
            "status": "failed",
            "reason": str(exc),
            "pdf_count": 0,
            "pdfs": [],
            "goldens_checked": 0,
            "goldens_skipped": [],
        }


def _studio_layout_quality_from_spec(document_path: Path) -> dict[str, Any]:
    spec_path = _veusz_spec_path(document_path)
    spec = _read_json(spec_path) if spec_path.exists() else {}
    series = spec.get("series") if isinstance(spec.get("series"), list) else []
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
    y_axis = axes.get("y") if isinstance(axes.get("y"), dict) else {}
    issues = [item for item in spec.get("layout_issues", []) if isinstance(item, dict)]
    autofixes = [
        str(item) for item in spec.get("autofixes_applied", []) if isinstance(item, str)
    ]
    return {
        "kind": "sciplot_studio_layout_quality",
        "review_mode": "native_veusz_editor",
        "needs_ai_intervention": any(
            item.get("severity") == "critical" for item in issues
        ),
        "issue_ids": sorted(
            {str(item["id"]) for item in issues if isinstance(item.get("id"), str)}
        ),
        "autofixes_applied": sorted(set(autofixes)),
        "summaries": [
            {
                "kind": "sciplot_veusz_layout_summary",
                "render_engine": "veusz",
                "qa_target": "veusz_export",
                "template": spec.get("template"),
                "document": str(document_path),
                "spec": str(spec_path),
                "series_count": len(series),
                "requested_size_mm": spec.get("size_mm")
                if isinstance(spec.get("size_mm"), list)
                else [],
                "figure_size_mm": spec.get("size_mm")
                if isinstance(spec.get("size_mm"), list)
                else [],
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
        ],
    }


def _studio_visual_presentation_transforms(document_path: Path) -> list[dict[str, Any]]:
    spec_path = _veusz_spec_path(document_path)
    spec = _read_json(spec_path) if spec_path.exists() else {}
    return [
        dict(item)
        for item in spec.get("visual_data_transforms", [])
        if isinstance(item, dict)
    ]


def _write_studio_analysis_report(
    output_dir: Path,
    *,
    request: dict[str, Any],
    document_path: Path,
    figures: list[str],
    analysis_metrics: list[dict[str, Any]],
    figure_set_export_scope: dict[str, Any] | None = None,
) -> None:
    notes = list(
        request.get("review_notes")
        if isinstance(request.get("review_notes"), list)
        else []
    )
    if figure_set_export_scope is not None:
        scope_note = _figure_set_export_review_note(figure_set_export_scope)
        if scope_note not in [str(value) for value in notes]:
            notes.append(scope_note)
    lines = [
        "# SciPlot Studio Export",
        "",
        "- Route: `studio`",
        "- Engine: `veusz`",
        f"- Document: `{document_path}`",
        f"- Figures: {len(figures)}",
        "",
        "## Analysis Metrics",
        "",
    ]
    if analysis_metrics:
        for item in analysis_metrics:
            value = item.get("value", "")
            unit = str(item.get("unit") or "").strip()
            status = str(item.get("status") or "ok")
            suffix = f" {unit}" if unit else ""
            lines.append(f"- `{item.get('metric')}`: {value}{suffix} ({status})")
            reason = str(item.get("reason") or "").strip()
            if reason:
                lines.append(f"  - {reason}")
    else:
        lines.append("- No deterministic rule metrics were registered for this export.")
    lines.extend(
        [
            "",
            "## Review Notes",
            "",
            *(f"- {note}" for note in notes),
        ]
    )
    if not notes:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_studio_review_html(output_dir: Path, *, manifest: dict[str, Any]) -> None:
    figures = [
        Path(path) for path in manifest.get("figures", []) if isinstance(path, str)
    ]
    figure_items = []
    for figure in figures:
        rel = (
            figure.relative_to(output_dir)
            if figure.exists() and figure.is_relative_to(output_dir)
            else figure
        )
        label = escape(str(rel))
        if figure.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            figure_items.append(
                f'<li><a href="{label}">{label}</a><br><img src="{label}" alt="{label}"></li>'
            )
        else:
            figure_items.append(f'<li><a href="{label}">{label}</a></li>')
    request = (
        manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    )
    notes = (
        request.get("review_notes")
        if isinstance(request.get("review_notes"), list)
        else []
    )
    figure_set_export_scope = (
        manifest.get("figure_set_export_scope")
        if isinstance(manifest.get("figure_set_export_scope"), dict)
        else None
    )
    if figure_set_export_scope is not None:
        scope_note = _figure_set_export_review_note(figure_set_export_scope)
        if scope_note not in [str(value) for value in notes]:
            notes = [*notes, scope_note]
    note_items = [f"<li>{escape(str(note))}</li>" for note in notes] or [
        "<li>No review notes supplied.</li>"
    ]
    revision_brief = manifest.get("revision_brief")
    html = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>SciPlot Studio Review</title>",
            "<style>",
            "body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}",
            "img{max-width:720px;border:1px solid #ddd}",
            "</style>",
            "</head>",
            "<body>",
            "<h1>SciPlot Studio Review</h1>",
            "<p>Route: <code>studio</code>; engine: <code>Veusz</code>.</p>",
            "<h2>Review Notes</h2>",
            "<ul>",
            *note_items,
            "</ul>",
            "<h2>Figures</h2>",
            "<ul>",
            *(figure_items or ["<li>No figures were exported.</li>"]),
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


def _write_studio_revision_brief(output_dir: Path, *, manifest: dict[str, Any]) -> str:
    figures = [
        Path(path) for path in manifest.get("figures", []) if isinstance(path, str)
    ]
    figure_lines = []
    for figure in figures:
        rel = (
            figure.relative_to(output_dir)
            if figure.exists() and figure.is_relative_to(output_dir)
            else figure
        )
        figure_lines.append(f"- `{rel}`")
    qa = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
    studio = manifest.get("studio") if isinstance(manifest.get("studio"), dict) else {}
    lines = [
        "# SciPlot Studio Revision Brief",
        "",
        "Use this brief for optional assisted repair of the SciPlot request or Veusz document bridge.",
        "",
        "## Run",
        "",
        f"- Output: `{output_dir}`",
        f"- Request: `{manifest.get('request_path')}`",
        "- Route: `studio`",
        f"- Veusz document: `{studio.get('document') or ''}`",
        f"- QA: `{qa.get('status') or 'unknown'}`",
        "",
        "## Figures",
        "",
        *(figure_lines or ["- No figures were recorded."]),
        "",
        "## Assisted Repair Request",
        "",
        "请按这些修改意见调整 SciPlot 数据识别、请求生成、数据整理或 Veusz 文档桥接，然后重新导出：",
        "",
        "- 数据导入/预处理：",
        "- 自动生成的 Veusz 对象：",
        "- 需要保留的 Veusz 手工编辑：",
        "- 导出格式或 QA：",
        "- 其他：",
    ]
    (output_dir / "revision_brief.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return "revision_brief.md"
