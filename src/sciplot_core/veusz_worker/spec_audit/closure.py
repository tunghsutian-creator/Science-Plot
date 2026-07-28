"""Reject unapproved data bindings, plotters, and overlay widgets."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.widget_bindings import (
    _dataset_setting_bindings,
    _node_is_visible,
    _visible_data_bindings,
)


def audit_closed_document_inventory(
    inventory: SpecAuditInventory,
    *,
    allowed_scalar_dataset: str | None,
    allowed_polygon_paths: set[str],
) -> None:
    loaded_document = inventory.loaded_document
    units = inventory.units
    categorical = inventory.categorical
    allowed_xy_records = inventory.allowed_xy_records
    xy_records = inventory.xy_records
    boxplot_records = inventory.boxplot_records
    allowed_boxplot_records = inventory.allowed_boxplot_records
    allowed_bar_paths = inventory.allowed_bar_paths
    if not units:
        raise ValueError(
            "Veusz specification contains no auditable rendered data units."
        )

    if isinstance(categorical, dict):
        allowed_xy_records.add(
            ("category_axis_label_provider", "category_axis_x", "category_axis_y")
        )

    for record in xy_records:
        bindings = record["bindings"]
        identity = (str(record["name"]), str(bindings["xData"]), str(bindings["yData"]))
        if identity not in allowed_xy_records:
            raise ValueError(
                f"Exact-current Veusz document contains an unapproved visible xy data binding at {record['path']}: {identity!r}."
            )
        allowed_dataset_paths = {"xData", "yData"}
        if record["name"] == "category_axis_label_provider":
            allowed_dataset_paths.add("labels")
            expected_provider_labels = "category_axis_labels"
            if bindings["labels"] != expected_provider_labels:
                raise ValueError(
                    "Categorical axis provider does not consume its exact label dataset."
                )
        if set(record["dataset_bindings"]) - allowed_dataset_paths:
            raise ValueError(
                f"Exact-current Veusz xy widget contains unapproved data settings at {record['path']}."
            )

    actual_boxplot_records: set[tuple[str, tuple[str, ...], tuple[float, ...]]] = set()

    for record in boxplot_records:
        if set(record["dataset_bindings"]) - {"values", "posn"}:
            raise ValueError(
                f"Exact-current Veusz boxplot contains unapproved data settings at {record['path']}."
            )
        values = tuple((str(value) for value in record["bindings"]["values"]))
        positions = tuple((float(value) for value in record["bindings"]["posn"]))
        identity = (str(record["name"]), values, positions)
        if record["mark_channels"]:
            actual_boxplot_records.add(identity)
            if identity not in allowed_boxplot_records:
                raise ValueError(
                    f"Exact-current Veusz document contains an unapproved visible boxplot data binding at {record['path']}."
                )

    if actual_boxplot_records != allowed_boxplot_records:
        raise ValueError(
            "Exact-current Veusz document does not contain the exact visible categorical boxplot inventory."
        )

    for widget_type in ("image", "contour"):
        for record in _visible_data_bindings(
            loaded_document, widget_type=widget_type, setting_names=("data",)
        ):
            data_binding = str(record["bindings"]["data"])
            if allowed_scalar_dataset is None or data_binding != allowed_scalar_dataset:
                raise ValueError(
                    f"Exact-current Veusz document contains an unapproved visible {widget_type} data binding at {record['path']}: {data_binding!r}."
                )
            if set(record["dataset_bindings"]) - {"data"}:
                raise ValueError(
                    f"Exact-current Veusz {widget_type} contains unapproved data settings at {record['path']}."
                )

    unapproved_plotters: list[str] = []

    unapproved_data_widgets: list[str] = []

    unapproved_overlay_widgets: list[str] = []

    other_data_widget_types = {
        "bar",
        "covariance",
        "fit",
        "function",
        "function3d",
        "histo",
        "nonorthfunc",
        "nonorthpoint",
        "point3d",
        "surface3d",
        "vectorfield",
        "volume3d",
    }

    def inspect_widget(path: str, node: Any) -> None:
        widget_type = str(getattr(node, "typename", ""))
        if (
            widget_type == "bar"
            and str(getattr(node, "name", "")) == "category_axis_tick_label_provider"
        ):
            return
        if widget_type == "bar" and str(path) in allowed_bar_paths:
            return
        if not _node_is_visible(node):
            return
        if widget_type in {"xy", "boxplot", "image", "contour"}:
            return
        if widget_type in {"ellipse", "imagefile", "svgfile"}:
            unapproved_overlay_widgets.append(f"{path}:{widget_type}")
        if widget_type == "polygon" and str(path) not in allowed_polygon_paths:
            unapproved_overlay_widgets.append(f"{path}:{widget_type}")
        if bool(getattr(node, "isplotter", False)):
            unapproved_plotters.append(f"{path}:{widget_type}")
        if widget_type in other_data_widget_types and _dataset_setting_bindings(
            getattr(node, "settings", None)
        ):
            unapproved_data_widgets.append(f"{path}:{widget_type}")

    loaded_document.walkNodes(inspect_widget, nodetypes=("widget",))

    if unapproved_plotters or unapproved_data_widgets or unapproved_overlay_widgets:
        offenders = sorted(
            set(
                unapproved_plotters
                + unapproved_data_widgets
                + unapproved_overlay_widgets
            )
        )
        raise ValueError(
            f"Exact-current Veusz document contains an unapproved visible data-bearing or overlay widget: {offenders[0]}."
        )
