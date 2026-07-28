"""Prepare managed and standalone export payloads and blockers."""

from __future__ import annotations

from typing import Any
from PyQt6 import QtWidgets
from sciplot_core.foundation.json_values import json_safe
from sciplot_gui.studio_project_status import (
    _read_json,
    export_result_message,
)

from sciplot_gui.studio_project.services import (
    _is_primary_figure_set_export_scope,
    _studio_figure_set_export_scope,
    export_studio_document,
    publish_standalone_export_receipt,
    publish_studio_export_run,
)


class ExportHelpersMixin:
    def _project_export(self) -> dict[str, Any]:
        assert self.project_dir is not None
        assert self.request_path is not None
        if self._figure_set_export_scope() != "project":
            raise RuntimeError(
                "Only the canonical project/studio/document.vsz may publish "
                "a project delivery receipt."
            )
        export_payload = export_studio_document(
            self.document_path,
            formats=["pdf", "tiff_300"],
        )
        exports = list(export_payload.get("exports") or [])
        export_document_sha256 = str(
            export_payload.get("document_sha256") or ""
        ).strip()
        run = publish_studio_export_run(
            project_dir=self.project_dir,
            request_path=self.request_path,
            document_path=self.document_path,
            exports=exports,
            export_document_sha256=export_document_sha256,
        )
        figure_set_export_scope = run.get("figure_set_export_scope")
        if (
            figure_set_export_scope is not None
            and not _is_primary_figure_set_export_scope(figure_set_export_scope)
        ):
            raise RuntimeError(
                "The project run returned a missing or malformed figure-set "
                "delivery scope, so SciPlot did not accept it as ready."
            )
        scope = (
            "full_figure_set_project_delivery"
            if _is_primary_figure_set_export_scope(figure_set_export_scope)
            else "project_delivery"
        )
        result = {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": scope,
            "status": "passed" if run.get("ready_to_use") is True else "failed",
            "state": run.get("state"),
            "ready_to_use": run.get("ready_to_use") is True,
            "export_payload": json_safe(export_payload),
            "exports": json_safe(run.get("exports") or exports),
            "studio_run": json_safe(run),
        }
        if isinstance(figure_set_export_scope, dict):
            result["figure_set_export_scope"] = json_safe(figure_set_export_scope)
        return result

    def _standalone_export(self) -> dict[str, Any]:
        if (
            self.project_dir is not None
            and self._figure_set_export_scope() == "standalone"
        ):
            artifact_root = (
                self.document_path.parent / "exports" / self.document_path.stem
            )
        else:
            artifact_root = self.document_path.parent / "exports"
        export_payload = export_studio_document(
            self.document_path,
            formats=["pdf", "tiff_300"],
            output_dir=artifact_root / "figures",
        )
        exports = list(export_payload.get("exports") or [])
        export_document_sha256 = str(
            export_payload.get("document_sha256") or ""
        ).strip()
        receipt = publish_standalone_export_receipt(
            document_path=self.document_path,
            requested_formats=["pdf", "tiff_300"],
            exports=exports,
            artifact_root=artifact_root,
            export_document_sha256=export_document_sha256,
        )
        return {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": "standalone_exact_current_export",
            "status": receipt.get("status"),
            "state": receipt.get("state"),
            "ready_to_use": receipt.get("export_ready") is True,
            "export_payload": json_safe(export_payload),
            "exports": json_safe(exports),
            "standalone_export": json_safe(receipt),
        }

    def _assistant_export_blocker(self) -> str | None:
        assistant = getattr(
            self.window,
            "_sciplot_assistant_bridge",
            None,
        )
        if assistant is None:
            return None
        try:
            runner = getattr(assistant, "runner", None)
            if runner is not None and bool(getattr(runner, "active", False)):
                return (
                    "Wait for the active SciPlot AI request to finish or stop "
                    "it before exporting."
                )
            pending = getattr(assistant, "pending_batch", None)
            if pending is None:
                pending = getattr(assistant, "_pending_batch", None)
            if pending is not None:
                return (
                    "Accept or reject the pending SciPlot AI proposal before exporting."
                )
        except Exception as exc:
            return (
                "SciPlot could not establish a safe AI transaction state: "
                f"{type(exc).__name__}: {exc}"
            )
        return None

    def _figure_set_export_scope(self) -> str:
        if self.project_dir is None:
            return "standalone"
        canonical_primary = (self.project_dir / "studio" / "document.vsz").resolve()
        return "project" if self.document_path == canonical_primary else "standalone"

    def _current_project_figure_set_scope(self) -> dict[str, Any] | None:
        if (
            self.project_dir is None
            or self.request_path is None
            or self._figure_set_export_scope() != "project"
        ):
            return None
        request = _read_json(self.request_path)
        scope = _studio_figure_set_export_scope(
            self.project_dir,
            request=request,
        )
        return dict(scope) if _is_primary_figure_set_export_scope(scope) else None

    def _figure_set_export_blocker(self) -> str | None:
        if (
            self.project_dir is None
            or self.request_path is None
            or self._figure_set_export_scope() != "project"
        ):
            return None
        try:
            request = _read_json(self.request_path)
            scope = _studio_figure_set_export_scope(
                self.project_dir,
                request=request,
            )
        except Exception as exc:
            return (
                "SciPlot could not establish the current figure-set delivery "
                f"scope: {type(exc).__name__}: {exc}"
            )
        if _is_primary_figure_set_export_scope(scope):
            return None
        if (
            scope is not None
            or (self.project_dir / "studio" / "figure_set.json").exists()
        ):
            return (
                "SciPlot cannot establish a complete all-figures figure-set "
                "scope from the current request and registry. Export is blocked "
                "until that scope is repaired."
            )
        return None

    def _project_delivery_scope(self) -> str:
        if self.mode == "project" and self._figure_set_export_scope() == "project":
            try:
                scope = self._current_project_figure_set_scope()
            except Exception:
                scope = None
            if _is_primary_figure_set_export_scope(scope):
                return "full_figure_set_project_delivery"
            return "project_delivery"
        return "standalone_exact_current_export"

    def _failed_export_payload(
        self,
        *,
        state: str,
        message: str,
        error_type: str = "RuntimeError",
        unaccepted_export: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": self._project_delivery_scope(),
            "status": "failed",
            "state": state,
            "ready_to_use": False,
            "error": {
                "type": error_type,
                "message": message,
            },
        }
        if unaccepted_export is not None:
            payload["unaccepted_export"] = json_safe(unaccepted_export)
        return payload

    def _show_export_message(self, payload: dict[str, Any]) -> None:
        level, title, message = export_result_message(payload)
        if level == "information":
            QtWidgets.QMessageBox.information(self.window, title, message)
        else:
            QtWidgets.QMessageBox.warning(self.window, title, message)
