from __future__ import annotations

import base64
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from PyQt6 import QtCore, QtWidgets

from sciplot_core._utils import json_safe
from sciplot_core.canvas.inspector import (
    SUPPORTED_INSPECTOR_TYPES,
    specs_for_object_type,
)
from sciplot_core.canvas.model import CanvasSelection
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.provider import (
    ASSISTANT_CONTEXT_KIND,
    ASSISTANT_CONTEXT_VERSION,
    AssistantProvider,
    AssistantRequest,
    AssistantResponse,
)
from sciplot_gui.assistant_runtime import AssistantRequestRunner
from sciplot_gui.studio_assistant_history import (
    append_assistant_history_event,
    assistant_history_path,
    build_assistant_history_event,
)


class StudioAssistantBridge(QtCore.QObject):
    """A narrow AI bridge over an existing Veusz MainWindow and Document.

    The bridge deliberately does not own a Canvas session, Document, PlotWindow,
    or undo stack. Human property edits and AI edits therefore share Veusz's
    native document history and the saved VSZ remains the visual authority.
    """

    requestSubmitted = QtCore.pyqtSignal(object)
    proposalReady = QtCore.pyqtSignal(object)
    proposalApplied = QtCore.pyqtSignal(object)
    requestRejected = QtCore.pyqtSignal(str)
    historyRecorded = QtCore.pyqtSignal(object)

    def __init__(
        self,
        window: Any,
        document_path: Path,
        *,
        provider: AssistantProvider | None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = window.document
        self.plot = window.plot
        self.document_path = document_path.expanduser().resolve()
        self.history_path = assistant_history_path(self.document_path)
        self.provider = provider
        self.runner = AssistantRequestRunner(provider, self)
        self._selected_widget: Any | None = None
        self._pending_request: AssistantRequest | None = None
        self._pending_response: AssistantResponse | None = None
        self._pending_batch: CanvasOperationBatch | None = None
        self._pending_capabilities: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_render_sha256: str | None = None

        self.dock = self._build_dock()
        # SciPlot augments the native Veusz MainWindow; it must not claim space
        # or rearrange the user's established Veusz dock layout on startup.
        # The SciPlot menu exposes QDockWidget.toggleViewAction(), so the panel
        # remains one reversible, opt-in native dock when it is needed.
        self.dock.hide()
        self.window.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            self.dock,
        )
        self._connect_signals()
        self._refresh_selection_label()
        self._set_provider_state()

    @property
    def selected_widget(self) -> Any | None:
        return self._selected_widget

    @property
    def pending_batch(self) -> CanvasOperationBatch | None:
        return self._pending_batch

    def _window_document_path(self) -> Path | None:
        filename = str(getattr(self.window, "filename", "") or "").strip()
        if not filename:
            return None
        try:
            return Path(filename).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    def _document_context_blocker(self) -> str | None:
        current = self._window_document_path()
        if current == self.document_path:
            return None
        current_label = str(current) if current is not None else "an unsaved document"
        return (
            "This Veusz window now points to "
            f"{current_label}, but SciPlot AI remains bound to "
            f"{self.document_path}. Close this window and reopen the new VSZ "
            "before asking AI so the exact-current document context can be "
            "rebuilt safely."
        )

    def handle_document_context_changed(self) -> str | None:
        message = self._document_context_blocker()
        if message is None:
            self._refresh_ask_button()
            return None
        if self.runner.active:
            try:
                self.runner.cancel()
            except Exception:
                pass
        if self._pending_request is not None:
            self._reject_stale(
                message,
                reason_code="document_context_changed",
            )
        else:
            self._clear_pending()
            self.status_label.setText(message)
            self.proposal_view.setPlainText(message)
            self.requestRejected.emit(message)
        self._refresh_ask_button()
        return message

    def _record_history(
        self,
        *,
        status: str,
        request: AssistantRequest,
        response: AssistantResponse | None = None,
        batch: CanvasOperationBatch | None = None,
        operations: list[Any] | tuple[Any, ...] | None = None,
        reason_code: str | None = None,
        applied_revision: int | None = None,
        after_page_render_sha256: str | None = None,
        render_changed: bool | None = None,
        native_undo_label: str | None = None,
    ) -> dict[str, Any]:
        event = build_assistant_history_event(
            status=status,
            request=request,
            descriptor=self.runner.descriptor,
            response=response,
            batch=batch,
            operations=operations,
            reason_code=reason_code,
            applied_revision=applied_revision,
            after_page_render_sha256=after_page_render_sha256,
            render_changed=render_changed,
            native_undo_label=native_undo_label,
        )
        append_assistant_history_event(self.history_path, event)
        self.historyRecorded.emit(event)
        return event

    def _clear_pending(self) -> None:
        """Release request-owned image bytes after a terminal outcome."""

        self._pending_response = None
        self._pending_batch = None
        self._pending_request = None
        self._pending_capabilities = {}
        try:
            self.apply_button.setEnabled(False)
            self.reject_button.setEnabled(False)
        except RuntimeError:
            # Window destruction can delete child widgets before this bridge's
            # shutdown slot releases request-owned image bytes.
            pass
        self._refresh_ask_button()

    @staticmethod
    def _terminal_history_status(response_status: str) -> str:
        if response_status in {
            "cancelled",
            "needs_human_confirmation",
            "needs_rule_repair",
        }:
            return response_status
        return "failed"

    def _build_dock(self) -> QtWidgets.QDockWidget:
        dock = QtWidgets.QDockWidget("SciPlot AI", self.window)
        dock.setObjectName("sciplotStudioAssistantDock")
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        body = QtWidgets.QWidget(dock)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.intro_label = QtWidgets.QLabel(
            "AI inspects the exact-current rendered page for context. It can "
            "propose changes only to the selected object's supported properties."
        )
        self.intro_label.setWordWrap(True)
        layout.addWidget(self.intro_label)

        self.selection_label = QtWidgets.QLabel()
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        self.intent_edit = QtWidgets.QPlainTextEdit()
        self.intent_edit.setPlaceholderText(
            "Example: make the selected axis label easier to read."
        )
        self.intent_edit.setMaximumHeight(110)
        layout.addWidget(self.intent_edit)

        self.auto_apply = QtWidgets.QCheckBox(
            "Apply a safe, current proposal immediately"
        )
        self.auto_apply.setChecked(False)
        self.auto_apply.setToolTip(
            "Every change remains one native Veusz Undo step. A stale response "
            "is rejected instead of being applied."
        )
        layout.addWidget(self.auto_apply)

        request_row = QtWidgets.QHBoxLayout()
        self.ask_button = QtWidgets.QPushButton("Suggest Changes for Selected Object")
        self.cancel_button = QtWidgets.QPushButton("Stop")
        self.cancel_button.setEnabled(False)
        request_row.addWidget(self.ask_button, 1)
        request_row.addWidget(self.cancel_button)
        layout.addLayout(request_row)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        self.proposal_view = QtWidgets.QPlainTextEdit()
        self.proposal_view.setReadOnly(True)
        self.proposal_view.setPlaceholderText(
            "The AI's bounded proposal and applied changes appear here."
        )
        layout.addWidget(self.proposal_view, 1)

        decision_row = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply Proposal")
        self.reject_button = QtWidgets.QPushButton("Reject")
        self.apply_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        decision_row.addWidget(self.apply_button)
        decision_row.addWidget(self.reject_button)
        layout.addLayout(decision_row)

        dock.setWidget(body)
        return dock

    def _connect_signals(self) -> None:
        self.window.treeedit.widgetsSelected.connect(self._widgets_selected)
        self.plot.sigWidgetClicked.connect(self._plot_widget_clicked)
        self.ask_button.clicked.connect(self._ask_from_ui)
        self.cancel_button.clicked.connect(self._cancel_request)
        self.apply_button.clicked.connect(self.accept_pending)
        self.reject_button.clicked.connect(self.reject_pending)
        self.runner.progress.connect(self._provider_progress)
        self.runner.response.connect(self._provider_response)
        self.runner.failed.connect(self._provider_failed)
        self.runner.activeChanged.connect(self._runner_active_changed)
        self.window.destroyed.connect(self._shutdown)

    def _set_provider_state(self) -> None:
        if self.provider is None:
            self.status_label.setText(
                "No OpenAI Assistant is connected. Veusz editing remains fully "
                "available; set OPENAI_API_KEY to enable visual AI edits."
            )
            self._refresh_ask_button()
            return
        descriptor = self.runner.descriptor
        label = descriptor.display_name if descriptor is not None else "Assistant"
        self.status_label.setText(
            f"{label} is ready. Select an object in the plot or object tree."
        )
        self._refresh_ask_button()

    def _refresh_ask_button(self) -> None:
        try:
            context_blocker = self._document_context_blocker()
            self.ask_button.setEnabled(
                self.provider is not None
                and self._selected_widget is not None
                and not self.runner.active
                and context_blocker is None
            )
            self.ask_button.setToolTip(context_blocker or "")
        except RuntimeError:
            # Child widgets can already be gone while the native MainWindow is
            # completing destruction.
            pass

    @QtCore.pyqtSlot(list, object)
    def _widgets_selected(self, widgets: list[Any], _settings_proxy: Any) -> None:
        self.set_selected_widget(widgets[0] if widgets else None)

    @QtCore.pyqtSlot(object, str)
    def _plot_widget_clicked(self, widget: Any, _mode: str) -> None:
        self.set_selected_widget(widget)

    def set_selected_widget(self, widget: Any | None) -> Any | None:
        candidate = widget
        selected: Any | None = None
        while candidate is not None:
            if str(getattr(candidate, "typename", "")) in SUPPORTED_INSPECTOR_TYPES:
                selected = candidate
                break
            candidate = getattr(candidate, "parent", None)

        previous = self._selected_widget
        self._selected_widget = selected
        self._refresh_selection_label()
        self._refresh_ask_button()
        if (
            previous is not selected
            and self._pending_request is not None
            and not self.runner.active
        ):
            self._reject_stale(
                "The selected Veusz object changed. The old-object proposal "
                "was discarded; ask again for the current selection.",
                reason_code="selected_object_changed",
            )
        return selected

    def _walk_widgets(self) -> list[Any]:
        result: list[Any] = []
        stack = list(self.document.basewidget.children)
        while stack:
            widget = stack.pop(0)
            result.append(widget)
            stack[0:0] = list(widget.children)
        return result

    def _refresh_selection_label(self) -> None:
        widget = self._selected_widget
        if widget is None:
            self.selection_label.setText(
                "Selected: none (choose a supported object in Veusz)"
            )
            return
        self.selection_label.setText(f"Selected: {widget.typename} · {widget.path}")

    def _object_id(self, widget: Any) -> str:
        document_id = uuid5(NAMESPACE_URL, str(self.document_path))
        return str(uuid5(document_id, str(widget.path)))

    def _request_targets_current_selection(self, request: AssistantRequest) -> bool:
        widget = self._selected_widget
        if widget is None:
            return False
        selected = request.context.get("selected_object")
        if not isinstance(selected, dict):
            return False
        return str(selected.get("object_id") or "") == self._object_id(widget) and str(
            selected.get("object_type") or ""
        ) == str(getattr(widget, "typename", ""))

    def _editing_capabilities(self, widget: Any) -> dict[str, Any]:
        target_id = self._object_id(widget)
        operations: list[dict[str, Any]] = []
        for spec in specs_for_object_type(str(widget.typename)):
            if spec.read_only:
                continue
            setting_path = f"{widget.path}/{spec.suffix}"
            try:
                setting = self.document.resolveSettingPath(None, setting_path)
            except ValueError:
                continue
            operations.append(
                {
                    "operation_type": "set_setting",
                    "target_id": target_id,
                    "field_id": spec.field_id,
                    "section": spec.section,
                    "label": spec.label,
                    "setting_path": setting_path,
                    "editor": spec.editor,
                    "current_value": json_safe(setting.get()),
                    "choices": [
                        str(choice) for choice in getattr(setting, "vallist", ())
                    ],
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                    "help_text": spec.help_text
                    or str(getattr(setting, "descr", "") or ""),
                }
            )
        return {
            "scope": "selected_object",
            "target_object_id": target_id,
            "allowed_operations": operations,
        }

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
        selection = CanvasSelection(
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
            if kind == "canvas_operation_batch"
        )
        if not allowed:
            raise RuntimeError(
                "The connected provider cannot propose bounded Canvas edits."
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

    @QtCore.pyqtSlot()
    def _ask_from_ui(self) -> None:
        try:
            self.submit_intent(self.intent_edit.toPlainText())
        except Exception as exc:
            self._show_error(str(exc))

    def submit_intent(self, intent: str) -> AssistantRequest:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.handle_document_context_changed()
            raise RuntimeError(context_blocker)
        if self.runner.active:
            raise RuntimeError("An Assistant request is already running.")
        self.reject_pending(
            silent=True,
            reason_code="superseded_by_new_request",
        )
        request = self.build_request(intent)
        capabilities = request.context["editing_capabilities"]["allowed_operations"]
        self._pending_request = request
        self._pending_capabilities = {
            (str(item["target_id"]), str(item["setting_path"])): dict(item)
            for item in capabilities
        }
        self.proposal_view.setPlainText(
            "Inspecting the exact-current rendered page…\n"
            f"PNG SHA-256: {request.visual_preview['sha256']}"
        )
        self.status_label.setText(
            "AI is inspecting the current page for a bounded selected-object proposal."
        )
        try:
            self._record_history(status="submitted", request=request)
        except Exception:
            self._clear_pending()
            raise RuntimeError(
                "The Assistant request was not sent because its local history "
                "could not be written."
            ) from None
        try:
            self.runner.submit(request)
        except Exception:
            try:
                self._record_history(
                    status="failed",
                    request=request,
                    reason_code="request_submit_failed",
                )
            except Exception:
                pass
            finally:
                self._clear_pending()
            raise
        self.requestSubmitted.emit(request)
        return request

    @QtCore.pyqtSlot()
    def _cancel_request(self) -> None:
        try:
            self.runner.cancel()
            self.status_label.setText("Stopping the Assistant request…")
        except Exception as exc:
            self._show_error(str(exc))

    @QtCore.pyqtSlot(object)
    def _provider_progress(self, event: Any) -> None:
        if self._document_context_blocker() is not None:
            return
        self.status_label.setText(str(getattr(event, "message", "AI is working…")))

    @QtCore.pyqtSlot(object)
    def _provider_response(self, response: AssistantResponse) -> None:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self._reject_stale(
                context_blocker,
                reason_code="document_context_changed",
                response=response,
            )
            return
        request = self._pending_request
        if request is None:
            self._reject_stale(
                "Assistant response has no active request.",
                reason_code="no_active_request",
                response=response,
            )
            return
        if not self._request_targets_current_selection(request):
            self._reject_stale(
                "The selected Veusz object changed while AI was inspecting it. "
                "The old-object proposal was discarded; ask again for the "
                "current selection.",
                reason_code="selected_object_changed",
                response=response,
            )
            return
        if int(self.document.changeset) != request.base_revision:
            self._reject_stale(
                "The Veusz document changed while AI was inspecting it. "
                "The stale proposal was discarded; ask again to use the "
                "current rendered page.",
                reason_code="document_revision_changed",
                response=response,
            )
            return
        self._pending_response = response
        if response.status != "proposal":
            self._pending_batch = None
            self.apply_button.setEnabled(False)
            self.reject_button.setEnabled(False)
            self.status_label.setText(response.understanding)
            self.proposal_view.setPlainText(self._response_text(response, batch=None))
            try:
                self._record_history(
                    status=self._terminal_history_status(response.status),
                    request=request,
                    response=response,
                )
            except Exception:
                self.status_label.setText(
                    f"{response.understanding} Local Assistant history could "
                    "not be finalized."
                )
            finally:
                self._clear_pending()
            return
        if response.proposal_kind != "canvas_operation_batch":
            self._reject_stale(
                "The Assistant returned an unsupported proposal.",
                reason_code="unsupported_proposal_kind",
                response=response,
            )
            return
        try:
            batch = CanvasOperationBatch.from_dict(dict(response.proposal or {}))
            self._prepare_native_operations(batch, request=request)
        except Exception as exc:
            self._reject_stale(
                f"Unsafe Assistant proposal rejected: {exc}",
                reason_code="typed_validation_failed",
                response=response,
            )
            return
        self._pending_batch = batch
        self.proposal_view.setPlainText(self._response_text(response, batch=batch))
        self.apply_button.setEnabled(True)
        self.reject_button.setEnabled(True)
        self.status_label.setText("A bounded proposal is ready.")
        try:
            self._record_history(
                status="proposal_ready",
                request=request,
                response=response,
                batch=batch,
            )
        except Exception:
            message = (
                "The bounded proposal was not retained because its local "
                "Assistant history could not be written."
            )
            self._clear_pending()
            self.status_label.setText(message)
            self.proposal_view.setPlainText(message)
            self.requestRejected.emit(message)
            return
        self.proposalReady.emit(batch)
        if self.auto_apply.isChecked():
            self.accept_pending()

    def _response_text(
        self,
        response: AssistantResponse,
        *,
        batch: CanvasOperationBatch | None,
    ) -> str:
        lines = [response.understanding]
        if response.warnings:
            lines.extend(
                ["", "Warnings:", *[f"• {item}" for item in response.warnings]]
            )
        if batch is not None:
            lines.extend(["", "Proposed changes:"])
            for operation in batch.operations:
                capability = self._pending_capabilities.get(
                    (
                        operation.target_id,
                        str(operation.arguments.get("setting_path") or ""),
                    ),
                    {},
                )
                label = capability.get("label") or operation.arguments.get(
                    "setting_path"
                )
                lines.append(
                    f"• {label}: {operation.arguments.get('expected_value')!r} "
                    f"→ {operation.arguments.get('value')!r}"
                )
        return "\n".join(lines)

    def _prepare_native_operations(
        self,
        batch: CanvasOperationBatch,
        *,
        request: AssistantRequest,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        if batch.base_revision != request.base_revision:
            raise ValueError("proposal revision does not match the request")
        if int(self.document.changeset) != request.base_revision:
            raise ValueError("the Veusz document has changed")
        from veusz.document.operations import OperationSettingSet

        native: list[Any] = []
        prepared: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for operation in batch.operations:
            if operation.operation_type != "set_setting":
                raise ValueError(f"unsupported operation {operation.operation_type!r}")
            setting_path = str(operation.arguments["setting_path"])
            key = (operation.target_id, setting_path)
            capability = self._pending_capabilities.get(key)
            if capability is None:
                raise ValueError("proposal is outside the advertised setting catalog")
            if setting_path in seen_paths:
                raise ValueError("proposal contains the same setting twice")
            seen_paths.add(setting_path)
            if "expected_value" not in operation.arguments:
                raise ValueError("proposal is missing expected_value")
            setting = self.document.resolveSettingPath(None, setting_path)
            current = json_safe(setting.get())
            expected = json_safe(operation.arguments["expected_value"])
            if current != expected or current != capability["current_value"]:
                raise ValueError(f"{setting_path} no longer has its expected value")
            normalized = setting.normalize(operation.arguments["value"])
            native.append(OperationSettingSet(setting_path, normalized))
            prepared.append(
                {
                    "operation_id": operation.operation_id,
                    "operation_type": operation.operation_type,
                    "target_id": operation.target_id,
                    "setting_path": setting_path,
                    "old_value": current,
                    "new_value": json_safe(normalized),
                }
            )
        if not native:
            raise ValueError("proposal contains no applicable edits")
        return native, prepared

    @QtCore.pyqtSlot()
    def accept_pending(self) -> dict[str, Any] | None:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.handle_document_context_changed()
            return None
        batch = self._pending_batch
        request = self._pending_request
        if batch is None or request is None:
            return None
        if not self._request_targets_current_selection(request):
            self._reject_stale(
                "The selected Veusz object changed. The old-object proposal "
                "was discarded; ask again for the current selection.",
                reason_code="selected_object_changed",
                batch=batch,
            )
            return None
        try:
            native, prepared = self._prepare_native_operations(
                batch,
                request=request,
            )
        except Exception as exc:
            reason_code = (
                "document_revision_changed"
                if int(self.document.changeset) != request.base_revision
                else "typed_validation_failed"
            )
            self._reject_stale(
                f"Assistant proposal was not applied: {exc}",
                reason_code=reason_code,
                response=self._pending_response,
                batch=batch,
            )
            return None

        description = f"SciPlot AI · {batch.batch_id[:8]}"
        try:
            self._record_history(
                status="apply_started",
                request=request,
                response=self._pending_response,
                batch=batch,
                operations=prepared,
                native_undo_label=description,
            )
        except Exception:
            self.status_label.setText(
                "The proposal was not applied because its durable local "
                "Assistant history could not be written."
            )
            return None

        from veusz.document.operations import OperationMultiple

        before_render = request.visual_preview["sha256"]
        try:
            self.document.applyOperation(OperationMultiple(native, descr=description))
        except Exception as exc:
            try:
                self._record_history(
                    status="failed",
                    request=request,
                    response=self._pending_response,
                    batch=batch,
                    operations=prepared,
                    reason_code="apply_failed",
                    native_undo_label=description,
                )
            except Exception:
                pass
            self._clear_pending()
            message = f"Assistant proposal could not be applied: {exc}"
            self.status_label.setText(message)
            self.proposal_view.setPlainText(message)
            self.requestRejected.emit(message)
            return None

        applied_revision = int(self.document.changeset)
        after_render: str | None = None
        verification_error = False
        try:
            after_render = self.current_render_sha256()
        except Exception:
            verification_error = True

        terminal_status = "applied_unverified" if verification_error else "applied"
        render_changed = (
            before_render != after_render if after_render is not None else None
        )
        history_finalized = True
        try:
            self._record_history(
                status=terminal_status,
                request=request,
                response=self._pending_response,
                batch=batch,
                operations=prepared,
                reason_code=(
                    "after_render_verification_failed" if verification_error else None
                ),
                applied_revision=applied_revision,
                after_page_render_sha256=after_render,
                render_changed=render_changed,
                native_undo_label=description,
            )
        except Exception:
            history_finalized = False

        result = {
            "batch_id": batch.batch_id,
            "base_revision": batch.base_revision,
            "applied_revision": applied_revision,
            "before_render_sha256": before_render,
            "after_render_sha256": after_render,
            "render_changed": render_changed,
            "operations": prepared,
            "native_undo_description": description,
            "verification_status": terminal_status,
            "history_finalized": history_finalized,
        }
        current = self.proposal_view.toPlainText()
        self._clear_pending()
        if verification_error:
            self.status_label.setText(
                "Applied as one native Veusz Undo step, but the exact-current "
                "after-render hash could not be verified. Use Edit → Undo or "
                "inspect the current page before saving."
            )
            self.proposal_view.setPlainText(
                f"{current}\n\nApplied as one native Veusz Undo step; "
                "after-render verification is incomplete."
            )
        elif not history_finalized:
            self.status_label.setText(
                "Applied as one native Veusz Undo step, but the terminal "
                "Assistant history row could not be finalized."
            )
            self.proposal_view.setPlainText(
                f"{current}\n\nApplied as one native Veusz Undo step; "
                "history finalization is incomplete."
            )
        else:
            self.status_label.setText(
                "Applied to the live Veusz document. Use Edit → Undo to revert; "
                "save when satisfied."
            )
            self.proposal_view.setPlainText(
                f"{current}\n\nApplied as one native Veusz Undo step."
            )
        self.proposalApplied.emit(result)
        return result

    @QtCore.pyqtSlot()
    def reject_pending(
        self,
        *,
        silent: bool = False,
        reason_code: str = "user_rejected",
    ) -> None:
        had_proposal = self._pending_batch is not None
        request = self._pending_request
        response = self._pending_response
        batch = self._pending_batch
        history_failed = False
        if request is not None and had_proposal:
            try:
                self._record_history(
                    status="rejected",
                    request=request,
                    response=response,
                    batch=batch,
                    reason_code=reason_code,
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        if had_proposal and not silent:
            message = "Proposal rejected; the Veusz document was unchanged."
            if history_failed:
                message += " Local Assistant history could not be finalized."
            self.status_label.setText(message)

    def _reject_stale(
        self,
        message: str,
        *,
        reason_code: str,
        response: AssistantResponse | None = None,
        batch: CanvasOperationBatch | None = None,
    ) -> None:
        request = self._pending_request
        history_failed = False
        if request is not None:
            try:
                self._record_history(
                    status="rejected",
                    request=request,
                    response=response or self._pending_response,
                    batch=batch or self._pending_batch,
                    reason_code=reason_code,
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        if history_failed:
            message = f"{message} Local Assistant history could not be finalized."
        self.status_label.setText(message)
        self.proposal_view.setPlainText(message)
        self.requestRejected.emit(message)

    @QtCore.pyqtSlot(object)
    def _provider_failed(self, payload: Any) -> None:
        if self._document_context_blocker() is not None:
            self.handle_document_context_changed()
            return
        error = payload.get("error") if isinstance(payload, dict) else str(payload)
        request = self._pending_request
        history_failed = False
        if request is not None:
            try:
                self._record_history(
                    status="failed",
                    request=request,
                    reason_code="provider_failed",
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        message = f"Assistant request failed: {error}"
        if history_failed:
            message += " Local Assistant history could not be finalized."
        self.status_label.setText(message)
        self.proposal_view.setPlainText(message)
        self.requestRejected.emit(message)

    @QtCore.pyqtSlot(bool)
    def _runner_active_changed(self, active: bool) -> None:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.status_label.setText(context_blocker)
            self.proposal_view.setPlainText(context_blocker)
            self._refresh_ask_button()
            return
        self._refresh_ask_button()
        descriptor = self.runner.descriptor
        self.cancel_button.setEnabled(
            bool(active and descriptor is not None and descriptor.supports_cancellation)
        )

    def _show_error(self, message: str) -> None:
        self.status_label.setText(message)
        QtWidgets.QMessageBox.warning(self.window, "SciPlot AI", message)

    @QtCore.pyqtSlot()
    def _shutdown(self) -> None:
        was_active = self.runner.active
        self.runner.shutdown(wait_ms=3000)
        request = self._pending_request
        if request is not None:
            try:
                self._record_history(
                    status=("cancelled" if was_active else "rejected"),
                    request=request,
                    response=self._pending_response,
                    batch=self._pending_batch,
                    reason_code="window_closed",
                )
            except Exception:
                pass
            self._clear_pending()


def attach_studio_assistant(
    window: Any,
    document_path: Path,
    *,
    provider: AssistantProvider | None = None,
    resolve_provider: bool = True,
) -> StudioAssistantBridge:
    existing = getattr(window, "_sciplot_assistant_bridge", None)
    if isinstance(existing, StudioAssistantBridge):
        return existing
    if provider is None and resolve_provider:
        from sciplot_gui.app import resolve_canvas_assistant_provider

        provider = resolve_canvas_assistant_provider()
    bridge = StudioAssistantBridge(
        window,
        document_path,
        provider=provider,
    )
    window._sciplot_assistant_bridge = bridge
    return bridge


__all__ = ["StudioAssistantBridge", "attach_studio_assistant"]
