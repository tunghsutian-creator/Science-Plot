from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_core.canvas.persistence import read_operation_journal
from sciplot_core.canvas.provider import (
    AssistantCancellationToken,
    AssistantProgressEvent,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantRequestRecord,
    AssistantResponse,
)

CANVAS_ASSISTANT_PROBE_KIND = "sciplot_canvas_assistant_probe"
CANVAS_ASSISTANT_PROBE_VERSION = 1


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


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(child.read_bytes())
    return digest.hexdigest()


def _copy_target(source: Path, run_root: Path) -> Path:
    if source.is_dir():
        target = run_root / "project"
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns(
                ".sciplot_canvas",
                "runs",
                "__pycache__",
            ),
        )
        return target
    target = run_root / source.name
    shutil.copy2(source, target)
    return target


def _edited_value(value: Any, suffix: str) -> str:
    text = str(value or "").strip()
    return f"{text} {suffix}".strip() if text else suffix.strip(" []")


def _setting_batch(
    *,
    revision: int,
    provider: str,
    target_id: str,
    setting_path: str,
    before: Any,
    after: Any,
    rationale: str,
) -> CanvasOperationBatch:
    return CanvasOperationBatch(
        base_revision=revision,
        provider=provider,
        rationale=rationale,
        operations=(
            CanvasOperation.set_setting(
                target_id=target_id,
                setting_path=setting_path,
                value=after,
                expected_value=before,
                require_expected_value=True,
            ),
        ),
    )


class _DeterministicCanvasProvider:
    """Controllable typed provider used to exercise the real threaded UI path."""

    def __init__(self) -> None:
        self.descriptor = AssistantProviderDescriptor(
            provider_id="assistant_probe_threaded_provider",
            display_name="SciPlot Probe Assistant",
            model_label="deterministic",
            capabilities=("canvas_operation_batch", "cancellation"),
        )
        self.first_started = threading.Event()
        self.first_release = threading.Event()
        self.cancel_started = threading.Event()
        self.cancellation_observed = threading.Event()
        self.worker_thread_ids: list[int] = []
        self.request_count = 0
        self.target_id: str | None = None
        self.setting_path: str | None = None
        self.before_value: Any = None
        self.after_value: Any = None

    def configure(
        self,
        *,
        target_id: str,
        setting_path: str,
        before_value: Any,
        after_value: Any,
    ) -> None:
        self.target_id = target_id
        self.setting_path = setting_path
        self.before_value = before_value
        self.after_value = after_value

    def _configured(self) -> tuple[str, str]:
        if self.target_id is None or self.setting_path is None:
            raise RuntimeError("Deterministic provider target is not configured.")
        return self.target_id, self.setting_path

    def generate(
        self,
        request: AssistantRequest,
        *,
        emit_progress: Any,
        cancellation: AssistantCancellationToken,
    ) -> AssistantResponse:
        target_id, setting_path = self._configured()
        self.request_count += 1
        ordinal = self.request_count
        self.worker_thread_ids.append(threading.get_ident())
        if ordinal == 1:
            emit_progress(
                AssistantProgressEvent(
                    request_id=request.request_id,
                    provider_id=request.provider_id,
                    sequence=1,
                    stage="understanding",
                    message="Reading the selected object and exact-current version.",
                    cancellable=self.descriptor.supports_cancellation,
                    progress=0.25,
                )
            )
            self.first_started.set()
            while not self.first_release.wait(0.01):
                cancellation.raise_if_cancelled()
            emit_progress(
                AssistantProgressEvent(
                    request_id=request.request_id,
                    provider_id=request.provider_id,
                    sequence=2,
                    stage="validating",
                    message="Validating one typed Canvas operation.",
                    cancellable=self.descriptor.supports_cancellation,
                    progress=0.85,
                )
            )
            batch = _setting_batch(
                revision=request.base_revision,
                provider=request.provider_id,
                target_id=target_id,
                setting_path=setting_path,
                before=self.before_value,
                after=self.after_value,
                rationale=(
                    "Apply the requested visible text refinement to the selected "
                    "object."
                ),
            )
            return AssistantResponse(
                request_id=request.request_id,
                transaction_id=request.transaction_id,
                provider_id=request.provider_id,
                request_sha256=request.payload_sha256,
                status="proposal",
                understanding=(
                    "Change one visible text setting on the selected object and "
                    "leave data, layout, and export settings unchanged."
                ),
                proposal_kind="canvas_operation_batch",
                proposal=batch.to_dict(),
            )

        emit_progress(
            AssistantProgressEvent(
                request_id=request.request_id,
                provider_id=request.provider_id,
                sequence=1,
                stage="planning",
                message="Preparing a second typed refinement.",
                cancellable=True,
                progress=None,
            )
        )
        self.cancel_started.set()
        while not cancellation.cancelled:
            time.sleep(0.005)
        self.cancellation_observed.set()
        late_batch = _setting_batch(
            revision=request.base_revision,
            provider=request.provider_id,
            target_id=target_id,
            setting_path=setting_path,
            before=self.after_value,
            after=_edited_value(self.after_value, "[Late Result]"),
            rationale="This late proposal must be discarded after cancellation.",
        )
        return AssistantResponse(
            request_id=request.request_id,
            transaction_id=request.transaction_id,
            provider_id=request.provider_id,
            request_sha256=request.payload_sha256,
            status="proposal",
            understanding=(
                "A deliberately late proposal returned after cancellation."
            ),
            proposal_kind="canvas_operation_batch",
            proposal=late_batch.to_dict(),
        )


def _wait_until(
    application: Any,
    predicate: Any,
    *,
    timeout_seconds: float = 5.0,
) -> bool:
    from PyQt6 import QtCore, QtTest

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        application.sendPostedEvents()
        application.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents,
            25,
        )
        if bool(predicate()):
            return True
        QtTest.QTest.qWait(10)
    application.processEvents()
    return bool(predicate())


