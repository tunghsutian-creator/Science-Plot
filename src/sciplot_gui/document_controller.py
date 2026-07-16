from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.model import CanvasSelection, CanvasSession
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.persistence import (
    append_operation_journal,
    load_canvas_session,
    save_canvas_session,
)
from sciplot_gui.veusz_canvas import VeuszCanvasAdapter


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DocumentController:
    """Serialize typed user and AI operations onto the GUI-owned document."""

    def __init__(
        self,
        *,
        document_path: Path,
        session_path: Path,
        journal_path: Path,
        project_id: str,
        parent: Any = None,
        visible: bool = False,
    ) -> None:
        self.document_path = document_path.expanduser().resolve()
        self.session_path = session_path.expanduser().resolve()
        self.journal_path = journal_path.expanduser().resolve()
        if not self.document_path.is_file():
            raise FileNotFoundError(self.document_path)
        self.recovered_from_snapshot: str | None = None
        expected_recovery_render: str | None = None
        if self.session_path.is_file():
            self.session = load_canvas_session(self.session_path)
            self.session.document_path = str(self.document_path)
            load_path = self.document_path
            if (
                self.session.document_sha256
                and file_sha256(self.document_path) != self.session.document_sha256
            ):
                self.session.set_state("conflict")
                self.persist()
                raise RuntimeError(
                    "The canonical VSZ changed outside the CanvasSession; "
                    "explicit conflict resolution is required."
                )
            if self.session.dirty:
                recovery_entry = next(
                    (
                        (value, self._resolve_recovery_snapshot(value))
                        for value in reversed(self.session.recovery_snapshots)
                        if self._resolve_recovery_snapshot(value).is_file()
                    ),
                    None,
                )
                if recovery_entry is None:
                    self.session.set_state("needs_rule_repair")
                    self.persist()
                    raise RuntimeError(
                        "CanvasSession is dirty but no recovery VSZ snapshot is available."
                    )
                recovery_reference, recovery_path = recovery_entry
                expected_recovery_hash = self.session.recovery_snapshot_hashes.get(
                    recovery_reference
                )
                if (
                    expected_recovery_hash is None
                    or file_sha256(recovery_path) != expected_recovery_hash
                    or self.session.last_render_sha256 is None
                ):
                    self.session.set_state("conflict")
                    self.persist()
                    raise RuntimeError(
                        "Canvas recovery snapshot integrity could not be verified."
                    )
                load_path = recovery_path
                expected_recovery_render = self.session.last_render_sha256
                self.recovered_from_snapshot = str(recovery_path)
        else:
            self.session = CanvasSession(
                project_id=project_id,
                document_id=str(uuid4()),
                document_path=str(self.document_path),
                state="canvas_ready",
                document_sha256=file_sha256(self.document_path),
            )
            load_path = self.document_path
        self.adapter = VeuszCanvasAdapter(load_path, parent=parent, visible=visible)
        self.inventory = self.adapter.bind_object_registry(self.session)
        self.session.current_page = self.adapter.set_page(self.session.current_page)
        self.session.viewport.zoom = self.adapter.set_zoom_factor(
            self.session.viewport.zoom
        )
        loaded_render = self.adapter.render_fingerprint()
        if (
            expected_recovery_render is not None
            and loaded_render != expected_recovery_render
        ):
            self.adapter.close()
            self.session.set_state("conflict")
            self.persist()
            raise RuntimeError(
                "Canvas recovery snapshot rendered differently from the accepted state."
            )
        self.session.last_render_sha256 = loaded_render
        if self.session.dirty:
            restored_state = "editing"
        elif (
            self.session.exported_revision == self.session.revision
            and self.session.qa_summary.get("ready_to_use") is True
        ):
            restored_state = "ready"
        elif (
            self.session.exported_revision == self.session.revision
            and self.session.qa_summary
        ):
            restored_state = "needs_rule_repair"
        else:
            restored_state = "canvas_ready"
        self.session.set_state(restored_state)
        self.persist()
        if self.recovered_from_snapshot is not None:
            append_operation_journal(
                self.journal_path,
                {
                    "kind": "sciplot_canvas_journal_entry",
                    "version": 1,
                    "event": "recovered_from_snapshot",
                    "recorded_at": _now(),
                    "revision": self.session.revision,
                    "snapshot": self.recovered_from_snapshot,
                },
            )

    def persist(self) -> Path:
        return save_canvas_session(self.session_path, self.session)

    @property
    def selected_object(self) -> dict[str, Any] | None:
        selected_id = self.session.selection.primary_object_id
        if selected_id is None:
            return None
        return next(
            (item for item in self.inventory if item.get("object_id") == selected_id),
            None,
        )

    def select_object_id(
        self,
        object_id: str,
        *,
        mode: str = "new",
    ) -> dict[str, Any]:
        item = next(
            (
                candidate
                for candidate in self.inventory
                if candidate.get("object_id") == object_id
            ),
            None,
        )
        if item is None:
            raise ValueError(f"Unknown Canvas object: {object_id}")
        current = list(self.session.selection.object_ids)
        if mode == "toggle":
            if object_id in current:
                current.remove(object_id)
            else:
                current.append(object_id)
        elif mode == "add":
            if object_id not in current:
                current.append(object_id)
        else:
            current = [object_id]
        primary = (
            object_id if object_id in current else (current[-1] if current else None)
        )
        self.session.selection = CanvasSelection(
            object_ids=current,
            primary_object_id=primary,
        )
        self.persist()
        return item

    def select_widget_path(
        self,
        widget_path: str,
        *,
        mode: str = "new",
    ) -> dict[str, Any] | None:
        item = next(
            (
                candidate
                for candidate in self.inventory
                if candidate.get("path") == widget_path
            ),
            None,
        )
        if item is None:
            return None
        return self.select_object_id(str(item["object_id"]), mode=mode)

    def visible_text_targets(self) -> list[dict[str, Any]]:
        return self.adapter.visible_text_targets(self.session)

    def set_page(self, page_index: int) -> int:
        page = self.adapter.set_page(page_index)
        self.session.current_page = page
        self.session.last_render_sha256 = self.adapter.render_fingerprint()
        self.persist()
        return page

    def set_zoom_factor(self, zoom: float) -> float:
        applied = self.adapter.set_zoom_factor(zoom)
        self.session.viewport.zoom = applied
        self.session.last_render_sha256 = self.adapter.render_fingerprint()
        self.persist()
        return applied

    def zoom_to_page(self) -> float:
        applied = self.adapter.zoom_to_page()
        self.session.viewport.zoom = applied
        self.session.last_render_sha256 = self.adapter.render_fingerprint()
        self.persist()
        return applied

    def _sync_view_state(self) -> None:
        self.session.current_page = self.adapter.current_page
        self.session.viewport.zoom = self.adapter.zoom_factor

    def sync_view_state(self) -> None:
        self._sync_view_state()
        self.session.last_render_sha256 = self.adapter.render_fingerprint()
        self.persist()

    def update_interface_state(
        self,
        *,
        inspector_visible: bool | None = None,
        inspector_width: int | None = None,
        high_contrast: bool | None = None,
        active_inspector: str | None = None,
    ) -> None:
        interface = self.session.interface
        if inspector_visible is not None:
            interface.inspector_visible = bool(inspector_visible)
        if inspector_width is not None:
            width = int(inspector_width)
            if not 280 <= width <= 720:
                raise ValueError(
                    "Canvas inspector width must be between 280 and 720 pixels."
                )
            interface.inspector_width = width
        if high_contrast is not None:
            interface.high_contrast = bool(high_contrast)
        if active_inspector is not None:
            text = str(active_inspector).strip()
            if not text:
                raise ValueError("active_inspector must be a non-empty string.")
            self.session.active_inspector = text
        self.persist()

    def _create_recovery_snapshot(self, *, revision: int, event: str) -> Path:
        snapshot = (
            self.session_path.parent
            / ".canvas_recovery"
            / f"revision_{revision:06d}_{event}.vsz"
        )
        return self.adapter.save_recovery_snapshot(snapshot)

    def _resolve_recovery_snapshot(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.session_path.parent / path
        resolved = path.resolve()
        recovery_root = (self.session_path.parent / ".canvas_recovery").resolve()
        if not resolved.is_relative_to(recovery_root):
            raise RuntimeError(
                "Canvas recovery snapshot resolves outside the project recovery root."
            )
        return resolved

    def _record_recovery_snapshot(self, snapshot: Path) -> tuple[str, str]:
        try:
            persisted = snapshot.relative_to(self.session_path.parent)
        except ValueError:
            persisted = snapshot
        persisted_value = str(persisted)
        self.session.recovery_snapshots.append(persisted_value)
        self.session.recovery_snapshots = self.session.recovery_snapshots[-20:]
        snapshot_hash = file_sha256(snapshot)
        self.session.recovery_snapshot_hashes[persisted_value] = snapshot_hash
        retained = set(self.session.recovery_snapshots)
        self.session.recovery_snapshot_hashes = {
            key: value
            for key, value in self.session.recovery_snapshot_hashes.items()
            if key in retained
        }
        return persisted_value, snapshot_hash

    def _resolve_operation_targets(
        self,
        batch: CanvasOperationBatch,
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for operation in batch.operations:
            target = self.session.object_registry.by_id(operation.target_id)
            if target is None:
                raise ValueError(f"Unknown Canvas target: {operation.target_id}")
            if operation.operation_type != "set_setting":
                raise ValueError(
                    f"Unsupported controller operation: {operation.operation_type}"
                )
            setting_path = str(operation.arguments["setting_path"])
            if not setting_path.startswith(f"{target.current_path}/"):
                raise ValueError(
                    f"Setting path {setting_path!r} is outside target {target.current_path!r}."
                )
            current_value = self.adapter.setting_value(setting_path)
            if (
                "expected_value" in operation.arguments
                and json_safe(current_value) != operation.arguments["expected_value"]
            ):
                raise ValueError(
                    f"Expected value conflict at {setting_path}: "
                    f"{operation.arguments['expected_value']!r} != {current_value!r}"
                )
            self.adapter.validate_setting_value(
                setting_path, operation.arguments["value"]
            )
            changes.append(
                {
                    "operation_id": operation.operation_id,
                    "target_id": operation.target_id,
                    "setting_path": setting_path,
                    "value": operation.arguments["value"],
                }
            )
        return changes

    def apply_batch(self, batch: CanvasOperationBatch) -> dict[str, Any]:
        self.adapter.assert_gui_thread()
        self._sync_view_state()
        batch = CanvasOperationBatch.from_dict(batch.to_dict())
        if batch.base_revision != self.session.revision:
            self.session.set_state("conflict")
            self.persist()
            raise ValueError(
                f"Stale CanvasOperationBatch: base_revision={batch.base_revision}, "
                f"current_revision={self.session.revision}."
            )
        changes = self._resolve_operation_targets(batch)
        before_render = self.adapter.render_fingerprint()
        applied = self.adapter.apply_setting_batch(changes, description=batch.rationale)
        after_render = self.adapter.render_fingerprint()
        next_revision = self.session.revision + 1
        try:
            snapshot = self._create_recovery_snapshot(
                revision=next_revision,
                event="operation_batch",
            )
        except Exception:
            self.adapter.undo()
            raise
        revision = self.session.advance_revision(state="editing")
        snapshot_reference, snapshot_hash = self._record_recovery_snapshot(snapshot)
        self.session.last_render_sha256 = after_render
        self.inventory = self.adapter.bind_object_registry(self.session)
        self.persist()
        entry = {
            "kind": "sciplot_canvas_journal_entry",
            "version": 1,
            "event": "operation_batch_applied",
            "recorded_at": _now(),
            "revision": revision,
            "batch": batch.to_dict(),
            "changes": json_safe(applied),
            "render_before": before_render,
            "render_after": after_render,
            "recovery_snapshot": snapshot_reference,
            "recovery_snapshot_sha256": snapshot_hash,
        }
        append_operation_journal(self.journal_path, entry)
        return entry

    def undo(self, *, provider: str = "user") -> dict[str, Any]:
        self._sync_view_state()
        before_render = self.adapter.render_fingerprint()
        after_render = self.adapter.undo()
        next_revision = self.session.revision + 1
        try:
            snapshot = self._create_recovery_snapshot(
                revision=next_revision, event="undo"
            )
        except Exception:
            self.adapter.redo()
            raise
        revision = self.session.advance_revision(state="editing")
        snapshot_reference, snapshot_hash = self._record_recovery_snapshot(snapshot)
        self.session.last_render_sha256 = after_render
        self.persist()
        entry = {
            "kind": "sciplot_canvas_journal_entry",
            "version": 1,
            "event": "undo",
            "provider": provider,
            "recorded_at": _now(),
            "revision": revision,
            "render_before": before_render,
            "render_after": after_render,
            "recovery_snapshot": snapshot_reference,
            "recovery_snapshot_sha256": snapshot_hash,
        }
        append_operation_journal(self.journal_path, entry)
        return entry

    def redo(self, *, provider: str = "user") -> dict[str, Any]:
        self._sync_view_state()
        before_render = self.adapter.render_fingerprint()
        after_render = self.adapter.redo()
        next_revision = self.session.revision + 1
        try:
            snapshot = self._create_recovery_snapshot(
                revision=next_revision, event="redo"
            )
        except Exception:
            self.adapter.undo()
            raise
        revision = self.session.advance_revision(state="editing")
        snapshot_reference, snapshot_hash = self._record_recovery_snapshot(snapshot)
        self.session.last_render_sha256 = after_render
        self.persist()
        entry = {
            "kind": "sciplot_canvas_journal_entry",
            "version": 1,
            "event": "redo",
            "provider": provider,
            "recorded_at": _now(),
            "revision": revision,
            "render_before": before_render,
            "render_after": after_render,
            "recovery_snapshot": snapshot_reference,
            "recovery_snapshot_sha256": snapshot_hash,
        }
        append_operation_journal(self.journal_path, entry)
        return entry

    def save(self) -> Path:
        target = self.adapter.save(self.document_path)
        self.session.document_path = str(target)
        self.session.mark_saved(document_sha256=file_sha256(target))
        self.session.set_state("canvas_ready")
        self.persist()
        append_operation_journal(
            self.journal_path,
            {
                "kind": "sciplot_canvas_journal_entry",
                "version": 1,
                "event": "save",
                "recorded_at": _now(),
                "revision": self.session.revision,
                "document": str(target),
                "document_sha256": self.session.document_sha256,
            },
        )
        return target

    def mark_exported(self, exports: list[dict[str, Any]]) -> None:
        if not exports or not all(
            isinstance(item, dict)
            and item.get("exists") is True
            and int(item.get("size_bytes") or 0) > 0
            for item in exports
        ):
            raise ValueError("Cannot mark missing or empty Canvas exports as complete.")
        if (
            self.session.document_sha256 is None
            or file_sha256(self.document_path) != self.session.document_sha256
        ):
            self.session.set_state("conflict")
            self.persist()
            raise RuntimeError("The canonical VSZ changed before export was recorded.")
        self.session.mark_exported()
        self.persist()
        append_operation_journal(
            self.journal_path,
            {
                "kind": "sciplot_canvas_journal_entry",
                "version": 1,
                "event": "exact_current_export",
                "recorded_at": _now(),
                "revision": self.session.revision,
                "exports": json_safe(exports),
            },
        )

    def record_export_result(self, payload: dict[str, Any]) -> None:
        exports = payload.get("exports")
        if not isinstance(exports, list):
            raise ValueError("Canvas export result must contain an exports list.")
        self.mark_exported(exports)
        self.session.qa_summary = {
            "status": payload.get("status"),
            "state": payload.get("state"),
            "ready_to_use": payload.get("ready_to_use") is True,
            "scope": payload.get("scope"),
        }
        self.session.set_state(
            "ready" if payload.get("ready_to_use") is True else "needs_rule_repair"
        )
        self.persist()

    def keep_recovery_on_close(self, *, provider: str = "user") -> dict[str, Any]:
        if not self.session.dirty:
            raise ValueError("A clean CanvasSession does not need recovery retention.")
        if not self.session.recovery_snapshots:
            raise RuntimeError("No Canvas recovery snapshot is available.")
        entry = {
            "kind": "sciplot_canvas_journal_entry",
            "version": 1,
            "event": "close_with_recovery",
            "provider": provider,
            "recorded_at": _now(),
            "revision": self.session.revision,
            "snapshot": self.session.recovery_snapshots[-1],
        }
        self.persist()
        append_operation_journal(self.journal_path, entry)
        return entry

    def close(self) -> None:
        self.persist()
        self.adapter.close()


__all__ = ["DocumentController"]
