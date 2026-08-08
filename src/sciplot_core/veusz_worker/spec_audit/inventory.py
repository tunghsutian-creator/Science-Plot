"""Collect visible plotters and categorical dataset bindings."""

from __future__ import annotations

import math
from typing import Any

from sciplot_core.veusz_worker.numeric_evidence import _dataset_evidence
from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.widget_bindings import (
    _numeric_setting_equal,
    _visible_data_bindings,
)


def build_spec_audit_inventory(
    loaded_document: Any,
    spec: dict[str, Any],
) -> SpecAuditInventory:
    units: list[dict[str, Any]] = []

    seen_identities: set[str] = set()

    allowed_xy_records: set[tuple[str, str, str]] = set()

    expected_xy_order: list[tuple[str, str, str, str]] = []

    allowed_boxplot_records: set[tuple[str, tuple[str, ...], tuple[float, ...]]] = set()

    expected_boxplot_order: list[tuple[str, tuple[str, ...], tuple[float, ...]]] = []

    categorical = spec.get("categorical")

    categorical_kind = (
        str(categorical.get("presentation_kind") or "")
        if isinstance(categorical, dict)
        else ""
    )

    categorical_groups = {
        str(group.get("y_name") or ""): group
        for group in (
            categorical.get("groups", []) if isinstance(categorical, dict) else []
        )
        if isinstance(group, dict)
    }

    eligible_box_groups = [
        group
        for group in categorical_groups.values()
        if group.get("boxplot_eligible") is True
    ]

    expected_box_name_by_y = {
        str(group["y_name"]): f"categorical_boxplot_{index}"
        for index, group in enumerate(eligible_box_groups, start=1)
    }

    xy_records = _visible_data_bindings(
        loaded_document,
        widget_type="xy",
        setting_names=(
            "xData",
            "yData",
            "labels",
            "key",
            "PlotLine/color",
            "PlotLine/style",
            "PlotLine/width",
            "PlotLine/hide",
            "PlotLine/transparency",
            "marker",
            "markerSize",
            "thinfactor",
            "MarkerFill/color",
            "MarkerFill/hide",
            "MarkerFill/transparency",
            "MarkerLine/color",
            "MarkerLine/width",
            "MarkerLine/hide",
            "MarkerLine/transparency",
        ),
    )

    boxplot_records = _visible_data_bindings(
        loaded_document, widget_type="boxplot", setting_names=("values", "posn")
    )

    bar_records = _visible_data_bindings(
        loaded_document,
        widget_type="bar",
        setting_names=(
            "mode",
            "direction",
            "posn",
            "lengths",
            "keys",
            "barfill",
            "groupfill",
            "errorstyle",
        ),
    )

    component_bar_record: dict[str, Any] | None = None

    component_bar_datasets_by_y: dict[str, list[dict[str, Any]]] = {}

    allowed_bar_paths: set[str] = set()

    if categorical_kind == "stacked_components":
        groups = [
            group for group in categorical.get("groups", []) if isinstance(group, dict)
        ]
        expected_lengths: list[str] = []
        for group_index, group in enumerate(groups, start=1):
            group_datasets: list[dict[str, Any]] = []
            components = [
                component
                for component in group.get("components", [])
                if isinstance(component, dict)
            ]
            for component_index, component in enumerate(components, start=1):
                dataset_name = f"category_bar_component_{group_index}_{component_index}"
                expected_lengths.append(dataset_name)
                group_datasets.append(
                    _dataset_evidence(
                        loaded_document,
                        dataset_name=dataset_name,
                        expected_values=[
                            float(component["value"])
                            if item_index == group_index
                            else math.nan
                            for item_index in range(1, len(groups) + 1)
                        ],
                        dimensions=1,
                    )
                )
            component_bar_datasets_by_y[str(group.get("y_name") or "")] = group_datasets
        _dataset_evidence(
            loaded_document,
            dataset_name="category_bar_positions",
            expected_values=[float(group["position"]) for group in groups],
            dimensions=1,
        )
        expected_keys = [""] * len(expected_lengths)
        if len(bar_records) != 1:
            raise ValueError(
                "Exact-current stacked-component specification requires one native Veusz bar plotter."
            )
        candidate = bar_records[0]
        bindings = candidate["bindings"]
        if (
            candidate["name"] != "categorical_bar"
            or str(bindings["mode"]) != "stacked"
            or str(bindings["direction"]) != "vertical"
            or (str(bindings["posn"]) != "category_bar_positions")
            or (list(bindings["lengths"]) != expected_lengths)
            or (list(bindings["keys"]) != expected_keys)
            or (
                not _numeric_setting_equal(
                    bindings["barfill"],
                    categorical.get("visual_style", {}).get("bar_width_fraction"),
                )
            )
            or (not _numeric_setting_equal(bindings["groupfill"], 0.75))
            or (str(bindings["errorstyle"]) != "none")
            or (set(candidate["dataset_bindings"]) != {"posn", "lengths"})
        ):
            raise ValueError(
                "Exact-current stacked-component bar geometry, keys, or dataset bindings differ from the rendered specification."
            )
        component_bar_record = candidate
        allowed_bar_paths.add(str(candidate["path"]))
    return SpecAuditInventory(
        loaded_document=loaded_document,
        units=units,
        seen_identities=seen_identities,
        allowed_xy_records=allowed_xy_records,
        expected_xy_order=expected_xy_order,
        allowed_boxplot_records=allowed_boxplot_records,
        expected_boxplot_order=expected_boxplot_order,
        categorical=categorical,
        categorical_kind=categorical_kind,
        categorical_groups=categorical_groups,
        expected_box_name_by_y=expected_box_name_by_y,
        xy_records=xy_records,
        boxplot_records=boxplot_records,
        bar_records=bar_records,
        component_bar_record=component_bar_record,
        component_bar_datasets_by_y=component_bar_datasets_by_y,
        allowed_bar_paths=allowed_bar_paths,
        series_encoding_evidence=[],
    )
