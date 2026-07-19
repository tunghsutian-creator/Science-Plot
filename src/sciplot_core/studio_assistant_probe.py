from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.setting_catalog import SUPPORTED_INSPECTOR_TYPES
from sciplot_core.assistant_operations import (
    VeuszSettingOperation,
    VeuszSettingOperationBatch,
)
from sciplot_core.assistant_provider import (
    AssistantCancellationToken,
    AssistantProgressEvent,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantResponse,
)
from sciplot_gui.studio_assistant_history import (
    canonical_value_sha256,
    read_assistant_history,
)

STUDIO_ASSISTANT_PROBE_KIND = "sciplot_studio_assistant_probe"
STUDIO_ASSISTANT_PROBE_VERSION = 1
_PROVIDER_ID = "studio_assistant_probe"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _wait_until(
    application: Any,
    predicate: Callable[[], bool],
    *,
    timeout_ms: int = 8000,
) -> bool:
    deadline = time.monotonic() + max(int(timeout_ms), 0) / 1000.0
    while time.monotonic() < deadline:
        application.sendPostedEvents()
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    application.sendPostedEvents()
    application.processEvents()
    return bool(predicate())


def _axis_widget(document: Any) -> Any:
    axes: list[Any] = []
    stack = list(document.basewidget.children)
    while stack:
        widget = stack.pop(0)
        stack[0:0] = list(widget.children)
        if str(getattr(widget, "typename", "")) == "axis":
            axes.append(widget)
    if not axes:
        raise RuntimeError("The supplied Veusz document contains no axis widget.")

    def score(axis: Any) -> tuple[int, int, str]:
        try:
            visible = not bool(axis.settings.hide)
        except (AttributeError, TypeError, ValueError):
            visible = True
        name = str(getattr(axis, "name", "") or "").casefold()
        preferred = 0 if name == "x" else (1 if name == "y" else 2)
        return (0 if visible else 1, preferred, str(axis.path))

    return sorted(axes, key=score)[0]


def _widget_identity(widget: Any | None) -> dict[str, str] | None:
    if widget is None:
        return None
    return {
        "type": str(getattr(widget, "typename", "")),
        "path": str(getattr(widget, "path", "")),
    }


def _axis_label_capability(request: AssistantRequest) -> dict[str, Any]:
    operations = request.context["editing_capabilities"]["allowed_operations"]
    target = next(
        (
            item
            for item in operations
            if item.get("field_id") == "axis_label"
            and str(item.get("setting_path") or "").endswith("/label")
        ),
        None,
    )
    if target is None:
        raise RuntimeError(
            "The selected axis does not advertise a typed axis-label capability."
        )
    return dict(target)


def _visual_preview_bytes(preview: dict[str, Any] | None) -> bytes:
    if not isinstance(preview, dict):
        raise RuntimeError("Assistant request has no exact-current visual preview.")
    encoded = preview.get("base64")
    if encoded is None:
        encoded = preview.get("data_base64")
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Assistant visual preview has no base64 PNG payload.")
    return base64.b64decode(encoded.encode("ascii"), validate=True)