def _rejects(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def _capture_window(
    window: Any,
    path: Path,
    *,
    application: Any,
) -> dict[str, Any]:
    from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

    window.controller.adapter.force_redraw()
    window._sync_ui()
    window.ensurePolished()
    for widget in window.findChildren(QtWidgets.QWidget):
        widget.ensurePolished()
        widget.update()
    window.update()
    QtTest.QTest.qWait(150)
    for _ in range(8):
        application.sendPostedEvents()
        application.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents,
            50,
        )
    image = (
        window.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_RGB888)
    )
    saved = image.save(str(path))
    black_pixels = 0
    sample_count = 0
    sample_step = 8
    for y in range(0, image.height(), sample_step):
        for x in range(0, image.width(), sample_step):
            color = image.pixelColor(x, y)
            sample_count += 1
            if color.red() < 8 and color.green() < 8 and color.blue() < 8:
                black_pixels += 1
    black_ratio = black_pixels / sample_count if sample_count else 1.0
    return {
        "saved": bool(saved),
        "width": image.width(),
        "height": image.height(),
        "sampled_black_ratio": black_ratio,
        "visually_plausible": bool(
            saved
            and image.width() >= 1000
            and image.height() >= 700
            and black_ratio < 0.08
        ),
    }


def run_canvas_assistant_probe(
    target: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Exercise visible, provider-neutral Assistant transaction semantics."""

    source = target.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="canvas_assistant_probe_", dir=resolved_output)
    )
    summary_path = run_root / "canvas_assistant_probe.json"
    proposal_screenshot = run_root / "assistant_proposal.png"
    applied_screenshot = run_root / "assistant_applied.png"
    provider_working_screenshot = run_root / "assistant_provider_working.png"
    provider_proposal_screenshot = run_root / "assistant_provider_proposal.png"
    provider_applied_screenshot = run_root / "assistant_provider_applied.png"
    stderr_log = run_root / "logs" / "canvas_assistant_stderr.log"
    progress_path = run_root / "progress.log"
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    error: dict[str, str] | None = None
    windows: list[Any] = []

    source_hash_before = _tree_hash(source)
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        from sciplot_core.studio import _capture_process_stderr
        from sciplot_gui.main_window import SciPlotCanvasWindow
        from sciplot_gui.workspace import resolve_canvas_workspace

        application = QtWidgets.QApplication.instance()
        if application is None:
            application = QtWidgets.QApplication([])
        application.setApplicationName("SciPlot Canvas Assistant Probe")
        application.setQuitOnLastWindowClosed(False)
        copied_target = _copy_target(source, run_root)
        progress_path.write_text("target_copied\n", encoding="utf-8")
        workspace = resolve_canvas_workspace(copied_target)
        progress_path.write_text("workspace_resolved\n", encoding="utf-8")
        document_hash_before = file_sha256(workspace.document_path)
        raw_root = (
            workspace.project_dir / "raw"
            if workspace.project_dir is not None
            and (workspace.project_dir / "raw").exists()
            else None
        )
        raw_hash_before = _tree_hash(raw_root) if raw_root is not None else None

        with _capture_process_stderr(stderr_log):
            window = SciPlotCanvasWindow(workspace, interactive=False)
            windows.append(window)
            window.resize(1380, 860)
            window.show()
            application.processEvents()
            idle_provider_optional = (
                not window.assistant.active
                and window.assistant_action.isEnabled()
                and window.inspector_tabs.count() == 3
                and window.assistant_panel.state_chip.text() == "Idle"
            )
            target_info = (
                window.controller.adapter.first_visible_text_target(
                    window.controller.session
                )
            )
            setting_path = str(target_info["setting_path"])
            target_id = str(target_info["object_id"])
            original_value = window.controller.adapter.setting_value(setting_path)
            baseline_render = window.controller.adapter.render_fingerprint()
            baseline_revision = window.controller.session.revision
            baseline_page = window.controller.session.current_page
            baseline_viewport = window.controller.session.viewport.to_dict()

            start = window.begin_assistant_transaction(
                provider="assistant_probe_provider",
                rationale=(
                    "Verify the visible provider-neutral Canvas transaction."
                ),
            )
            context = start["context"]
            transaction = window.assistant.transaction
            if transaction is None:
                raise RuntimeError("Assistant transaction did not start.")
            baseline_vsz = window.controller._resolve_transaction_artifact(
                str(transaction.snapshot_path),
                transaction_id=transaction.transaction_id,
            )
            baseline_review = window.controller._resolve_transaction_artifact(
                str(transaction.review_snapshot_path),
                transaction_id=transaction.transaction_id,
            )
            baseline_integrity = bool(
                baseline_vsz.is_file()
                and file_sha256(baseline_vsz) == transaction.snapshot_sha256
                and baseline_review.is_file()
                and file_sha256(baseline_review)
                == transaction.review_snapshot_sha256
            )
            first_value = _edited_value(original_value, "[Assistant A]")
            first_batch = _setting_batch(
                revision=window.controller.session.revision,
                provider=transaction.provider,
                target_id=target_id,
                setting_path=setting_path,
                before=original_value,
                after=first_value,
                rationale="Rename one visible scientific text target.",
            )
            preview = window.propose_assistant_batch(first_batch)
            proposal_capture = _capture_window(
                window,
                proposal_screenshot,
                application=application,
            )
            preview_zero_mutation = bool(
                window.controller.session.revision == baseline_revision
                and window.controller.adapter.setting_value(setting_path)
                == original_value
                and window.controller.adapter.render_fingerprint()
                == baseline_render
                and preview.get("publication_document_changed") is False
            )
            proposal_ui = {
                "tab_index": window.inspector_tabs.currentIndex(),
                "state_chip": window.assistant_panel.state_chip.text(),
                "change_rows": window.assistant_panel.change_count,
                "accept_enabled": (
                    window.assistant_panel.accept_button.isEnabled()
                ),
                "save_locked": not window.save_action.isEnabled(),
                "edit_locked": not window.inspector_panel.isEnabled(),
            }

            window.pause_assistant_transaction()
            paused_accept_rejected = False
            try:
                window.accept_assistant_proposal()
            except RuntimeError:
                paused_accept_rejected = True
            window.resume_assistant_transaction()
            accept_started = time.perf_counter()
            first_accept = window.accept_assistant_proposal()
            first_latency_ms = (time.perf_counter() - accept_started) * 1000.0
            application.processEvents()
            first_render = window.controller.adapter.render_fingerprint()
            first_live = bool(
                window.controller.adapter.setting_value(setting_path)
                == first_value
                and first_render != baseline_render
                and first_accept["entry"]["revision"] == baseline_revision + 1
            )

            second_value = _edited_value(first_value, "[Assistant B]")
            second_batch = _setting_batch(
                revision=window.controller.session.revision,
                provider=transaction.provider,
                target_id=target_id,
                setting_path=setting_path,
                before=first_value,
                after=second_value,
                rationale="Apply a second visible text refinement.",
            )
            window.propose_assistant_batch(second_batch)
            second_accept = window.accept_assistant_proposal()
            second_render = window.controller.adapter.render_fingerprint()
            applied_capture = _capture_window(
                window,
                applied_screenshot,
                application=application,
            )
            undo_entry = window.undo_assistant_batch()
            per_batch_undo = bool(
                window.controller.adapter.setting_value(setting_path)
                == first_value
                and window.controller.adapter.render_fingerprint()
                == first_render
                and undo_entry.get("batch_id") == second_batch.batch_id
            )

            rejected_value = _edited_value(first_value, "[Rejected]")
            rejected_batch = _setting_batch(
                revision=window.controller.session.revision,
                provider=transaction.provider,
                target_id=target_id,
                setting_path=setting_path,
                before=first_value,
                after=rejected_value,
                rationale="This proposal is intentionally rejected.",
            )
            before_reject_render = window.controller.adapter.render_fingerprint()
            before_reject_revision = window.controller.session.revision
            window.propose_assistant_batch(rejected_batch)
            reject_entry = window.reject_assistant_proposal(
                reason="Probe rejection."
            )
            proposal_rejection_isolated = bool(
                reject_entry.get("publication_document_changed") is False
                and window.controller.session.revision
                == before_reject_revision
                and window.controller.adapter.render_fingerprint()
                == before_reject_render
            )

            stale_rejected = False
            invalid_target_rejected = False
            manual_bypass_rejected = False
            mutation_guard_render = window.controller.adapter.render_fingerprint()
            mutation_guard_revision = window.controller.session.revision
            stale_batch = _setting_batch(
                revision=baseline_revision,
                provider=transaction.provider,
                target_id=target_id,
                setting_path=setting_path,
                before=first_value,
                after=_edited_value(first_value, "[Stale]"),
                rationale="Intentionally stale proposal.",
            )
            try:
                window.propose_assistant_batch(stale_batch)
            except ValueError:
                stale_rejected = True
            invalid_batch = _setting_batch(
                revision=window.controller.session.revision,
                provider=transaction.provider,
                target_id="missing-object-id",
                setting_path=setting_path,
                before=first_value,
                after=_edited_value(first_value, "[Invalid]"),
                rationale="Intentionally invalid target.",
            )
            try:
                window.propose_assistant_batch(invalid_batch)
            except ValueError:
                invalid_target_rejected = True
            bypass_batch = _setting_batch(
                revision=window.controller.session.revision,
                provider=transaction.provider,
                target_id=target_id,
                setting_path=setting_path,
                before=first_value,
                after=_edited_value(first_value, "[Bypass]"),
                rationale="Attempt to bypass the Assistant transaction.",
            )
            try:
                window.controller.apply_batch(bypass_batch)
            except RuntimeError:
                manual_bypass_rejected = True
            invalid_no_partial_mutation = bool(
                window.controller.session.revision == mutation_guard_revision
                and window.controller.adapter.render_fingerprint()
                == mutation_guard_render
                and window.controller.adapter.setting_value(setting_path)
                == first_value
            )
            applied_navigation_zoom = window.controller.set_zoom_factor(
                float(baseline_viewport["zoom"]) + 0.35
            )
            navigation_changed = (
                applied_navigation_zoom != baseline_viewport["zoom"]
            )

            transaction_id = transaction.transaction_id
            window.set_close_policy_for_test("keep_recovery")
            window.close()
            application.processEvents()
            windows.remove(window)

            reopened = SciPlotCanvasWindow(workspace, interactive=False)
            windows.append(reopened)
            reopened.show()
            application.processEvents()
            reopened_transaction = reopened.assistant.transaction
            reopened_target = (
                reopened.controller.adapter.first_visible_text_target(
                    reopened.controller.session
                )
            )
            reopened_setting_path = str(reopened_target["setting_path"])
            interruption_preserves_turn = bool(
                reopened_transaction is not None
                and reopened_transaction.transaction_id == transaction_id
                and reopened.controller.adapter.setting_value(
                    reopened_setting_path
                )
                == first_value
            )
            rollback = reopened.rollback_assistant_transaction(
                reason="Cross-process whole-turn rollback probe."
            )
            rollback_exact = bool(
                reopened.assistant.transaction is None
                and reopened.controller.adapter.setting_value(
                    reopened_setting_path
                )
                == original_value
                and reopened.controller.adapter.render_fingerprint()
                == baseline_render
                and rollback.get("verification", {}).get(
                    "exact_baseline_render"
                )
                is True
                and reopened.controller.session.current_page == baseline_page
                and reopened.controller.session.viewport.to_dict()
                == baseline_viewport
                and navigation_changed
                and file_sha256(workspace.document_path)
                == document_hash_before
            )

            commit_provider = "assistant_probe_commit_provider"
            reopened.begin_assistant_transaction(
                provider=commit_provider,
                rationale="Verify commit, save, reopen, export, and QA.",
            )
            commit_value = _edited_value(original_value, "[Committed AI]")
            commit_batch = _setting_batch(
                revision=reopened.controller.session.revision,
                provider=commit_provider,
                target_id=str(reopened_target["object_id"]),
                setting_path=reopened_setting_path,
                before=original_value,
                after=commit_value,
                rationale="Commit one accepted visible Canvas change.",
            )
            reopened.propose_assistant_batch(commit_batch)
            reopened.accept_assistant_proposal()
            commit_entry = reopened.commit_assistant_transaction()
            commit_unlocks_manual_work = bool(
                not reopened.assistant.active
                and reopened.controller.session.dirty
                and reopened.save_action.isEnabled()
                and reopened.inspector_panel.isEnabled()
            )
            reopened.save_document()
            export_payload = reopened.export_current()
            accepted_revision = reopened.controller.session.revision
            accepted_render = reopened.controller.adapter.render_fingerprint()
            reopened.close()
            application.processEvents()
            windows.remove(reopened)

            committed = SciPlotCanvasWindow(workspace, interactive=False)
            windows.append(committed)
            committed.show()
            application.processEvents()
            committed_target = (
                committed.controller.adapter.first_visible_text_target(
                    committed.controller.session
                )
            )
            committed_setting_path = str(committed_target["setting_path"])
            commit_reopens_exact = bool(
                committed.controller.adapter.setting_value(
                    committed_setting_path
                )
                == commit_value
                and committed.controller.adapter.render_fingerprint()
                == accepted_render
                and committed.controller.session.revision == accepted_revision
                and not committed.controller.session.dirty
            )

            committed.begin_assistant_transaction(
                provider="assistant_probe_interrupt_provider",
                rationale="Simulate interruption after apply-start persistence.",
            )
            interrupted_transaction = committed.assistant.transaction
            if interrupted_transaction is None:
                raise RuntimeError("Interrupted transaction did not start.")
            interrupted_value = _edited_value(commit_value, "[Interrupted]")
            interrupted_batch = _setting_batch(
                revision=committed.controller.session.revision,
                provider=interrupted_transaction.provider,
                target_id=str(committed_target["object_id"]),
                setting_path=committed_setting_path,
                before=commit_value,
                after=interrupted_value,
                rationale="Persist an applying marker without mutating the VSZ.",
            )
            committed.propose_assistant_batch(interrupted_batch)
            interrupted_transaction.begin_applying()
            committed.controller.session.set_state("ai_applying")
            committed.controller.persist()
            interrupted_id = interrupted_transaction.transaction_id
            committed.close()
            application.processEvents()
            windows.remove(committed)

            interrupted = SciPlotCanvasWindow(workspace, interactive=False)
            windows.append(interrupted)
            interrupted.show()
            application.processEvents()
            recovered_transaction = interrupted.assistant.transaction
            apply_interruption_safe = bool(
                recovered_transaction is not None
                and recovered_transaction.transaction_id == interrupted_id
                and recovered_transaction.status == "paused"
                and recovered_transaction.applying_batch_id is None
                and recovered_transaction.pending_batch is not None
                and interrupted.controller.adapter.setting_value(
                    committed_setting_path
                )
                == commit_value
            )
            interrupted.rollback_assistant_transaction(
                reason="Finish interrupted apply probe."
            )

            conflict_target = (
                interrupted.controller.adapter.first_visible_text_target(
                    interrupted.controller.session
                )
            )
            conflict_setting_path = str(conflict_target["setting_path"])
            conflict_before = interrupted.controller.adapter.setting_value(
                conflict_setting_path
            )
            interrupted.begin_assistant_transaction(
                provider="assistant_probe_conflict_provider",
                rationale="Verify an applying conflict remains recoverable.",
            )
            conflict_transaction = interrupted.assistant.transaction
            if conflict_transaction is None:
                raise RuntimeError("Conflict transaction did not start.")
            conflict_batch = _setting_batch(
                revision=interrupted.controller.session.revision,
                provider=conflict_transaction.provider,
                target_id=str(conflict_target["object_id"]),
                setting_path=conflict_setting_path,
                before=conflict_before,
                after=_edited_value(conflict_before, "[Conflict]"),
                rationale="Preserve this proposal while clearing a deadlock.",
            )
            interrupted.propose_assistant_batch(conflict_batch)
            conflict_transaction.begin_applying()
            interrupted.controller.session.set_state("ai_applying")
            interrupted.controller.persist()
            interrupted.assistant._mark_conflict(
                "Simulated applying-marker conflict."
            )
            interrupted._sync_ui()
            conflicted = interrupted.assistant.transaction
            conflict_unlocks_rollback = bool(
                conflicted is not None
                and conflicted.status == "conflict"
                and conflicted.applying_batch_id is None
                and conflicted.pending_batch is not None
                and interrupted.assistant_rollback_action.isEnabled()
            )
            conflict_rollback = interrupted.rollback_assistant_transaction(
                reason="Resolve simulated applying-marker conflict."
            )
            conflict_rollback_safe = bool(
                conflict_unlocks_rollback
                and interrupted.assistant.transaction is None
                and interrupted.controller.adapter.setting_value(
                    conflict_setting_path
                )
                == conflict_before
                and conflict_rollback.get("verification", {}).get(
                    "exact_baseline_render"
                )
                is True
            )

            interrupted.set_close_policy_for_test("keep_recovery")
            interrupted.close()
            application.processEvents()
            windows.remove(interrupted)

            provider = _DeterministicCanvasProvider()
            provider_window = SciPlotCanvasWindow(
                workspace,
                interactive=False,
                assistant_provider=provider,
            )
            windows.append(provider_window)
            provider_window.resize(1380, 860)
            provider_window.show()
            application.processEvents()
            provider_target = (
                provider_window.controller.adapter.first_visible_text_target(
                    provider_window.controller.session
                )
            )
            provider_target_id = str(provider_target["object_id"])
            provider_setting_path = str(provider_target["setting_path"])
            provider_before = provider_window.controller.adapter.setting_value(
                provider_setting_path
            )
            provider_after = _edited_value(
                provider_before,
                "[Threaded Provider]",
            )
            provider.configure(
                target_id=provider_target_id,
                setting_path=provider_setting_path,
                before_value=provider_before,
                after_value=provider_after,
            )
            provider_baseline_render = (
                provider_window.controller.adapter.render_fingerprint()
            )
            provider_baseline_revision = (
                provider_window.controller.session.revision
            )
            provider_document_hash_before = file_sha256(
                provider_window.controller.document_path
            )
            provider_composer_ready = bool(
                provider_window.assistant_panel.composer_card.isVisible()
                and provider_window.assistant_panel.request_editor.isEnabled()
                and provider_window.assistant_panel.state_chip.text() == "Ready"
                and not provider_window.assistant.active
            )
            main_thread_id = threading.get_ident()
            provider_window.assistant_panel.request_editor.setPlainText(
                "Append [Threaded Provider] to the selected visible text."
            )
            provider_window.assistant_panel.send_button.click()
            provider_working = _wait_until(
                application,
                lambda: (
                    provider.first_started.is_set()
                    and provider_window.assistant.request_record is not None
                    and provider_window.assistant.request_record.status == "running"
                    and len(
                        provider_window.assistant.request_record.events
                    )
                    == 1
                ),
            )
            if not provider_working:
                raise RuntimeError(
                    "Threaded provider did not reach the visible progress state."
                )
            provider_progress_capture = _capture_window(
                provider_window,
                provider_working_screenshot,
                application=application,
            )
            provider_progress_ui = bool(
                provider_window.assistant_panel.state_chip.text() == "Working"
                and provider_window.assistant_panel.progress_card.isVisible()
                and provider_window.assistant_panel.cancel_request_button.isEnabled()
                and not provider_window.assistant_panel.composer_card.isVisible()
                and provider_window.controller.session.revision
                == provider_baseline_revision
                and provider_window.controller.adapter.render_fingerprint()
                == provider_baseline_render
                and provider.worker_thread_ids
                and provider.worker_thread_ids[0] != main_thread_id
            )
            exposed_runner_request = provider_window.assistant_runner.request
            runner_request_isolated = False
            if exposed_runner_request is not None:
                original_structural_status = str(
                    exposed_runner_request.context["qa"]["structural_status"]
                )
                exposed_runner_request.context["qa"][
                    "structural_status"
                ] = "tampered"
                second_runner_request = provider_window.assistant_runner.request
                persisted_running_record = (
                    provider_window.assistant.request_record
                )
                runner_request_isolated = bool(
                    second_runner_request is not None
                    and second_runner_request.context["qa"][
                        "structural_status"
                    ]
                    == original_structural_status
                    and persisted_running_record is not None
                    and persisted_running_record.parsed_request.context["qa"][
                        "structural_status"
                    ]
                    == original_structural_status
                )
            provider.first_release.set()
            provider_proposal_ready = _wait_until(
                application,
                lambda: (
                    not provider_window.assistant_runner.active
                    and provider_window.assistant.transaction is not None
                    and provider_window.assistant.transaction.pending_batch
                    is not None
                ),
            )
            if not provider_proposal_ready:
                raise RuntimeError(
                    "Threaded provider did not deliver a reviewable proposal."
                )
            provider_record = provider_window.assistant.request_record
            if provider_record is None:
                raise RuntimeError("Provider request record was not persisted.")
            provider_request = provider_record.parsed_request
            provider_response = provider_record.parsed_response
            if provider_response is None:
                raise RuntimeError("Provider response was not persisted.")
            provider_response.validate_for_request(provider_request)
            provider_preview_zero_mutation = bool(
                provider_record.status == "proposal_ready"
                and provider_window.controller.session.revision
                == provider_baseline_revision
                and provider_window.controller.adapter.setting_value(
                    provider_setting_path
                )
                == provider_before
                and provider_window.controller.adapter.render_fingerprint()
                == provider_baseline_render
            )
            provider_proposal_capture = _capture_window(
                provider_window,
                provider_proposal_screenshot,
                application=application,
            )
            provider_proposal_ui = {
                "state_chip": provider_window.assistant_panel.state_chip.text(),
                "change_rows": provider_window.assistant_panel.change_count,
                "accept_enabled": (
                    provider_window.assistant_panel.accept_button.isEnabled()
                ),
            }

            def request_with_context(context: dict[str, Any]) -> AssistantRequest:
                return AssistantRequest(
                    transaction_id=provider_request.transaction_id,
                    provider_id=provider_request.provider_id,
                    intent=provider_request.intent,
                    base_revision=provider_request.base_revision,
                    context=context,
                    allowed_proposal_kinds=(
                        provider_request.allowed_proposal_kinds
                    ),
                )

            hidden_array_context = copy.deepcopy(provider_request.context)
            hidden_array_context["selection"]["raw_values"] = [1.0, 2.0]
            declared_raw_context = copy.deepcopy(provider_request.context)
            declared_raw_context["raw_dataset_arrays_included"] = True
            tampered_record_payload = provider_record.to_dict()
            tampered_record_payload["request"]["intent"] += " tampered"
            wrong_hash_response = AssistantResponse(
                request_id=provider_request.request_id,
                transaction_id=provider_request.transaction_id,
                provider_id=provider_request.provider_id,
                request_sha256="0" * 64,
                status="cancelled",
                understanding="This response is intentionally misbound.",
            )
            wrong_revision_batch = _setting_batch(
                revision=provider_request.base_revision + 1,
                provider=provider_request.provider_id,
                target_id=provider_target_id,
                setting_path=provider_setting_path,
                before=provider_before,
                after=provider_after,
                rationale="Intentionally stale provider response.",
            )
            wrong_revision_response = AssistantResponse(
                request_id=provider_request.request_id,
                transaction_id=provider_request.transaction_id,
                provider_id=provider_request.provider_id,
                request_sha256=provider_request.payload_sha256,
                status="proposal",
                understanding="This response has the wrong base revision.",
                proposal_kind="canvas_operation_batch",
                proposal=wrong_revision_batch.to_dict(),
            )

            def append_noncontiguous_progress() -> None:
                empty_record = AssistantRequestRecord(
                    request=provider_request.to_dict()
                )
                empty_record.append_event(
                    AssistantProgressEvent(
                        request_id=provider_request.request_id,
                        provider_id=provider_request.provider_id,
                        sequence=2,
                        stage="planning",
                        message="Intentionally skipped sequence one.",
                        cancellable=True,
                    )
                )

            provider_contract_guards = {
                "runner_request_copy_isolated": runner_request_isolated,
                "nested_raw_array_rejected": _rejects(
                    lambda: request_with_context(hidden_array_context)
                ),
                "declared_raw_array_rejected": _rejects(
                    lambda: request_with_context(declared_raw_context)
                ),
                "request_record_tamper_rejected": _rejects(
                    lambda: AssistantRequestRecord.from_dict(
                        tampered_record_payload
                    )
                ),
                "wrong_request_hash_rejected": _rejects(
                    lambda: wrong_hash_response.validate_for_request(
                        provider_request
                    )
                ),
                "wrong_base_revision_rejected": _rejects(
                    lambda: wrong_revision_response.validate_for_request(
                        provider_request
                    )
                ),
                "noncontiguous_progress_rejected": _rejects(
                    append_noncontiguous_progress
                ),
                "untyped_output_rejected": _rejects(
                    lambda: AssistantResponse(
                        request_id=provider_request.request_id,
                        transaction_id=provider_request.transaction_id,
                        provider_id=provider_request.provider_id,
                        request_sha256=provider_request.payload_sha256,
                        status="proposal",
                        understanding="Executable output must be rejected.",
                        proposal_kind="python",
                        proposal={"code": "pass"},
                    )
                ),
            }

            provider_window.assistant_panel.accept_button.click()
            provider_applied = _wait_until(
                application,
                lambda: (
                    provider_window.assistant.request_record is not None
                    and provider_window.assistant.request_record.status
                    == "applied"
                    and provider_window.controller.session.revision
                    == provider_baseline_revision + 1
                ),
            )
            provider_applied_render = (
                provider_window.controller.adapter.render_fingerprint()
            )
            provider_live_apply = bool(
                provider_applied
                and provider_window.controller.adapter.setting_value(
                    provider_setting_path
                )
                == provider_after
                and provider_applied_render != provider_baseline_render
                and provider_window.assistant_panel.composer_card.isVisible()
            )
            provider_applied_capture = _capture_window(
                provider_window,
                provider_applied_screenshot,
                application=application,
            )

            provider_window.assistant_panel.request_editor.setPlainText(
                "Try a second refinement, then stop before accepting anything."
            )
            provider_window.assistant_panel.send_button.click()
            cancel_request_running = _wait_until(
                application,
                lambda: (
                    provider.cancel_started.is_set()
                    and provider_window.assistant.request_record is not None
                    and provider_window.assistant.request_record.status == "running"
                ),
            )
            if not cancel_request_running:
                raise RuntimeError(
                    "The cancellable provider request did not start."
                )
            cancel_revision = provider_window.controller.session.revision
            cancel_render = (
                provider_window.controller.adapter.render_fingerprint()
            )
            provider_window.assistant_panel.cancel_request_button.click()
            cancellation_completed = _wait_until(
                application,
                lambda: (
                    provider.cancellation_observed.is_set()
                    and not provider_window.assistant_runner.active
                    and provider_window.assistant.request_record is not None
                    and provider_window.assistant.request_record.status
                    == "cancelled"
                ),
            )
            cancelled_record = provider_window.assistant.request_record
            cancelled_response = (
                cancelled_record.parsed_response
                if cancelled_record is not None
                else None
            )
            late_result_discarded = bool(
                cancellation_completed
                and cancelled_response is not None
                and cancelled_response.status == "cancelled"
                and any(
                    "discarded" in warning.casefold()
                    for warning in cancelled_response.warnings
                )
                and provider_window.assistant.transaction is not None
                and provider_window.assistant.transaction.pending_batch is None
                and provider_window.controller.session.revision
                == cancel_revision
                and provider_window.controller.adapter.render_fingerprint()
                == cancel_render
                and provider_window.controller.adapter.setting_value(
                    provider_setting_path
                )
                == provider_after
            )
            provider_rollback = provider_window.rollback_assistant_transaction(
                reason="Restore the threaded-provider turn baseline."
            )
            provider_rollback_exact = bool(
                provider_window.assistant.transaction is None
                and provider_window.controller.adapter.setting_value(
                    provider_setting_path
                )
                == provider_before
                and provider_window.controller.adapter.render_fingerprint()
                == provider_baseline_render
                and file_sha256(provider_window.controller.document_path)
                == provider_document_hash_before
                and provider_rollback.get("verification", {}).get(
                    "exact_baseline_render"
                )
                is True
            )
            provider_window.close()
            application.processEvents()
            windows.remove(provider_window)

            noncancellable_provider = _DeterministicCanvasProvider()
            noncancellable_provider.descriptor = AssistantProviderDescriptor(
                provider_id="assistant_probe_noncancellable_provider",
                display_name="Non-cancellable Probe Assistant",
                model_label="deterministic",
                capabilities=("canvas_operation_batch",),
            )
            noncancellable_window = SciPlotCanvasWindow(
                workspace,
                interactive=False,
                assistant_provider=noncancellable_provider,
            )
            windows.append(noncancellable_window)
            noncancellable_window.show()
            application.processEvents()
            noncancellable_target = (
                noncancellable_window.controller.adapter.first_visible_text_target(
                    noncancellable_window.controller.session
                )
            )
            noncancellable_path = str(noncancellable_target["setting_path"])
            noncancellable_before = (
                noncancellable_window.controller.adapter.setting_value(
                    noncancellable_path
                )
            )
            noncancellable_provider.configure(
                target_id=str(noncancellable_target["object_id"]),
                setting_path=noncancellable_path,
                before_value=noncancellable_before,
                after_value=_edited_value(
                    noncancellable_before,
                    "[Must Not Apply]",
                ),
            )
            noncancellable_window.assistant_panel.request_editor.setPlainText(
                "Exercise bounded close while this provider is still working."
            )
            noncancellable_window.assistant_panel.send_button.click()
            noncancellable_running = _wait_until(
                application,
                lambda: (
                    noncancellable_provider.first_started.is_set()
                    and noncancellable_window.assistant.request_record is not None
                    and noncancellable_window.assistant.request_record.status
                    == "running"
                ),
            )
            noncancellable_stop_disabled = bool(
                noncancellable_running
                and not noncancellable_window.assistant_panel.cancel_request_button.isEnabled()
            )
            noncancellable_closed = noncancellable_window.close()
            application.processEvents()
            noncancellable_shutdown_safe = bool(
                noncancellable_closed
                and noncancellable_window._closed
                and not noncancellable_window.assistant_runner.active
            )
            windows.remove(noncancellable_window)

            noncancellable_recovery = SciPlotCanvasWindow(
                workspace,
                interactive=False,
            )
            windows.append(noncancellable_recovery)
            noncancellable_recovery.show()
            application.processEvents()
            noncancellable_record = (
                noncancellable_recovery.assistant.request_record
            )
            noncancellable_cancelled = bool(
                noncancellable_record is not None
                and noncancellable_record.status == "cancelled"
            )
            noncancellable_rollback = (
                noncancellable_recovery.rollback_assistant_transaction(
                    reason="Clean up the non-cancellable close probe."
                )
            )
            noncancellable_recovered_exact = bool(
                noncancellable_cancelled
                and noncancellable_recovery.assistant.transaction is None
                and noncancellable_recovery.controller.adapter.setting_value(
                    noncancellable_path
                )
                == noncancellable_before
                and noncancellable_rollback.get("verification", {}).get(
                    "exact_baseline_render"
                )
                is True
            )
            noncancellable_recovery.close()
            application.processEvents()
            windows.remove(noncancellable_recovery)

            journal = read_operation_journal(workspace.journal_path)
            journal_events = {
                str(entry.get("event") or "") for entry in journal
            }
            required_events = {
                "assistant_transaction_started",
                "assistant_batch_proposed",
                "assistant_transaction_paused",
                "assistant_transaction_resumed",
                "assistant_batch_apply_started",
                "assistant_batch_applied",
                "assistant_batch_undone",
                "assistant_batch_rejected",
                "assistant_transaction_rolled_back",
                "assistant_transaction_committed",
                "assistant_transaction_interrupted",
                "assistant_transaction_conflict",
                "assistant_request_submitted",
                "assistant_request_progress",
                "assistant_request_cancel_requested",
                "assistant_response_received",
            }
            journal_event_ids = [
                str(entry.get("event_id"))
                for entry in journal
                if entry.get("event_id")
            ]
            raw_hash_after = (
                _tree_hash(raw_root) if raw_root is not None else None
            )
            source_hash_after = _tree_hash(source)

            checks.extend(
                [
                    _check(
                        "assistant_optional_idle",
                        "The Canvas opens fully usable with no Assistant provider",
                        idle_provider_optional,
                    ),
                    _check(
                        "bounded_context_excludes_raw_values",
                        "Assistant context is structured and excludes raw dataset values",
                        context.get("kind")
                        == "sciplot_canvas_assistant_context"
                        and context.get("version") == 2
                        and context.get("raw_dataset_arrays_included") is False
                        and isinstance(context.get("document_inventory"), dict)
                        and isinstance(context.get("review"), dict),
                        context,
                    ),
                    _check(
                        "transaction_baseline_integrity",
                        "A transaction starts from hashed VSZ and review baselines",
                        baseline_integrity,
                        {
                            "vsz": str(baseline_vsz),
                            "review": str(baseline_review),
                        },
                    ),
                    _check(
                        "proposal_preview_zero_mutation",
                        "Typed proposal preview does not mutate revision, render, or VSZ",
                        preview_zero_mutation,
                        preview,
                    ),
                    _check(
                        "assistant_utility_pane",
                        "The Assistant utility pane shows one bounded proposal and locks untracked editors",
                        proposal_ui["tab_index"] == 2
                        and proposal_ui["state_chip"] == "Proposal"
                        and proposal_ui["change_rows"] == 1
                        and proposal_ui["accept_enabled"]
                        and proposal_ui["save_locked"]
                        and proposal_ui["edit_locked"],
                        proposal_ui,
                    ),
                    _check(
                        "provider_composer_ready",
                        "A connected provider exposes one bounded natural-language composer",
                        provider_composer_ready,
                    ),
                    _check(
                        "provider_progress_visible_off_gui_thread",
                        "Provider progress is visible while generation stays off the GUI thread",
                        provider_progress_ui,
                        {
                            "main_thread_id": main_thread_id,
                            "worker_thread_ids": provider.worker_thread_ids,
                            "capture": {
                                "path": str(provider_working_screenshot),
                                **provider_progress_capture,
                            },
                        },
                    ),
                    _check(
                        "provider_zero_trust_contract",
                        "Provider requests and responses reject hidden data, tampering, stale revisions, gaps, and untyped output",
                        all(provider_contract_guards.values()),
                        provider_contract_guards,
                    ),
                    _check(
                        "provider_typed_proposal_preview",
                        "The exact request hash yields one reviewable zero-mutation CanvasOperationBatch",
                        provider_preview_zero_mutation
                        and provider_response.request_sha256
                        == provider_request.payload_sha256
                        and provider_record.request_sha256
                        == provider_request.payload_sha256
                        and provider_proposal_ui["state_chip"] == "Proposal"
                        and provider_proposal_ui["change_rows"] == 1
                        and provider_proposal_ui["accept_enabled"]
                        and provider_proposal_capture["visually_plausible"],
                        {
                            "request_id": provider_request.request_id,
                            "request_sha256": provider_request.payload_sha256,
                            "response_id": provider_response.response_id,
                            "ui": provider_proposal_ui,
                            "capture": {
                                "path": str(provider_proposal_screenshot),
                                **provider_proposal_capture,
                            },
                        },
                    ),
                    _check(
                        "provider_accept_redraws_live",
                        "Accepting the threaded provider proposal redraws the live Canvas",
                        provider_live_apply,
                        {
                            "revision": provider_baseline_revision + 1,
                            "render_before": provider_baseline_render,
                            "render_after": provider_applied_render,
                        },
                    ),
                    _check(
                        "provider_cancel_discards_late_result",
                        "Stopping a provider request rejects its deliberately late proposal without mutation",
                        late_result_discarded,
                        (
                            cancelled_response.to_dict()
                            if cancelled_response is not None
                            else None
                        ),
                    ),
                    _check(
                        "provider_close_without_cancel_capability",
                        "Window close safely stops a provider that does not expose a Stop action",
                        noncancellable_stop_disabled
                        and noncancellable_shutdown_safe
                        and noncancellable_recovered_exact,
                        {
                            "stop_disabled": noncancellable_stop_disabled,
                            "window_closed": noncancellable_shutdown_safe,
                            "recovered_exact": noncancellable_recovered_exact,
                        },
                    ),
                    _check(
                        "provider_whole_turn_rollback_exact",
                        "The full threaded-provider turn restores its hashed starting document",
                        provider_rollback_exact,
                        provider_rollback,
                    ),
                    _check(
                        "provider_ui_screenshots",
                        "Working, proposal, and accepted provider states render as stable screenshots",
                        provider_progress_capture["visually_plausible"]
                        and provider_proposal_capture["visually_plausible"]
                        and provider_applied_capture["visually_plausible"],
                        {
                            "working": {
                                "path": str(provider_working_screenshot),
                                **provider_progress_capture,
                            },
                            "proposal": {
                                "path": str(provider_proposal_screenshot),
                                **provider_proposal_capture,
                            },
                            "applied": {
                                "path": str(provider_applied_screenshot),
                                **provider_applied_capture,
                            },
                        },
                    ),
                    _check(
                        "pause_blocks_apply",
                        "Pausing prevents a proposal from being accepted",
                        paused_accept_rejected,
                    ),
                    _check(
                        "accepted_batch_redraws_live",
                        "An accepted typed batch changes the live Canvas immediately",
                        first_live,
                        {
                            "latency_ms": first_latency_ms,
                            "entry": first_accept["entry"],
                        },
                    ),
                    _check(
                        "per_batch_undo",
                        "The latest accepted Assistant batch undoes independently",
                        per_batch_undo,
                        {
                            "second_revision": second_accept["entry"][
                                "revision"
                            ],
                            "second_render": second_render,
                            "undo": undo_entry,
                        },
                    ),
                    _check(
                        "proposal_rejection_isolated",
                        "Rejecting a pending proposal leaves the publication document unchanged",
                        proposal_rejection_isolated,
                    ),
                    _check(
                        "invalid_and_stale_rejected_atomically",
                        "Stale, invalid-target, and bypass attempts fail without partial mutation",
                        stale_rejected
                        and invalid_target_rejected
                        and manual_bypass_rejected
                        and invalid_no_partial_mutation,
                        {
                            "stale_rejected": stale_rejected,
                            "invalid_target_rejected": (
                                invalid_target_rejected
                            ),
                            "manual_bypass_rejected": manual_bypass_rejected,
                            "no_partial_mutation": (
                                invalid_no_partial_mutation
                            ),
                        },
                    ),
                    _check(
                        "active_turn_reopens",
                        "An accepted active turn reopens from verified recovery",
                        interruption_preserves_turn,
                    ),
                    _check(
                        "whole_turn_rollback_exact",
                        "Whole-turn rollback restores the exact cross-process document and baseline viewport",
                        rollback_exact,
                        {
                            "rollback": rollback,
                            "baseline_page": baseline_page,
                            "baseline_viewport": baseline_viewport,
                            "navigation_zoom": applied_navigation_zoom,
                        },
                    ),
                    _check(
                        "commit_unlocks_manual_work",
                        "Committing closes the transaction and returns control to ordinary Canvas editing",
                        commit_unlocks_manual_work,
                        commit_entry,
                    ),
                    _check(
                        "committed_save_reopen_exact",
                        "Committed Assistant output saves and reopens at the accepted revision",
                        commit_reopens_exact,
                    ),
                    _check(
                        "committed_export_qa",
                        "Committed Assistant output passes the normal exact-current export and QA path",
                        export_payload.get("ready_to_use") is True
                        and export_payload.get("status") == "passed",
                        export_payload,
                    ),
                    _check(
                        "apply_interruption_recovers_paused",
                        "An interrupted apply marker reopens paused with the proposal preserved and unapplied",
                        apply_interruption_safe,
                    ),
                    _check(
                        "applying_conflict_remains_recoverable",
                        "An applying-marker conflict clears its deadlock and permits exact whole-turn rollback",
                        conflict_rollback_safe,
                        {
                            "rollback_enabled": conflict_unlocks_rollback,
                            "rollback_verification": conflict_rollback.get(
                                "verification"
                            ),
                        },
                    ),
                    _check(
                        "transaction_audit_complete",
                        "Assistant lifecycle events have unique IDs and complete audit coverage",
                        required_events <= journal_events
                        and len(journal_event_ids) == len(set(journal_event_ids)),
                        {
                            "required": sorted(required_events),
                            "observed": sorted(journal_events),
                            "event_id_count": len(journal_event_ids),
                        },
                    ),
                    _check(
                        "raw_inputs_immutable",
                        "Assistant transactions never mutate original or project raw inputs",
                        source_hash_after == source_hash_before
                        and raw_hash_after == raw_hash_before,
                        {
                            "source_before": source_hash_before,
                            "source_after": source_hash_after,
                            "raw_before": raw_hash_before,
                            "raw_after": raw_hash_after,
                        },
                    ),
                    _check(
                        "assistant_screenshots",
                        "Proposal and applied Assistant states render as stable, non-empty screenshots",
                        proposal_capture["visually_plausible"]
                        and proposal_screenshot.is_file()
                        and proposal_screenshot.stat().st_size > 0
                        and applied_capture["visually_plausible"]
                        and applied_screenshot.is_file()
                        and applied_screenshot.stat().st_size > 0,
                        {
                            "proposal": {
                                "path": str(proposal_screenshot),
                                **proposal_capture,
                            },
                            "applied": {
                                "path": str(applied_screenshot),
                                **applied_capture,
                            },
                        },
                    ),
                ]
            )
            evidence = {
                "workspace": workspace.to_dict(),
                "baseline_revision": baseline_revision,
                "accepted_revision": accepted_revision,
                "first_apply_latency_ms": round(first_latency_ms, 3),
                "journal_event_count": len(journal),
                "journal_events": sorted(journal_events),
                "provider_request_count": provider.request_count,
                "provider_worker_thread_ids": provider.worker_thread_ids,
                "provider_contract_guards": provider_contract_guards,
                "provider_late_result_discarded": late_result_discarded,
                "provider_rollback_exact": provider_rollback_exact,
                "export": json_safe(export_payload),
                "source_hash_before": source_hash_before,
                "source_hash_after": source_hash_after,
            }
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "canvas_assistant_probe_exception",
                "The Assistant transaction lifecycle completes without an exception",
                False,
                error,
            )
        )
    finally:
        for window in windows:
            try:
                window.set_close_policy_for_test("keep_recovery")
                window.close()
            except Exception:
                try:
                    window.controller.close()
                except Exception:
                    pass

    failed_ids = [
        str(check["id"]) for check in checks if check["status"] == "failed"
    ]
    payload = {
        "kind": CANVAS_ASSISTANT_PROBE_KIND,
        "version": CANVAS_ASSISTANT_PROBE_VERSION,
        "generated_at": _now(),
        "status": "passed" if checks and not failed_ids else "failed",
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(
                check["status"] == "passed" for check in checks
            ),
            "failed_ids": failed_ids,
        },
        "checks": checks,
        "evidence": json_safe(evidence),
        "artifacts": {
            "run_root": str(run_root),
            "summary": str(summary_path),
            "proposal_screenshot": str(proposal_screenshot),
            "applied_screenshot": str(applied_screenshot),
            "provider_working_screenshot": str(
                provider_working_screenshot
            ),
            "provider_proposal_screenshot": str(
                provider_proposal_screenshot
            ),
            "provider_applied_screenshot": str(
                provider_applied_screenshot
            ),
            "stderr_log": str(stderr_log),
            "progress_log": str(progress_path),
        },
        "error": error,
        "limitations": [
            "This probe uses an injected deterministic provider and does not call "
            "a production model endpoint.",
            "It proves the threaded CanvasOperationBatch provider UI loop. "
            "Deterministic DataMappingProposal execution is validated separately; "
            "its Canvas confirmation UI remains follow-on work.",
            "Automated probes do not count as real human daily-use sessions.",
        ],
    }
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "CANVAS_ASSISTANT_PROBE_KIND",
    "CANVAS_ASSISTANT_PROBE_VERSION",
    "run_canvas_assistant_probe",
]
