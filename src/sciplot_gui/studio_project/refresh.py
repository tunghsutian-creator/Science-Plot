"""Refresh pure status and exact-current document audit state."""

from __future__ import annotations

from typing import Any
from sciplot_gui.studio_project_status import (
    _bind_mapping_to_artifact_qa,
    _finalize_status,
    _live_document_payload,
    _qa_display_status,
    _status_text,
    _workflow_status,
)

from sciplot_gui.studio_project.services import (
    _is_primary_figure_set_export_scope,
)
from sciplot_gui.studio_project.status_adapter import build_studio_project_status


class RefreshMixin:
    def _audit_failure_status(self, exc: Exception) -> dict[str, Any]:
        if self.status_snapshot:
            status = {
                **self.status_snapshot,
                "audit_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
            workflow = (
                dict(status.get("workflow"))
                if isinstance(status.get("workflow"), dict)
                else _workflow_status(status)
            )
            workflow["audit_state"] = "failed"
            status["workflow"] = workflow
        else:
            status = {
                "kind": "sciplot_studio_project_status",
                "version": 1,
                "mode": self.mode,
                "project": None,
                "document": _live_document_payload(
                    document_path=self.document_path,
                    document=self.document,
                    render_sha256=None,
                ),
                "source": {
                    "status": "audit_failed",
                    "path": None,
                    "audit_status": "audit_failed",
                },
                "mapping": {
                    "status": "audit_failed",
                    "coverage_status": "unknown",
                },
                "provenance": {
                    "status": "audit_failed",
                    "complete": False,
                    "full_project_evidence_current": False,
                },
                "qa": {
                    "status": "audit_failed",
                    "artifact_status": "not_run",
                    "artifact_qa_current": False,
                    "exports_current": False,
                    "evidence": None,
                },
                "audit_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        self.status_snapshot = status
        self.status_view.setPlainText(
            f"{_status_text(status)}\n\nAudit error: {type(exc).__name__}: {exc}"
        )
        self._update_controls(status)
        self.statusChanged.emit(status)
        return status

    def refresh(
        self,
        *,
        capture_render: bool = False,
        audit_source: bool = False,
    ) -> dict[str, Any]:
        context_status = self.handle_document_context_changed()
        if context_status is not None:
            return context_status
        render_sha256 = (
            self._current_render_sha256()
            if capture_render
            else self.status_snapshot.get("document", {}).get("live_render_sha256")
        )
        if self.status_snapshot:
            previous_revision = self.status_snapshot.get("document", {}).get("revision")
            if previous_revision != int(self.document.changeset):
                render_sha256 = None
        try:
            status = build_studio_project_status(
                document_path=self.document_path,
                document=self.document,
                project_dir=self.project_dir,
                request_path=self.request_path,
                render_sha256=render_sha256,
                audit_source=audit_source,
            )
        except Exception as exc:
            return self._audit_failure_status(exc)
        return self._publish_status(status)

    def _refresh_document_state(self) -> dict[str, Any]:
        context_status = self.handle_document_context_changed()
        if context_status is not None:
            return context_status
        if not self.status_snapshot:
            return self.refresh()
        previous_document = (
            self.status_snapshot.get("document")
            if isinstance(self.status_snapshot.get("document"), dict)
            else {}
        )
        previous_revision = previous_document.get("revision")
        current_revision = int(self.document.changeset)
        render_sha256 = (
            previous_document.get("live_render_sha256")
            if previous_revision == current_revision
            else None
        )
        live_document = _live_document_payload(
            document_path=self.document_path,
            document=self.document,
            render_sha256=(
                str(render_sha256) if isinstance(render_sha256, str) else None
            ),
            saved_sha256=(
                str(previous_document.get("saved_sha256"))
                if previous_document.get("saved_sha256")
                else None
            ),
        )
        status = {
            **self.status_snapshot,
            "document": live_document,
        }
        previous_qa = status.get("qa") if isinstance(status.get("qa"), dict) else {}
        qa = dict(previous_qa)
        if qa.get("evidence") is not None:
            evidence_hash = qa.get("evidence_document_sha256")
            document_hash_current = bool(
                live_document.get("modified") is False
                and live_document.get("saved_sha256")
                and evidence_hash
                and live_document.get("saved_sha256") == evidence_hash
            )
            current_document = bool(
                document_hash_current and qa.get("exports_current") is True
            )
            qa_status, artifact_qa_current = _qa_display_status(
                artifact_status=str(qa.get("artifact_status") or "not_run"),
                ready=qa.get("ready_to_use") is True,
                current_document=current_document,
                exports_current=qa.get("exports_current") is True,
            )
            qa.update(
                {
                    "status": qa_status,
                    "current_document": current_document,
                    "document_hash_current": document_hash_current,
                    "artifact_qa_current": artifact_qa_current,
                }
            )
        status["qa"] = qa
        if (
            status.get("mode") == "project"
            and status.get("document_scope") != "project_secondary_standalone_receipt"
        ):
            mapping = (
                status.get("mapping") if isinstance(status.get("mapping"), dict) else {}
            )
            mapping = _bind_mapping_to_artifact_qa(
                mapping,
                artifact_qa_current=qa.get("artifact_qa_current") is True,
            )
            status["mapping"] = mapping
            provenance = (
                dict(status.get("provenance"))
                if isinstance(status.get("provenance"), dict)
                else {}
            )
            mapping_current = mapping.get("status") in {
                "not_applied",
                "verified",
            }
            current_evidence = bool(
                provenance.get("run_evidence_complete") is True
                and provenance.get("source_current") is True
                and mapping_current
                and qa.get("artifact_qa_current") is True
            )
            figure_set_scope_status = str(
                provenance.get("figure_set_export_scope_status") or ""
            )
            full_figure_set_scope = bool(
                figure_set_scope_status in {"persisted", "recomputed_current_project"}
                and _is_primary_figure_set_export_scope(
                    provenance.get("figure_set_export_scope")
                )
            )
            full_project_scope = bool(
                figure_set_scope_status == "not_applicable" or full_figure_set_scope
            )
            delivery_scope_known = full_project_scope
            primary_current = bool(current_evidence and full_figure_set_scope)
            full_current = bool(current_evidence and full_project_scope)
            source = (
                status.get("source") if isinstance(status.get("source"), dict) else {}
            )
            audit_pending = bool(
                source.get("audit_status") == "not_computed"
                or mapping.get("status") == "audit_pending"
            )
            current_result_awaiting_audit = bool(
                provenance.get("run_evidence_complete") is True
                and qa.get("artifact_qa_current") is True
                and audit_pending
                and delivery_scope_known
            )
            provenance.update(
                {
                    "status": (
                        "unknown_or_incomplete_figure_set_scope"
                        if not delivery_scope_known
                        else "current_full_project_evidence"
                        if full_current
                        else "current_primary_figure_evidence"
                        if primary_current
                        else "audit_pending_for_current_project"
                        if current_result_awaiting_audit
                        else "incomplete_or_stale_project_evidence"
                    ),
                    "complete": full_current,
                    "full_project_evidence_current": full_current,
                    "primary_figure_evidence_current": primary_current,
                    "delivery_scope_known": delivery_scope_known,
                    "primary_figure_delivery_current": bool(
                        provenance.get("project_delivery_current") is True
                        and full_figure_set_scope
                    ),
                    "full_project_delivery_current": bool(
                        provenance.get("project_delivery_current") is True
                        and full_project_scope
                    ),
                    "audit_pending": current_result_awaiting_audit,
                    "artifact_qa_current": (qa.get("artifact_qa_current") is True),
                    "mapping_current": mapping_current,
                }
            )
            status["provenance"] = provenance
        results = (
            dict(status.get("results"))
            if isinstance(status.get("results"), dict)
            else {}
        )
        pdf = dict(results.get("pdf")) if isinstance(results.get("pdf"), dict) else {}
        pdf["current"] = bool(pdf.get("path") and qa.get("artifact_qa_current") is True)
        results["pdf"] = pdf
        delivery = (
            dict(results.get("delivery"))
            if isinstance(results.get("delivery"), dict)
            else {}
        )
        delivery["current"] = bool(
            delivery.get("path")
            and qa.get("artifact_qa_current") is True
            and status.get("provenance", {}).get("project_delivery_current") is True
            and status.get("provenance", {}).get("delivery_scope_known") is True
        )
        results["delivery"] = delivery
        status["results"] = results
        return self._publish_status(_finalize_status(status))

    def refresh_full(self) -> None:
        self.refresh(capture_render=True, audit_source=True)

    def _document_modified(self, _modified: int) -> None:
        if self._exporting:
            return
        try:
            self._refresh_document_state()
        except Exception as exc:
            self._audit_failure_status(exc)

    def _dock_visibility_changed(self, visible: bool) -> None:
        if visible and not self._exporting:
            self._refresh_document_state()
