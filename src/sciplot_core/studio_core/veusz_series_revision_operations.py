"""Build native Veusz operations for one validated series revision."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


ErrorFactory = Callable[[str, str], Exception]


def build_native_series_revision_operation(
    document: Any,
    *,
    contract: dict[str, Any],
    target_order: list[str],
    error_factory: ErrorFactory,
) -> Any:
    """Return one native Undo operation for the validated target order."""

    from veusz.document.operations import OperationMultiple

    return OperationMultiple(
        _native_revision_operations(
            document,
            contract=contract,
            target_order=target_order,
            error_factory=error_factory,
        ),
        descr="revise SciPlot series",
    )


def unique_widgets_by_name(
    document: Any,
    names: list[str],
    *,
    error_factory: ErrorFactory,
) -> dict[str, Any]:
    """Resolve every requested live widget exactly once."""

    wanted = set(names)
    found: dict[str, list[Any]] = {name: [] for name in names}

    def visit(widget: Any) -> None:
        name = str(getattr(widget, "name", ""))
        if name in wanted:
            found[name].append(widget)
        for child in getattr(widget, "children", []):
            visit(child)

    visit(document.basewidget)
    if any(len(matches) != 1 for matches in found.values()):
        raise error_factory(
            "series_revision_widget_mismatch",
            "Every source series must resolve to one unique live Veusz widget.",
        )
    return {name: matches[0] for name, matches in found.items()}


def series_widget_suffix(name: str, *, error_factory: ErrorFactory) -> str:
    """Return the generated numeric suffix used by categorical widgets."""

    prefix = "series_"
    if not name.startswith(prefix) or not name.removeprefix(prefix).isdigit():
        raise error_factory(
            "series_revision_widget_mismatch",
            "Categorical revision requires generated series_N widget identities.",
        )
    return name.removeprefix(prefix)


def first_setting_number(value: Any) -> float:
    """Read the first numeric value from a scalar or Veusz setting sequence."""

    if isinstance(value, list | tuple):
        return float(value[0])
    try:
        return float(value[0])
    except (TypeError, IndexError):
        return float(value)


def _native_revision_operations(
    document: Any,
    *,
    contract: dict[str, Any],
    target_order: list[str],
    error_factory: ErrorFactory,
) -> list[Any]:
    from veusz.document.operations import OperationSettingSet

    target_set = set(target_order)
    operations: list[Any] = []
    for label, item in zip(contract["source_order"], contract["series"], strict=True):
        operations.append(
            OperationSettingSet(
                contract["widgets"][item["name"]].settings.get("hide"),
                label not in target_set,
            )
        )
    desired_names = [
        _series_item(contract, label)["name"]
        for label in [
            *target_order,
            *(label for label in contract["source_order"] if label not in target_set),
        ]
    ]
    operations.extend(_widget_order_operations(contract["graph"], desired_names))
    if contract["template"] == "box_strip":
        operations.extend(
            _categorical_revision_operations(
                document,
                contract=contract,
                target_order=target_order,
                error_factory=error_factory,
            )
        )
    return operations


def _widget_order_operations(parent: Any, desired_names: list[str]) -> list[Any]:
    from veusz.document.operations import OperationWidgetMove

    names = [child.name for child in parent.children]
    slots = sorted(names.index(name) for name in desired_names)
    operations: list[Any] = []
    for slot, name in zip(slots, desired_names, strict=True):
        current = names.index(name)
        if current == slot:
            continue
        requested_index = slot + 1 if current < slot else slot
        child = next(child for child in parent.children if child.name == name)
        operations.append(OperationWidgetMove(child.path, parent.path, requested_index))
        names.insert(slot, names.pop(current))
    return operations


def _categorical_revision_operations(
    document: Any,
    *,
    contract: dict[str, Any],
    target_order: list[str],
    error_factory: ErrorFactory,
) -> list[Any]:
    from veusz.datasets.oned import Dataset
    from veusz.datasets.text import DatasetText
    from veusz.document.operations import OperationDatasetSet, OperationSettingSet

    operations: list[Any] = []
    widget_names: list[str] = []
    for item in contract["series"]:
        suffix = series_widget_suffix(
            item["name"],
            error_factory=error_factory,
        )
        widget_names.extend(
            [f"categorical_box_median_{suffix}", f"categorical_boxplot_{suffix}"]
        )
    components = unique_widgets_by_name(
        document,
        widget_names,
        error_factory=error_factory,
    )
    target_position = {label: index for index, label in enumerate(target_order, 1)}
    for label, item in zip(contract["source_order"], contract["series"], strict=True):
        suffix = series_widget_suffix(
            item["name"],
            error_factory=error_factory,
        )
        median = components[f"categorical_box_median_{suffix}"]
        box = components[f"categorical_boxplot_{suffix}"]
        included = label in target_position
        operations.extend(
            [
                OperationSettingSet(median.settings.get("hide"), not included),
                OperationSettingSet(box.settings.get("hide"), not included),
            ]
        )
        if not included:
            continue
        old_position = first_setting_number(box.settings.get("posn").get())
        new_position = float(target_position[label])
        delta = new_position - old_position
        x_name = str(item.get("x_name") or "")
        x_values = [float(value) for value in document.data[x_name].data]
        operations.append(
            OperationDatasetSet(x_name, Dataset([value + delta for value in x_values]))
        )
        operations.append(OperationSettingSet(box.settings.get("posn"), [new_position]))
        for setting_name in ("xPos", "xPos2"):
            setting = median.settings.get(setting_name)
            values = [float(value) + delta for value in setting.get()]
            operations.append(OperationSettingSet(setting, values))

    groups = contract["categorical_groups"]
    medians = [
        float(groups[label]["descriptive_statistics"]["median"])
        for label in target_order
    ]
    positions = [float(index) for index in range(1, len(target_order) + 1)]
    operations.extend(
        [
            OperationDatasetSet("category_axis_labels", DatasetText(target_order)),
            OperationDatasetSet("category_axis_x", Dataset(positions)),
            OperationDatasetSet("category_axis_y", Dataset(medians)),
        ]
    )
    axis = unique_widgets_by_name(
        document,
        ["x"],
        error_factory=error_factory,
    )["x"]
    operations.extend(
        [
            OperationSettingSet(axis.settings.get("min"), 0.5),
            OperationSettingSet(axis.settings.get("max"), len(target_order) + 0.5),
            OperationSettingSet(
                axis.settings.get("MajorTicks").get("manualTicks"), positions
            ),
        ]
    )
    return operations


def _series_item(contract: dict[str, Any], label: str) -> dict[str, Any]:
    return next(
        item
        for item in contract["series"]
        if str(item.get("label") or "").strip() == label
    )


__all__ = [
    "build_native_series_revision_operation",
    "first_setting_number",
    "series_widget_suffix",
    "unique_widgets_by_name",
]
