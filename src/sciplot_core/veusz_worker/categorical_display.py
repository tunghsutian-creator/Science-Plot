"""Exact source-bound categorical presentation deltas in the loaded native owner."""
from copy import deepcopy
from importlib import import_module
from typing import Any

import numpy as np

from sciplot_core.studio_core.categorical_display import KEY, display_axes, effective_presentation, overlay
from sciplot_core.studio_core.categorical_display_errors import CategoricalPresentationConflict
from sciplot_core.studio_core.series_encoding_contract import series_encoding_from_spec
from sciplot_core.studio_core.series_request import veusz_literal_text
from sciplot_core.studio_core.veusz_data_import import category_display_labels

PARENT = "/page1/graph1/"


def dataset_snapshot(document: Any) -> dict[str, Any]:
    return {name: np.asarray(dataset.data).copy() for name, dataset in document.data.items()
            if name != "category_axis_display_labels"}


def audit_unchanged_datasets(document: Any, before: dict[str, Any]) -> None:
    after = dataset_snapshot(document)
    if set(before) != set(after) or any(not np.array_equal(value, after[name], equal_nan=True)
            if np.issubdtype(value.dtype, np.number) else not np.array_equal(value, after[name])
            for name, value in before.items()):
        raise ValueError("Categorical presentation changed original datasets, statistics or category identities.")


def _same(actual: Any, expected: Any, setting: str) -> bool:
    if setting.endswith("/color"):
        from PyQt6.QtGui import QColor

        return QColor(str(actual)).name() == QColor(str(expected)).name()
    return bool(actual == expected)


