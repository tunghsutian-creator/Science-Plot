from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.model import CanvasSession
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
        self.adapter = VeuszCanvasAdapter(load_path)
        self.inventory = self.adapter.bind_object_registry(self.session)
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
        self.session.set_state("editing" if self.session.dirty else "canvas_ready")
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

    def close(self) -> None:
        self.persist()
        self.adapter.close()


__all__ = ["DocumentController"]