def _visual_preview_metadata(preview: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(preview, dict):
        return {}
    return {
        key: value
        for key, value in preview.items()
        if key not in {"base64", "data_base64"}
    }


def _capture_plot(bridge: Any, path: Path) -> dict[str, Any]:
    png, preview = bridge.capture_current_plot_png()
    path.write_bytes(png)
    return {
        "path": str(path),
        "size_bytes": len(png),
        "sha256": hashlib.sha256(png).hexdigest(),
        "width": int(preview["width"]),
        "height": int(preview["height"]),
        "revision": int(preview["revision"]),
    }


class DeterministicStudioAssistantProvider:
    """Offline typed provider with an optional controlled response delay."""

    def __init__(self) -> None:
        self._descriptor = AssistantProviderDescriptor(
            provider_id=_PROVIDER_ID,
            display_name="Offline Studio Assistant Probe",
            model_label="deterministic-fixture",
            capabilities=("veusz_setting_operation_batch", "cancellation"),
        )
        self._lock = threading.Lock()
        self._next_value = ""
        self._delay_next = False
        self._started = threading.Event()
        self._release = threading.Event()
        self.requests: list[AssistantRequest] = []

    @property
    def descriptor(self) -> AssistantProviderDescriptor:
        return self._descriptor

    @property
    def started(self) -> bool:
        return self._started.is_set()

    def configure(self, *, next_value: str, delayed: bool = False) -> None:
        with self._lock:
            self._next_value = str(next_value)
            self._delay_next = bool(delayed)
        self._started.clear()
        self._release.clear()
        if not delayed:
            self._release.set()

    def release(self) -> None:
        self._release.set()

    def generate(
        self,
        request: AssistantRequest,
        *,
        emit_progress: Callable[[AssistantProgressEvent], None],
        cancellation: AssistantCancellationToken,
    ) -> AssistantResponse:
        restored = AssistantRequest.from_dict(request.to_dict())
        with self._lock:
            self.requests.append(restored)
            next_value = self._next_value
            delayed = self._delay_next
        capability = _axis_label_capability(restored)
        self._started.set()
        emit_progress(
            AssistantProgressEvent(
                request_id=restored.request_id,
                provider_id=self.descriptor.provider_id,
                sequence=1,
                stage="understanding",
                message="Inspecting the exact-current offline PNG.",
                cancellable=True,
                progress=0.25,
            )
        )
        if delayed:
            while not self._release.wait(0.01):
                cancellation.raise_if_cancelled()
        cancellation.raise_if_cancelled()
        emit_progress(
            AssistantProgressEvent(
                request_id=restored.request_id,
                provider_id=self.descriptor.provider_id,
                sequence=2,
                stage="validating",
                message="Returning one bounded axis-label operation.",
                cancellable=True,
                progress=0.9,
            )
        )
        operation = VeuszSettingOperation.set_setting(
            target_id=str(capability["target_id"]),
            setting_path=str(capability["setting_path"]),
            value=next_value,
            expected_value=capability["current_value"],
            require_expected_value=True,
        )
        batch = VeuszSettingOperationBatch(
            base_revision=restored.base_revision,
            provider=self.descriptor.provider_id,
            rationale="Offline Studio axis-label probe",
            operations=(operation,),
        )
        return AssistantResponse(
            request_id=restored.request_id,
            transaction_id=restored.transaction_id,
            provider_id=restored.provider_id,
            request_sha256=restored.payload_sha256,
            status="proposal",
            understanding="The exact-current axis label has one bounded edit.",
            proposal_kind="veusz_setting_operation_batch",
            proposal=batch.to_dict(),
        )


@contextmanager
def _injected_provider_resolution(
    provider: DeterministicStudioAssistantProvider | None,
) -> Iterator[None]:
    from sciplot_gui import studio_assistant as studio_assistant_module

    original = studio_assistant_module.resolve_assistant_provider

    def resolve(
        assistant_provider: object = None,
        *,
        environ: object = None,
    ) -> DeterministicStudioAssistantProvider | None:
        _ = assistant_provider, environ
        return provider

    studio_assistant_module.resolve_assistant_provider = resolve
    try:
        yield
    finally:
        studio_assistant_module.resolve_assistant_provider = original


def _create_window(
    document: Path,
    *,
    provider: DeterministicStudioAssistantProvider | None,
) -> tuple[Any, Any]:
    from sciplot_core.studio import _create_veusz_window

    with _injected_provider_resolution(provider):
        window = _create_veusz_window(document)
    bridge = getattr(window, "_sciplot_assistant_bridge", None)
    if bridge is None:
        raise RuntimeError("SciPlot Studio did not attach its Assistant bridge.")
    return window, bridge


def _close_window(window: Any | None) -> None:
    if window is None:
        return
    try:
        bridge = getattr(window, "_sciplot_assistant_bridge", None)
        if bridge is not None:
            bridge.runner.shutdown(wait_ms=3000)
    except Exception:
        pass
    try:
        window.document.setModified(False)
    except Exception:
        pass
    try:
        window.close()
    except Exception:
        pass


def run_studio_assistant_probe(
    document: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    source = document.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.casefold() != ".vsz":
        raise ValueError("Studio Assistant probe input must be a .vsz file.")

    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="studio_assistant_probe_", dir=resolved_output)
    )
    copied_document = run_root / "document.vsz"
    shutil.copy2(source, copied_document)
    summary_path = run_root / "studio_assistant_probe.json"
    before_png = run_root / "before.png"
    applied_png = run_root / "applied.png"
    undo_png = run_root / "undo.png"
    reopen_png = run_root / "reopen.png"
    export_root = run_root / "exports"
    source_sha256 = file_sha256(source)
    copied_initial_sha256 = file_sha256(copied_document)

    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    error: dict[str, str] | None = None
    window: Any | None = None
    reopened_window: Any | None = None

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        from sciplot_core.studio import (
            _ensure_veusz_on_path,
            export_studio_document,
        )

        _ensure_veusz_on_path()
        application = QtWidgets.QApplication.instance()
        if application is None:
            application = QtWidgets.QApplication([])
        application.setApplicationName("SciPlot Studio Assistant Probe")
        application.setQuitOnLastWindowClosed(False)

        provider = DeterministicStudioAssistantProvider()
        window, bridge = _create_window(copied_document, provider=provider)
        window.resize(1200, 820)
        window.show()
        _wait_until(
            application,
            lambda: bool(window.isVisible()),
            timeout_ms=2000,
        )

        native_startup_widgets = list(window.treeedit.selwidgets)
        native_startup_widget = (
            native_startup_widgets[0] if native_startup_widgets else None
        )
        startup_selection = {
            "selected_widget": _widget_identity(bridge.selected_widget),
            "native_selected_widget": _widget_identity(native_startup_widget),
            "selection_label": bridge.selection_label.text(),
            "ask_enabled": bridge.ask_button.isEnabled(),
            "provider_request_count": len(provider.requests),
            "has_bridge_default_selector": hasattr(
                bridge,
                "_select_default_widget",
            ),
        }
        checks.append(
            _check(
                "native_startup_selection_synchronized",
                "Studio AI follows Veusz's real initial tree selection without a bridge-specific default",
                native_startup_widget is not None
                and bridge.selected_widget is native_startup_widget
                and str(getattr(native_startup_widget, "typename", ""))
                in SUPPORTED_INSPECTOR_TYPES
                and str(native_startup_widget.path) in bridge.selection_label.text()
                and bridge.ask_button.isEnabled()
                and not provider.requests
                and not hasattr(bridge, "_select_default_widget"),
                startup_selection,
            )
        )

        axis = _axis_widget(window.document)
        bridge.set_selected_widget(axis)
        setting_path = f"{axis.path}/label"
        label_setting = window.document.resolveSettingPath(None, setting_path)
        original_label = json_safe(label_setting.get())
        ai_label = (
            f"{original_label} · AI"
            if str(original_label).strip()
            else "Frequency · AI"
        )

        unsupported = SimpleNamespace(
            typename="unsupported_probe_widget",
            parent=None,
        )
        bridge._widgets_selected([unsupported], None)
        unsupported_selection = {
            "selected_widget": _widget_identity(bridge.selected_widget),
            "selection_label": bridge.selection_label.text(),
            "ask_enabled": bridge.ask_button.isEnabled(),
        }
        checks.append(
            _check(
                "unsupported_native_selection_clears",
                "Selecting an unsupported native object clears the prior supported selection",
                bridge.selected_widget is None
                and "selected: none" in bridge.selection_label.text().casefold()
                and not bridge.ask_button.isEnabled(),
                unsupported_selection,
            )
        )

        ancestor_proxy = SimpleNamespace(
            typename="unsupported_probe_child",
            parent=axis,
        )
        bridge._widgets_selected([ancestor_proxy], None)
        ancestor_selection = {
            "selected_path": (
                str(bridge.selected_widget.path)
                if bridge.selected_widget is not None
                else None
            ),
            "axis_path": str(axis.path),
            "ask_enabled": bridge.ask_button.isEnabled(),
        }
        checks.append(
            _check(
                "supported_ancestor_fallback",
                "An unsupported clicked child resolves to its nearest supported Veusz ancestor",
                bridge.selected_widget is axis and bridge.ask_button.isEnabled(),
                ancestor_selection,
            )
        )

        bridge._widgets_selected([], None)
        provider_requests_before_blocked_ask = len(provider.requests)
        blocked_ask_error: str | None = None
        try:
            bridge.submit_intent("This must not reuse the previously selected axis.")
        except RuntimeError as exc:
            blocked_ask_error = str(exc)
        blocked_old_selection = {
            "selected_widget": _widget_identity(bridge.selected_widget),
            "selection_label": bridge.selection_label.text(),
            "ask_enabled": bridge.ask_button.isEnabled(),
            "error": blocked_ask_error,
            "provider_requests_before": provider_requests_before_blocked_ask,
            "provider_requests_after": len(provider.requests),
        }
        checks.append(
            _check(
                "empty_selection_blocks_old_object_request",
                "An empty native selection cannot continue proposing changes for the old object",
                bridge.selected_widget is None
                and "selected: none" in bridge.selection_label.text().casefold()
                and not bridge.ask_button.isEnabled()
                and blocked_ask_error is not None
                and "select a supported veusz object" in blocked_ask_error.casefold()
                and len(provider.requests) == provider_requests_before_blocked_ask
                and bridge._pending_request is None,
                blocked_old_selection,
            )
        )

        bridge.set_selected_widget(axis)

        identity = {
            "bridge_document_is_window_document": bridge.document is window.document,
            "bridge_plot_is_window_plot": bridge.plot is window.plot,
            "plot_document_is_window_document": window.plot.document is window.document,
        }
        checks.append(
            _check(
                "single_veusz_document_identity",
                "Studio, the AI bridge, and PlotWindow share one Veusz Document",
                all(identity.values()),
                identity,
            )
        )

        assistant_action = bridge.dock.toggleViewAction()
        sciplot_menu = next(
            (
                action.menu()
                for action in window.menuBar().actions()
                if action.menu() is not None
                and action.text().replace("&", "") == "SciPlot"
            ),
            None,
        )
        native_identity_before = {
            "document": id(window.document),
            "plot": id(window.plot),
            "treeedit": id(window.treeedit),
            "propdock": id(window.propdock),
            "formatdock": id(window.formatdock),
            "datadock": id(window.datadock),
            "undo_action": id(window.vzactions["edit.undo"]),
            "redo_action": id(window.vzactions["edit.redo"]),
            "undo_shortcut": window.vzactions["edit.undo"].shortcut().toString(),
            "redo_shortcut": window.vzactions["edit.redo"].shortcut().toString(),
        }
        native_plot_geometry_before = window.plot.geometry().getRect()
        dock_default_hidden = (
            not bridge.dock.isVisible() and not assistant_action.isChecked()
        )
        action_in_sciplot_menu = (
            sciplot_menu is not None and assistant_action in sciplot_menu.actions()
        )
        assistant_action.trigger()
        dock_shown = _wait_until(
            application,
            lambda: bridge.dock.isVisible() and assistant_action.isChecked(),
            timeout_ms=2000,
        )
        identity_while_shown = {
            "document": id(window.document),
            "plot": id(window.plot),
            "treeedit": id(window.treeedit),
            "propdock": id(window.propdock),
            "formatdock": id(window.formatdock),
            "datadock": id(window.datadock),
            "undo_action": id(window.vzactions["edit.undo"]),
            "redo_action": id(window.vzactions["edit.redo"]),
            "undo_shortcut": window.vzactions["edit.undo"].shortcut().toString(),
            "redo_shortcut": window.vzactions["edit.redo"].shortcut().toString(),
        }
        assistant_action.trigger()
        dock_hidden_again = _wait_until(
            application,
            lambda: not bridge.dock.isVisible() and not assistant_action.isChecked(),
            timeout_ms=2000,
        )
        native_layout_preserved = _wait_until(
            application,
            lambda: (
                window.plot.geometry().getRect()[:3] == native_plot_geometry_before[:3]
                and abs(
                    window.plot.geometry().getRect()[3] - native_plot_geometry_before[3]
                )
                <= 8
            ),
            timeout_ms=2000,
        )
        native_identity_after = {
            "document": id(window.document),
            "plot": id(window.plot),
            "treeedit": id(window.treeedit),
            "propdock": id(window.propdock),
            "formatdock": id(window.formatdock),
            "datadock": id(window.datadock),
            "undo_action": id(window.vzactions["edit.undo"]),
            "redo_action": id(window.vzactions["edit.redo"]),
            "undo_shortcut": window.vzactions["edit.undo"].shortcut().toString(),
            "redo_shortcut": window.vzactions["edit.redo"].shortcut().toString(),
        }
        native_plot_geometry_after = window.plot.geometry().getRect()
        dock_behavior = {
            "default_hidden": dock_default_hidden,
            "action_in_sciplot_menu": action_in_sciplot_menu,
            "shown_by_toggle": dock_shown,
            "hidden_by_toggle": dock_hidden_again,
            "native_layout_preserved": native_layout_preserved,
            "dock_area": int(window.dockWidgetArea(bridge.dock).value),
            "dock_floating": bridge.dock.isFloating(),
            "native_identity_before": native_identity_before,
            "identity_while_shown": identity_while_shown,
            "native_identity_after": native_identity_after,
            "native_plot_geometry_before": native_plot_geometry_before,
            "native_plot_geometry_after": native_plot_geometry_after,
        }
        checks.append(
            _check(
                "veusz_native_layout_opt_in_dock",
                "The SciPlot AI dock starts hidden and the SciPlot menu toggles it without replacing Veusz",
                dock_default_hidden
                and action_in_sciplot_menu
                and dock_shown
                and dock_hidden_again
                and native_layout_preserved
                and not bridge.dock.isFloating()
                and native_identity_before
                == identity_while_shown
                == native_identity_after
                and native_plot_geometry_before[:3] == native_plot_geometry_after[:3]
                and abs(native_plot_geometry_before[3] - native_plot_geometry_after[3])
                <= 8,
                dock_behavior,
            )
        )
        ui_scope = {
            "intro": bridge.intro_label.text(),
            "placeholder": bridge.intent_edit.placeholderText(),
            "ask_button": bridge.ask_button.text(),
            "auto_apply_checked": bridge.auto_apply.isChecked(),
            "history_path": str(bridge.history_path),
            "history_exists_before_request": bridge.history_path.exists(),
        }
        checks.append(
            _check(
                "selected_object_ui_scope",
                "The Assistant describes the current page as context, names selected-object scope, and does not auto-apply by default",
                "rendered page" in bridge.intro_label.text().casefold()
                and "selected object" in bridge.intro_label.text().casefold()
                and "selected object" in bridge.ask_button.text().casefold()
                and "selected axis label"
                in bridge.intent_edit.placeholderText().casefold()
                and bridge.auto_apply.isChecked() is False
                and not bridge.history_path.exists(),
                ui_scope,
            )
        )
        checks.append(
            _check(
                "axis_selected",
                "The probe selects a supported visible axis through the public bridge API",
                bridge.selected_widget is axis
                and str(axis.typename) == "axis"
                and setting_path.endswith("/label"),
                {
                    "axis_path": str(axis.path),
                    "axis_name": str(axis.name),
                    "setting_path": setting_path,
                    "original_label": original_label,
                },
            )
        )

        before_capture = _capture_plot(bridge, before_png)
        applied_events: list[dict[str, Any]] = []
        rejected_events: list[str] = []
        submitted_requests: list[AssistantRequest] = []
        history_observations: list[dict[str, Any]] = []
        bridge.proposalApplied.connect(lambda value: applied_events.append(dict(value)))
        bridge.requestRejected.connect(rejected_events.append)
        bridge.requestSubmitted.connect(submitted_requests.append)
        bridge.historyRecorded.connect(
            lambda event: history_observations.append(
                {
                    "status": str(event.get("status")),
                    "document_changeset": int(window.document.changeset),
                }
            )
        )

        blocked_proposal_target = f"{original_label} · obsolete AI"
        provider.configure(next_value=blocked_proposal_target)
        blocked_proposal_request = bridge.submit_intent(
            "Prepare a proposal that must be discarded when selection changes."
        )
        blocked_proposal_ready = _wait_until(
            application,
            lambda: bridge.pending_batch is not None and not bridge.runner.active,
        )
        if not blocked_proposal_ready:
            raise RuntimeError(
                "The old-object selection proposal did not become ready."
            )
        bridge._widgets_selected([unsupported], None)
        blocked_proposal_apply = bridge.accept_pending()
        blocked_proposal_history = [
            event
            for event in read_assistant_history(bridge.history_path)
            if event.get("request_id") == blocked_proposal_request.request_id
        ]
        checks.append(
            _check(
                "old_object_proposal_discarded_on_selection_change",
                "A ready proposal cannot continue after native selection leaves its target",
                bridge.selected_widget is None
                and not bridge.ask_button.isEnabled()
                and not bridge.apply_button.isEnabled()
                and bridge.pending_batch is None
                and bridge._pending_request is None
                and blocked_proposal_apply is None
                and json_safe(label_setting.get()) == original_label
                and [event.get("status") for event in blocked_proposal_history]
                == ["submitted", "proposal_ready", "rejected"]
                and blocked_proposal_history[-1].get("reason_code")
                == "selected_object_changed",
                {
                    "statuses": [
                        event.get("status") for event in blocked_proposal_history
                    ],
                    "terminal": (
                        blocked_proposal_history[-1]
                        if blocked_proposal_history
                        else None
                    ),
                    "selected_widget": _widget_identity(bridge.selected_widget),
                    "ask_enabled": bridge.ask_button.isEnabled(),
                    "apply_enabled": bridge.apply_button.isEnabled(),
                    "label_value": json_safe(label_setting.get()),
                },
            )
        )
        bridge.set_selected_widget(axis)

        provider.configure(next_value=ai_label)
        request = bridge.submit_intent(
            "Inspect the current plot and make the selected x-axis label visibly clearer."
        )
        proposal_completed = _wait_until(
            application,
            lambda: bridge.pending_batch is not None and not bridge.runner.active,
        )
        if not proposal_completed:
            raise RuntimeError("The deterministic Assistant proposal did not complete.")
        manual_apply_result = bridge.accept_pending()
        positive_completed = _wait_until(
            application,
            lambda: bool(applied_events),
        )
        if not positive_completed:
            raise RuntimeError("The deterministic Assistant edit did not complete.")
        if manual_apply_result is None:
            raise RuntimeError("The deterministic Assistant proposal was not applied.")

        provider_request = next(
            item for item in provider.requests if item.request_id == request.request_id
        )
        request_capability = _axis_label_capability(request)
        provider_preview = provider_request.visual_preview
        provider_png = _visual_preview_bytes(provider_preview)
        request_visual = {
            "request_revision": request.base_revision,
            "context_revision": request.context["revision"],
            "preview": _visual_preview_metadata(request.visual_preview),
            "png_size_bytes": len(provider_png),
            "png_sha256": hashlib.sha256(provider_png).hexdigest(),
            "capability": request_capability,
        }
        checks.append(
            _check(
                "exact_current_visual_request",
                "The provider receives the exact-current PNG, hash, revision, and typed axis capability",
                bool(submitted_requests)
                and request.request_id == provider_request.request_id
                and request.base_revision == before_capture["revision"]
                and request.context["revision"] == request.base_revision
                and isinstance(request.visual_preview, dict)
                and request.visual_preview["sha256"] == before_capture["sha256"]
                and hashlib.sha256(provider_png).hexdigest()
                == request.visual_preview["sha256"]
                and int(request.visual_preview["width"]) == before_capture["width"]
                and int(request.visual_preview["height"]) == before_capture["height"]
                and int(request.visual_preview["revision"]) == request.base_revision
                and request.context.get("raw_dataset_arrays_included") is False
                and "datasets" not in request.context
                and request_capability["setting_path"] == setting_path
                and json_safe(request_capability["current_value"]) == original_label,
                request_visual,
            )
        )

        applied_capture = _capture_plot(bridge, applied_png)
        applied_value = json_safe(label_setting.get())
        apply_result = applied_events[0]
        checks.append(
            _check(
                "typed_axis_label_manual_apply",
                "One explicitly accepted typed axis-label proposal applies to the live Veusz plot and changes its render",
                applied_value == ai_label
                and apply_result["operations"][0]["setting_path"] == setting_path
                and apply_result["operations"][0]["old_value"] == original_label
                and apply_result["operations"][0]["new_value"] == ai_label
                and apply_result["render_changed"] is True
                and apply_result["verification_status"] == "applied"
                and apply_result["history_finalized"] is True
                and applied_capture["sha256"] != before_capture["sha256"]
                and bridge._pending_request is None
                and bridge._pending_response is None
                and window.document.canUndo()
                and str(window.document.historyundo[-1].descr).startswith(
                    "SciPlot AI · "
                ),
                {
                    "applied_value": applied_value,
                    "apply_result": apply_result,
                    "capture": applied_capture,
                    "undo_description": str(window.document.historyundo[-1].descr),
                },
            )
        )

        history_events = read_assistant_history(bridge.history_path)
        positive_history = [
            event
            for event in history_events
            if event.get("request_id") == request.request_id
        ]
        history_text = bridge.history_path.read_text(encoding="utf-8")
        apply_started_event = next(
            (
                event
                for event in positive_history
                if event.get("status") == "apply_started"
            ),
            {},
        )
        applied_history_event = next(
            (event for event in positive_history if event.get("status") == "applied"),
            {},
        )
        apply_started_observation = next(
            (
                event
                for event in history_observations
                if event.get("status") == "apply_started"
            ),
            {},
        )
        applied_observation = next(
            (
                event
                for event in history_observations
                if event.get("status") == "applied"
            ),
            {},
        )
        history_safety = {
            "path": str(bridge.history_path),
            "statuses": [event.get("status") for event in positive_history],
            "apply_started": apply_started_event,
            "applied": applied_history_event,
            "observations": history_observations,
            "line_count": len(history_events),
        }
        checks.append(
            _check(
                "durable_privacy_minimal_assistant_history",
                "The fsynced allowlisted history binds request, operations, and before/after renders without retaining images, prompts, model text, values, secrets, or filesystem paths",
                [event.get("status") for event in positive_history]
                == [
                    "submitted",
                    "proposal_ready",
                    "apply_started",
                    "applied",
                ]
                and apply_started_observation.get("document_changeset")
                == request.base_revision
                and applied_observation.get("document_changeset")
                == apply_result["applied_revision"]
                and apply_started_event.get("before_page_render_sha256")
                == before_capture["sha256"]
                and applied_history_event.get("after_page_render_sha256")
                == applied_capture["sha256"]
                and applied_history_event.get("render_changed") is True
                and applied_history_event.get("operations", [{}])[0].get(
                    "old_value_sha256"
                )
                == canonical_value_sha256(original_label)
                and applied_history_event.get("operations", [{}])[0].get(
                    "new_value_sha256"
                )
                == canonical_value_sha256(ai_label)
                and request.visual_preview["base64"] not in history_text
                and request.intent not in history_text
                and provider_request.intent not in history_text
                and "The exact-current axis label has one bounded edit."
                not in history_text
                and "Offline Studio axis-label probe" not in history_text
                and ai_label not in history_text
                and str(copied_document) not in history_text
                and '"intent"' not in history_text
                and '"visual_preview"' not in history_text
                and '"understanding"' not in history_text
                and '"rationale"' not in history_text
                and '"api_key"' not in history_text
                and '"authorization"' not in history_text,
                history_safety,
            )
        )

        window.slotEditUndo()
        undo_capture = _capture_plot(bridge, undo_png)
        undo_value = json_safe(label_setting.get())
        checks.append(
            _check(
                "native_veusz_undo",
                "Veusz native Undo restores the exact prior label and render",
                undo_value == original_label
                and undo_capture["sha256"] == before_capture["sha256"]
                and window.document.canRedo(),
                {
                    "value": undo_value,
                    "capture": undo_capture,
                    "can_redo": window.document.canRedo(),
                },
            )
        )

        window.slotEditRedo()
        redo_capture = _capture_plot(bridge, run_root / "redo.png")
        redo_value = json_safe(label_setting.get())
        checks.append(
            _check(
                "native_veusz_redo",
                "Veusz native Redo reapplies the complete AI batch",
                redo_value == ai_label
                and redo_capture["sha256"] == applied_capture["sha256"],
                {"value": redo_value, "capture": redo_capture},
            )
        )

        from veusz.document.operations import OperationSettingSet

        manual_label = f"{ai_label} · manual"
        window.document.applyOperation(
            OperationSettingSet(setting_path, label_setting.normalize(manual_label))
        )
        manual_context = bridge.context_for_current_selection()
        manual_capability = next(
            item
            for item in manual_context["editing_capabilities"]["allowed_operations"]
            if item["setting_path"] == setting_path
        )
        checks.append(
            _check(
                "manual_edit_reread",
                "AI context reads an exact-current value changed through native Veusz editing",
                json_safe(label_setting.get()) == manual_label
                and json_safe(manual_capability["current_value"]) == manual_label
                and manual_context["revision"] == int(window.document.changeset),
                {
                    "manual_value": json_safe(label_setting.get()),
                    "context_value": manual_capability["current_value"],
                    "revision": manual_context["revision"],
                },
            )
        )

        reject_target = f"{manual_label} · rejected AI"
        reject_revision = int(window.document.changeset)
        reject_render = bridge.current_render_sha256()
        provider.configure(next_value=reject_target)
        reject_request = bridge.submit_intent(
            "Propose a bounded label change that will be explicitly rejected."
        )
        reject_ready = _wait_until(
            application,
            lambda: bridge.pending_batch is not None and not bridge.runner.active,
        )
        if not reject_ready:
            raise RuntimeError("The rejection proposal did not become ready.")
        bridge.reject_pending()
        reject_history = [
            event
            for event in read_assistant_history(bridge.history_path)
            if event.get("request_id") == reject_request.request_id
        ]
        checks.append(
            _check(
                "explicit_rejection_history",
                "Reject records a typed terminal outcome without changing the live Veusz Document",
                json_safe(label_setting.get()) == manual_label
                and int(window.document.changeset) == reject_revision
                and bridge.current_render_sha256() == reject_render
                and [event.get("status") for event in reject_history]
                == ["submitted", "proposal_ready", "rejected"]
                and reject_history[-1].get("reason_code") == "user_rejected"
                and reject_history[-1]
                .get("operations", [{}])[0]
                .get("new_value_sha256")
                == canonical_value_sha256(reject_target)
                and bridge._pending_request is None,
                {
                    "statuses": [event.get("status") for event in reject_history],
                    "terminal": reject_history[-1] if reject_history else None,
                    "revision": int(window.document.changeset),
                },
            )
        )

        stale_target = f"{manual_label} · stale AI"
        provider.configure(next_value=stale_target, delayed=True)
        stale_history_before = len(window.document.historyundo)
        stale_applied_before = len(applied_events)
        stale_rejected_before = len(rejected_events)
        stale_request = bridge.submit_intent(
            "Delay this bounded axis-label edit so concurrent native editing can be tested."
        )
        provider_started = _wait_until(
            application,
            lambda: provider.started,
            timeout_ms=4000,
        )
        if not provider_started:
            raise RuntimeError("The delayed deterministic provider did not start.")
        concurrent_label = f"{manual_label} · concurrent"
        window.document.applyOperation(
            OperationSettingSet(
                setting_path,
                label_setting.normalize(concurrent_label),
            )
        )
        concurrent_revision = int(window.document.changeset)
        provider.release()
        stale_completed = _wait_until(
            application,
            lambda: (
                len(rejected_events) > stale_rejected_before
                and not bridge.runner.active
            ),
        )
        if not stale_completed:
            raise RuntimeError("The stale Assistant response was not resolved.")
        stale_request_history = [
            event
            for event in read_assistant_history(bridge.history_path)
            if event.get("request_id") == stale_request.request_id
        ]
        checks.append(
            _check(
                "stale_response_atomic_rejection",
                "A concurrent native edit makes the delayed AI response stale and rejects its whole batch",
                stale_request.base_revision != concurrent_revision
                and json_safe(label_setting.get()) == concurrent_label
                and len(applied_events) == stale_applied_before
                and len(window.document.historyundo) == stale_history_before + 1
                and not bridge.pending_batch
                and bridge._pending_request is None
                and [event.get("status") for event in stale_request_history]
                == ["submitted", "rejected"]
                and stale_request_history[-1].get("reason_code")
                == "document_revision_changed"
                and any(
                    "changed while AI was inspecting" in message
                    for message in rejected_events
                ),
                {
                    "request_revision": stale_request.base_revision,
                    "concurrent_revision": concurrent_revision,
                    "current_value": json_safe(label_setting.get()),
                    "history_before": stale_history_before,
                    "history_after": len(window.document.historyundo),
                    "rejections": rejected_events,
                    "assistant_history": stale_request_history,
                },
            )
        )

        unverified_target = f"{concurrent_label} · unverified AI"
        provider.configure(next_value=unverified_target)
        unverified_request = bridge.submit_intent(
            "Apply one bounded label change while after-render verification is forced to fail."
        )
        unverified_ready = _wait_until(
            application,
            lambda: bridge.pending_batch is not None and not bridge.runner.active,
        )
        if not unverified_ready:
            raise RuntimeError("The unverified proposal did not become ready.")
        original_render_method = bridge.current_render_sha256

        def fail_after_render() -> str:
            raise RuntimeError("forced after-render verification failure")

        bridge.current_render_sha256 = fail_after_render
        try:
            unverified_result = bridge.accept_pending()
        finally:
            bridge.current_render_sha256 = original_render_method
        if unverified_result is None:
            raise RuntimeError("The unverified Assistant operation did not apply.")
        unverified_history = [
            event
            for event in read_assistant_history(bridge.history_path)
            if event.get("request_id") == unverified_request.request_id
        ]
        value_before_unverified_undo = json_safe(label_setting.get())
        window.slotEditUndo()
        value_after_unverified_undo = json_safe(label_setting.get())
        checks.append(
            _check(
                "applied_unverified_is_honest_and_undoable",
                "An after-render verification failure remains an applied native Undo step and is never reported as not applied",
                value_before_unverified_undo == unverified_target
                and value_after_unverified_undo == concurrent_label
                and unverified_result["verification_status"] == "applied_unverified"
                and unverified_result["after_render_sha256"] is None
                and unverified_result["history_finalized"] is True
                and [event.get("status") for event in unverified_history]
                == [
                    "submitted",
                    "proposal_ready",
                    "apply_started",
                    "applied_unverified",
                ]
                and unverified_history[-1].get("reason_code")
                == "after_render_verification_failed"
                and "after_page_render_sha256" not in unverified_history[-1]
                and bridge._pending_request is None
                and "not applied" not in bridge.status_label.text().casefold(),
                {
                    "result": unverified_result,
                    "statuses": [event.get("status") for event in unverified_history],
                    "terminal": (
                        unverified_history[-1] if unverified_history else None
                    ),
                    "value_before_undo": value_before_unverified_undo,
                    "value_after_undo": value_after_unverified_undo,
                    "status_text": bridge.status_label.text(),
                },
            )
        )

        history_failure_target = f"{concurrent_label} · blocked AI"
        provider.configure(next_value=history_failure_target)
        history_failure_request = bridge.submit_intent(
            "Propose a change that must not apply when apply-start history fails."
        )
        history_failure_ready = _wait_until(
            application,
            lambda: bridge.pending_batch is not None and not bridge.runner.active,
        )
        if not history_failure_ready:
            raise RuntimeError("The history-failure proposal did not become ready.")
        history_failure_revision = int(window.document.changeset)
        history_failure_undo_count = len(window.document.historyundo)
        original_record_history = bridge._record_history

        def fail_apply_started_history(**kwargs: Any) -> dict[str, Any]:
            if kwargs.get("status") == "apply_started":
                raise OSError("forced apply-start history failure")
            return original_record_history(**kwargs)

        bridge._record_history = fail_apply_started_history
        try:
            blocked_result = bridge.accept_pending()
        finally:
            bridge._record_history = original_record_history
        history_failure_value = json_safe(label_setting.get())
        history_failure_pending = bridge.pending_batch is not None
        bridge.reject_pending()
        history_failure_events = [
            event
            for event in read_assistant_history(bridge.history_path)
            if event.get("request_id") == history_failure_request.request_id
        ]
        checks.append(
            _check(
                "apply_started_history_is_fail_closed",
                "A durable apply-start history failure prevents any Veusz Document mutation",
                blocked_result is None
                and history_failure_value == concurrent_label
                and int(window.document.changeset) == history_failure_revision
                and len(window.document.historyundo) == history_failure_undo_count
                and history_failure_pending
                and [event.get("status") for event in history_failure_events]
                == ["submitted", "proposal_ready", "rejected"]
                and history_failure_events[-1].get("reason_code") == "user_rejected"
                and bridge._pending_request is None,
                {
                    "statuses": [
                        event.get("status") for event in history_failure_events
                    ],
                    "value": history_failure_value,
                    "revision": int(window.document.changeset),
                    "undo_count": len(window.document.historyundo),
                    "blocked_status": bridge.status_label.text(),
                },
            )
        )

        final_value = json_safe(label_setting.get())
        window.slotFileSave()
        saved_sha256 = file_sha256(copied_document)
        _close_window(window)
        window = None

        reopened_window, reopened_bridge = _create_window(
            copied_document,
            provider=None,
        )
        reopened_window.resize(1200, 820)
        reopened_window.show()
        _wait_until(
            application,
            lambda: bool(reopened_window.isVisible()),
            timeout_ms=2000,
        )
        reopened_setting = reopened_window.document.resolveSettingPath(
            None,
            setting_path,
        )
        reopened_value = json_safe(reopened_setting.get())
        reopen_capture = _capture_plot(reopened_bridge, reopen_png)
        checks.append(
            _check(
                "save_reopen_current_value",
                "The exact-current manually and AI edited VSZ saves and reopens with its final value",
                saved_sha256 == file_sha256(copied_document)
                and saved_sha256 != copied_initial_sha256
                and reopened_value == final_value
                and reopen_capture["sha256"],
                {
                    "saved_sha256": saved_sha256,
                    "reopened_value": reopened_value,
                    "expected_value": final_value,
                    "capture": reopen_capture,
                },
            )
        )
        _close_window(reopened_window)
        reopened_window = None

        export_payload = export_studio_document(
            copied_document,
            formats=["pdf", "tiff_300"],
            output_dir=export_root,
        )
        exports = [
            dict(item)
            for item in export_payload.get("exports", [])
            if isinstance(item, dict)
        ]
        ready_formats = {
            str(item.get("format"))
            for item in exports
            if item.get("exists") is True and int(item.get("size_bytes") or 0) > 0
        }
        checks.append(
            _check(
                "exact_current_pdf_tiff_export",
                "The saved exact-current VSZ exports a non-empty PDF/TIFF pair",
                {"pdf", "tiff_300"} <= ready_formats,
                {"formats": sorted(ready_formats), "exports": exports},
            )
        )
        checks.append(
            _check(
                "source_document_immutable",
                "The probe modifies only its copied VSZ",
                file_sha256(source) == source_sha256
                and source != copied_document
                and copied_initial_sha256 == source_sha256,
                {
                    "source": str(source),
                    "source_sha256": source_sha256,
                    "copied_document": str(copied_document),
                },
            )
        )

        final_history_events = read_assistant_history(bridge.history_path)
        evidence = {
            "document_identity": identity,
            "dock_behavior": dock_behavior,
            "axis_path": str(axis.path),
            "setting_path": setting_path,
            "original_label": original_label,
            "ai_label": ai_label,
            "manual_label": manual_label,
            "concurrent_label": concurrent_label,
            "final_value": final_value,
            "positive_request": {
                "request_id": request.request_id,
                "base_revision": request.base_revision,
                "payload_sha256": request.payload_sha256,
                "visual_preview": _visual_preview_metadata(request.visual_preview),
            },
            "stale_request": {
                "request_id": stale_request.request_id,
                "base_revision": stale_request.base_revision,
                "concurrent_revision": concurrent_revision,
            },
            "renders": {
                "before": before_capture,
                "applied": applied_capture,
                "undo": undo_capture,
                "redo": redo_capture,
                "reopen": reopen_capture,
            },
            "exports": exports,
            "source_sha256": source_sha256,
            "saved_document_sha256": saved_sha256,
            "assistant_history": {
                "path": str(bridge.history_path),
                "event_count": len(final_history_events),
                "statuses": [event.get("status") for event in final_history_events],
            },
        }
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "studio_assistant_probe_exception",
                "The offline Studio Assistant lifecycle completes without an exception",
                False,
                error,
            )
        )
    finally:
        _close_window(window)
        _close_window(reopened_window)

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": STUDIO_ASSISTANT_PROBE_KIND,
        "version": STUDIO_ASSISTANT_PROBE_VERSION,
        "generated_at": _now(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "evidence": evidence,
        "artifacts": {
            "run_root": str(run_root),
            "source_document": str(source),
            "copied_document": str(copied_document),
            "before_png": str(before_png),
            "applied_png": str(applied_png),
            "undo_png": str(undo_png),
            "reopen_png": str(reopen_png),
            "exports": str(export_root),
            "assistant_history": (
                str(bridge.history_path) if "bridge" in locals() else None
            ),
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "The injected provider is deterministic and offline; this proves the "
            "typed Studio host lifecycle, not live OpenAI model quality.",
            "The probe modifies a copied VSZ. Its result does not strengthen the "
            "evidence tier or authorization status of the supplied source.",
            "Pixel hashes verify exact-current render transitions, while broader "
            "publication judgment remains a separate visual-review task.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise the offline SciPlot AI bridge inside the native Veusz "
            "MainWindow using a copied VSZ."
        )
    )
    parser.add_argument(
        "--document",
        type=Path,
        required=True,
        help="Existing Veusz .vsz document to copy and exercise.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for the isolated probe run.",
    )
    return parser


