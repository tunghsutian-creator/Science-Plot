from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from sciplot_core._paths import VEUSZ_ROOT
from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.composition import (
    COMPOSITE_CANVAS_WIDTH_MM,
    CompositionProject,
    CompositionSourceModule,
    CompositionVariant,
)
from sciplot_core.composition_workspace import (
    CompositionWorkspace,
    archive_variant_document,
    mark_composition_compiled,
    verify_composition_sources,
    write_composition_compile_manifest,
)
from sciplot_core.policy import COMPOSITION_NATIVE_STYLE_POLICY

COMPOSITION_COMPILER_KIND = "sciplot_native_veusz_composition_compile"
COMPOSITION_COMPILER_VERSION = 3
_MIN_PLOT_FRAME_MM = 18.0
_DISTANCE = re.compile(
    r"^\s*(?P<value>(?:\d+(?:\.\d*)?|\.\d+))\s*"
    r"(?P<unit>mm|cm|pt|in|inch|\")\s*$",
    re.IGNORECASE,
)


class CompositionCompileBlocked(ValueError):
    state = "needs_human_confirmation"

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def _load_runtime() -> dict[str, Any]:
    runtime_root = str(VEUSZ_ROOT)
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)

    from PyQt6 import QtWidgets

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    application = application or QtWidgets.QApplication([])

    from sciplot_core.studio import (
        _ensure_veusz_loader_compat,
        ensure_veusz_qsettings_compat,
    )

    ensure_veusz_qsettings_compat()
    _ensure_veusz_loader_compat()

    from veusz import dataimport, document, widgets
    from veusz.document import mime
    from veusz.document.commandinterface import CommandInterface
    from veusz.document.operations import (
        OperationSettingSet,
        OperationWidgetAdd,
    )
    from veusz.document.painthelper import PaintHelper

    _ = dataimport, widgets
    return {
        "application": application,
        "owns_application": owns_application,
        "Document": document.Document,
        "CommandInterface": CommandInterface,
        "mime": mime,
        "OperationSettingSet": OperationSettingSet,
        "OperationWidgetAdd": OperationWidgetAdd,
        "PaintHelper": PaintHelper,
    }


def _set_setting(
    document: Any,
    operation_type: type[Any],
    setting_path: str,
    value: Any,
) -> None:
    setting = document.resolveSettingPath(None, setting_path)
    normalized = setting.normalize(value)
    document.applyOperation(operation_type(setting_path, normalized))


def _set_if_exists(
    document: Any,
    operation_type: type[Any],
    setting_path: str,
    value: Any,
) -> bool:
    try:
        _set_setting(document, operation_type, setting_path, value)
    except ValueError:
        return False
    return True


def _walk_widgets(document: Any) -> list[Any]:
    widgets: list[Any] = []
    document.walkNodes(
        lambda _path, node: widgets.append(node),
        nodetypes=("widget",),
    )
    return widgets


def _walk_widget_tree(root: Any) -> list[Any]:
    widgets = [root]
    for child in root.children:
        widgets.extend(_walk_widget_tree(child))
    return widgets


def _setting_value(document: Any, setting_path: str) -> Any:
    try:
        return json_safe(document.resolveSettingPath(None, setting_path).get())
    except ValueError:
        return None


def _select_source_graph(document: Any, module: CompositionSourceModule) -> Any:
    if module.source_graph_path is not None:
        try:
            graph = document.resolveWidgetPath(None, module.source_graph_path)
        except ValueError as exc:
            raise CompositionCompileBlocked(
                "source_graph_missing",
                f"Module {module.module_id} no longer contains "
                f"{module.source_graph_path!r}.",
            ) from exc
        if str(getattr(graph, "typename", "")) != "graph":
            raise CompositionCompileBlocked(
                "source_graph_type_mismatch",
                f"Module {module.module_id} source path is not a Veusz graph.",
            )
        return graph

    graphs = [
        widget
        for widget in _walk_widgets(document)
        if str(getattr(widget, "typename", "")) == "graph"
    ]
    if len(graphs) != 1:
        raise CompositionCompileBlocked(
            "source_graph_ambiguous",
            f"Module {module.module_id} contains {len(graphs)} graphs; "
            "choose one graph explicitly before composition.",
        )
    return graphs[0]


def _page_index(document: Any, graph: Any) -> int:
    ancestor = graph
    while ancestor is not None and str(getattr(ancestor, "typename", "")) != "page":
        ancestor = getattr(ancestor, "parent", None)
    if ancestor is None:
        raise CompositionCompileBlocked(
            "source_graph_without_page",
            f"Source graph {graph.path!r} is not inside a Veusz page.",
        )
    for page_index in document.getVisiblePages():
        if document.getPage(page_index) is ancestor:
            return int(page_index)
    raise CompositionCompileBlocked(
        "source_page_hidden",
        f"Source graph {graph.path!r} is not on a visible page.",
    )


def _dataset_name(module_id: str, source_name: str) -> str:
    candidate = f"{module_id}__{source_name}"
    if len(candidate) <= 180:
        return candidate
    digest = hashlib.sha256(source_name.encode("utf-8")).hexdigest()[:20]
    return f"{module_id}__dataset_{digest}"


