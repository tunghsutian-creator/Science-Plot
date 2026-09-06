"""Validate axes, ordered series, categorical consumers, and dataset evidence."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_core.series_encoding_contract import (
    validate_series_encoding_contract,
)
from sciplot_core.studio_core.axis_data_visibility import (
    validate_axis_data_visibility,
)
from sciplot_core.studio_render.models import (
    CATEGORICAL_POINT_LINE_KIND,
    IMPACT_POINT_LINE_SUMMARY_KIND,
)
from sciplot_core.veusz_worker.axis_matchers import _axis_record_matches_spec
from sciplot_core.veusz_worker.numeric_evidence import _dataset_evidence
from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.spec_audit.bar_error import audit_bar_error_consumer
from sciplot_core.veusz_worker.spec_audit.series_encoding import (
    audit_series_encoding,
)
from sciplot_core.veusz_worker.widget_bindings import _visible_data_bindings
from sciplot_core.veusz_worker.spec_audit.scientific_geometry import (
    axis_matches_science,
)


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
    style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
    validate_series_encoding_contract(spec)
    validate_axis_data_visibility(spec)

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

    if len(axis_records) != 2 or any(
        not (
            _axis_record_matches_spec(record, axes[name], axis_name=name)
            if inventory.check_presentation
            else axis_matches_science(record, axes[name], name=name, spec=spec)
        )
        for record, name in zip(axis_records, ("x", "y"), strict=True)
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

    if (
        isinstance(categorical, dict)
        and categorical.get("presentation_kind") == CATEGORICAL_POINT_LINE_KIND
    ):
        x_axis = axes["x"]
        expected_labels = list(categorical.get("category_labels") or [])
        expected_positions = [
            float(value) for value in categorical.get("category_positions") or []
        ]
        if (
            list(x_axis.get("category_labels") or []) != expected_labels
            or [float(value) for value in x_axis.get("category_positions") or []]
            != expected_positions
            or any(
                list(item.get("component_labels") or []) != expected_labels
                or [float(value) for value in item.get("x_values") or []]
                != expected_positions
                for item in spec.get("series", [])
                if isinstance(item, dict)
            )
        ):
            raise ValueError(
                "Categorical point-line labels do not match the source-bound "
                "numeric positions."
            )
    elif inventory.categorical_kind == "point_line_raw_overlay":
        summaries = [
            item
            for item in series
            if item.get("presentation_kind") == IMPACT_POINT_LINE_SUMMARY_KIND
        ]
        labels = list(categorical.get("sample_labels") or [])
        if (
            list(axes["x"].get("category_labels") or []) != labels
            or [str(item.get("label") or "") for item in summaries]
            != list(categorical.get("condition_labels") or [])
            or any(
                list(item.get("component_labels") or []) != labels for item in summaries
            )
            or not summaries
        ):
            raise ValueError("Impact overlay sample/condition labels changed.")
    elif isinstance(categorical, dict):
        categorical_labels: list[str] = []
        for y_name, group in categorical_groups.items():
            raw_series = series_by_y.get(y_name)
            if raw_series is None or str(group.get("label") or "") != str(
                raw_series.get("label") or ""
            ):
                raise ValueError(
                    "Categorical group labels do not match their rendered series identities."
                )
            categorical_labels.append(
                str(
                    group.get("sample_label")
                    if inventory.categorical_kind == "grouped_bar_error"
                    else group.get("label") or ""
                )
            )
        if inventory.categorical_kind == "grouped_bar_error":
            categorical_labels = list(dict.fromkeys(categorical_labels))
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
        bindings = matching_xy[0]["bindings"]
        if bindings.get("xAxis") != "x" or bindings.get("yAxis") != "y":
            raise ValueError(f"Exact-current Veusz series {name!r} has different axis bindings.")
        audit_series_encoding(
            inventory,
            raw_series=raw_series,
            matching_xy=matching_xy[0],
            style=style,
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
        if (
            raw_points_required
            and presentation_kind in {
                "categorical_replicates", "categorical_grouped_replicates",
                "impact_point_line_raw_points",
            }
            and bindings.get("thinfactor") != 1
        ):
            raise ValueError(f"Exact-current Veusz series {name!r} must retain every raw-point marker.")
        if presentation_kind not in {
            "categorical_replicates",
            "categorical_grouped_replicates",
            "categorical_components",
        }:
            if not matching_xy[0]["mark_channels"]:
                raise ValueError(
                    f"Exact-current Veusz series {name!r} has no visible line, marker, or fill channel."
                )
            consumers.append(str(matching_xy[0]["path"]))
        elif presentation_kind in {
            "categorical_replicates",
            "categorical_grouped_replicates",
        }:
            if not isinstance(group, dict):
                raise ValueError(f"Categorical series {name!r} has no group contract.")
            if raw_points_required:
                if "marker" not in matching_xy[0]["mark_channels"]:
                    raise ValueError(
                        f"Categorical series {name!r} requires visible raw-point markers."
                    )
                consumers.append(str(matching_xy[0]["path"]))
            if inventory.categorical_kind in {"bar_error", "grouped_bar_error"}:
                bar_datasets, bar_path = audit_bar_error_consumer(
                    inventory, y_name=y_name
                )
                datasets.extend(bar_datasets)
                consumers.append(bar_path)
            elif group.get("boxplot_eligible") is True:
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

    return series
