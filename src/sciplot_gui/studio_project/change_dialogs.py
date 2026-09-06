"""Review source and presentation changes before an explicit Apply action."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from PyQt6 import QtWidgets


def _style_summary(item: dict[str, Any]) -> list[str]:
    labels = {
        "Label/font": "label font",
        "Label/size": "label font size",
        "TickLabels/font": "tick label font",
        "TickLabels/size": "tick label size",
        "Line/width": "axis line width",
        "MajorTicks/width": "major tick width",
        "MinorTicks/width": "minor tick width",
        "PlotLine/width": "curve line width",
        "MarkerLine/width": "marker outline width",
        "PlotLine/color": "curve color",
        "MarkerFill/color": "marker fill color",
        "MarkerLine/color": "marker outline color",
        "Border/width": "border width",
        "Whisker/width": "whisker width",
        "Fill/color": "fill color",
        "Border/color": "border color",
        "Whisker/color": "whisker color",
        "Text/font": "text font",
        "Text/size": "text size",
        "horzPosn": "horizontal legend position",
        "vertPosn": "vertical legend position",
        "horzManual": "manual legend x position",
        "vertManual": "manual legend y position",
    }
    reasons = {
        "template_changed": "New plot type retained; previous styles are incompatible",
        "axis_meaning_or_unit_changed": "New axis meaning or units retained; previous styles are incompatible",
        "scientific_rule_changed": "New scientific rule retained; previous styles are incompatible",
        "figure_task_identity_changed": "Figure task changed; previous styles are incompatible",
        "new_or_ambiguous_series_identity": "New or ambiguous sample identity; previous sample styles skipped",
        "widget_not_compatible": "Incompatible plot element; previous styles skipped",
        "semantic_color_encoding_kept_from_new_source": "Scientific color encoding retained from the new source",
        "new_source_legend_layout_kept": "New source legend layout retained",
        "scientific_geometry_style_kept_from_new_source": "New-source geometry styles retained",
        "sample_removed": "Removed sample; previous sample styles skipped",
    }
    applied = item.get("applied", [])
    if applied:
        counts = Counter(
            labels.get(str(value.get("setting")), "other compatible style")
            for value in applied
        )
        details = ", ".join(f"{label} ({count})" for label, count in counts.items())
        lines = [f"Preserved {len(applied)} compatible style changes: {details}"]
    else:
        lines = ["No compatible custom style changes"]
    skipped = item.get("skipped", [])
    if skipped:
        lines.append(f"Skipped style transfers: {len(skipped)}")
    for skip in skipped:
        reason = reasons.get(
            str(skip.get("reason")),
            "Some styles could not be transferred; see Full preview details",
        )
        kinds = skip.get("widget_types", [])
        if kinds:
            names = {"rect": "rectangle", "xy": "curve", "key": "legend"}
            reason += ": " + ", ".join(
                names.get(str(kind), str(kind).replace("_", " ")) for kind in kinds
            )
        lines.append(reason)
    if item.get("reasons"):
        lines.append(
            "Additional style review information is available in Full preview details"
        )
    return lines


def project_change_preview_text(operation: str, preview: dict[str, Any]) -> str:
    lines = [
        f"Project: {preview.get('project', '')}",
        f"Status: {preview.get('status', '')}",
    ]
    if preview.get("status") != "ready":
        lines.append(
            str(preview.get("message") or preview.get("reason") or "Preview blocked.")
        )
    elif operation == "delivery_recovery":
        fingerprints = preview.get("fingerprints", {})
        lines.extend(
            [
                f"Recover from: {preview.get('candidate', '')}",
                f"Replace managed document: {preview.get('document', '')}",
                "Samples and numerical values: unchanged; source audit passed.",
                "Presentation: adopt the audited visible document exactly.",
                "Style transfer/skipped settings: not applicable; no styles are copied separately.",
                "Archived raw sources:",
                *[f"  {path}" for path in fingerprints.get("raw_files", {})],
            ]
        )
    else:
        lines.extend(
            [
                f"New source: {preview.get('source', '')}",
                f"Worksheet: {preview.get('worksheet') or '(automatic / inherited)'}",
                "Figures, samples and numerical changes:",
            ]
        )
        for figure in preview.get("changes", {}).get("figures", []):
            lines.extend(
                [
                    f"  {figure['figure_id']}: {figure['change']}",
                    f"    Added samples: {', '.join(figure['samples_added']) or '(none)'}",
                    f"    Removed samples: {', '.join(figure['samples_removed']) or '(none)'}",
                    f"    Sample order changed: {figure['sample_order_changed']}",
                    f"    Axes changed: {figure['axes_changed']}",
                ]
            )
            previous = {
                item["sample"]: item
                for item in (figure.get("before") or {}).get("series", [])
            }
            for item in (figure.get("after") or {}).get("series", []):
                old = previous.get(item["sample"])
                if old is not None:
                    changed = [
                        axis
                        for axis in ("x", "y", "error")
                        if old[axis]["sha256"] != item[axis]["sha256"]
                    ]
                    lines.append(
                        f"    {item['sample']} value changes: {', '.join(changed) or '(none)'}"
                    )
            for difference in figure.get("numerical_differences", []):
                lines.append(
                    f"    {difference['sample']} {difference['values']}: "
                    f"{difference['changed_value_count']} changed values"
                )
                for example in difference.get("examples", [])[:8]:
                    lines.append(
                        f"      Point {example['point_index']}: "
                        f"{example['before']} → {example['after']}"
                    )
                omitted = difference.get("omitted_example_count", 0)
                if omitted:
                    lines.append(f"      {omitted} further changed values")
            for phase in ("before", "after"):
                summary = figure.get(phase) or {}
                lines.append(f"    {phase.capitalize()}:")
                for series in summary.get("series", []):
                    ranges = []
                    for axis in ("x", "y", "error"):
                        values = series[axis]
                        if axis == "error" and not values["count"]:
                            continue
                        ranges.append(
                            f"{axis}: {values['count']} points, {values['minimum']} … {values['maximum']}"
                        )
                    lines.append(f"      {series['sample']} — {'; '.join(ranges)}")
                for group in summary.get("groups", []):
                    values = group.get("raw_values") or {}
                    statistics = group.get("statistics") or {}
                    details = "; ".join(
                        f"{name.replace('_', ' ')}: {value}"
                        for name, value in statistics.items()
                        if isinstance(value, str | int | float)
                    )
                    lines.append(
                        f"      {group['sample']}: {values.get('count', 0)} raw values"
                        + (f"; {details}" if details else "")
                    )
        lines.append("Compatible styles and skipped settings:")
        for item in preview.get("styles", []):
            lines.append(f"  {item['figure_id'].replace('_', ' ')}:")
            lines.extend(f"    {line}" for line in _style_summary(item))
    lines.extend(
        [
            "",
            "Apply archives the previous project revision and reopens the managed document.",
            "Then use Save && Export to refresh the visible delivery.",
        ]
    )
    return "\n".join(lines)


class SourceUpdateDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update project source — select input")
        layout = QtWidgets.QVBoxLayout(self)
        self.source = QtWidgets.QLineEdit()
        self.source.setPlaceholderText("Source file or dedicated data directory")
        layout.addWidget(self.source)
        browse = QtWidgets.QHBoxLayout()
        for label, directory in (("Choose file…", False), ("Choose directory…", True)):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, directory=directory: self._browse(directory)
            )
            browse.addWidget(button)
        layout.addLayout(browse)
        self.worksheet = QtWidgets.QLineEdit()
        self.worksheet.setPlaceholderText(
            "Worksheet (optional; leave blank to inherit selection)"
        )
        layout.addWidget(self.worksheet)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.preview_button = QtWidgets.QPushButton("Preview")
        buttons.addButton(
            self.preview_button, QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.preview_button.setEnabled(False)
        self.source.textChanged.connect(
            lambda value: self.preview_button.setEnabled(bool(value.strip()))
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, 180)

    def _browse(self, directory: bool) -> None:
        path = (
            QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select new source directory"
            )
            if directory
            else QtWidgets.QFileDialog.getOpenFileName(self, "Select new source file")[
                0
            ]
        )
        if path:
            self.source.setText(path)

    def selection(self) -> tuple[Path, str | None]:
        return Path(
            self.source.text().strip()
        ).expanduser().resolve(), self.worksheet.text().strip() or None


def confirm_project_change(
    parent: QtWidgets.QWidget, operation: str, preview: dict[str, Any]
) -> bool:
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(
        "Recover visible edits — preview"
        if operation == "delivery_recovery"
        else "Update project source — preview"
    )
    layout = QtWidgets.QVBoxLayout(dialog)
    details = QtWidgets.QPlainTextEdit(project_change_preview_text(operation, preview))
    details.setReadOnly(True)
    layout.addWidget(details)
    full_toggle = QtWidgets.QToolButton()
    full_toggle.setText("Full preview details")
    full_toggle.setCheckable(True)
    layout.addWidget(full_toggle)
    full = QtWidgets.QPlainTextEdit(json.dumps(preview, indent=2, ensure_ascii=False))
    full.setReadOnly(True)
    full.hide()
    full_toggle.toggled.connect(full.setVisible)
    layout.addWidget(full)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Cancel
    )
    if preview.get("status") == "ready":
        apply = QtWidgets.QPushButton("Apply reviewed changes")
        buttons.addButton(apply, QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        apply.setAutoDefault(False)
        apply.setDefault(False)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    cancel = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    if cancel is not None:
        cancel.setDefault(True)
        cancel.setFocus()
    dialog.resize(760, 620)
    return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