def _copy_source_datasets(
    source_document: Any,
    destination_document: Any,
    module: CompositionSourceModule,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    mapping: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for source_name, dataset in sorted(source_document.data.items()):
        target_name = _dataset_name(module.module_id, str(source_name))
        if target_name in destination_document.data:
            raise RuntimeError(f"Composition dataset collision: {target_name!r}")
        copied = dataset.returnCopy()
        if hasattr(copied, "linked"):
            copied.linked = None
        destination_document.setData(target_name, copied)
        mapping[str(source_name)] = target_name
        records.append(
            {
                "source_name": str(source_name),
                "target_name": target_name,
                "dimensions": int(getattr(copied, "dimensions", 0)),
                "datatype": str(getattr(copied, "datatype", "unknown")),
                "materialized": True,
            }
        )
    return mapping, records


def _settings_by_relative_path(document: Any, root: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    prefix = str(root.path)

    def collect(path: str, node: Any) -> None:
        if not path.startswith(prefix):
            raise RuntimeError("Veusz setting traversal escaped its graph root.")
        settings[path[len(prefix) :]] = node

    document.walkNodes(
        collect,
        root=root,
        nodetypes=("setting",),
    )
    return settings


def _materialized_expression_name(
    module_id: str,
    relative_path: str,
    destination_document: Any,
) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
    base = f"{module_id}__expression_{digest}"
    if base not in destination_document.data:
        return base
    index = 2
    while f"{base}_{index}" in destination_document.data:
        index += 1
    return f"{base}_{index}"


def _remap_graph_datasets(
    *,
    source_document: Any,
    source_graph: Any,
    destination_document: Any,
    cloned_graph: Any,
    module: CompositionSourceModule,
    dataset_mapping: dict[str, str],
    operation_type: type[Any],
) -> list[dict[str, Any]]:
    source_settings = _settings_by_relative_path(source_document, source_graph)
    records: list[dict[str, Any]] = []
    for relative_path, source_setting in source_settings.items():
        setting_type = str(getattr(source_setting, "typename", ""))
        if not setting_type.startswith("dataset"):
            continue
        destination_path = f"{cloned_graph.path}{relative_path}"
        destination_setting = destination_document.resolveSettingPath(
            None,
            destination_path,
        )
        source_value = source_setting.get()
        target_value: Any = source_value
        action = "unchanged"
        if setting_type == "dataset-multi":
            values = list(source_value)
            missing = [
                str(value)
                for value in values
                if str(value) and str(value) not in dataset_mapping
            ]
            if missing:
                raise CompositionCompileBlocked(
                    "dataset_reference_unresolved",
                    f"Module {module.module_id} setting {relative_path!r} "
                    f"references missing datasets {missing!r}.",
                )
            target_value = tuple(
                dataset_mapping[str(value)] if str(value) else str(value)
                for value in values
            )
            action = "renamed_dataset_list" if values else "unchanged"
        elif isinstance(source_value, str) and source_value in dataset_mapping:
            target_value = dataset_mapping[source_value]
            action = "renamed_dataset"
        elif setting_type == "dataset-extended" and isinstance(
            source_value,
            str,
        ):
            expression = source_value.strip()
            if expression:
                evaluated = source_setting.getData(source_document)
                if evaluated is None:
                    raise CompositionCompileBlocked(
                        "dataset_expression_unresolved",
                        f"Module {module.module_id} setting {relative_path!r} "
                        "contains an expression that cannot be materialized.",
                    )
                target_name = _materialized_expression_name(
                    module.module_id,
                    relative_path,
                    destination_document,
                )
                copied = evaluated.returnCopy()
                if hasattr(copied, "linked"):
                    copied.linked = None
                destination_document.setData(target_name, copied)
                target_value = target_name
                action = "materialized_expression"
        elif setting_type == "dataset" and isinstance(source_value, str):
            if source_value.strip():
                raise CompositionCompileBlocked(
                    "dataset_reference_unresolved",
                    f"Module {module.module_id} setting {relative_path!r} "
                    f"references unknown dataset {source_value!r}.",
                )
        if json_safe(destination_setting.get()) != json_safe(target_value):
            normalized = destination_setting.normalize(target_value)
            destination_document.applyOperation(
                operation_type(destination_path, normalized)
            )
        records.append(
            {
                "relative_setting_path": relative_path,
                "setting_type": setting_type,
                "action": action,
                "source_value": json_safe(source_value),
                "target_value": json_safe(target_value),
            }
        )
    return records


def _distance_to_mm(value: object, *, label: str) -> float:
    match = _DISTANCE.fullmatch(str(value))
    if match is None:
        raise CompositionCompileBlocked(
            "non_physical_graph_margin",
            f"{label} must use a physical unit before composition; got {value!r}.",
        )
    number = float(match.group("value"))
    unit = match.group("unit").casefold()
    factors = {
        "mm": 1.0,
        "cm": 10.0,
        "pt": 25.4 / 72.0,
        "in": 25.4,
        "inch": 25.4,
        '"': 25.4,
    }
    return number * factors[unit]


def _graph_margins_mm(graph: Any, *, module_id: str) -> dict[str, float]:
    return {
        side: _distance_to_mm(
            graph.settings.get(f"{side}Margin").get(),
            label=f"Module {module_id} {side} margin",
        )
        for side in ("left", "right", "top", "bottom")
    }


def _common_margins(
    records: list[dict[str, Any]],
    variant: CompositionVariant,
) -> dict[str, float]:
    common = {
        side: max(float(record["margins_mm"][side]) for record in records)
        for side in ("left", "right", "top", "bottom")
    }
    minimum_width = min(slot.width_mm for slot in variant.layout.slots)
    if minimum_width - common["left"] - common["right"] < _MIN_PLOT_FRAME_MM:
        raise CompositionCompileBlocked(
            "insufficient_horizontal_plot_frame",
            "The shared graph margins leave less than "
            f"{_MIN_PLOT_FRAME_MM:g} mm for the smallest panel.",
        )
    if (
        variant.layout.canvas_height_mm - common["top"] - common["bottom"]
        < _MIN_PLOT_FRAME_MM
    ):
        raise CompositionCompileBlocked(
            "insufficient_vertical_plot_frame",
            "The shared graph margins leave less than "
            f"{_MIN_PLOT_FRAME_MM:g} mm vertically.",
        )
    return {side: round(value, 6) for side, value in common.items()}


def _normalize_graph_style(
    *,
    document: Any,
    graph: Any,
    operation_set: type[Any],
) -> dict[str, Any]:
    policy = COMPOSITION_NATIVE_STYLE_POLICY
    applied: list[dict[str, Any]] = []
    for widget in _walk_widget_tree(graph):
        widget_type = str(getattr(widget, "typename", ""))
        settings: dict[str, Any] = {}
        if widget_type in {"axis", "axis-function", "colorbar"}:
            settings.update(
                {
                    "Line/width": policy["axis_line_width"],
                    "Label/font": policy["font_family"],
                    "Label/size": policy["font_size"],
                    "TickLabels/font": policy["font_family"],
                    "TickLabels/size": policy["font_size"],
                    "MajorTicks/width": policy["major_tick_width"],
                    "MinorTicks/width": policy["minor_tick_width"],
                }
            )
        if widget_type in {
            "xy",
            "function",
            "bar",
            "boxplot",
            "histo",
            "contour",
        }:
            settings.update(
                {
                    "PlotLine/width": policy["plot_line_width"],
                    "MarkerLine/width": policy["marker_line_width"],
                }
            )
        if widget_type in {"key", "label"}:
            settings.update(
                {
                    "Text/font": policy["font_family"],
                    "Text/size": policy["font_size"],
                }
            )
        for relative_path, value in settings.items():
            path = f"{widget.path}/{relative_path}"
            if _set_if_exists(document, operation_set, path, value):
                applied.append(
                    {
                        "widget_path": str(widget.path),
                        "widget_type": widget_type,
                        "setting_path": path,
                        "value": value,
                    }
                )
    return {
        "graph_path": str(graph.path),
        "policy": dict(policy),
        "applied_setting_count": len(applied),
        "applied_settings": applied,
    }


def _axis_signature(document: Any, graph: Any, direction: str) -> dict[str, Any] | None:
    axes = [
        widget
        for widget in _walk_widget_tree(graph)
        if str(getattr(widget, "typename", "")) == "axis"
        and str(_setting_value(document, f"{widget.path}/direction") or "horizontal")
        == direction
    ]
    if not axes:
        return None
    axis = axes[0]
    return {
        "label": _setting_value(document, f"{axis.path}/label"),
        "log": bool(_setting_value(document, f"{axis.path}/log")),
        "min": _setting_value(document, f"{axis.path}/min"),
        "max": _setting_value(document, f"{axis.path}/max"),
        "direction": direction,
    }


def _series_keys(document: Any, graph: Any) -> list[str]:
    values: list[str] = []
    for widget in _walk_widget_tree(graph):
        value = _setting_value(document, f"{widget.path}/key")
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def _visible_key_count(document: Any, graph: Any) -> int:
    count = 0
    for widget in _walk_widget_tree(graph):
        if str(getattr(widget, "typename", "")) != "key":
            continue
        hidden = bool(_setting_value(document, f"{widget.path}/hide"))
        if not hidden:
            count += 1
    return count


def _composition_eligibility(records: list[dict[str, Any]]) -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    for record in records:
        document = record["document"]
        graph = record["graph"]
        modules.append(
            {
                "module_id": record["module"].module_id,
                "horizontal_axis": _axis_signature(
                    document,
                    graph,
                    "horizontal",
                ),
                "vertical_axis": _axis_signature(
                    document,
                    graph,
                    "vertical",
                ),
                "series_keys": _series_keys(document, graph),
                "visible_key_count": _visible_key_count(document, graph),
            }
        )

    def equivalent(key: str) -> bool:
        values = [module[key] for module in modules]
        return (
            bool(values)
            and values[0] is not None
            and all(value == values[0] for value in values[1:])
        )

    horizontal = equivalent("horizontal_axis")
    vertical = equivalent("vertical_axis")
    legend_values = [module["series_keys"] for module in modules]
    visible_key_counts = [module["visible_key_count"] for module in modules]
    has_visible_legends = bool(visible_key_counts) and all(
        count > 0 for count in visible_key_counts
    )
    shared_legend = (
        bool(legend_values and legend_values[0])
        and all(value == legend_values[0] for value in legend_values[1:])
        and has_visible_legends
    )
    return {
        "module_count": len(modules),
        "modules": modules,
        "shared_axis": {
            "horizontal_eligible": horizontal,
            "vertical_eligible": vertical,
            "both_eligible": horizontal and vertical,
        },
        "shared_legend": {
            "eligible": shared_legend,
            "reason": (
                "equivalent_nonempty_series_keys"
                if shared_legend
                else (
                    "no_visible_legends"
                    if not has_visible_legends
                    else "series_keys_are_missing_or_not_equivalent"
                )
            ),
        },
    }


def _apply_legend_policy(
    *,
    document: Any,
    graphs: list[Any],
    variant: CompositionVariant,
    eligibility: dict[str, Any],
    operation_set: type[Any],
) -> dict[str, Any]:
    keys_by_graph = [
        [
            widget
            for widget in _walk_widget_tree(graph)
            if str(getattr(widget, "typename", "")) == "key"
            and not bool(_setting_value(document, f"{widget.path}/hide"))
        ]
        for graph in graphs
    ]
    visible_before = [len(keys) for keys in keys_by_graph]
    if not any(visible_before):
        return {
            "status": "not_applicable",
            "requested": variant.legend_policy,
            "applied": "no_visible_legends",
            "visible_keys_before": visible_before,
            "visible_keys_after": visible_before,
            "hidden_key_paths": [],
        }
    should_share = (
        variant.legend_policy in {"auto", "shared_when_equivalent"}
        and eligibility["shared_legend"]["eligible"] is True
    )
    if not should_share:
        return {
            "status": "passed",
            "requested": variant.legend_policy,
            "applied": "per_panel",
            "visible_keys_before": visible_before,
            "visible_keys_after": visible_before,
            "hidden_key_paths": [],
        }
    hidden: list[str] = []
    for keys in keys_by_graph[1:]:
        for key in keys:
            path = f"{key.path}/hide"
            if _set_if_exists(document, operation_set, path, True):
                hidden.append(str(key.path))
    visible_after = [_visible_key_count(document, graph) for graph in graphs]
    passed = bool(visible_after and visible_after[0] > 0) and all(
        count == 0 for count in visible_after[1:]
    )
    return {
        "status": "passed" if passed else "failed",
        "requested": variant.legend_policy,
        "applied": "single_representative_legend",
        "visible_keys_before": visible_before,
        "visible_keys_after": visible_after,
        "hidden_key_paths": hidden,
    }


def _graph_style_snapshot(document: Any, graph: Any) -> dict[str, Any]:
    axes: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    for widget in _walk_widget_tree(graph):
        widget_type = str(getattr(widget, "typename", ""))
        if widget_type == "axis":
            axes.append(
                {
                    "path": str(widget.path),
                    "line_width": _setting_value(
                        document,
                        f"{widget.path}/Line/width",
                    ),
                    "label_font": _setting_value(
                        document,
                        f"{widget.path}/Label/font",
                    ),
                    "label_size": _setting_value(
                        document,
                        f"{widget.path}/Label/size",
                    ),
                    "tick_font": _setting_value(
                        document,
                        f"{widget.path}/TickLabels/font",
                    ),
                    "tick_size": _setting_value(
                        document,
                        f"{widget.path}/TickLabels/size",
                    ),
                    "major_tick_width": _setting_value(
                        document,
                        f"{widget.path}/MajorTicks/width",
                    ),
                    "minor_tick_width": _setting_value(
                        document,
                        f"{widget.path}/MinorTicks/width",
                    ),
                }
            )
        if widget_type in {"xy", "function", "bar", "boxplot", "histo"}:
            series.append(
                {
                    "path": str(widget.path),
                    "plot_line_width": _setting_value(
                        document,
                        f"{widget.path}/PlotLine/width",
                    ),
                    "marker_line_width": _setting_value(
                        document,
                        f"{widget.path}/MarkerLine/width",
                    ),
                }
            )
    return {
        "graph_path": str(graph.path),
        "axes": axes,
        "series": series,
    }


def _style_alignment_audit(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    policy = COMPOSITION_NATIVE_STYLE_POLICY
    axis_checks: list[bool] = []
    series_checks: list[bool] = []
    for snapshot in snapshots:
        for axis in snapshot["axes"]:
            axis_checks.append(
                axis["line_width"] == policy["axis_line_width"]
                and axis["label_font"] == policy["font_family"]
                and axis["label_size"] == policy["font_size"]
                and axis["tick_font"] == policy["font_family"]
                and axis["tick_size"] == policy["font_size"]
                and axis["major_tick_width"] == policy["major_tick_width"]
                and axis["minor_tick_width"] == policy["minor_tick_width"]
            )
        for series in snapshot["series"]:
            available = [
                value
                for value in (
                    series["plot_line_width"],
                    series["marker_line_width"],
                )
                if value is not None
            ]
            if available:
                series_checks.append(
                    (
                        series["plot_line_width"]
                        in {
                            None,
                            policy["plot_line_width"],
                        }
                    )
                    and (
                        series["marker_line_width"]
                        in {None, policy["marker_line_width"]}
                    )
                )
    return {
        "policy": dict(policy),
        "axis_count": len(axis_checks),
        "series_count": len(series_checks),
        "axes_aligned": bool(axis_checks) and all(axis_checks),
        "series_strokes_aligned": all(series_checks),
        "snapshots": snapshots,
    }


def _compile_fingerprint(
    project: CompositionProject,
    variant: CompositionVariant,
) -> str:
    payload = {
        "compiler_version": COMPOSITION_COMPILER_VERSION,
        "composition_id": project.composition_id,
        "variant": variant.to_dict(),
        "sources": [module.to_dict() for module in project.source_modules],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _add_panel_labels(
    *,
    document: Any,
    page: Any,
    variant: CompositionVariant,
    operation_add: type[Any],
    operation_set: type[Any],
) -> list[dict[str, Any]]:
    if len(variant.layout.slots) <= 1:
        return []
    labels: list[dict[str, Any]] = []
    for slot in variant.layout.slots:
        name = f"panel_label_{slot.panel_label}"
        widget = document.applyOperation(
            operation_add(
                page,
                "label",
                autoadd=False,
                name=name,
            )
        )
        x_fraction = (slot.x_mm + 1.0) / COMPOSITE_CANVAS_WIDTH_MM
        settings = {
            "xPos": [x_fraction],
            "yPos": [0.985],
            "positioning": "relative",
            "label": slot.panel_label,
            "alignHorz": "left",
            "alignVert": "top",
            "margin": "0pt",
            "clip": False,
            "Text/font": COMPOSITION_NATIVE_STYLE_POLICY["font_family"],
            "Text/size": COMPOSITION_NATIVE_STYLE_POLICY["panel_label_size"],
            "Text/bold": True,
            "Background/hide": True,
            "Border/hide": True,
        }
        applied: list[str] = []
        for relative_path, value in settings.items():
            path = f"{widget.path}/{relative_path}"
            if _set_if_exists(document, operation_set, path, value):
                applied.append(path)
        labels.append(
            {
                "slot_ref": slot.slot_id,
                "panel_label": slot.panel_label,
                "widget_path": str(widget.path),
                "x_fraction": round(x_fraction, 6),
                "settings": applied,
            }
        )
    return labels


def _audit_compiled_document(
    document_path: Path,
    *,
    variant: CompositionVariant,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    document = runtime["Document"]()
    document.load(str(document_path))
    visible_pages = list(document.getVisiblePages())
    if visible_pages != [0]:
        raise RuntimeError("Native composition must contain exactly one visible page.")
    size = document.pageSize(0, dpi=(72.0, 72.0), integer=False)
    size_mm = [float(value) / 72.0 * 25.4 for value in size]
    helper = runtime["PaintHelper"](document, size, dpi=(72.0, 72.0))
    document.paintTo(helper, 0)
    widgets = _walk_widgets(document)
    grids = [
        widget for widget in widgets if str(getattr(widget, "typename", "")) == "grid"
    ]
    graphs = [
        widget for widget in widgets if str(getattr(widget, "typename", "")) == "graph"
    ]
    if len(grids) != 1 or len(graphs) != len(variant.layout.slots):
        raise RuntimeError(
            "Native composition requires one grid and one graph per layout slot."
        )
    grid = grids[0]
    if any(graph.parent is not grid for graph in graphs):
        raise RuntimeError("Every composition module graph must be a grid child.")
    graph_records: list[dict[str, Any]] = []
    for slot, graph in zip(variant.layout.slots, grid.children, strict=True):
        if str(getattr(graph, "typename", "")) != "graph":
            raise RuntimeError("Composition grid contains a non-graph module root.")
        state = helper.states.get((graph, 0))
        if state is None:
            raise RuntimeError(f"Composition graph did not render: {graph.path}")
        plot_bounds = list(state.bounds)
        margins = list(graph.getMargins(helper))
        slot_bounds_px = [
            plot_bounds[0] - margins[0],
            plot_bounds[1] - margins[1],
            plot_bounds[2] + margins[2],
            plot_bounds[3] + margins[3],
        ]
        slot_bounds_mm = [
            round(float(value) / 72.0 * 25.4, 6) for value in slot_bounds_px
        ]
        expected = [
            slot.x_mm,
            slot.y_mm,
            slot.x_mm + slot.width_mm,
            slot.y_mm + slot.height_mm,
        ]
        error = max(
            abs(float(actual) - float(target))
            for actual, target in zip(slot_bounds_mm, expected, strict=True)
        )
        graph_records.append(
            {
                "slot_ref": slot.slot_id,
                "graph_path": str(graph.path),
                "parent_path": str(graph.parent.path),
                "root_widget_type": str(graph.typename),
                "slot_bounds_mm": slot_bounds_mm,
                "expected_slot_bounds_mm": expected,
                "maximum_geometry_error_mm": round(error, 6),
            }
        )
    maximum_error = max(record["maximum_geometry_error_mm"] for record in graph_records)
    if maximum_error > 0.02:
        raise RuntimeError(
            "Compiled Veusz graph slots exceed the 0.02 mm geometry tolerance."
        )
    panel_label_records = [
        {
            "path": str(widget.path),
            "label": _setting_value(document, f"{widget.path}/label"),
            "font": _setting_value(document, f"{widget.path}/Text/font"),
            "size": _setting_value(document, f"{widget.path}/Text/size"),
            "bold": bool(_setting_value(document, f"{widget.path}/Text/bold")),
        }
        for widget in widgets
        if str(getattr(widget, "typename", "")) == "label"
        and str(getattr(widget, "name", "")).startswith("panel_label_")
    ]
    panel_labels_aligned = len(panel_label_records) == (
        len(variant.layout.slots) if len(variant.layout.slots) > 1 else 0
    ) and all(
        record["font"] == COMPOSITION_NATIVE_STYLE_POLICY["font_family"]
        and record["size"] == COMPOSITION_NATIVE_STYLE_POLICY["panel_label_size"]
        and record["bold"] is True
        for record in panel_label_records
    )
    style_snapshots = [_graph_style_snapshot(document, graph) for graph in graphs]
    style_alignment = _style_alignment_audit(style_snapshots)
    legend_audit = {
        "visible_key_counts_by_graph": [
            _visible_key_count(document, graph) for graph in graphs
        ],
        "total_visible_key_count": sum(
            _visible_key_count(document, graph) for graph in graphs
        ),
    }
    return {
        "page_count": 1,
        "page_size_mm": [round(value, 6) for value in size_mm],
        "page_width_error_mm": round(abs(size_mm[0] - 183.0), 6),
        "page_height_error_mm": round(
            abs(size_mm[1] - variant.layout.canvas_height_mm),
            6,
        ),
        "grid_path": str(grid.path),
        "native_module_root_types": ["graph" for _graph in graphs],
        "graph_slots": graph_records,
        "maximum_geometry_error_mm": maximum_error,
        "panel_label_paths": [record["path"] for record in panel_label_records],
        "panel_labels": panel_label_records,
        "panel_labels_aligned": panel_labels_aligned,
        "style_alignment": style_alignment,
        "legend_audit": legend_audit,
        "raster_panel_composition_detected": False,
        "dataset_count": len(document.data),
    }


def compile_native_composition(
    workspace: CompositionWorkspace,
    *,
    variant_id: str | None = None,
    regenerate_edited: bool = False,
) -> dict[str, Any]:
    project = workspace.load()
    variant = project.variant(variant_id or project.active_variant_id)
    if not variant.ready_to_compile:
        raise CompositionCompileBlocked(
            "incomplete_layout",
            "Every composition slot must contain exactly one source module.",
        )
    source_verification = verify_composition_sources(workspace, project)
    document_path = workspace.variant_document_path(variant.variant_id)
    compile_fingerprint = _compile_fingerprint(project, variant)
    existing_manifest_path = workspace.variant_compile_manifest_path(variant.variant_id)
    existing_manifest: dict[str, Any] = {}
    if existing_manifest_path.is_file():
        payload = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        existing_manifest = payload if isinstance(payload, dict) else {}
    if document_path.is_file() and variant.compiled_document_sha256:
        current_hash = file_sha256(document_path)
        if (
            current_hash == variant.compiled_document_sha256
            and existing_manifest.get("compile_fingerprint") == compile_fingerprint
        ):
            return {
                "kind": COMPOSITION_COMPILER_KIND,
                "version": COMPOSITION_COMPILER_VERSION,
                "status": "passed",
                "state": "compiled",
                "idempotent": True,
                "document": str(document_path),
                "document_sha256": current_hash,
                "composition": str(workspace.composition_path),
                "variant_id": variant.variant_id,
                "compile_manifest": str(existing_manifest_path),
                "source_verification": source_verification,
                "native_audit": existing_manifest.get("native_audit"),
                "style_normalization": existing_manifest.get("style_normalization"),
                "eligibility": existing_manifest.get("eligibility"),
                "legend_resolution": existing_manifest.get("legend_resolution"),
            }
        if current_hash != variant.compiled_document_sha256 and not regenerate_edited:
            raise CompositionCompileBlocked(
                "edited_composite_is_authoritative",
                "The compiled VSZ changed after generation. Preserve it as visual "
                "authority or explicitly regenerate after archiving.",
            )

    archive = archive_variant_document(workspace, variant.variant_id)
    runtime = _load_runtime()
    operation_set = runtime["OperationSettingSet"]
    operation_add = runtime["OperationWidgetAdd"]
    source_records: list[dict[str, Any]] = []
    loaded_sources: list[dict[str, Any]] = []
    style_normalization: list[dict[str, Any]] = []
    try:
        active_module_ids = {
            module_id
            for slot in variant.layout.slots
            if (module_id := variant.module_for_slot(slot.slot_id)) is not None
        }
        for module in project.source_modules:
            if module.module_id not in active_module_ids:
                continue
            source_path = workspace.source_path(module)
            source_document = runtime["Document"]()
            source_document.load(str(source_path))
            source_graph = _select_source_graph(source_document, module)
            page_index = _page_index(source_document, source_graph)
            loaded_sources.append(
                {
                    "module": module,
                    "path": source_path,
                    "document": source_document,
                    "graph": source_graph,
                    "page_index": page_index,
                    "margins_mm": _graph_margins_mm(
                        source_graph,
                        module_id=module.module_id,
                    ),
                }
            )

        common_margins = _common_margins(loaded_sources, variant)
        eligibility = _composition_eligibility(loaded_sources)
        shared_legend_eligible = bool(eligibility["shared_legend"]["eligible"])
        eligibility["legend_policy"] = {
            "requested": variant.legend_policy,
            "recommended": (
                "shared_when_equivalent"
                if variant.legend_policy in {"auto", "shared_when_equivalent"}
                and shared_legend_eligible
                else "per_panel"
            ),
        }
        destination = runtime["Document"]()
        destination.setCompatLevel(0)
        _set_setting(destination, operation_set, "/width", "183mm")
        _set_setting(
            destination,
            operation_set,
            "/height",
            f"{variant.layout.canvas_height_mm:g}mm",
        )
        _set_if_exists(
            destination,
            operation_set,
            "/StyleSheet/Line/width",
            COMPOSITION_NATIVE_STYLE_POLICY["plot_line_width"],
        )
        _set_if_exists(
            destination,
            operation_set,
            "/StyleSheet/Font/font",
            COMPOSITION_NATIVE_STYLE_POLICY["font_family"],
        )
        _set_if_exists(
            destination,
            operation_set,
            "/StyleSheet/Font/size",
            COMPOSITION_NATIVE_STYLE_POLICY["font_size"],
        )
        page = destination.applyOperation(
            operation_add(
                destination.basewidget,
                "page",
                autoadd=False,
                name="composition_page",
            )
        )
        _set_if_exists(
            destination,
            operation_set,
            f"{page.path}/Background/color",
            "white",
        )
        _set_if_exists(
            destination,
            operation_set,
            f"{page.path}/Background/hide",
            False,
        )
        grid = destination.applyOperation(
            operation_add(
                page,
                "grid",
                autoadd=False,
                name="composition_grid",
            )
        )
        grid_settings = {
            "rows": 1,
            "columns": len(variant.layout.slots),
            "scaleRows": [1.0],
            "scaleCols": [slot.width_mm for slot in variant.layout.slots],
            "leftMargin": f"{variant.layout.outer_left_mm:g}mm",
            "rightMargin": f"{variant.layout.outer_right_mm:g}mm",
            "topMargin": "0mm",
            "bottomMargin": "0mm",
            "internalMargin": (
                f"{variant.layout.gaps_mm[0]:g}mm" if variant.layout.gaps_mm else "0mm"
            ),
        }
        for name, value in grid_settings.items():
            _set_setting(
                destination,
                operation_set,
                f"{grid.path}/{name}",
                value,
            )

        source_by_module = {
            str(record["module"].module_id): record for record in loaded_sources
        }
        resolved_modules: dict[str, CompositionSourceModule] = {}
        cloned_graphs: list[Any] = []
        for slot in variant.layout.slots:
            module_id = variant.module_for_slot(slot.slot_id)
            if module_id is None:
                raise RuntimeError("Composition slot became empty during compile.")
            record = source_by_module[module_id]
            module = record["module"]
            source_document = record["document"]
            source_graph = record["graph"]
            dataset_mapping, datasets = _copy_source_datasets(
                source_document,
                destination,
                module,
            )
            clone = destination.applyOperation(
                runtime["mime"].OperationWidgetClone(
                    source_graph,
                    grid,
                    module.module_id,
                )
            )
            cloned_graphs.append(clone)
            remaps = _remap_graph_datasets(
                source_document=source_document,
                source_graph=source_graph,
                destination_document=destination,
                cloned_graph=clone,
                module=module,
                dataset_mapping=dataset_mapping,
                operation_type=operation_set,
            )
            for side, margin_mm in common_margins.items():
                _set_setting(
                    destination,
                    operation_set,
                    f"{clone.path}/{side}Margin",
                    f"{margin_mm:g}mm",
                )
            style_normalization.append(
                _normalize_graph_style(
                    document=destination,
                    graph=clone,
                    operation_set=operation_set,
                )
            )
            _set_if_exists(
                destination,
                operation_set,
                f"{clone.path}/notes",
                "SciPlot composition module "
                f"{module.module_id}; source SHA-256 {module.source_sha256}",
            )
            resolved = replace(
                module,
                source_graph_path=str(source_graph.path),
                source_page_index=int(record["page_index"]),
            )
            resolved_modules[module.module_id] = resolved
            source_records.append(
                {
                    "module_id": module.module_id,
                    "slot_ref": slot.slot_id,
                    "source_ref": module.source_ref,
                    "source_sha256": module.source_sha256,
                    "source_graph_path": str(source_graph.path),
                    "source_page_index": int(record["page_index"]),
                    "cloned_graph_path": str(clone.path),
                    "dataset_count": len(datasets),
                    "datasets": datasets,
                    "dataset_setting_remaps": remaps,
                    "source_margins_mm": record["margins_mm"],
                }
            )

        legend_resolution = _apply_legend_policy(
            document=destination,
            graphs=cloned_graphs,
            variant=variant,
            eligibility=eligibility,
            operation_set=operation_set,
        )

        panel_labels = _add_panel_labels(
            document=destination,
            page=page,
            variant=variant,
            operation_add=operation_add,
            operation_set=operation_set,
        )
        document_path.parent.mkdir(parents=True, exist_ok=True)
        destination.save(str(document_path))
        document_hash = file_sha256(document_path)
        if any(
            file_sha256(workspace.source_path(module)) != module.source_sha256
            for module in project.source_modules
        ):
            raise RuntimeError("A composition source VSZ changed during compilation.")
        native_audit = _audit_compiled_document(
            document_path,
            variant=variant,
            runtime=runtime,
        )
        document_ref = document_path.relative_to(workspace.root).as_posix()
        updated = mark_composition_compiled(
            project,
            variant_id=variant.variant_id,
            document_ref=document_ref,
            document_sha256=document_hash,
            resolved_sources=tuple(
                resolved_modules.get(module.module_id, module)
                for module in project.source_modules
            ),
        )
        workspace.save(updated)
        updated_variant = updated.variant(variant.variant_id)
        manifest_path = write_composition_compile_manifest(
            workspace,
            updated_variant,
            {
                "status": "passed",
                "state": "compiled",
                "compile_fingerprint": _compile_fingerprint(
                    updated,
                    updated_variant,
                ),
                "document": str(document_path),
                "document_ref": document_ref,
                "document_sha256": document_hash,
                "source_verification": source_verification,
                "source_modules": source_records,
                "common_graph_margins_mm": common_margins,
                "style_normalization": style_normalization,
                "eligibility": eligibility,
                "legend_resolution": legend_resolution,
                "panel_labels": panel_labels,
                "archive": archive,
                "native_audit": native_audit,
                "authority": {
                    "source_vsz_files_unchanged": True,
                    "native_veusz_graph_cloning": True,
                    "raster_panel_composition_used": False,
                    "compiled_vsz_is_visual_authority_after_manual_save": True,
                },
            },
        )
        return {
            "kind": COMPOSITION_COMPILER_KIND,
            "version": COMPOSITION_COMPILER_VERSION,
            "status": "passed",
            "state": "compiled",
            "idempotent": False,
            "composition": str(workspace.composition_path),
            "variant_id": variant.variant_id,
            "document": str(document_path),
            "document_sha256": document_hash,
            "compile_manifest": str(manifest_path),
            "source_verification": source_verification,
            "source_modules": source_records,
            "common_graph_margins_mm": common_margins,
            "style_normalization": style_normalization,
            "eligibility": eligibility,
            "legend_resolution": legend_resolution,
            "panel_labels": panel_labels,
            "archive": archive,
            "native_audit": native_audit,
        }
    finally:
        if runtime.get("owns_application"):
            runtime["application"].quit()


def audit_native_composition_document(
    workspace: CompositionWorkspace,
    *,
    variant_id: str | None = None,
) -> dict[str, Any]:
    project = workspace.load()
    variant = project.variant(variant_id or project.active_variant_id)
    document_path = workspace.variant_document_path(variant.variant_id)
    if not document_path.is_file():
        raise FileNotFoundError(
            f"Compiled composition document not found: {document_path}"
        )
    runtime = _load_runtime()
    try:
        return _audit_compiled_document(
            document_path,
            variant=variant,
            runtime=runtime,
        )
    finally:
        if runtime.get("owns_application"):
            runtime["application"].quit()


def render_source_module_previews(
    workspace: CompositionWorkspace,
    *,
    dpi: int = 110,
) -> list[dict[str, Any]]:
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 220:
        raise ValueError("Composition preview DPI must be between 72 and 220.")
    project = workspace.load()
    verify_composition_sources(workspace, project)
    preview_root = workspace.root / "previews"
    preview_root.mkdir(parents=True, exist_ok=True)
    runtime = _load_runtime()
    records: list[dict[str, Any]] = []
    try:
        for module in project.source_modules:
            source_path = workspace.source_path(module)
            preview = preview_root / (
                f"{module.module_id}_{module.source_sha256[:12]}_{dpi}dpi.png"
            )
            document = runtime["Document"]()
            document.load(str(source_path))
            graph = _select_source_graph(document, module)
            page_index = _page_index(document, graph)
            if not preview.is_file():
                runtime["CommandInterface"](document).Export(
                    str(preview),
                    page=[page_index],
                    dpi=dpi,
                )
            if not preview.is_file() or preview.stat().st_size <= 0:
                raise RuntimeError(
                    f"Could not render composition preview for {module.module_id}."
                )
            records.append(
                {
                    "module_id": module.module_id,
                    "source_ref": module.source_ref,
                    "source_sha256": module.source_sha256,
                    "source_graph_path": str(graph.path),
                    "source_page_index": page_index,
                    "preview": str(preview),
                    "preview_ref": preview.relative_to(workspace.root).as_posix(),
                    "preview_sha256": file_sha256(preview),
                    "dpi": dpi,
                    "authority": "non_authoritative_raster_preview_only",
                }
            )
        return records
    finally:
        if runtime.get("owns_application"):
            runtime["application"].quit()


__all__ = [
    "COMPOSITION_COMPILER_KIND",
    "COMPOSITION_COMPILER_VERSION",
    "CompositionCompileBlocked",
    "audit_native_composition_document",
    "compile_native_composition",
    "render_source_module_previews",
]
