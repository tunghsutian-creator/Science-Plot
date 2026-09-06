"""Bind categorical summary bars to their source-derived means and geometry."""

from __future__ import annotations

import math
from typing import Any

from sciplot_core.veusz_worker.numeric_evidence import _dataset_evidence
from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.widget_bindings import _numeric_setting_equal


def audit_bar_error_consumer(
    inventory: SpecAuditInventory, *, y_name: str
) -> tuple[list[dict[str, Any]], str]:
    groups = list(inventory.categorical_groups.values())
    evidence = [
        _dataset_evidence(
            inventory.loaded_document,
            dataset_name="category_bar_positions",
            expected_values=[float(group["position"]) for group in groups],
            dimensions=1,
        )
    ]
    lengths = [f"category_bar_mean_{index}" for index in range(1, len(groups) + 1)]
    group_index = next(
        index
        for index, group in enumerate(groups, start=1)
        if group["y_name"] == y_name
    )
    group = groups[group_index - 1]
    evidence.append(
        _dataset_evidence(
            inventory.loaded_document,
            dataset_name=lengths[group_index - 1],
            expected_values=[
                float(group["bar_mean"]) if index == group_index else math.nan
                for index in range(1, len(groups) + 1)
            ],
            dimensions=1,
        )
    )
    if inventory.categorical_kind == "grouped_bar_error":
        # This builder deliberately hides its native bars and paints fills and
        # error/outline shapes, whose exact scientific geometry is audited later.
        return evidence, f"/page1/graph1/categorical_bar_fill_{group_index}"
    candidates = inventory.bar_records
    if len(candidates) != 1:
        raise ValueError("Categorical mean/error data require one visible native bar.")
    record = candidates[0]
    bindings = record["bindings"]
    style = inventory.categorical.get("visual_style", {})
    if (
        record["name"] != "categorical_bar"
        or bindings["mode"] != "stacked"
        or bindings["direction"] != "vertical"
        or bindings["posn"] != "category_bar_positions"
        or list(bindings["lengths"]) != lengths
        or any(str(value) for value in bindings["keys"])
        or bindings["errorstyle"] != "none"
        or set(record["dataset_bindings"]) != {"posn", "lengths"}
        or not _numeric_setting_equal(
            bindings["barfill"],
            style.get("native_barfill", style.get("bar_width_fraction")),
        )
        or not _numeric_setting_equal(bindings["groupfill"], 0.75)
    ):
        raise ValueError("Categorical mean/error bar bindings or geometry changed.")
    inventory.allowed_bar_paths.add(str(record["path"]))
    return evidence, str(record["path"])
