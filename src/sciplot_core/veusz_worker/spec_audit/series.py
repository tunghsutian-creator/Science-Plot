"""Validate axes, ordered series, categorical consumers, and dataset evidence."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_worker.axis_matchers import _axis_record_matches_spec
from sciplot_core.veusz_worker.numeric_evidence import _dataset_evidence
from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.widget_bindings import _visible_data_bindings


def audit_axes_and_series(
    inventory: SpecAuditInventory,
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    from sciplot_core.studio_core.series_request import veusz_literal_text

    loaded_document = inventory.loaded_document
    units = inventory.units
    seen_identities = inventory.seen_identities
    allowed_xy_records = inventory.allowed_xy_records
    expected_xy_order = inventory.expected_xy_order
    allowed_boxplot_records = inventory.allowed_boxplot_records
    expected_boxplot_order = inventory.expected_boxplot_order
    categorical = inventory.categorical
    categorical_groups = inventory.categorical_groups
    expected_box_name_by_y = inventory.expected_box_name_by_y
    xy_records = inventory.xy_records
    boxplot_records = inventory.boxplot_records
    component_bar_record = inventory.component_bar_record
    component_bar_datasets_by_y = inventory.component_bar_datasets_by_y
    axes = spec.get("axes")

    if (
        not isinstance(axes, dict)
        or not isinstance(axes.get("x"), dict)
        or (not isinstance(axes.get("y"), dict))
    ):
        raise ValueError("Veusz specification has no closed x/y axis inventory.")

    axis_records = _visible_data_bindings(
        loaded_document,
        widget_type="axis",
        setting_names=(
            "label",
            "direction",
            "mode",
            "log",
            "min",
            "max",
            "TickLabels/format",
            "MajorTicks/manualTicks",
            "MinorTicks/number",
            "MinorTicks/manualTicks",
            "MajorTicks/hide",
            "MinorTicks/hide",
            "TickLabels/hide",
            "Label/hide",
            "Label/size",
            "TickLabels/size",
            "Line/width",
            "MajorTicks/width",
            "MajorTicks/length",
            "MinorTicks/width",
            "MinorTicks/length",
            "Line/hide",
            "Line/transparency",
            "MajorTicks/transparency",
            "MinorTicks/transparency",
            "Line/color",
            "Label/color",
            "TickLabels/color",
        ),
    )

    if (
        len(axis_records) != 2
        or not _axis_record_matches_spec(axis_records[0], axes["x"], axis_name="x")
        or (not _axis_record_matches_spec(axis_records[1], axes["y"], axis_name="y"))
    ):
        raise ValueError(
            "Exact-current Veusz x/y axis labels, scales, bounds, ticks, visibility, or order differ from the rendered specification."
        )

    series = spec.get("series")

    if not isinstance(series, list):
        raise ValueError("Veusz specification has no series list.")

    series_by_y: dict[str, dict[str, Any]] = {}

    for raw_series in series:
        if not isinstance(raw_series, dict):
            raise ValueError("Veusz specification contains an invalid series.")
        y_name = str(raw_series.get("y_name") or "").strip()
        if not y_name or y_name in series_by_y:
            raise ValueError(
                "Veusz specification repeats or omits a series y identity."
            )
        series_by_y[y_name] = raw_series

    if isinstance(categorical, dict):
        categorical_labels: list[str] = []
        for y_name, group in categorical_groups.items():
            raw_series = series_by_y.get(y_name)
            if raw_series is None or str(group.get("label") or "") != str(
                raw_series.get("label") or ""
            ):
                raise ValueError(
                    "Categorical group labels do not match their rendered series identities."
                )
            categorical_labels.append(str(group.get("label") or ""))
        x_axis = (
            spec.get("axes", {}).get("x")
            if isinstance(spec.get("axes"), dict)
            and isinstance(spec["axes"].get("x"), dict)
            else {}
        )
        if list(x_axis.get("category_labels") or []) != categorical_labels:
            raise ValueError(
                "Categorical axis labels do not match the ordered series identity mapping."
            )

    for index, raw_series in enumerate(series, start=1):
        if not isinstance(raw_series, dict):
            raise ValueError(f"Veusz specification series {index} is invalid.")
        name = str(raw_series.get("name") or "").strip()
        x_name = str(raw_series.get("x_name") or "").strip()
        y_name = str(raw_series.get("y_name") or "").strip()
        identity = f"series:{name}"
        if not name or not x_name or (not y_name) or (identity in seen_identities):
            raise ValueError(
                f"Veusz specification series {index} has no unique data identity."
            )
        seen_identities.add(identity)
        allowed_xy_records.add((name, x_name, y_name))
        expected_xy_order.append(
            (
                name,
                x_name,
                y_name,
                veusz_literal_text(
                    raw_series.get("legend_key", raw_series.get("label"))
                ),
            )
        )
        datasets = [
            _dataset_evidence(
                loaded_document,
                dataset_name=x_name,
                expected_values=raw_series.get("x_values"),
                dimensions=1,
            ),
            _dataset_evidence(
                loaded_document,
                dataset_name=y_name,
                expected_values=raw_series.get("y_values"),
                dimensions=1,
            ),
        ]
        matching_xy = [
            record
            for record in xy_records
            if record["name"] == name
            and str(record["bindings"]["xData"]) == x_name
            and (str(record["bindings"]["yData"]) == y_name)
            and (
                str(record["bindings"]["key"])
                == veusz_literal_text(
                    raw_series.get("legend_key", raw_series.get("label"))
                )
            )
        ]
        if len(matching_xy) != 1:
            raise ValueError(
                f"Exact-current Veusz document does not contain exactly one bound xy widget for series {name!r}."
            )
        expected_channels = raw_series.get("expected_mark_channels")
        if isinstance(expected_channels, list) and matching_xy[0]["mark_channels"] != [
            str(value) for value in expected_channels
        ]:
            raise ValueError(
                f"Exact-current Veusz series {name!r} mark channels differ from the rendered performance contract."
            )
        consumers: list[str] = []
        presentation_kind = str(raw_series.get("presentation_kind") or "curve")
        group = categorical_groups.get(y_name)
        raw_points_required = raw_series.get("raw_points_visible") is not False
        if presentation_kind not in {
            "categorical_replicates",
            "categorical_components",
        }:
            if not matching_xy[0]["mark_channels"]:
                raise ValueError(
                    f"Exact-current Veusz series {name!r} has no visible line, marker, or fill channel."
                )
            consumers.append(str(matching_xy[0]["path"]))
        elif presentation_kind == "categorical_replicates":
            if not isinstance(group, dict):
                raise ValueError(f"Categorical series {name!r} has no group contract.")
            if raw_points_required:
                if "marker" not in matching_xy[0]["mark_channels"]:
                    raise ValueError(
                        f"Categorical series {name!r} requires visible raw-point markers."
                    )
                consumers.append(str(matching_xy[0]["path"]))
            if group.get("boxplot_eligible") is True:
                expected_box_name = expected_box_name_by_y[y_name]
                expected_position = (float(group["position"]),)
                expected_values = (y_name,)
                allowed_boxplot_records.add(
                    (expected_box_name, expected_values, expected_position)
                )
                expected_boxplot_order.append(
                    (expected_box_name, expected_values, expected_position)
                )
                matching_boxes = [
                    record
                    for record in boxplot_records
                    if record["name"] == expected_box_name
                    and tuple(record["bindings"]["values"]) == expected_values
                    and (
                        tuple((float(value) for value in record["bindings"]["posn"]))
                        == expected_position
                    )
                ]
                if len(matching_boxes) != 1 or not matching_boxes[0]["mark_channels"]:
                    raise ValueError(
                        f"Categorical series {name!r} requires its exact visible native boxplot."
                    )
                consumers.append(str(matching_boxes[0]["path"]))
        else:
            if not isinstance(group, dict):
                raise ValueError(
                    f"Categorical component series {name!r} has no group contract."
                )
            if component_bar_record is None:
                raise ValueError(
                    f"Categorical component series {name!r} has no native bar consumer."
                )
            component_datasets = component_bar_datasets_by_y.get(y_name)
            if not component_datasets:
                raise ValueError(
                    f"Categorical component series {name!r} has no stacked datasets."
                )
            datasets.extend(component_datasets)
            consumers.append(str(component_bar_record["path"]))
        if not consumers:
            raise ValueError(
                f"Exact-current Veusz document does not visibly consume series {name!r}."
            )
        units.append(
            {
                "identity": identity,
                "kind": "series",
                "datasets": datasets,
                "consumer_paths": consumers,
            }
        )

    if isinstance(categorical, dict):
        expected_xy_order.append(
            ("category_axis_label_provider", "category_axis_x", "category_axis_y", "")
        )

    actual_xy_order = [
        (
            str(record["name"]),
            str(record["bindings"]["xData"]),
            str(record["bindings"]["yData"]),
            str(record["bindings"]["key"]),
        )
        for record in xy_records
    ]

    if actual_xy_order != expected_xy_order:
        raise ValueError(
            "Exact-current Veusz xy object and legend-key order differs from the rendered series order."
        )

    actual_boxplot_order = [
        (
            str(record["name"]),
            tuple((str(value) for value in record["bindings"]["values"])),
            tuple((float(value) for value in record["bindings"]["posn"])),
        )
        for record in boxplot_records
    ]

    if actual_boxplot_order != expected_boxplot_order:
        raise ValueError(
            "Exact-current Veusz boxplot object order differs from the rendered categorical order."
        )
    return series
