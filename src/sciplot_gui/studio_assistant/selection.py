"""Track native Veusz selection and derive editable setting capabilities."""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.setting_catalog import (
    SUPPORTED_INSPECTOR_TYPES,
    specs_for_object_type,
)
from sciplot_core.assistant_provider import (
    AssistantRequest,
)


class SelectionMixin:
    def _widgets_selected(self, widgets: list[Any], _settings_proxy: Any) -> None:
        self.set_selected_widget(widgets[0] if widgets else None)

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