def _point_settings(spec: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    encoding = series_encoding_from_spec(item, style=spec["style"])
    return {"PlotLine/color": encoding["line"]["color"], "marker": encoding["marker"]["shape"],
            "MarkerFill/color": encoding["marker"]["fill_color"], "MarkerLine/color": encoding["marker"]["line_color"],
            "MarkerFill/hide": not encoding["marker"]["fill_visible"], "MarkerLine/hide": not encoding["marker"]["line_visible"]}


def _display(spec: dict[str, Any]) -> list[str]:
    return category_display_labels(display_axes(spec), spec["style"], spec["size_mm"])


def audit_presentation(document: Any, spec: dict[str, Any]) -> None:
    if KEY not in spec:
        return
    value, effective = overlay(spec), effective_presentation(spec)
    for item in effective["series"]:
        if item["name"] not in value["styles"] or spec["template"] != "point_line":
            continue
        for suffix, expected in _point_settings(effective, item).items():
            path = PARENT + item["name"] + "/" + suffix
            if not _same(document.resolveSettingPath(None, path).get(), expected, path):
                raise CategoricalPresentationConflict("Categorical display style differs from its source-bound presentation overlay. Restore the reviewed native style before retrying export.")
    if spec["template"] == "bar" and value["styles"]:
        _audit_bar_styles(document, effective, set(value["styles"]))
    if value["legend"]:
        legend = value["legend"]
        expected = {"columns": legend["columns"], "horzPosn": "left" if legend["position"].endswith("left") else "right",
                    "vertPosn": "top" if legend["position"].startswith("upper") else "bottom"}
        if any(document.resolveSettingPath(None, PARENT + "key1/" + field).get() != item for field, item in expected.items()):
            raise CategoricalPresentationConflict("Categorical native key differs from the explicit presentation overlay. Restore the reviewed native key before retrying export.")


def _audit_bar_styles(document: Any, spec: dict[str, Any], names: set[str]) -> None:
    grouped = spec["categorical"]["presentation_kind"] == "grouped_bar_error"
    labels = {item["label"] for item in spec["series"] if item["name"] in names}
    for index, group in enumerate(spec["categorical"]["groups"], 1):
        if group["label"] not in labels:
            continue
        path = PARENT + (f"categorical_bar_{index}" if grouped else "categorical_bar")
        for field, offset, key in (("BarFill/fills", 1, "fill_color"), ("BarLine/lines", 2, "keyline_color")):
            rows = document.resolveSettingPath(None, path + "/" + field).get()
            if not _same(rows[0 if grouped else index - 1][offset], group[key], "/color"):
                raise CategoricalPresentationConflict("Native bar colour differs from the categorical presentation overlay.")
        settings = {PARENT + f"categorical_bar_outline_{index}_{outline}/Line/color": group["keyline_color"]
                    for outline in range(1, 4)}
        if grouped:
            settings[PARENT + f"categorical_bar_fill_{index}/Fill/color"] = group["fill_color"]
        for path, color in settings.items():
            if not _same(document.resolveSettingPath(None, path).get(), color, path):
                raise CategoricalPresentationConflict("Native bar shape colour differs from its explicit categorical style.")
    from sciplot_core.studio_core.legend_contracts import categorical_component_legend_rect_contracts

    for record in categorical_component_legend_rect_contracts(spec):
        path = PARENT + record["name"] + "/Fill/color"
        if not _same(document.resolveSettingPath(None, path).get(), record["fill_color"], path):
            raise CategoricalPresentationConflict("Native segmented legend colour differs from its explicit categorical style.")


def prepare_operations(document: Any, before: dict[str, Any], after: dict[str, Any], changes: list[dict[str, Any]]) -> list[Any]:
    """No caller native paths, arrays, positions, expression or dataset setters."""
    ops = import_module("veusz.document.operations")
    result = []
    audit_presentation(document, before)
    old, new = effective_presentation(before), effective_presentation(after)
    raw_labels = [veusz_literal_text(label) for label in before["axes"]["x"]["category_labels"]]
    if list(document.data["category_axis_labels"].data) != raw_labels:
        raise ValueError("Original categorical text identities changed.")
    old_display, new_display = _display(before), _display(after)
    provider = PARENT + "category_axis_label_provider/labels"
    expected_dataset = "category_axis_labels" if old_display == raw_labels else "category_axis_display_labels"
    if document.resolveSettingPath(None, provider).get() != expected_dataset:
        raise ValueError("Categorical label provider differs from its exact display baseline.")
    if old_display != raw_labels and list(document.data[expected_dataset].data) != old_display:
        raise ValueError("Categorical display text differs from its exact baseline.")
    if new_display != old_display:
        if new_display == raw_labels:
            if "category_axis_display_labels" in document.data:
                result.append(ops.OperationDatasetDelete("category_axis_display_labels"))
            result.append(ops.OperationSettingSet(provider, "category_axis_labels"))
        else:
            result.append(ops.OperationDatasetSet("category_axis_display_labels", import_module("veusz.datasets").DatasetText(new_display)))
            result.append(ops.OperationSettingSet(provider, "category_axis_display_labels"))

    def setting(path: str, previous: Any, current: Any) -> None:
        if not _same(document.resolveSettingPath(None, path).get(), previous, path):
            raise ValueError("Current categorical style differs from the reviewed original series baseline.")
        if previous == current:
            return
        result.append(ops.OperationSettingSet(path, current))

    if before["template"] == "point_line":
        for original, revised in zip(old["series"], new["series"], strict=True):
            previous, current = _point_settings(old, original), _point_settings(new, revised)
            for suffix in previous:
                setting(PARENT + original["name"] + "/" + suffix, previous[suffix], current[suffix])
    else:
        _bar_operations(document, old, new, result, ops, setting)
    for change in changes:
        if "expected_legend" not in change:
            continue
        expected, legend = change["expected_legend"], overlay(after)["legend"]
        current = {"columns": legend["columns"], "horzPosn": "left" if legend["position"].endswith("left") else "right",
                   "vertPosn": "top" if legend["position"].startswith("upper") else "bottom"}
        for field in expected:
            setting(PARENT + "key1/" + field, expected[field], current[field])
    return result


def _bar_operations(document: Any, old: dict[str, Any], new: dict[str, Any], result: list[Any], ops: Any, setting: Any) -> None:
    grouped = old["categorical"]["presentation_kind"] == "grouped_bar_error"
    groups, revised = old["categorical"]["groups"], new["categorical"]["groups"]
    bar_settings: dict[str, Any] = {}
    for index, (before, after) in enumerate(zip(groups, revised, strict=True), 1):
        if before["fill_color"] == after["fill_color"] and before["keyline_color"] == after["keyline_color"]:
            continue
        path = PARENT + (f"categorical_bar_{index}" if grouped else "categorical_bar")
        for field, offset, key in (("BarFill/fills", 1, "fill_color"), ("BarLine/lines", 2, "keyline_color")):
            previous = document.resolveSettingPath(None, path + "/" + field).get()
            current = bar_settings.setdefault(path + "/" + field, [list(row) for row in deepcopy(previous)])
            row = 0 if grouped else index - 1
            if not _same(current[row][offset], before[key], "/color"):
                raise ValueError("Original bar colour differs from its source-bound contract.")
            current[row][offset] = after[key]
        for outline in range(1, 4):
            setting(PARENT + f"categorical_bar_outline_{index}_{outline}/Line/color", before["keyline_color"], after["keyline_color"])
        if grouped:
            setting(PARENT + f"categorical_bar_fill_{index}/Fill/color", before["fill_color"], after["fill_color"])
    result.extend(ops.OperationSettingSet(path, value) for path, value in bar_settings.items())
    from sciplot_core.studio_core.legend_contracts import categorical_component_legend_rect_contracts

    for before, after in zip(categorical_component_legend_rect_contracts(old), categorical_component_legend_rect_contracts(new), strict=True):
        setting(PARENT + before["name"] + "/Fill/color", before["fill_color"], after["fill_color"])
