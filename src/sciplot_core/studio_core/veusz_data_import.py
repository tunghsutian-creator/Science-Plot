"""Import plot-series and categorical datasets into a Veusz document."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_core.series_request import _veusz_literal_text


def import_veusz_spec_data(
    interface: Any,
    *,
    series: list[dict[str, Any]],
    axes: dict[str, Any],
    categorical: dict[str, Any] | None,
) -> None:
    """Create all numeric and text datasets referenced by plot widgets."""

    for item in series:
        x_data = "\n".join(f"{float(value):.12g}" for value in item["x_values"])
        y_data = "\n".join(f"{float(value):.12g}" for value in item["y_values"])
        interface.ImportString(f"{item['x_name']}(numeric)", x_data)
        interface.ImportString(f"{item['y_name']}(numeric)", y_data)
    if categorical is None:
        return

    groups = [
        group for group in categorical.get("groups", []) if isinstance(group, dict)
    ]
    x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
    category_labels = (
        x_axis.get("category_labels")
        if isinstance(x_axis.get("category_labels"), list)
        else []
    )
    category_positions = (
        x_axis.get("category_positions")
        if isinstance(x_axis.get("category_positions"), list)
        else []
    )
    grouped_bar = categorical.get("presentation_kind") == "grouped_bar_error"
    interface.SetDataText(
        "category_axis_labels",
        [_veusz_literal_text(str(label)) for label in category_labels],
    )
    interface.ImportString(
        "category_axis_x(numeric)",
        "\n".join(
            f"{float(position):.12g}"
            for position in (
                category_positions
                if grouped_bar
                else [group["position"] for group in groups]
            )
        ),
    )
    interface.ImportString(
        "category_axis_y(numeric)",
        (
            "\n".join("0" for _position in category_positions)
            if grouped_bar
            else "\n".join(
                f"{float(group['descriptive_statistics']['median']):.12g}"
                for group in groups
            )
        ),
    )
    presentation_kind = categorical.get("presentation_kind")
    if presentation_kind in {"bar_error", "grouped_bar_error"}:
        _import_bar_error_data(interface, groups)
    elif presentation_kind == "stacked_components":
        _import_stacked_component_data(interface, groups)


def _import_bar_error_data(
    interface: Any,
    groups: list[dict[str, Any]],
) -> None:
    interface.ImportString(
        "category_bar_positions(numeric)",
        "\n".join(f"{float(group['position']):.12g}" for group in groups),
    )
    for bar_index, group in enumerate(groups, start=1):
        interface.ImportString(
            f"category_bar_mean_{bar_index}(numeric)",
            "\n".join(
                f"{float(group['bar_mean']):.12g}" if item_index == bar_index else "nan"
                for item_index in range(1, len(groups) + 1)
            ),
        )


def _import_stacked_component_data(
    interface: Any,
    groups: list[dict[str, Any]],
) -> None:
    interface.ImportString(
        "category_bar_positions(numeric)",
        "\n".join(f"{float(group['position']):.12g}" for group in groups),
    )
    for group_index, group in enumerate(groups, start=1):
        components = [
            component
            for component in group.get("components", [])
            if isinstance(component, dict)
        ]
        for component_index, component in enumerate(components, start=1):
            interface.ImportString(
                f"category_bar_component_{group_index}_{component_index}(numeric)",
                "\n".join(
                    f"{float(component['value']):.12g}"
                    if item_index == group_index
                    else "nan"
                    for item_index in range(1, len(groups) + 1)
                ),
            )
