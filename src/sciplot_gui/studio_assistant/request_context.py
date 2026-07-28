"""Build bounded selected-object context and capture the current plot preview."""

from __future__ import annotations

import base64
import hashlib
from collections import Counter
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5
from PyQt6 import QtCore, QtWidgets
from sciplot_core.assistant_selection import VeuszSelection
from sciplot_core.assistant_provider import (
    ASSISTANT_CONTEXT_KIND,
    ASSISTANT_CONTEXT_VERSION,
    AssistantRequest,
)


class RequestContextMixin:
    def context_for_current_selection(self) -> dict[str, Any]:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.handle_document_context_changed()
            raise RuntimeError(context_blocker)
        widget = self._selected_widget
        if widget is None:
            raise RuntimeError("Select a supported Veusz object before asking AI.")
        inventory = self._walk_widgets()
        object_types = Counter(str(item.typename) for item in inventory)
        object_id = self._object_id(widget)
        selection = VeuszSelection(
            object_ids=[object_id],
            primary_object_id=object_id,
        )
        revision = int(self.document.changeset)
        return {
            "kind": ASSISTANT_CONTEXT_KIND,
            "version": ASSISTANT_CONTEXT_VERSION,
            "project_id": self.document_path.parent.parent.name
            if self.document_path.parent.name == "studio"
            else self.document_path.stem,
            "document_id": str(uuid5(NAMESPACE_URL, str(self.document_path))),
            "revision": revision,
            "state": "manual_editing",
            "page": int(self.plot.getPageNumber()),
            "selection": selection.to_dict(),
            "selected_object": {
                "object_id": object_id,
                "object_type": str(widget.typename),
                "display_name": str(widget.name or widget.typename),
            },
            "document_inventory": {
                "object_count": len(inventory),
                "object_types": dict(sorted(object_types.items())),
            },
            "review": {"active_count": 0, "annotations": []},
            "qa": {
                "structural_status": "not_run",
                "structural_failed_ids": [],
                "structural_warning_ids": [],
                "ready_for_artifact_qa": False,
                "artifact_status": "not_run",
                "ready_to_use": None,
            },
            "editing_capabilities": self._editing_capabilities(widget),
            "raw_dataset_arrays_included": False,
            "explicit_selected_point_included": False,
        }

    def _wait_for_plot(self, *, timeout_ms: int = 4000) -> None:
        deadline = QtCore.QDeadlineTimer(max(int(timeout_ms), 0))
        application = QtWidgets.QApplication.instance()
        while (
            int(getattr(self.window, "plotqueuecount", 0)) > 0
            and not deadline.hasExpired()
        ):
            application.processEvents(
                QtCore.QEventLoop.ProcessEventsFlag.AllEvents,
                25,
            )
        application.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents,
            25,
        )

    def capture_current_plot_png(self) -> tuple[bytes, dict[str, Any]]:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.handle_document_context_changed()
            raise RuntimeError(context_blocker)
        revision = int(self.document.changeset)
        self.plot.actionForceUpdate()
        self._wait_for_plot()
        if int(self.document.changeset) != revision:
            raise RuntimeError("The Veusz document changed while capturing the figure.")
        pixmap = self.plot.pixmapitem.pixmap()
        if pixmap.isNull() or pixmap.width() <= 1 or pixmap.height() <= 1:
            raise RuntimeError("The current Veusz plot has no rendered image.")
        byte_array = QtCore.QByteArray()
        buffer = QtCore.QBuffer(byte_array)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        try:
            if not pixmap.save(buffer, "PNG"):
                raise RuntimeError("Could not serialize the current Veusz plot.")
        finally:
            buffer.close()
        png = bytes(byte_array)
        digest = hashlib.sha256(png).hexdigest()
        self._last_render_sha256 = digest
        return png, {
            "base64": base64.b64encode(png).decode("ascii"),
            "sha256": digest,
            "width": int(pixmap.width()),
            "height": int(pixmap.height()),
            "revision": revision,
        }

    def current_render_sha256(self) -> str:
        _png, preview = self.capture_current_plot_png()
        return str(preview["sha256"])

    def build_request(self, intent: str) -> AssistantRequest:
        descriptor = self.runner.descriptor
        if descriptor is None:
            raise RuntimeError("No Assistant provider is connected.")
        intent_text = str(intent or "").strip()
        if not intent_text:
            intent_text = (
                "Inspect the exact-current rendered page for context and suggest "
                "a change only for the selected object when a visible issue can "
                "be corrected with the allowed settings."
            )
        context = self.context_for_current_selection()
        _png, visual_preview = self.capture_current_plot_png()
        if int(self.document.changeset) != int(context["revision"]):
            raise RuntimeError(
                "The document changed while the AI request was prepared."
            )
        allowed = tuple(
            kind
            for kind in descriptor.proposal_kinds
            if kind == "veusz_setting_operation_batch"
        )
        if not allowed:
            raise RuntimeError(
                "The connected provider cannot propose bounded selected-object edits."
            )
        return AssistantRequest(
            transaction_id=str(uuid4()),
            provider_id=descriptor.provider_id,
            intent=intent_text,
            base_revision=int(context["revision"]),
            context=context,
            allowed_proposal_kinds=allowed,
            visual_preview=visual_preview,
        )
