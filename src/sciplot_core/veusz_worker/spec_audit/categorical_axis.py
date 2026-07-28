"""Validate categorical text datasets and label positions."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_worker.numeric_evidence import (
    _dataset_evidence,
    _text_dataset_values,
)
from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.widget_bindings import _visible_data_bindings


def audit_categorical_axis(
    inventory: SpecAuditInventory,
    spec: dict[str, Any],
) -> None:
    from sciplot_core.studio_core.series_request import veusz_literal_text

    loaded_document = inventory.loaded_document
    categorical = inventory.categorical
    if isinstance(categorical, dict):
        groups = [
            group for group in categorical.get("groups", []) if isinstance(group, dict)
        ]
        x_axis = spec["axes"]["x"]
        category_positions = [
            float(value) for value in x_axis.get("category_positions", [])
        ]
        expected_category_labels = [
            veusz_literal_text(value) for value in x_axis.get("category_labels", [])
        ]
        if (
            _text_dataset_values(loaded_document, dataset_name="category_axis_labels")
            != expected_category_labels
        ):
            raise ValueError(
                "Exact-current Veusz category text dataset does not match the ordered series labels."
            )
        _dataset_evidence(
            loaded_document,
            dataset_name="category_axis_x",
            expected_values=category_positions,
            dimensions=1,
        )
        _dataset_evidence(
            loaded_document,
            dataset_name="category_axis_y",
            expected_values=[0.0 for _position in category_positions]
            if categorical.get("presentation_kind") == "grouped_bar_error"
            else [float(group["descriptive_statistics"]["median"]) for group in groups],
            dimensions=1,
        )
        x_axis_records = [
            record
            for record in _visible_data_bindings(
                loaded_document,
                widget_type="axis",
                setting_names=("mode", "MajorTicks/manualTicks"),
            )
            if record["name"] == "x"
        ]
        if (
            len(x_axis_records) != 1
            or x_axis_records[0]["bindings"]["mode"] != "labels"
            or [
                float(value)
                for value in x_axis_records[0]["bindings"]["MajorTicks/manualTicks"]
            ]
            != category_positions
        ):
            raise ValueError(
                "Exact-current Veusz categorical axis does not expose the ordered label positions."
            )
