"""Track the document path and reject stale project contexts."""

from __future__ import annotations

from typing import Any
from sciplot_gui.studio_project_status import (
    _status_text,
)
from sciplot_gui.window_context import resolved_window_document_path


class ContextMixin:
    @property
    def mode(self) -> str:
        return "project" if self.project_dir is not None else "standalone_vsz"

    def _document_context_blocker(self) -> str | None:
        current = resolved_window_document_path(self.window)
        if current == self.document_path:
            return None
        current_label = str(current) if current is not None else "an unsaved document"
        return (
            "This Veusz window now points to "
            f"{current_label}, but SciPlot Project remains bound to "
            f"{self.document_path}. Close this window and reopen the new VSZ "
            "so SciPlot can bind a fresh exact-current project context. The "
            "old project path will not be overwritten."
        )

    def _document_context_status(self, message: str) -> dict[str, Any]:
        status = dict(self.status_snapshot)
        workflow = (
            dict(status.get("workflow"))
            if isinstance(status.get("workflow"), dict)
            else {}
        )
        workflow.update(
            {
                "state": "document_context_changed",
                "audit_state": "blocked",
                "result_ready": False,
                "ready_to_use": False,
                "message": (
                    "The Veusz document context changed. Reopen this VSZ before "
                    "using prior results or exporting."
                ),
            }
        )
        qa = dict(status.get("qa")) if isinstance(status.get("qa"), dict) else {}
        for key in tuple(qa):
            if key == "current" or key.endswith("_current"):
                qa[key] = False
        qa.update(
            {
                "status": "stale_for_document_context",
                "ready_to_use": False,
                "current_document": False,
                "document_hash_current": False,
                "artifact_qa_current": False,
                "exports_current": False,
                "qa_report_current": False,
                "state": "document_context_changed",
            }
        )
        provenance = (
            dict(status.get("provenance"))
            if isinstance(status.get("provenance"), dict)
            else {}
        )
        for key in tuple(provenance):
            if (
                key == "current"
                or key == "complete"
                or key.endswith("_current")
                or key.endswith("_complete")
            ):
                provenance[key] = False
        provenance.update(
            {
                "status": "document_context_changed",
                "complete": False,
                "full_project_evidence_current": False,
                "primary_figure_evidence_current": False,
                "project_delivery_current": False,
                "delivery_scope_known": False,
            }
        )
        results = (
            dict(status.get("results"))
            if isinstance(status.get("results"), dict)
            else {}
        )
        for key, value in tuple(results.items()):
            target = dict(value) if isinstance(value, dict) else {}
            target["current"] = False
            target["available"] = False
            results[key] = target
        project = (
            dict(status.get("project"))
            if isinstance(status.get("project"), dict)
            else status.get("project")
        )
        if isinstance(project, dict):
            project["request_snapshot_current"] = False
        window_document = resolved_window_document_path(self.window)
        status.update(
            {
                "kind": "sciplot_studio_project_status",
                "version": 1,
                "mode": self.mode,
                "state": "document_context_changed",
                "ready_to_use": False,
                "workflow": workflow,
                "project": project,
                "qa": qa,
                "provenance": provenance,
                "results": results,
                "document_context": {
                    "state": "document_context_changed",
                    "bound_document": str(self.document_path),
                    "window_document": str(window_document)
                    if window_document is not None
                    else None,
                    "message": message,
                },
            }
        )
        return status

    def handle_document_context_changed(self) -> dict[str, Any] | None:
        message = self._document_context_blocker()
        if message is None:
            return None
        status = self._document_context_status(message)
        self._publish_status(status)
        self.status_view.setPlainText(
            f"{_status_text(status)}\n\nDocument context changed: {message}"
        )
        return status