def _maybe_reexec_with_qt_runtime(argv: list[str]) -> None:
    if (
        sys.platform != "darwin"
        or os.environ.get("SCIPLOT_STUDIO_ASSISTANT_PROBE_QT_RUNTIME") == "1"
    ):
        return
    from sciplot_core.studio import _qt_framework_paths

    framework_paths = _qt_framework_paths()
    if not framework_paths:
        return
    env = os.environ.copy()
    joined = ":".join(str(path) for path in framework_paths)
    for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
        current = env.get(key)
        env[key] = f"{joined}:{current}" if current else joined
    env["SCIPLOT_STUDIO_ASSISTANT_PROBE_QT_RUNTIME"] = "1"
    os.execvpe(
        sys.executable,
        [
            sys.executable,
            "-m",
            "sciplot_core.studio_assistant_probe",
            *argv,
        ],
        env,
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        _maybe_reexec_with_qt_runtime(sys.argv[1:])
    args = _build_parser().parse_args(argv)
    payload = run_studio_assistant_probe(
        args.document,
        output_root=args.out,
    )
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "STUDIO_ASSISTANT_PROBE_KIND",
    "STUDIO_ASSISTANT_PROBE_VERSION",
    "DeterministicStudioAssistantProvider",
    "run_studio_assistant_probe",
]
