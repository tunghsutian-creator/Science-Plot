from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.annotations import (
    ReviewAnnotation,
    ReviewAnnotationStyle,
)
from sciplot_core.canvas.inspector import CanvasInspectorModel
from sciplot_core.canvas.model import (
    CanvasSelection,
    CanvasSession,
    CanvasViewport,
)
from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_core.canvas.persistence import (
    append_operation_journal,
    append_operation_journal_once,
    load_canvas_session,
    load_review_annotations,
    read_operation_journal,
    save_canvas_session,
    save_review_annotations,
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
        annotations_path: Path | None = None,
        journal_path: Path,
        project_id: str,
        parent: Any = None,
        visible: bool = False,
    ) -> None:
        self.document_path = document_path.expanduser().resolve()
        self.session_path = session_path.expanduser().resolve()
        self.annotations_path = (
            annotations_path.expanduser().resolve()
            if annotations_path is not None
            else (self.session_path.parent / "review_annotations.json").resolve()
        )
        self.journal_path = journal_path.expanduser().resolve()
        self._history_side_effects_undo: list[dict[str, Any] | None] = []
        self._history_side_effects_redo: list[dict[str, Any] | None] = []
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
        if self.annotations_path.is_file():
            self.review_annotations = load_review_annotations(self.annotations_path)
        else:
            self.review_annotations = []
            if self.session.review_annotation_ids:
                self.session.set_state("conflict")
                self.persist()
                raise RuntimeError(
                    "CanvasSession references review annotations, but the "
                    "non-exported review sidecar is missing."
                )
        annotation_ids = [
            annotation.annotation_id for annotation in self.review_annotations
        ]
        if self.session.review_annotation_ids:
            if self.session.review_annotation_ids != annotation_ids:
                self.session.set_state("conflict")
                self.persist()
                raise RuntimeError(
                    "CanvasSession and review_annotations.json disagree about "
                    "the persisted review layer."
                )
        elif annotation_ids:
            self.session.review_annotation_ids = annotation_ids
        self.adapter = VeuszCanvasAdapter(load_path, parent=parent, visible=visible)
        self.inventory = self.adapter.bind_object_registry(self.session)
        selected_id = self.session.selection.primary_object_id
        if selected_id is not None and not any(
            item.get("object_id") == selected_id for item in self.inventory
        ):
            self.session.selection = CanvasSelection()
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
        if self.session.selection.primary_object_id is None:
            default_id = self.adapter.default_inspector_object_id(self.session)
            if default_id is not None:
                self.session.selection = CanvasSelection(
                    object_ids=[default_id],
                    primary_object_id=default_id,
                )
        self.adapter.restore_data_point_selection(
            self.session.selection.data_point,
            self.session,
        )
        self.persist()
        self.flush_journal_outbox()
        if self.recovered_from_snapshot is not None:
            self.record_journal_entry(
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

    def _queue_journal_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        payload = json_safe(
            {
                "kind": "sciplot_canvas_journal_entry",
                "version": 1,
                "event_id": str(entry.get("event_id") or uuid4()),
                "recorded_at": str(entry.get("recorded_at") or _now()),
                **entry,
            }
        )
        if not isinstance(payload, dict):
            raise ValueError("Canvas journal entries must be JSON objects.")
        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("Canvas journal entries require an event_id.")
        if any(
            str(value.get("event_id") or "") == event_id
            for value in self.session.journal_outbox
        ):
            raise ValueError(f"Duplicate Canvas journal event ID: {event_id}")
        self.session.journal_outbox.append(payload)
        return payload

    def flush_journal_outbox(self) -> list[str]:
        if not self.session.journal_outbox:
            return []
        pending = list(self.session.journal_outbox)
        existing_ids = {
            str(entry.get("event_id") or "")
            for entry in read_operation_journal(self.journal_path)
            if entry.get("event_id")
        }
        flushed: list[str] = []
        for entry in pending:
            event_id = str(entry["event_id"])
            if event_id not in existing_ids:
                append_operation_journal_once(self.journal_path, entry)
                existing_ids.add(event_id)
            flushed.append(event_id)
        flushed_ids = set(flushed)
        self.session.journal_outbox = [
            entry
            for entry in pending
            if str(entry.get("event_id") or "") not in flushed_ids
        ]
        try:
            self.persist()
        except Exception:
            self.session.journal_outbox = pending
            raise
        return flushed

    def record_journal_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        payload = self._queue_journal_entry(entry)
        self.persist()
        try:
            self.flush_journal_outbox()
        except Exception as exc:
            payload["journal_flush_pending"] = True
            payload["journal_flush_error"] = f"{type(exc).__name__}: {exc}"
        return payload

    def _assert_no_active_transaction(self, action: str) -> None:
        transaction = self.session.active_transaction
        if transaction is None:
            return
        raise RuntimeError(
            f"Resolve assistant transaction {transaction.transaction_id} "
            f"before you {action}."
        )

    def review_annotation(self, annotation_id: str) -> ReviewAnnotation:
        annotation = next(
            (
                value
                for value in self.review_annotations
                if value.annotation_id == annotation_id
            ),
            None,
        )
        if annotation is None:
            raise ValueError(f"Unknown review annotation: {annotation_id}")
        return annotation

    def active_review_annotations(
        self,
        *,
        page_index: int | None = None,
    ) -> list[ReviewAnnotation]:
        page = self.session.current_page if page_index is None else int(page_index)
        return [
            annotation
            for annotation in self.review_annotations
            if annotation.page_index == page and annotation.state == "review_only"
        ]

    def _save_review_state(
        self,
        annotations: list[ReviewAnnotation],
    ) -> None:
        previous_annotations = list(self.review_annotations)
        previous_ids = list(self.session.review_annotation_ids)
        self.review_annotations = list(annotations)
        self.session.review_annotation_ids = [
            annotation.annotation_id for annotation in self.review_annotations
        ]
        try:
            save_review_annotations(
                self.annotations_path,
                self.review_annotations,
            )
            self.persist()
        except Exception:
            self.review_annotations = previous_annotations
            self.session.review_annotation_ids = previous_ids
            save_review_annotations(
                self.annotations_path,
                self.review_annotations,
            )
            self.persist()
            raise

    def add_review_annotation(
        self,
        annotation: ReviewAnnotation,
        *,
        provider: str = "user_review",
    ) -> ReviewAnnotation:
        self._assert_no_active_transaction("edit the review layer")
        if any(
            value.annotation_id == annotation.annotation_id
            for value in self.review_annotations
        ):
            raise ValueError(
                f"Duplicate review annotation ID: {annotation.annotation_id}"
            )
        self._save_review_state([*self.review_annotations, annotation])
        append_operation_journal(
            self.journal_path,
            {
                "kind": "sciplot_canvas_journal_entry",
                "version": 1,
                "event": "review_annotation_added",
                "provider": provider,
                "recorded_at": _now(),
                "revision": self.session.revision,
                "annotation": annotation.to_dict(),
                "publication_document_changed": False,
            },
        )
        return annotation

    def create_review_annotation_from_scene(
        self,
        *,
        shape: str,
        scene_geometry: dict[str, Any],
        coordinate_space: str = "normalized_page",
        target_object_id: str | None = None,
        text: str = "",
        style: ReviewAnnotationStyle | dict[str, Any] | None = None,
        provider: str = "user_review",
    ) -> ReviewAnnotation:
        resolved_target = (
            target_object_id
            if target_object_id is not None
            else self.adapter.review_anchor_target_id(
                self.session,
                coordinate_space,
            )
        )
        geometry = self.adapter.review_geometry_from_scene(
            shape=shape,
            scene_geometry=scene_geometry,
            coordinate_space=coordinate_space,
            target_object_id=resolved_target,
            page_index=self.session.current_page,
            session=self.session,
        )
        annotation_style = (
            style
            if isinstance(style, ReviewAnnotationStyle)
            else ReviewAnnotationStyle.from_dict(style)
        )
        annotation = ReviewAnnotation(
            page_index=self.session.current_page,
            shape=shape,
            coordinate_space=coordinate_space,
            geometry=geometry,
            text=(
                str(text).strip()
                or ("Review note" if shape == "text" else "")
            ),
            target_object_id=resolved_target,
            style=annotation_style,
        )
        return self.add_review_annotation(annotation, provider=provider)

    def update_review_annotation(
        self,
        annotation_id: str,
        *,
        geometry: dict[str, Any] | None = None,
        text: str | None = None,
        style: ReviewAnnotationStyle | dict[str, Any] | None = None,
        provider: str = "user_review",
    ) -> ReviewAnnotation:
        self._assert_no_active_transaction("edit the review layer")
        current = self.review_annotation(annotation_id)
        if current.state != "review_only":
            raise ValueError("Only active review-only annotations can be edited.")
        updated = replace(
            current,
            geometry=dict(geometry) if geometry is not None else current.geometry,
            text=str(text) if text is not None else current.text,
            style=(
                style
                if isinstance(style, ReviewAnnotationStyle)
                else (
                    ReviewAnnotationStyle.from_dict(style)
                    if style is not None
                    else current.style
                )
            ),
            updated_at=_now(),
        )
        annotations = [
            updated if value.annotation_id == annotation_id else value
            for value in self.review_annotations
        ]
        self._save_review_state(annotations)
        append_operation_journal(
            self.journal_path,
            {
                "kind": "sciplot_canvas_journal_entry",
                "version": 1,
                "event": "review_annotation_updated",
                "provider": provider,
                "recorded_at": _now(),
                "revision": self.session.revision,
                "annotation_id": annotation_id,
                "before": current.to_dict(),
                "after": updated.to_dict(),
                "publication_document_changed": False,
            },
        )
        return updated

    def move_review_annotation_from_scene(
        self,
        annotation_id: str,
        scene_geometry: dict[str, Any],
        *,
        provider: str = "user_review_direct_manipulation",
    ) -> ReviewAnnotation:
        annotation = self.review_annotation(annotation_id)
        geometry = self.adapter.review_geometry_from_scene(
            shape=annotation.shape,
            scene_geometry=scene_geometry,
            coordinate_space=annotation.coordinate_space,
            target_object_id=annotation.target_object_id,
            page_index=annotation.page_index,
            session=self.session,
        )
        return self.update_review_annotation(
            annotation_id,
            geometry=geometry,
            provider=provider,
        )

    def remove_review_annotation(
        self,
        annotation_id: str,
        *,
        provider: str = "user_review",
    ) -> ReviewAnnotation:
        self._assert_no_active_transaction("edit the review layer")
        current = self.review_annotation(annotation_id)
        if current.state != "review_only":
            raise ValueError(
                "Only an active review-only annotation can be removed."
            )
        removed = replace(
            current,
            state="removed",
            updated_at=_now(),
        )
        annotations = [
            removed if value.annotation_id == annotation_id else value
            for value in self.review_annotations
        ]
        self._save_review_state(annotations)
        append_operation_journal(
            self.journal_path,
            {
                "kind": "sciplot_canvas_journal_entry",
                "version": 1,
                "event": "review_annotation_removed",
                "provider": provider,
                "recorded_at": _now(),
                "revision": self.session.revision,
                "annotation_id": annotation_id,
                "before": current.to_dict(),
                "after": removed.to_dict(),
                "publication_document_changed": False,
            },
        )
        return removed

    def _record_history_side_effect(
        self,
        side_effect: dict[str, Any] | None,
    ) -> None:
        self._history_side_effects_undo.append(side_effect)
        self._history_side_effects_undo = self._history_side_effects_undo[-10:]
        self._history_side_effects_redo.clear()

    def _apply_history_side_effect(
        self,
        side_effect: dict[str, Any] | None,
        *,
        direction: str,
    ) -> dict[str, Any] | None:
        if side_effect is None:
            return None
        if direction not in {"undo", "redo"}:
            raise ValueError(f"Unsupported history direction: {direction!r}")
        payload = side_effect["before" if direction == "undo" else "after"]
        replacement = ReviewAnnotation.from_dict(dict(payload))
        annotations = [
            (
                replacement
                if value.annotation_id == replacement.annotation_id
                else value
            )
            for value in self.review_annotations
        ]
        self._save_review_state(annotations)
        return {
            "annotation_id": replacement.annotation_id,
            "state": replacement.state,
            "direction": direction,
        }

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
            data_point=(
                self.session.selection.data_point
                if self.session.selection.data_point is not None
                and self.session.selection.data_point.target_object_id == primary
                else None
            ),
        )
        self.adapter.restore_data_point_selection(
            self.session.selection.data_point,
            self.session,
        )
        self.persist()
        return item

    def select_widget_path(
        self,
        widget_path: str,
        *,
        mode: str = "new",
    ) -> dict[str, Any] | None:
        object_id = self.adapter.nearest_inspector_object_id(
            self.session,
            widget_path,
        )
        if object_id is None:
            return None
        return self.select_object_id(object_id, mode=mode)

    def visible_text_targets(self) -> list[dict[str, Any]]:
        return self.adapter.visible_text_targets(self.session)

    def contextual_inspector(self) -> CanvasInspectorModel:
        selected_id = self.session.selection.primary_object_id
        if selected_id is None:
            default_id = self.adapter.default_inspector_object_id(self.session)
            if default_id is None:
                raise RuntimeError(
                    "The current page does not contain a supported Canvas object."
                )
            self.select_object_id(default_id)
            selected_id = default_id
        return self.adapter.contextual_inspector(self.session, selected_id)

    def assistant_editing_capabilities(self) -> dict[str, Any]:
        """Describe only the selected object's bounded editable Inspector fields."""

        selected_id = self.session.selection.primary_object_id
        if selected_id is None:
            return {
                "scope": "selected_object",
                "target_object_id": None,
                "allowed_operations": [],
            }
        model = self.adapter.contextual_inspector(self.session, selected_id)
        operations = []
        for field in model.fields:
            if field.read_only:
                continue
            operations.append(
                {
                    "operation_type": "set_setting",
                    "target_id": selected_id,
                    "field_id": field.field_id,
                    "section": field.section,
                    "label": field.label,
                    "setting_path": field.setting_path,
                    "editor": field.editor,
                    "current_value": json_safe(field.value),
                    "choices": list(field.choices),
                    "minimum": field.minimum,
                    "maximum": field.maximum,
                    "help_text": field.help_text,
                }
            )
        return {
            "scope": "selected_object",
            "target_object_id": selected_id,
            "allowed_operations": operations,
        }

    def select_data_point(self, pickinfo: Any) -> dict[str, Any]:
        point = self.adapter.point_selection_from_pick(self.session, pickinfo)
        self.session.selection = CanvasSelection(
            object_ids=[point.target_object_id],
            primary_object_id=point.target_object_id,
            data_point=point,
        )
        self.persist()
        self.adapter.restore_data_point_selection(point, self.session)
        return point.to_dict()

    def clear_data_point_selection(self) -> None:
        selection = self.session.selection
        self.session.selection = CanvasSelection(
            object_ids=list(selection.object_ids),
            primary_object_id=selection.primary_object_id,
        )
        self.adapter.restore_data_point_selection(None, self.session)
        self.persist()

    def set_interaction_mode(self, mode: str) -> str:
        return self.adapter.set_interaction_mode(mode)

    def set_page(self, page_index: int) -> int:
        page = self.adapter.set_page(page_index)
        self.session.current_page = page
        selected = self.selected_object
        current_page_path = self.adapter.current_page_path
        if selected is None or not (
            str(selected.get("path")) == current_page_path
            or str(selected.get("path")).startswith(f"{current_page_path}/")
        ):
            default_id = self.adapter.default_inspector_object_id(self.session)
            self.session.selection = (
                CanvasSelection(
                    object_ids=[default_id],
                    primary_object_id=default_id,
                )
                if default_id is not None
                else CanvasSelection()
            )
            self.adapter.restore_data_point_selection(None, self.session)
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

    def _transaction_root(self, transaction_id: str) -> Path:
        transaction_text = str(transaction_id)
        try:
            normalized = str(UUID(transaction_text))
        except ValueError as exc:
            raise ValueError("Assistant transaction ID must be a UUID.") from exc
        if normalized != transaction_text:
            raise ValueError("Assistant transaction ID must use canonical UUID form.")
        root = (
            self.session_path.parent
            / ".canvas_transactions"
            / normalized
        ).resolve()
        transaction_parent = (
            self.session_path.parent / ".canvas_transactions"
        ).resolve()
        if not root.is_relative_to(transaction_parent):
            raise RuntimeError("Assistant transaction path escaped its project root.")
        return root

    def _resolve_transaction_artifact(
        self,
        reference: str,
        *,
        transaction_id: str,
    ) -> Path:
        value = Path(reference).expanduser()
        if not value.is_absolute():
            value = self.session_path.parent / value
        resolved = value.resolve()
        root = self._transaction_root(transaction_id)
        if not resolved.is_relative_to(root):
            raise RuntimeError(
                "Assistant transaction artifact resolves outside its transaction root."
            )
        return resolved

    def create_transaction_baseline(
        self,
        transaction_id: str,
    ) -> dict[str, Any]:
        """Persist the exact document and review sidecar before an AI turn."""

        self.adapter.assert_gui_thread()
        if self.session.active_transaction is not None:
            raise RuntimeError("An assistant transaction is already active.")
        self._sync_view_state()
        root = self._transaction_root(transaction_id)
        if root.exists() and any(root.iterdir()):
            raise RuntimeError(
                f"Assistant transaction artifacts already exist: {root}"
            )
        root.mkdir(parents=True, exist_ok=True)
        snapshot = root / "baseline.vsz"
        review_snapshot = root / "review_annotations.json"
        try:
            self.adapter.save_recovery_snapshot(snapshot)
            save_review_annotations(review_snapshot, self.review_annotations)
        except Exception:
            if snapshot.exists():
                snapshot.unlink()
            if review_snapshot.exists():
                review_snapshot.unlink()
            try:
                root.rmdir()
            except OSError:
                pass
            raise
        return {
            "snapshot_path": str(snapshot.relative_to(self.session_path.parent)),
            "snapshot_sha256": file_sha256(snapshot),
            "review_snapshot_path": str(
                review_snapshot.relative_to(self.session_path.parent)
            ),
            "review_snapshot_sha256": file_sha256(review_snapshot),
            "baseline_render_sha256": self.adapter.render_fingerprint(),
        }

    def restore_transaction_baseline(
        self,
        transaction_id: str,
        *,
        outcome: str,
        reason: str,
    ) -> dict[str, Any]:
        """Restore the exact cross-process transaction baseline and finalize."""

        self.adapter.assert_gui_thread()
        transaction = self.session.active_transaction
        if transaction is None or transaction.transaction_id != transaction_id:
            raise ValueError("No matching assistant transaction is active.")
        if outcome not in {"rejected", "rolled_back"}:
            raise ValueError(f"Unsupported assistant rollback outcome: {outcome!r}")
        if transaction.applying_batch_id is not None:
            raise RuntimeError(
                "An interrupted applying batch must be reconciled before rollback."
            )
        if not transaction.baseline_complete:
            transaction.status = "conflict"
            self.session.set_state("conflict")
            self.persist()
            raise RuntimeError(
                "Assistant transaction baseline is incomplete and cannot roll back."
            )
        baseline = self._resolve_transaction_artifact(
            str(transaction.snapshot_path),
            transaction_id=transaction_id,
        )
        review_baseline = self._resolve_transaction_artifact(
            str(transaction.review_snapshot_path),
            transaction_id=transaction_id,
        )
        if (
            not baseline.is_file()
            or file_sha256(baseline) != transaction.snapshot_sha256
            or not review_baseline.is_file()
            or file_sha256(review_baseline)
            != transaction.review_snapshot_sha256
        ):
            transaction.status = "conflict"
            self.session.set_state("conflict")
            self.persist()
            raise RuntimeError(
                "Assistant transaction baseline integrity could not be verified."
            )

        root = self._transaction_root(transaction_id)
        current_snapshot = root / "pre_rollback_current.vsz"
        current_review = root / "pre_rollback_review_annotations.json"
        self.adapter.save_recovery_snapshot(current_snapshot)
        save_review_annotations(current_review, self.review_annotations)
        session_before = self.session.to_dict()
        annotations_before = list(self.review_annotations)
        before_render = self.adapter.render_fingerprint()
        rollback_snapshot: Path | None = None
        committed = False
        entry: dict[str, Any] | None = None
        try:
            baseline_clean = (
                transaction.baseline_saved_revision
                == transaction.base_revision
            )
            baseline_viewport = CanvasViewport.from_dict(
                transaction.baseline_viewport
            )
            restored_render = self.adapter.restore_snapshot(
                baseline,
                mark_modified=not baseline_clean,
                page_index=transaction.baseline_page,
                zoom_factor=baseline_viewport.zoom,
            )
            if restored_render != transaction.baseline_render_sha256:
                raise RuntimeError(
                    "Restored assistant baseline rendered differently from "
                    "the transaction start."
                )
            restored_annotations = load_review_annotations(review_baseline)
            next_revision = self.session.revision + 1
            rollback_snapshot = self._create_recovery_snapshot(
                revision=next_revision,
                event=f"assistant_{outcome}",
            )
            terminal_transaction = CanvasSession.from_dict(
                session_before
            ).active_transaction
            if terminal_transaction is None:
                raise RuntimeError("Missing assistant transaction during rollback.")
            terminal_transaction.status = outcome
            terminal_transaction.pending_batch = None
            terminal_transaction.pending_preview = None
            terminal_transaction.applying_batch_id = None
            terminal_transaction.updated_at = _now()

            self.session.revision = next_revision
            self.session.saved_revision = (
                next_revision
                if baseline_clean
                else int(transaction.baseline_saved_revision)
            )
            self.session.exported_revision = (
                next_revision
                if baseline_clean
                and transaction.baseline_exported_revision
                == transaction.base_revision
                else transaction.baseline_exported_revision
            )
            self.session.document_sha256 = transaction.baseline_document_sha256
            self.session.qa_summary = dict(transaction.baseline_qa_summary)
            self.session.structural_qa_summary = dict(
                transaction.baseline_structural_qa_summary
            )
            self.session.last_render_sha256 = restored_render
            self.session.current_page = self.adapter.current_page
            self.session.viewport = baseline_viewport
            self.review_annotations = restored_annotations
            self.session.review_annotation_ids = [
                annotation.annotation_id for annotation in restored_annotations
            ]
            save_review_annotations(
                self.annotations_path,
                restored_annotations,
            )
            snapshot_reference, snapshot_hash = self._record_recovery_snapshot(
                rollback_snapshot
            )
            self.inventory = self.adapter.bind_object_registry(self.session)
            self.adapter.restore_data_point_selection(
                self.session.selection.data_point,
                self.session,
            )
            self.session.active_transaction = None
            self.session.set_state(
                str(transaction.baseline_state)
                if baseline_clean
                else "editing"
            )
            entry = self._queue_journal_entry(
                {
                    "event": f"assistant_transaction_{outcome}",
                    "provider": transaction.provider,
                    "transaction_id": transaction_id,
                    "revision": next_revision,
                    "reason": str(reason or "").strip(),
                    "transaction": terminal_transaction.to_dict(),
                    "render_before": before_render,
                    "render_after": restored_render,
                    "baseline_render_sha256": (
                        transaction.baseline_render_sha256
                    ),
                    "recovery_snapshot": snapshot_reference,
                    "recovery_snapshot_sha256": snapshot_hash,
                    "verification": {
                        "exact_baseline_render": (
                            restored_render
                            == transaction.baseline_render_sha256
                        ),
                        "baseline_vsz_hash_verified": True,
                        "baseline_review_hash_verified": True,
                        "canonical_vsz_unchanged": (
                            transaction.baseline_document_sha256 is None
                            or (
                                self.document_path.is_file()
                                and file_sha256(self.document_path)
                                == transaction.baseline_document_sha256
                            )
                        ),
                    },
                }
            )
            self.persist()
            committed = True
            current_snapshot.unlink(missing_ok=True)
            current_review.unlink(missing_ok=True)
            self._history_side_effects_undo.clear()
            self._history_side_effects_redo.clear()
            self.flush_journal_outbox()
            return entry
        except Exception as exc:
            if committed and entry is not None:
                entry["journal_flush_pending"] = True
                entry["journal_flush_error"] = f"{type(exc).__name__}: {exc}"
                return entry
            try:
                self.adapter.restore_snapshot(
                    current_snapshot,
                    mark_modified=(
                        session_before["revision"]
                        != session_before["saved_revision"]
                    ),
                    page_index=int(session_before["current_page"]),
                    zoom_factor=float(session_before["viewport"]["zoom"]),
                )
                self.review_annotations = annotations_before
                save_review_annotations(
                    self.annotations_path,
                    annotations_before,
                )
            finally:
                if rollback_snapshot is not None and rollback_snapshot.exists():
                    rollback_snapshot.unlink()
                self.session = CanvasSession.from_dict(session_before)
                self.inventory = self.adapter.bind_object_registry(self.session)
                self.adapter.restore_data_point_selection(
                    self.session.selection.data_point,
                    self.session,
                )
                self.persist()
            raise

    def _resolve_operation_targets(
        self,
        batch: CanvasOperationBatch,
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        setting_paths: set[str] = set()
        widget_paths: set[str] = set()
        inventory_paths = {str(item.get("path") or "") for item in self.inventory}
        for operation in batch.operations:
            target = self.session.object_registry.by_id(operation.target_id)
            if target is None:
                raise ValueError(f"Unknown Canvas target: {operation.target_id}")
            if operation.operation_type == "set_setting":
                setting_path = str(operation.arguments["setting_path"])
                if setting_path in setting_paths:
                    raise ValueError(
                        f"CanvasOperationBatch repeats setting path {setting_path!r}."
                    )
                setting_paths.add(setting_path)
                if not setting_path.startswith(f"{target.current_path}/"):
                    raise ValueError(
                        f"Setting path {setting_path!r} is outside target "
                        f"{target.current_path!r}."
                    )
                current_value = self.adapter.setting_value(setting_path)
                if (
                    "expected_value" in operation.arguments
                    and json_safe(current_value)
                    != operation.arguments["expected_value"]
                ):
                    raise ValueError(
                        f"Expected value conflict at {setting_path}: "
                        f"{operation.arguments['expected_value']!r} "
                        f"!= {current_value!r}"
                    )
                normalized = self.adapter.validate_setting_value(
                    setting_path,
                    operation.arguments["value"],
                )
                changes.append(
                    {
                        "operation_type": "set_setting",
                        "operation_id": operation.operation_id,
                        "target_id": operation.target_id,
                        "setting_path": setting_path,
                        "old_value": json_safe(current_value),
                        "value": json_safe(normalized),
                    }
                )
                continue
            if operation.operation_type == "add_widget":
                if target.object_type not in {"page", "graph"}:
                    raise ValueError(
                        "Native annotations can only be added to a page or graph."
                    )
                widget_path = (
                    f"{target.current_path.rstrip('/')}/"
                    f"{operation.arguments['name']}"
                )
                if widget_path in widget_paths or widget_path in inventory_paths:
                    raise ValueError(
                        f"CanvasOperationBatch widget path already exists: "
                        f"{widget_path!r}."
                    )
                widget_paths.add(widget_path)
                changes.append(
                    {
                        "operation_type": "add_widget",
                        "operation_id": operation.operation_id,
                        "target_id": operation.target_id,
                        "parent_path": target.current_path,
                        "widget_type": operation.arguments["widget_type"],
                        "name": operation.arguments["name"],
                        "proposed_path": widget_path,
                        "index": operation.arguments.get("index", -1),
                        "settings": dict(operation.arguments["settings"]),
                    }
                )
                continue
            raise ValueError(
                f"Unsupported controller operation: {operation.operation_type}"
            )
        return changes

    def preview_batch(self, batch: CanvasOperationBatch) -> dict[str, Any]:
        """Validate a typed batch and summarize it without mutating the VSZ."""

        self.adapter.assert_gui_thread()
        self._sync_view_state()
        batch = CanvasOperationBatch.from_dict(batch.to_dict())
        if batch.base_revision != self.session.revision:
            raise ValueError(
                f"Stale CanvasOperationBatch: base_revision={batch.base_revision}, "
                f"current_revision={self.session.revision}."
            )
        changes = self._resolve_operation_targets(batch)
        effectful = any(
            change["operation_type"] == "add_widget"
            or json_safe(change.get("old_value")) != json_safe(change.get("value"))
            for change in changes
        )
        if not effectful:
            raise ValueError(
                "CanvasOperationBatch does not change the exact-current document."
            )
        return {
            "kind": "sciplot_canvas_operation_preview",
            "version": 1,
            "batch_id": batch.batch_id,
            "base_revision": batch.base_revision,
            "provider": batch.provider,
            "rationale": batch.rationale,
            "operation_count": len(batch.operations),
            "affected_target_ids": list(
                dict.fromkeys(
                    str(change["target_id"]) for change in changes
                )
            ),
            "changes": json_safe(changes),
            "render_before": self.adapter.render_fingerprint(),
            "publication_document_changed": False,
        }

    def _assert_operation_gateway(
        self,
        batch: CanvasOperationBatch,
        *,
        transaction_id: str | None,
    ) -> None:
        transaction = self.session.active_transaction
        if transaction is None:
            if transaction_id is not None:
                raise ValueError("No active assistant transaction matches this batch.")
            return
        if transaction_id != transaction.transaction_id:
            raise RuntimeError(
                "An active assistant transaction owns document mutations. "
                "Accept, reject, commit, or roll it back first."
            )
        if transaction.status != "active":
            raise RuntimeError("Resume the assistant transaction before applying.")
        if transaction.current_revision != self.session.revision:
            transaction.status = "conflict"
            self.session.set_state("conflict")
            self.persist()
            raise ValueError(
                "The assistant transaction revision no longer matches the "
                "exact-current document."
            )
        if transaction.applying_batch_id != batch.batch_id:
            raise ValueError(
                "The assistant transaction did not authorize this batch for apply."
            )

    def apply_batch(
        self,
        batch: CanvasOperationBatch,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        self.adapter.assert_gui_thread()
        self._sync_view_state()
        batch = CanvasOperationBatch.from_dict(batch.to_dict())
        self._assert_operation_gateway(batch, transaction_id=transaction_id)
        if batch.base_revision != self.session.revision:
            if transaction_id is not None and self.session.active_transaction:
                self.session.active_transaction.status = "conflict"
            self.session.set_state("conflict")
            self.persist()
            raise ValueError(
                f"Stale CanvasOperationBatch: base_revision={batch.base_revision}, "
                f"current_revision={self.session.revision}."
            )
        changes = self._resolve_operation_targets(batch)
        if not any(
            change["operation_type"] == "add_widget"
            or json_safe(change.get("old_value")) != json_safe(change.get("value"))
            for change in changes
        ):
            raise ValueError(
                "CanvasOperationBatch does not change the exact-current document."
            )
        session_before = self.session.to_dict()
        before_render = self.adapter.render_fingerprint()
        snapshot: Path | None = None
        applied_document = False
        committed = False
        entry: dict[str, Any] | None = None
        try:
            applied = self.adapter.apply_operation_batch(
                changes,
                description=batch.rationale,
            )
            applied_document = True
            after_render = self.adapter.render_fingerprint()
            next_revision = self.session.revision + 1
            snapshot = self._create_recovery_snapshot(
                revision=next_revision,
                event=(
                    "assistant_batch"
                    if transaction_id is not None
                    else "operation_batch"
                ),
            )
            revision = self.session.advance_revision(
                state=(
                    "ai_proposing"
                    if transaction_id is not None
                    else "editing"
                )
            )
            snapshot_reference, snapshot_hash = self._record_recovery_snapshot(
                snapshot
            )
            self.session.last_render_sha256 = after_render
            self.inventory = self.adapter.bind_object_registry(self.session)
            if transaction_id is not None:
                transaction = self.session.active_transaction
                if transaction is None:
                    raise RuntimeError(
                        "The assistant transaction disappeared during apply."
                    )
                transaction.record_applied(
                    batch_id=batch.batch_id,
                    revision=revision,
                )
            entry = self._queue_journal_entry(
                {
                    "event": (
                        "assistant_batch_applied"
                        if transaction_id is not None
                        else "operation_batch_applied"
                    ),
                    "provider": batch.provider,
                    "transaction_id": transaction_id,
                    "revision": revision,
                    "batch": batch.to_dict(),
                    "changes": json_safe(applied),
                    "affected_targets": list(
                        dict.fromkeys(
                            str(change["target_id"]) for change in changes
                        )
                    ),
                    "render_before": before_render,
                    "render_after": after_render,
                    "recovery_snapshot": snapshot_reference,
                    "recovery_snapshot_sha256": snapshot_hash,
                    "verification": {
                        "target_resolution": "passed",
                        "atomic_batch": True,
                        "live_render_changed": after_render != before_render,
                        "recovery_snapshot_verified": (
                            file_sha256(snapshot) == snapshot_hash
                        ),
                    },
                }
            )
            self.persist()
            committed = True
            self.flush_journal_outbox()
            self._record_history_side_effect(None)
            return entry
        except Exception as exc:
            if committed and entry is not None:
                entry["journal_flush_pending"] = True
                entry["journal_flush_error"] = f"{type(exc).__name__}: {exc}"
                self._record_history_side_effect(None)
                return entry
            if applied_document:
                try:
                    self.adapter.undo()
                except Exception:
                    pass
            if snapshot is not None and snapshot.exists():
                snapshot.unlink()
            self.session = CanvasSession.from_dict(session_before)
            self.inventory = self.adapter.bind_object_registry(self.session)
            self.adapter.force_redraw()
            self.persist()
            raise

    def apply_setting_changes(
        self,
        *,
        target_id: str,
        changes: list[dict[str, Any]],
        provider: str,
        rationale: str,
    ) -> dict[str, Any]:
        if not changes:
            raise ValueError("Canvas setting changes cannot be empty.")
        operations: list[CanvasOperation] = []
        for change in changes:
            setting_path = str(change.get("setting_path") or "")
            if not setting_path:
                raise ValueError("Canvas setting_path must be a non-empty string.")
            current_value = self.adapter.setting_value(setting_path)
            operations.append(
                CanvasOperation.set_setting(
                    target_id=target_id,
                    setting_path=setting_path,
                    value=change.get("value"),
                    expected_value=current_value,
                    require_expected_value=True,
                )
            )
        return self.apply_batch(
            CanvasOperationBatch(
                base_revision=self.session.revision,
                provider=provider,
                rationale=rationale,
                operations=tuple(operations),
            )
        )

    def promote_review_annotation(
        self,
        annotation_id: str,
        *,
        provider: str = "user_review_promotion",
    ) -> dict[str, Any]:
        """Atomically promote a sidecar mark into one native Veusz widget."""

        self._assert_no_active_transaction("promote a review annotation")
        self.adapter.assert_gui_thread()
        self._sync_view_state()
        annotation = self.review_annotation(annotation_id)
        if annotation.page_index != self.session.current_page:
            raise ValueError(
                "Open the review annotation's page before promoting it."
            )
        spec = self.adapter.native_annotation_spec(annotation, self.session)
        operation = CanvasOperation.add_widget(
            target_id=str(spec["target_id"]),
            widget_type=str(spec["widget_type"]),
            name=str(spec["name"]),
            settings=dict(spec["settings"]),
            index=int(spec.get("index", -1)),
        )
        batch = CanvasOperationBatch(
            base_revision=self.session.revision,
            provider=provider,
            rationale=(
                f"Promote review {annotation.shape} into a native Veusz "
                "annotation."
            ),
            operations=(operation,),
        )
        batch = CanvasOperationBatch.from_dict(batch.to_dict())
        prepared = self._resolve_operation_targets(batch)
        session_before = self.session.to_dict()
        annotations_before = list(self.review_annotations)
        before_render = self.adapter.render_fingerprint()
        snapshot: Path | None = None
        applied_document = False
        try:
            applied = self.adapter.apply_operation_batch(
                prepared,
                description=batch.rationale,
            )
            applied_document = True
            after_render = self.adapter.render_fingerprint()
            next_revision = self.session.revision + 1
            snapshot = self._create_recovery_snapshot(
                revision=next_revision,
                event="review_promotion",
            )
            revision = self.session.advance_revision(state="editing")
            snapshot_reference, snapshot_hash = self._record_recovery_snapshot(
                snapshot
            )
            self.session.last_render_sha256 = after_render
            self.inventory = self.adapter.bind_object_registry(self.session)
            created_path = str(applied[0].get("created_path") or "")
            created_item = next(
                (
                    item
                    for item in self.inventory
                    if str(item.get("path")) == created_path
                ),
                None,
            )
            if created_item is None:
                raise RuntimeError(
                    "The promoted native annotation did not enter the "
                    "stable-object registry."
                )
            promoted = replace(
                annotation,
                state="promoted",
                promoted_object_id=str(created_item["object_id"]),
                updated_at=_now(),
            )
            promoted_annotations = [
                (
                    promoted
                    if value.annotation_id == annotation.annotation_id
                    else value
                )
                for value in self.review_annotations
            ]
            self._save_review_state(promoted_annotations)
            entry = {
                "kind": "sciplot_canvas_journal_entry",
                "version": 1,
                "event": "review_annotation_promoted",
                "provider": provider,
                "recorded_at": _now(),
                "revision": revision,
                "annotation_id": annotation.annotation_id,
                "before": annotation.to_dict(),
                "after": promoted.to_dict(),
                "batch": batch.to_dict(),
                "changes": json_safe(applied),
                "render_before": before_render,
                "render_after": after_render,
                "recovery_snapshot": snapshot_reference,
                "recovery_snapshot_sha256": snapshot_hash,
                "publication_document_changed": True,
            }
            append_operation_journal(self.journal_path, entry)
            self._record_history_side_effect(
                {
                    "kind": "review_annotation_transition",
                    "annotation_id": annotation.annotation_id,
                    "before": annotation.to_dict(),
                    "after": promoted.to_dict(),
                }
            )
            return entry
        except Exception:
            if applied_document:
                try:
                    self.adapter.undo()
                except Exception:
                    pass
            if snapshot is not None and snapshot.exists():
                snapshot.unlink()
            self.session = CanvasSession.from_dict(session_before)
            self.review_annotations = annotations_before
            self.session.review_annotation_ids = [
                value.annotation_id for value in annotations_before
            ]
            save_review_annotations(self.annotations_path, annotations_before)
            self.persist()
            self.inventory = self.adapter.bind_object_registry(self.session)
            self.adapter.force_redraw()
            raise

    def run_structural_qa(self) -> dict[str, Any]:
        report = self.adapter.structural_qa(self.session)
        checks = list(report.get("checks") or [])
        annotation_ids = [
            annotation.annotation_id for annotation in self.review_annotations
        ]
        ids_consistent = annotation_ids == self.session.review_annotation_ids
        checks.append(
            {
                "id": "review_sidecar_consistent",
                "label": (
                    "CanvasSession and the non-exported review sidecar "
                    "reference the same annotations"
                ),
                "status": "passed" if ids_consistent else "failed",
                "detail": {
                    "session_ids": list(self.session.review_annotation_ids),
                    "sidecar_ids": annotation_ids,
                },
            }
        )
        active = self.active_review_annotations()
        unresolved: list[dict[str, str]] = []
        for annotation in active:
            try:
                self.adapter.review_geometry_to_scene(annotation, self.session)
            except Exception as exc:
                unresolved.append(
                    {
                        "annotation_id": annotation.annotation_id,
                        "error": str(exc),
                    }
                )
        checks.append(
            {
                "id": "review_anchors_resolve",
                "label": (
                    "Active review marks resolve from persisted page, graph, "
                    "data, or object coordinates"
                ),
                "status": "passed" if not unresolved else "failed",
                "detail": {
                    "active_count": len(active),
                    "unresolved": unresolved,
                },
            }
        )
        sidecar_only = all(
            annotation.state != "review_only"
            or annotation.promoted_object_id is None
            for annotation in self.review_annotations
        )
        checks.append(
            {
                "id": "review_marks_sidecar_only",
                "label": (
                    "Unpromoted review marks remain outside the publication "
                    "document"
                ),
                "status": "passed" if sidecar_only else "failed",
                "detail": {
                    "active_count": len(active),
                    "annotations_path": str(self.annotations_path),
                },
            }
        )
        failed_ids = [
            str(check["id"])
            for check in checks
            if check.get("status") == "failed"
        ]
        warning_ids = [
            str(check["id"])
            for check in checks
            if check.get("status") == "warning"
        ]
        report["checks"] = checks
        report["status"] = (
            "failed" if failed_ids else ("warning" if warning_ids else "passed")
        )
        report["ready_for_artifact_qa"] = not failed_ids
        report["summary"] = {
            "check_count": len(checks),
            "passed_count": sum(
                check.get("status") == "passed" for check in checks
            ),
            "failed_ids": failed_ids,
            "warning_ids": warning_ids,
        }
        self.session.structural_qa_summary = json_safe(report)
        self.session.last_render_sha256 = self.adapter.render_fingerprint()
        self.persist()
        return report

    def undo(
        self,
        *,
        provider: str = "user",
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        self._sync_view_state()
        transaction = self.session.active_transaction
        transaction_batch_id: str | None = None
        if transaction is not None:
            if transaction_id != transaction.transaction_id:
                raise RuntimeError(
                    "The active assistant transaction owns document undo."
                )
            if transaction.status != "active":
                raise RuntimeError(
                    "Resume the assistant transaction before undoing its batch."
                )
            if transaction.pending_batch is not None:
                raise RuntimeError(
                    "Accept or reject the pending proposal before undoing a batch."
                )
            if transaction.current_revision != self.session.revision:
                transaction.status = "conflict"
                self.session.set_state("conflict")
                self.persist()
                raise RuntimeError(
                    "The assistant transaction revision no longer matches "
                    "the document."
                )
            active_batches = transaction.active_batch_ids
            if not active_batches:
                raise RuntimeError(
                    "The assistant transaction has no accepted batch to undo."
                )
            transaction_batch_id = active_batches[-1]
        elif transaction_id is not None:
            raise ValueError("No active assistant transaction matches this undo.")
        before_render = self.adapter.render_fingerprint()
        has_side_effect = bool(self._history_side_effects_undo)
        side_effect = (
            self._history_side_effects_undo[-1]
            if has_side_effect
            else None
        )
        if transaction is not None and not self.adapter.can_undo:
            raise RuntimeError(
                "Per-batch undo is unavailable after a recovery boundary; "
                "roll back the whole assistant turn instead."
            )
        session_before = self.session.to_dict()
        annotations_before = list(self.review_annotations)
        snapshot: Path | None = None
        committed = False
        entry: dict[str, Any] | None = None
        after_render = self.adapter.undo()
        next_revision = self.session.revision + 1
        review_transition: dict[str, Any] | None = None
        try:
            review_transition = self._apply_history_side_effect(
                side_effect,
                direction="undo",
            )
            snapshot = self._create_recovery_snapshot(
                revision=next_revision,
                event=(
                    "assistant_undo"
                    if transaction is not None
                    else "undo"
                ),
            )
            revision = self.session.advance_revision(
                state=(
                    "ai_proposing"
                    if transaction is not None
                    else "editing"
                )
            )
            snapshot_reference, snapshot_hash = self._record_recovery_snapshot(
                snapshot
            )
            self.session.last_render_sha256 = after_render
            if transaction is not None:
                if transaction_batch_id is None:
                    raise RuntimeError("Missing assistant batch identity for undo.")
                transaction.record_undo(
                    batch_id=transaction_batch_id,
                    revision=revision,
                )
            entry = self._queue_journal_entry(
                {
                    "event": (
                        "assistant_batch_undone"
                        if transaction is not None
                        else "undo"
                    ),
                    "provider": provider,
                    "transaction_id": transaction_id,
                    "batch_id": transaction_batch_id,
                    "revision": revision,
                    "render_before": before_render,
                    "render_after": after_render,
                    "recovery_snapshot": snapshot_reference,
                    "recovery_snapshot_sha256": snapshot_hash,
                    "review_transition": review_transition,
                    "verification": {
                        "live_render_changed": after_render != before_render,
                        "recovery_snapshot_verified": (
                            file_sha256(snapshot) == snapshot_hash
                        ),
                    },
                }
            )
            self.persist()
            committed = True
            self.flush_journal_outbox()
            if has_side_effect:
                self._history_side_effects_undo.pop()
                self._history_side_effects_redo.append(side_effect)
            return entry
        except Exception as exc:
            if committed and entry is not None:
                entry["journal_flush_pending"] = True
                entry["journal_flush_error"] = f"{type(exc).__name__}: {exc}"
                if has_side_effect:
                    self._history_side_effects_undo.pop()
                    self._history_side_effects_redo.append(side_effect)
                return entry
            if review_transition is not None:
                try:
                    self._apply_history_side_effect(
                        side_effect,
                        direction="redo",
                    )
                except Exception:
                    self.review_annotations = annotations_before
                    save_review_annotations(
                        self.annotations_path,
                        annotations_before,
                    )
            self.adapter.redo()
            if snapshot is not None and snapshot.exists():
                snapshot.unlink()
            self.session = CanvasSession.from_dict(session_before)
            self.inventory = self.adapter.bind_object_registry(self.session)
            self.adapter.force_redraw()
            self.persist()
            raise

    def redo(self, *, provider: str = "user") -> dict[str, Any]:
        self._assert_no_active_transaction("redo document history")
        self._sync_view_state()
        before_render = self.adapter.render_fingerprint()
        has_side_effect = bool(self._history_side_effects_redo)
        side_effect = (
            self._history_side_effects_redo[-1]
            if has_side_effect
            else None
        )
        after_render = self.adapter.redo()
        next_revision = self.session.revision + 1
        review_transition: dict[str, Any] | None = None
        try:
            review_transition = self._apply_history_side_effect(
                side_effect,
                direction="redo",
            )
            snapshot = self._create_recovery_snapshot(
                revision=next_revision, event="redo"
            )
        except Exception:
            if review_transition is not None:
                self._apply_history_side_effect(side_effect, direction="undo")
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
            "review_transition": review_transition,
        }
        append_operation_journal(self.journal_path, entry)
        if has_side_effect:
            self._history_side_effects_redo.pop()
            self._history_side_effects_undo.append(side_effect)
        return entry

    def save(self) -> Path:
        self._assert_no_active_transaction("save the canonical VSZ")
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
        self._assert_no_active_transaction("record an exact-current export")
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
