"""Native Veusz sample membership controls for the Project dock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtWidgets

from sciplot_core.studio import (
    VeuszSeriesRevisionError,
    apply_veusz_series_revision,
    can_revert_veusz_series_revision,
    commit_project_series_revision,
    has_pending_veusz_series_revision,
    inspect_veusz_series_revision,
    preview_veusz_series_revision,
    revert_veusz_series_revision,
)


class SeriesRevisionMixin:
    """Keep presentation selection in the live Document and native Undo."""

    def _initialize_series_revision(self) -> None:
        self._series_revision_available = False
        self._series_revision_preview_target: tuple[str, ...] | None = None
        self._series_revision_preview_changed = False
        self.series_revision_list.itemChanged.connect(
            self._series_revision_selection_changed
        )
        self.series_revision_up.clicked.connect(
            lambda: self._move_series_revision_item(-1)
        )
        self.series_revision_down.clicked.connect(
            lambda: self._move_series_revision_item(1)
        )
        self.series_revision_preview.clicked.connect(self.preview_series_revision)
        self.series_revision_apply.clicked.connect(self.apply_series_revision)
        self.series_revision_commit.clicked.connect(self.commit_series_revision)
        self.series_revision_undo.clicked.connect(self.undo_series_revision)
        self._refresh_series_revision()

    def _refresh_series_revision(self) -> None:
        try:
            state = inspect_veusz_series_revision(self.document, self.document_path)
        except VeuszSeriesRevisionError as exc:
            self._series_revision_available = False
            self.series_revision_group.hide()
            self._series_revision_unavailable = str(exc)
            self._update_series_revision_controls()
            return
        self._series_revision_available = True
        self._series_revision_unavailable = None
        self.series_revision_group.show()
        order = [*state["current_order"], *state["excluded"]]
        included = set(state["current_order"])
        blocker = QtCore.QSignalBlocker(self.series_revision_list)
        self.series_revision_list.clear()
        for label in order:
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if label in included
                else QtCore.Qt.CheckState.Unchecked
            )
            self.series_revision_list.addItem(item)
        del blocker
        if self.series_revision_list.count():
            self.series_revision_list.setCurrentRow(0)
        self._series_revision_preview_target = None
        self._series_revision_preview_changed = False
        self.series_revision_summary.setPlainText(
            "Current: " + " → ".join(state["current_order"])
        )
        self._update_series_revision_controls()

    def _series_revision_target(self) -> tuple[str, ...]:
        return tuple(
            self.series_revision_list.item(index).text()
            for index in range(self.series_revision_list.count())
            if self.series_revision_list.item(index).checkState()
            == QtCore.Qt.CheckState.Checked
        )

    def _series_revision_selection_changed(self, _item: Any = None) -> None:
        self._series_revision_preview_target = None
        self._series_revision_preview_changed = False
        self.series_revision_summary.setPlainText(
            "Selection changed. Preview before applying."
        )
        self._update_series_revision_controls()

    def _move_series_revision_item(self, direction: int) -> None:
        row = self.series_revision_list.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.series_revision_list.count():
            return
        item = self.series_revision_list.takeItem(row)
        self.series_revision_list.insertItem(target, item)
        self.series_revision_list.setCurrentRow(target)
        self._series_revision_selection_changed()

    def preview_series_revision(self) -> dict[str, Any] | None:
        target = self._series_revision_target()
        try:
            preview = preview_veusz_series_revision(
                self.document,
                self.document_path,
                target,
            )
        except VeuszSeriesRevisionError as exc:
            self.series_revision_summary.setPlainText(str(exc))
            self._series_revision_preview_target = None
            self._update_series_revision_controls()
            return None
        self._series_revision_preview_target = target
        self._series_revision_preview_changed = bool(preview["changed"])
        changes = []
        for key, label in (
            ("removed", "Remove"),
            ("added", "Add back"),
            ("moved", "Move"),
        ):
            if preview[key]:
                changes.append(f"{label}: {', '.join(preview[key])}")
        changes.append("Target: " + " → ".join(preview["target_order"]))
        changes.append(
            "Preserve: page size, margins, y axis, source values, and series style."
        )
        self.series_revision_summary.setPlainText("\n".join(changes))
        self._update_series_revision_controls()
        return preview

    def apply_series_revision(self) -> dict[str, Any] | None:
        target = self._series_revision_target()
        if target != self._series_revision_preview_target:
            return self.preview_series_revision()
        try:
            result = apply_veusz_series_revision(
                self.document,
                self.document_path,
                target,
            )
        except VeuszSeriesRevisionError as exc:
            self.series_revision_summary.setPlainText(str(exc))
            return None
        self._refresh_series_revision()
        if result.get("applied") is True:
            self.series_revision_summary.setPlainText(
                "Applied as one native Veusz Undo step. Commit the figure set "
                "to make this the exact-current project selection."
            )
        else:
            self.series_revision_summary.setPlainText(
                "The sample selection is unchanged."
            )
        self._refresh_document_state()
        return result

    def commit_series_revision(self) -> dict[str, Any] | None:
        if self.project_dir is None:
            self.series_revision_summary.setPlainText(
                "Series revision commit requires a managed Studio project."
            )
            return None
        target = self._series_revision_target()
        try:
            result = commit_project_series_revision(
                project_dir=self.project_dir,
                active_order=target,
                live_documents=self._live_project_documents(),
            )
        except Exception as exc:
            self.series_revision_summary.setPlainText(str(exc))
            return None
        self._refresh_project_revision_bridges()
        self.series_revision_summary.setPlainText(
            "Committed across the exact-current figure set: "
            + " → ".join(result["active_order"])
        )
        return result

    def save_or_commit_current_document(
        self,
        target: Path,
    ) -> dict[str, Any]:
        resolved_target = target.expanduser().resolve()
        if not self._series_revision_available:
            return self._atomic_save_document(self.document, resolved_target)
        pending = has_pending_veusz_series_revision(
            self.document,
            self.document_path,
        )
        if not pending:
            return self._atomic_save_document(self.document, resolved_target)
        if self.project_dir is None or resolved_target != self.document_path:
            raise RuntimeError(
                "Commit or undo the sample revision before saving to another path."
            )
        state = inspect_veusz_series_revision(self.document, self.document_path)
        commit = commit_project_series_revision(
            project_dir=self.project_dir,
            active_order=state["current_order"],
            live_documents=self._live_project_documents(),
        )
        self._refresh_project_revision_bridges()
        return {
            "kind": "sciplot_series_revision_save",
            "version": 1,
            "status": "passed",
            "target": str(resolved_target),
            "reopen_validated": True,
            "ready_for_export": True,
            "revision_commit": commit,
        }

    def _live_project_documents(self) -> dict[Path, Any]:
        documents: dict[Path, Any] = {}
        for window in getattr(type(self.window), "windows", []):
            bridge = getattr(window, "_sciplot_project_bridge", None)
            if (
                bridge is not None
                and getattr(bridge, "project_dir", None) == self.project_dir
            ):
                documents[bridge.document_path] = bridge.document
        return documents

    def _refresh_project_revision_bridges(self) -> None:
        for window in getattr(type(self.window), "windows", []):
            bridge = getattr(window, "_sciplot_project_bridge", None)
            if (
                bridge is not None
                and getattr(bridge, "project_dir", None) == self.project_dir
            ):
                bridge._refresh_series_revision()
                bridge._refresh_document_state()

    def undo_series_revision(self) -> dict[str, Any] | None:
        try:
            result = revert_veusz_series_revision(
                self.document,
                self.document_path,
            )
        except VeuszSeriesRevisionError as exc:
            self.series_revision_summary.setPlainText(str(exc))
            return None
        self._refresh_series_revision()
        self.series_revision_summary.setPlainText(
            "Revision reverted through native Veusz Undo."
        )
        self._refresh_document_state()
        return result

    def _series_revision_export_blocker(self) -> str | None:
        if not self._series_revision_available:
            return None
        if has_pending_veusz_series_revision(self.document, self.document_path):
            return (
                "The live sample order differs from the exact-current project. "
                "Commit the figure set or undo the revision before exporting."
            )
        return None

    def _update_series_revision_controls(self) -> None:
        if not hasattr(self, "series_revision_group"):
            return
        active = bool(
            self._series_revision_available
            and self.series_revision_group.isVisible()
            and not getattr(self, "_exporting", False)
        )
        target = self._series_revision_target() if active else ()
        self.series_revision_list.setEnabled(active)
        self.series_revision_preview.setEnabled(active and bool(target))
        self.series_revision_apply.setEnabled(
            active
            and bool(target)
            and target == self._series_revision_preview_target
            and self._series_revision_preview_changed
        )
        self.series_revision_commit.setEnabled(
            active
            and self.project_dir is not None
            and has_pending_veusz_series_revision(
                self.document,
                self.document_path,
            )
        )
        self.series_revision_up.setEnabled(
            active and self.series_revision_list.currentRow() > 0
        )
        self.series_revision_down.setEnabled(
            active
            and 0
            <= self.series_revision_list.currentRow()
            < self.series_revision_list.count() - 1
        )
        self.series_revision_undo.setEnabled(
            active and can_revert_veusz_series_revision(self.document)
        )
