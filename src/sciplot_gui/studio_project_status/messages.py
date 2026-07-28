"""Format export and compact dock status messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_gui.studio_project_status.workflow_status import (
    _workflow_status,
)


def export_result_message(
    payload: dict[str, Any],
) -> tuple[str, str, str]:
    if payload.get("ready_to_use") is True and payload.get("status") == "passed":
        if payload.get("scope") == "standalone_exact_current_export":
            receipt = (
                payload.get("standalone_export")
                if isinstance(payload.get("standalone_export"), dict)
                else {}
            )
            return (
                "information",
                "SciPlot exact-current export",
                "PDF/TIFF export and artifact QA passed.\n\n"
                f"Receipt: {receipt.get('receipt_path')}\n\n"
                "This standalone receipt does not establish raw-source, "
                "transform-lineage, or portable-project provenance.",
            )
        run = (
            payload.get("studio_run")
            if isinstance(payload.get("studio_run"), dict)
            else {}
        )
        figure_scope = (
            payload.get("figure_set_export_scope")
            if isinstance(payload.get("figure_set_export_scope"), dict)
            else {}
        )
        scope_note = (
            "\n\nFigure set: every registered VSZ and its matching "
            "PDF/TIFF pair are bound to this one delivery."
            if figure_scope.get("status") == "full_figure_set_exact_current"
            else ""
        )
        delivery_summary = (
            "All figure PDF/TIFF pairs, QA, and the portable delivery passed."
            if payload.get("scope") == "full_figure_set_project_delivery"
            else "PDF/TIFF, QA, and the portable project delivery passed."
        )
        return (
            "information",
            "SciPlot project export",
            f"{delivery_summary}\n\n"
            f"Review: {run.get('review_html')}\n"
            f"Output: {run.get('output')}"
            f"{scope_note}",
        )
    evidence = (
        payload.get("standalone_export")
        if isinstance(payload.get("standalone_export"), dict)
        else payload.get("studio_run")
        if isinstance(payload.get("studio_run"), dict)
        else {}
    )
    qa = (
        evidence.get("artifact_qa")
        if isinstance(evidence.get("artifact_qa"), dict)
        else evidence.get("qa")
        if isinstance(evidence.get("qa"), dict)
        else {}
    )
    return (
        "warning",
        "SciPlot export needs review",
        "Files may have been written, but SciPlot did not mark this export "
        "ready.\n\n"
        f"State: {payload.get('state') or evidence.get('state') or 'failed'}\n"
        f"QA: {qa.get('status') or 'not_run'}\n"
        f"Evidence: {evidence.get('receipt_path') or evidence.get('output')}",
    )


def _short_hash(value: object) -> str:
    text = str(value or "")
    return f"{text[:12]}…" if len(text) > 12 else text or "—"


def _status_text(status: dict[str, Any]) -> str:
    document = status["document"]
    source = status["source"]
    mapping = status["mapping"]
    provenance = status["provenance"]
    qa = status["qa"]
    workflow = (
        status.get("workflow")
        if isinstance(status.get("workflow"), dict)
        else _workflow_status(status)
    )
    project = status.get("project")
    mode_label = (
        "Project secondary — standalone exact-current receipt"
        if status.get("document_scope") == "project_secondary_standalone_receipt"
        else "Project package"
        if status["mode"] == "project"
        else "Standalone VSZ"
    )
    lines = [
        f"Mode: {mode_label}",
        f"Result: {workflow.get('state')} — {workflow.get('message')}",
        f"Audit: {workflow.get('audit_state')}",
    ]
    if isinstance(project, dict):
        lines.extend(
            [
                f"Project: {project.get('name')}",
                f"Request: {project.get('request_status')} "
                f"(snapshot current: "
                f"{project.get('request_snapshot_current') is True})",
                f"Rule / template: {project.get('rule_id') or '—'} / "
                f"{project.get('template') or '—'}",
            ]
        )
    lines.extend(
        [
            "",
            f"Document: {Path(str(document['path'])).name}",
            f"Live state: {'modified, not saved' if document['modified'] else 'saved'} "
            f"(revision {document['revision']})",
            f"Saved VSZ SHA-256: {_short_hash(document.get('saved_sha256'))}",
            f"Live render SHA-256: {_short_hash(document.get('live_render_sha256'))}",
            "",
            f"Source: {source.get('status')} / {source.get('audit_status')}",
            f"Source path: {source.get('path') or 'not established'}",
            f"Source SHA-256: {_short_hash(source.get('sha256'))}",
            f"Mapping: {mapping.get('status')} "
            f"(coverage: {mapping.get('coverage_status')})",
            f"Project evidence: {provenance.get('status')}",
            f"Artifact QA: {qa.get('status')} "
            f"(QA result: {qa.get('artifact_status')}, "
            f"exports current: {qa.get('exports_current') is True})",
            f"Evidence: {qa.get('evidence') or 'not run'}",
        ]
    )
    return "\n".join(lines)
