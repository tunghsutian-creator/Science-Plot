from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6 import QtCore

from sciplot_core.canvas.composition import (
    CompositionProject,
    CompositionVariant,
    preview_composition_batch,
)
from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_core.composition_workspace import (
    CompositionWorkspace,
    activate_composition_variant,
    composition_variant_authority_status,
    create_composition_variant,
    persist_composition_batch,
)
from sciplot_gui.composition_compiler import (
    compile_native_composition,
    render_source_module_previews,
)


class CompositionAuthorityConflict(RuntimeError):
    """A layout change would overwrite an exact-current edited composite."""

    def __init__(self, status: dict[str, Any]) -> None:
        self.status = dict(status)
        state = str(status.get("state") or "composition_authority_conflict")
        super().__init__(
            "The exact-current composite cannot be regenerated automatically "
            f"because its authority state is {state}."
        )


@dataclass(frozen=True)
class CompositionTransactionResult:
    preview: dict[str, Any]
    receipt: dict[str, Any]
    compile_result: dict[str, Any] | None
    project: CompositionProject

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview": self.preview,
            "receipt": self.receipt,
            "compile_result": self.compile_result,
            "project": self.project.to_dict(),
        }


class CompositionController(QtCore.QObject):
    """Route user and AI composition intent through one typed gateway."""

    projectChanged = QtCore.pyqtSignal(object)
    previewReady = QtCore.pyqtSignal(object)
    batchApplied = QtCore.pyqtSignal(object)
    compileStarted = QtCore.pyqtSignal(str)
    compileFinished = QtCore.pyqtSignal(object)
    sourcePreviewsReady = QtCore.pyqtSignal(object)
    errorRaised = QtCore.pyqtSignal(str)
    historyChanged = QtCore.pyqtSignal(bool, bool)

    def __init__(
        self,
        workspace: CompositionWorkspace,
        *,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.project = workspace.load()
        self.source_previews: dict[str, dict[str, Any]] = {}
        self.last_compile_result: dict[str, Any] | None = None
        self._undo_stack: list[tuple[dict[str, Any], ...]] = []
        self._redo_stack: list[tuple[dict[str, Any], ...]] = []

    @property
    def variant(self) -> CompositionVariant:
        return self.project.active_variant

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def reload(self) -> CompositionProject:
        self.project = self.workspace.load()
        self.projectChanged.emit(self.project)
        return self.project

    def _reset_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.historyChanged.emit(False, False)

    def create_variant(self, name: str) -> CompositionProject:
        self.project = create_composition_variant(
            self.workspace,
            source_variant_id=self.variant.variant_id,
            name=name,
        )
        self._reset_history()
        self.projectChanged.emit(self.project)
        return self.project

    def activate_variant(self, variant_id: str) -> CompositionProject:
        self.project = activate_composition_variant(self.workspace, variant_id)
        self._reset_history()
        self.projectChanged.emit(self.project)
        return self.project

    def authority_status(self) -> dict[str, Any]:
        return composition_variant_authority_status(
            self.workspace,
            self.project,
            self.variant.variant_id,
        )

    def load_source_previews(self, *, dpi: int = 110) -> dict[str, dict[str, Any]]:
        records = render_source_module_previews(self.workspace, dpi=dpi)
        self.source_previews = {str(record["module_id"]): record for record in records}
        self.sourcePreviewsReady.emit(dict(self.source_previews))
        return dict(self.source_previews)

    def _batch(
        self,
        operation: CanvasOperation,
        *,
        provider: str,
        rationale: str,
    ) -> CanvasOperationBatch:
        return CanvasOperationBatch(
            base_revision=self.variant.revision,
            operations=(operation,),
            provider=provider,
            rationale=rationale,
        )

    def placement_batch(
        self,
        module_id: str,
        slot_ref: str | None,
        *,
        provider: str = "user",
    ) -> CanvasOperationBatch:
        current = self.variant.placement(module_id).slot_ref
        return self._batch(
            CanvasOperation.place_composition_module(
                variant_id=self.variant.variant_id,
                module_id=module_id,
                slot_ref=slot_ref,
                expected_slot_ref=current,
            ),
            provider=provider,
            rationale=f"Place {module_id} in {slot_ref or 'the module tray'}.",
        )

    def reorder_batch(
        self,
        ordered_module_ids: list[str] | tuple[str, ...],
        *,
        provider: str = "user",
    ) -> CanvasOperationBatch:
        return self._batch(
            CanvasOperation.reorder_composition_modules(
                variant_id=self.variant.variant_id,
                ordered_module_ids=ordered_module_ids,
                expected_ordered_module_ids=self.variant.ordered_module_ids(),
            ),
            provider=provider,
            rationale="Reorder composition modules on the physical canvas.",
        )

    def layout_batch(
        self,
        layout_id: str,
        *,
        provider: str = "user",
    ) -> CanvasOperationBatch:
        return self._batch(
            CanvasOperation.set_composition_layout(
                variant_id=self.variant.variant_id,
                layout_id=layout_id,
                expected_layout_id=self.variant.layout.layout_id,
            ),
            provider=provider,
            rationale=f"Use the exact {layout_id} publication layout.",
        )

    def height_batch(
        self,
        height_mm: float,
        *,
        provider: str = "user",
    ) -> CanvasOperationBatch:
        return self._batch(
            CanvasOperation.set_composition_canvas_height(
                variant_id=self.variant.variant_id,
                height_mm=height_mm,
                expected_height_mm=self.variant.layout.canvas_height_mm,
            ),
            provider=provider,
            rationale=f"Set the composition height to {height_mm:g} mm.",
        )

    def legend_policy_batch(
        self,
        legend_policy: str,
        *,
        provider: str = "user",
    ) -> CanvasOperationBatch:
        return self._batch(
            CanvasOperation.set_composition_legend_policy(
                variant_id=self.variant.variant_id,
                legend_policy=legend_policy,
                expected_legend_policy=self.variant.legend_policy,
            ),
            provider=provider,
            rationale=f"Set composition legend policy to {legend_policy}.",
        )

    def preview_batch(self, batch: CanvasOperationBatch) -> dict[str, Any]:
        preview = preview_composition_batch(self.project, batch)
        self.previewReady.emit(preview)
        return preview

    @staticmethod
    def _inverse_operation_specs(
        preview: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        variant_id = str(preview["variant_id"])
        specs: list[dict[str, Any]] = []
        for change in reversed(list(preview.get("changes") or [])):
            if not change.get("effectful"):
                continue
            operation_type = str(change["operation_type"])
            if operation_type == "composition_place_module":
                arguments = {
                    "module_id": str(change["module_id"]),
                    "slot_ref": change.get("old_slot_ref"),
                    "expected_slot_ref": change.get("new_slot_ref"),
                }
            elif operation_type == "composition_reorder_modules":
                arguments = {
                    "ordered_module_ids": list(change["old_order"]),
                    "expected_ordered_module_ids": list(change["new_order"]),
                }
            elif operation_type == "composition_set_layout":
                arguments = {
                    "layout_id": str(change["old_layout_id"]),
                    "expected_layout_id": str(change["new_layout_id"]),
                }
            elif operation_type == "composition_set_canvas_height":
                arguments = {
                    "height_mm": float(change["old_height_mm"]),
                    "expected_height_mm": float(change["new_height_mm"]),
                }
            elif operation_type == "composition_set_legend_policy":
                arguments = {
                    "legend_policy": str(change["old_legend_policy"]),
                    "expected_legend_policy": str(change["new_legend_policy"]),
                }
            else:
                raise ValueError(
                    f"Cannot build composition history for {operation_type!r}."
                )
            specs.append(
                {
                    "operation_type": operation_type,
                    "target_id": variant_id,
                    "arguments": arguments,
                }
            )
        if not specs:
            raise ValueError("Composition history requires an effectful operation.")
        return tuple(specs)

    def _batch_from_specs(
        self,
        specs: tuple[dict[str, Any], ...],
        *,
        provider: str,
        rationale: str,
    ) -> CanvasOperationBatch:
        return CanvasOperationBatch(
            base_revision=self.variant.revision,
            operations=tuple(
                CanvasOperation(
                    operation_type=str(spec["operation_type"]),
                    target_id=str(spec["target_id"]),
                    arguments=dict(spec["arguments"]),
                )
                for spec in specs
            ),
            provider=provider,
            rationale=rationale,
        )

    def ensure_compiled(
        self,
        *,
        regenerate_edited: bool = False,
    ) -> dict[str, Any]:
        self.compileStarted.emit(self.variant.variant_id)
        try:
            result = compile_native_composition(
                self.workspace,
                variant_id=self.variant.variant_id,
                regenerate_edited=regenerate_edited,
            )
        except Exception as exc:
            self.errorRaised.emit(str(exc))
            raise
        self.last_compile_result = result
        self.reload()
        self.compileFinished.emit(result)
        return result

    def apply_batch(
        self,
        batch: CanvasOperationBatch,
        *,
        compile_document: bool = True,
        record_history: bool = True,
        regenerate_edited: bool = False,
    ) -> CompositionTransactionResult:
        self.reload()
        preview = self.preview_batch(batch)
        inverse_specs = self._inverse_operation_specs(preview)
        status = self.authority_status()
        if not status.get("safe_to_mutate_composition"):
            if not regenerate_edited:
                raise CompositionAuthorityConflict(status)
            self.ensure_compiled(regenerate_edited=True)
            preview = self.preview_batch(batch)
            inverse_specs = self._inverse_operation_specs(preview)
        try:
            updated, receipt = persist_composition_batch(self.workspace, batch)
        except Exception as exc:
            self.errorRaised.emit(str(exc))
            raise
        self.project = updated
        compile_result: dict[str, Any] | None = None
        if compile_document and self.variant.ready_to_compile:
            compile_result = self.ensure_compiled()
        else:
            self.projectChanged.emit(self.project)
        if record_history:
            self._undo_stack.append(inverse_specs)
            self._redo_stack.clear()
            self.historyChanged.emit(self.can_undo, self.can_redo)
        result = CompositionTransactionResult(
            preview=preview,
            receipt=receipt,
            compile_result=compile_result,
            project=self.project,
        )
        self.batchApplied.emit(result)
        return result

    def _apply_history(
        self,
        source: list[tuple[dict[str, Any], ...]],
        destination: list[tuple[dict[str, Any], ...]],
        *,
        provider: str,
        rationale: str,
    ) -> CompositionTransactionResult:
        if not source:
            raise ValueError("No composition history action is available.")
        specs = source.pop()
        batch = self._batch_from_specs(
            specs,
            provider=provider,
            rationale=rationale,
        )
        preview = self.preview_batch(batch)
        reciprocal = self._inverse_operation_specs(preview)
        try:
            result = self.apply_batch(
                batch,
                record_history=False,
            )
        except Exception:
            source.append(specs)
            raise
        destination.append(reciprocal)
        self.historyChanged.emit(self.can_undo, self.can_redo)
        return result

    def undo(self) -> CompositionTransactionResult:
        return self._apply_history(
            self._undo_stack,
            self._redo_stack,
            provider="user_undo",
            rationale="Undo the last accepted composition operation.",
        )

    def redo(self) -> CompositionTransactionResult:
        return self._apply_history(
            self._redo_stack,
            self._undo_stack,
            provider="user_redo",
            rationale="Redo the last undone composition operation.",
        )


__all__ = [
    "CompositionAuthorityConflict",
    "CompositionController",
    "CompositionTransactionResult",
]
