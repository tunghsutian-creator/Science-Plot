from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.policy import (
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
)
from sciplot_core.scalar_visual import scalar_visual_contract


def export_request(request_path: Path, *, formats: list[str]) -> dict[str, Any]:
    """Compile one request to VSZ, then export through the production renderer."""

    from sciplot_core.studio import export_studio_document, prepare_studio_document

    payload = prepare_studio_document(request_path.expanduser().resolve())
    document_path = Path(str(payload["document"]))
    export_payload = export_studio_document(document_path, formats=formats)
    payload["exports"] = export_payload["exports"]
    return payload


def export_document(
    document_path: Path,
    *,
    formats: list[str],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Export the exact current VSZ without regenerating it."""

    from sciplot_core.studio import export_studio_document

    return export_studio_document(
        document_path.expanduser().resolve(),
        formats=formats,
        output_dir=output_dir.expanduser().resolve()
        if output_dir is not None
        else None,
    )


def audit_documents(document_paths: list[Path]) -> dict[str, Any]:
    """Inspect exact current VSZ state through Veusz without rewriting it."""

    from PyQt6 import QtWidgets

    from sciplot_core.studio import _ensure_veusz_loader_compat, _ensure_veusz_on_path

    _ensure_veusz_on_path()
    from veusz import dataimport, document, widgets

    _ = dataimport, document, widgets
    _ensure_veusz_loader_compat()
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        from sciplot_core.veusz_audit import audit_veusz_documents

        return audit_veusz_documents(
            [path.expanduser().resolve() for path in document_paths]
        )
    finally:
        if existing_app is None:
            app.quit()


def inspect_document_state(document_path: Path) -> dict[str, Any]:
    """Reopen one VSZ and materialize its widget setting state."""

    from PyQt6 import QtWidgets

    from sciplot_core.studio import (
        _ensure_veusz_loader_compat,
        _ensure_veusz_on_path,
    )

    resolved_document = document_path.expanduser().resolve()
    if not resolved_document.is_file():
        raise FileNotFoundError(f"Veusz document not found: {resolved_document}")
    _ensure_veusz_on_path()
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        _ensure_veusz_loader_compat()
        from veusz import dataimport, document, widgets

        _ = dataimport, widgets
        loaded_document = document.Document()
        loaded_document.load(str(resolved_document))
        materialized_widgets: dict[str, dict[str, Any]] = {}

        def collect(path: str, node: Any) -> None:
            materialized_widgets[str(path)] = {
                "name": str(getattr(node, "name", "")),
                "type": str(getattr(node, "typename", "")),
                "settings": _settings_snapshot(
                    getattr(node, "settings", None)
                ),
            }

        loaded_document.walkNodes(collect, nodetypes=("widget",))
        return {
            "kind": "sciplot_veusz_document_state",
            "version": 1,
            "status": "passed",
            "document": {
                "path": str(resolved_document),
                "sha256": file_sha256(resolved_document),
            },
            "widgets": materialized_widgets,
            "widget_count": len(materialized_widgets),
        }
    finally:
        if existing_app is None:
            app.quit()


def _exact_numeric_token(value: object) -> str:
    number = float(value)
    if math.isnan(number):
        return "nan"
    if math.isinf(number):
        return "inf" if number > 0.0 else "-inf"
    return number.hex()


def _persisted_expected_numeric_token(value: object) -> str:
    number = float(value)
    if math.isnan(number):
        return "nan"
    if math.isinf(number):
        return "inf" if number > 0.0 else "-inf"
    # Veusz Save writes ordinary numeric datasets with six digits after the
    # decimal point in scientific notation. Quantize the generation spec once
    # to that persisted token, then compare the reopened value exactly. Do not
    # round the reopened value: a hand-edited token carrying extra precision
    # must remain distinguishable.
    return float(f"{number:.6e}").hex()


def _numeric_payload(
    value: object,
    *,
    expected_persisted: bool = False,
) -> list[Any]:
    materialized = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(materialized, list | tuple):
        raise ValueError("Veusz numeric evidence must be a list or array.")
    token = (
        _persisted_expected_numeric_token
        if expected_persisted
        else _exact_numeric_token
    )
    return [
        _numeric_payload(item, expected_persisted=expected_persisted)
        if isinstance(item, list | tuple) or hasattr(item, "tolist")
        else token(item)
        for item in materialized
    ]


def _numeric_digest(
    value: object,
    *,
    expected_persisted: bool = False,
) -> str:
    payload = json.dumps(
        _numeric_payload(value, expected_persisted=expected_persisted),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _dataset_evidence(
    loaded_document: Any,
    *,
    dataset_name: str,
    expected_values: object,
    dimensions: int,
) -> dict[str, Any]:
    dataset = loaded_document.data.get(dataset_name)
    if dataset is None:
        raise ValueError(
            f"Exact-current Veusz document has no dataset {dataset_name!r}."
        )
    if int(getattr(dataset, "dimensions", -1)) != dimensions:
        raise ValueError(
            f"Veusz dataset {dataset_name!r} has the wrong dimensionality."
        )
    actual_values = getattr(dataset, "data", None)
    expected_hash = _numeric_digest(
        expected_values,
        expected_persisted=True,
    )
    actual_hash = _numeric_digest(actual_values)
    if actual_hash != expected_hash:
        raise ValueError(
            f"Veusz dataset {dataset_name!r} differs from the rendered specification."
        )
    materialized = (
        actual_values.tolist()
        if hasattr(actual_values, "tolist")
        else actual_values
    )
    if dimensions == 1:
        shape = [len(materialized)]
    else:
        rows = len(materialized)
        columns = len(materialized[0]) if rows else 0
        if any(not isinstance(row, list | tuple) or len(row) != columns for row in materialized):
            raise ValueError(
                f"Veusz dataset {dataset_name!r} is not a rectangular 2D array."
            )
        shape = [rows, columns]
    return {
        "name": dataset_name,
        "dimensions": dimensions,
        "shape": shape,
        "value_sha256": actual_hash,
    }


def _text_dataset_values(
    loaded_document: Any,
    *,
    dataset_name: str,
) -> list[str]:
    dataset = loaded_document.data.get(dataset_name)
    if dataset is None:
        raise ValueError(
            f"Exact-current Veusz document has no text dataset "
            f"{dataset_name!r}."
        )
    values = getattr(dataset, "data", None)
    materialized = values.tolist() if hasattr(values, "tolist") else values
    if not isinstance(materialized, list | tuple):
        raise ValueError(
            f"Veusz text dataset {dataset_name!r} is not a text sequence."
        )
    return [str(value) for value in materialized]


def _node_is_visible(node: Any) -> bool:
    ancestor = node
    while ancestor is not None:
        settings = getattr(ancestor, "settings", None)
        setting_map = getattr(settings, "setdict", {})
        hide = setting_map.get("hide")
        if hide is not None and bool(hide.val):
            return False
        ancestor = getattr(ancestor, "parent", None)
    return True


def _setting_value(settings: Any, path: str, default: Any = None) -> Any:
    current = settings
    parts = path.split("/")
    for index, part in enumerate(parts):
        setting_map = getattr(current, "setdict", {})
        item = setting_map.get(part)
        if item is None:
            return default
        if index == len(parts) - 1:
            return getattr(item, "val", default)
        current = item
    return default


def _distance_is_positive(value: object) -> bool:
    if isinstance(value, int | float):
        return math.isfinite(float(value)) and float(value) > 0.0
    match = re.search(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
        str(value or ""),
    )
    if match is None:
        # A live Veusz reference resolves to a positive stylesheet default.
        return bool(value)
    return float(match.group(0)) > 0.0


def _distance_matches_mm(value: object, expected_mm: object) -> bool:
    match = re.fullmatch(
        r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
        r"\s*(mm|cm|in|pt)\s*",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    if match is None:
        return False
    factors = {
        "mm": 1.0,
        "cm": 10.0,
        "in": 25.4,
        "pt": 25.4 / 72.0,
    }
    actual_mm = float(match.group(1)) * factors[match.group(2).casefold()]
    try:
        expected = float(expected_mm)
    except (TypeError, ValueError):
        return False
    return math.isclose(
        actual_mm,
        expected,
        rel_tol=0.0,
        abs_tol=1e-9,
    )


def _distance_matches_pt(value: object, expected_pt: object) -> bool:
    try:
        expected_mm = float(expected_pt) * 25.4 / 72.0
    except (TypeError, ValueError):
        return False
    return _distance_matches_mm(value, expected_mm)


def _style_channel_visible(settings: Any, group: str) -> bool:
    return (
        _setting_value(settings, f"{group}/hide", False) is not True
        and int(_setting_value(settings, f"{group}/transparency", 0) or 0)
        < 100
    )


def _visible_mark_channels(node: Any) -> list[str]:
    settings = getattr(node, "settings", None)
    widget_type = str(getattr(node, "typename", ""))
    channels: list[str] = []
    if widget_type == "xy":
        if _style_channel_visible(settings, "PlotLine") and _distance_is_positive(
            _setting_value(
                settings,
                "PlotLine/width",
                f"{UNIFIED_LINE_WIDTH_PT:g}pt",
            )
        ):
            channels.append("line")
        marker = str(_setting_value(settings, "marker", "none") or "none")
        marker_visible = (
            marker != "none"
            and _distance_is_positive(
                _setting_value(
                    settings,
                    "markerSize",
                    f"{UNIFIED_MARKER_SIZE_PT:g}pt",
                )
            )
            and (
                _style_channel_visible(settings, "MarkerFill")
                or (
                    _style_channel_visible(settings, "MarkerLine")
                    and _distance_is_positive(
                        _setting_value(
                            settings,
                            "MarkerLine/width",
                            f"{UNIFIED_MARKER_LINE_WIDTH_PT:g}pt",
                        )
                    )
                )
            )
        )
        if marker_visible:
            channels.append("marker")
        for group, channel in (
            ("FillBelow", "fill_below"),
            ("FillAbove", "fill_above"),
        ):
            if _style_channel_visible(settings, group):
                channels.append(channel)
    elif widget_type == "boxplot":
        fill_fraction = float(
            _setting_value(settings, "fillfraction", 0.0) or 0.0
        )
        if fill_fraction > 0.0 and _style_channel_visible(settings, "Fill"):
            channels.append("box_fill")
        for group, channel in (
            ("Border", "box_border"),
            ("Whisker", "box_whisker"),
        ):
            if _style_channel_visible(settings, group) and _distance_is_positive(
                _setting_value(
                    settings,
                    f"{group}/width",
                    f"{UNIFIED_LINE_WIDTH_PT:g}pt",
                )
            ):
                channels.append(channel)
    elif widget_type == "image":
        if int(_setting_value(settings, "transparency", 0) or 0) < 100:
            channels.append("image")
    return channels


def _normalized_setting_value(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [
            float(item) if isinstance(item, int | float) else str(item)
            for item in value
        ]
    if isinstance(value, int | float):
        return float(value)
    return str(value or "")


def _settings_snapshot(settings: Any, *, prefix: str = "") -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for name, item in getattr(settings, "setdict", {}).items():
        path = f"{prefix}/{name}" if prefix else str(name)
        nested = getattr(item, "setdict", None)
        if isinstance(nested, dict):
            snapshot.update(_settings_snapshot(item, prefix=path))
        else:
            snapshot[path] = _normalized_setting_value(
                getattr(item, "val", None)
            )
    return snapshot


def _dataset_setting_bindings(settings: Any, *, prefix: str = "") -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    for name, item in getattr(settings, "setdict", {}).items():
        path = f"{prefix}/{name}" if prefix else str(name)
        nested = getattr(item, "setdict", None)
        if isinstance(nested, dict):
            bindings.update(_dataset_setting_bindings(item, prefix=path))
            continue
        setting_type = str(getattr(item, "typename", ""))
        if not setting_type.startswith("dataset"):
            continue
        value = getattr(item, "val", None)
        normalized = _normalized_setting_value(value)
        if normalized is None or normalized == "" or normalized == []:
            continue
        bindings[path] = normalized
    return bindings


def _visible_data_bindings(
    loaded_document: Any,
    *,
    widget_type: str,
    setting_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def collect(path: str, node: Any) -> None:
        if str(getattr(node, "typename", "")) != widget_type:
            return
        if not _node_is_visible(node):
            return
        settings = getattr(node, "settings", None)
        bindings: dict[str, Any] = {}
        for setting_name in setting_names:
            bindings[setting_name] = _normalized_setting_value(
                _setting_value(settings, setting_name)
            )
        records.append(
            {
                "path": str(path),
                "name": str(getattr(node, "name", "")),
                "bindings": bindings,
                "dataset_bindings": _dataset_setting_bindings(settings),
                "mark_channels": _visible_mark_channels(node),
            }
        )

    loaded_document.walkNodes(collect, nodetypes=("widget",))
    return records


def _numeric_setting_equal(actual: object, expected: object) -> bool:
    if expected is None:
        return str(actual or "").strip().casefold() in {
            "",
            "auto",
            "none",
        }
    try:
        return _exact_numeric_token(actual) == _exact_numeric_token(expected)
    except (TypeError, ValueError):
        return False


def _numeric_sequence_equal(actual: object, expected: object) -> bool:
    actual_values = actual if isinstance(actual, list | tuple) else []
    expected_values = expected if isinstance(expected, list | tuple) else []
    if len(actual_values) != len(expected_values):
        return False
    return all(
        _numeric_setting_equal(actual_value, expected_value)
        for actual_value, expected_value in zip(
            actual_values,
            expected_values,
            strict=True,
        )
    )


def _axis_record_matches_spec(
    record: dict[str, Any],
    axis_spec: dict[str, Any],
    *,
    axis_name: str,
) -> bool:
    bindings = record["bindings"]
    expected_ticks = (
        axis_spec.get("ticks")
        if isinstance(axis_spec.get("ticks"), list)
        and 1 < len(axis_spec["ticks"]) <= 12
        else []
    )
    expected_mode = str(axis_spec.get("mode") or "numeric")
    expected_log = axis_spec.get("scale") == "log"
    expected_direction = "vertical" if axis_name == "y" else "horizontal"
    ticks_visible = axis_spec.get("show_ticks") is not False
    visibility_matches = all(
        bool(bindings[path]) is (not ticks_visible)
        for path in (
            "MajorTicks/hide",
            "MinorTicks/hide",
            "TickLabels/hide",
        )
    )
    label = str(axis_spec.get("label") or "")
    label_visibility_matches = (
        not label or not bool(bindings["Label/hide"])
    )
    foreground = str(axis_spec["foreground_color"])
    return (
        record["name"] == axis_name
        and str(bindings["label"]) == label
        and str(bindings["direction"]) == expected_direction
        and str(bindings["mode"]) == expected_mode
        and bool(bindings["log"]) is expected_log
        and _numeric_setting_equal(bindings["min"], axis_spec.get("min"))
        and _numeric_setting_equal(bindings["max"], axis_spec.get("max"))
        and str(bindings["TickLabels/format"])
        == str(axis_spec.get("tick_format") or "Auto")
        and _numeric_sequence_equal(
            bindings["MajorTicks/manualTicks"],
            expected_ticks,
        )
        and _numeric_setting_equal(
            bindings["MinorTicks/number"],
            int(axis_spec.get("minor_tick_count") or 20),
        )
        and _numeric_sequence_equal(
            bindings["MinorTicks/manualTicks"],
            axis_spec.get("minor_ticks"),
        )
        and _distance_matches_pt(
            bindings["Label/size"],
            axis_spec["label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["TickLabels/size"],
            axis_spec["tick_label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["Line/width"],
            axis_spec["line_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/width"],
            axis_spec["major_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/length"],
            axis_spec["major_tick_length_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/width"],
            axis_spec["minor_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/length"],
            axis_spec["minor_tick_length_pt"],
        )
        and not bool(bindings["Line/hide"])
        and all(
            _numeric_setting_equal(bindings[path], 0)
            for path in (
                "Line/transparency",
                "MajorTicks/transparency",
                "MinorTicks/transparency",
            )
        )
        and all(
            str(bindings[path]) == foreground
            for path in (
                "Line/color",
                "Label/color",
                "TickLabels/color",
            )
        )
        and visibility_matches
        and label_visibility_matches
    )


def _scalar_image_matches_contract(
    record: dict[str, Any],
    *,
    data_name: str,
    visual: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["name"] == "field_image"
        and str(bindings["data"]) == data_name
        and _numeric_setting_equal(bindings["min"], visual["z_min"])
        and _numeric_setting_equal(bindings["max"], visual["z_max"])
        and str(bindings["colorScaling"]) == str(visual["zscale"])
        and str(bindings["colorMap"]) == str(visual["colormap_name"])
        and bool(bindings["colorInvert"]) is bool(visual["color_invert"])
        and str(bindings["mapping"]) == str(visual["field_mapping"])
        and str(bindings["drawMode"]) == str(visual["field_draw_mode"])
        and _numeric_setting_equal(
            bindings["transparency"],
            visual["field_transparency"],
        )
        and record["mark_channels"] == ["image"]
    )


def _colorbar_record_matches_contract(
    record: dict[str, Any],
    *,
    scalar: dict[str, Any],
    visual: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    direction = str(visual["colorbar_direction"]).strip().casefold()
    if direction not in {"horizontal", "vertical"}:
        direction = "horizontal"
    if visual["colorbar_manual_position"] is True:
        horz_position = "manual"
        vert_position = "manual"
        horz_manual = visual["colorbar_horz_manual"]
        vert_manual = visual["colorbar_vert_manual"]
    elif direction == "horizontal":
        horz_position = "right"
        vert_position = "top"
        horz_manual = 0.0
        vert_manual = 0.0
    else:
        horz_position = "manual"
        vert_position = "manual"
        horz_manual = visual["colorbar_horz_manual"]
        vert_manual = visual["colorbar_vert_manual"]
    z_ticks = (
        list(visual["z_ticks"])
        if isinstance(visual["z_ticks"], list)
        and 1 < len(visual["z_ticks"]) <= 12
        else []
    )
    foreground = str(visual["colorbar_foreground_color"])
    return (
        record["name"] == "field_colorbar"
        and str(bindings["label"])
        == str(scalar.get("z_label") or "Z")
        and str(bindings["widgetName"]) == "field_image"
        and _numeric_setting_equal(bindings["min"], visual["z_min"])
        and _numeric_setting_equal(bindings["max"], visual["z_max"])
        and str(bindings["direction"]) == direction
        and str(bindings["horzPosn"]) == horz_position
        and str(bindings["vertPosn"]) == vert_position
        and _numeric_setting_equal(bindings["horzManual"], horz_manual)
        and _numeric_setting_equal(bindings["vertManual"], vert_manual)
        and _distance_matches_mm(
            bindings["width"],
            visual["colorbar_width_mm"],
        )
        and _distance_matches_mm(
            bindings["height"],
            visual["colorbar_height_mm"],
        )
        and str(bindings["TickLabels/format"])
        == str(visual["z_tick_format"])
        and _numeric_sequence_equal(
            bindings["MajorTicks/manualTicks"],
            z_ticks,
        )
        and _distance_matches_pt(
            bindings["Label/size"],
            visual["colorbar_label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["TickLabels/size"],
            visual["colorbar_tick_label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["Line/width"],
            visual["colorbar_line_width_pt"],
        )
        and _distance_matches_pt(
            bindings["Border/width"],
            visual["colorbar_border_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/width"],
            visual["colorbar_major_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/length"],
            visual["colorbar_major_tick_length_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/width"],
            visual["colorbar_minor_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/length"],
            visual["colorbar_minor_tick_length_pt"],
        )
        and all(
            not bool(bindings[path])
            for path in (
                "Label/hide",
                "TickLabels/hide",
                "MajorTicks/hide",
                "MinorTicks/hide",
                "Line/hide",
                "Border/hide",
            )
        )
        and all(
            _numeric_setting_equal(bindings[path], 0)
            for path in (
                "Line/transparency",
                "Border/transparency",
                "MajorTicks/transparency",
                "MinorTicks/transparency",
            )
        )
        and all(
            str(bindings[path]) == foreground
            for path in (
                "Line/color",
                "Border/color",
                "Label/color",
                "TickLabels/color",
            )
        )
    )


def _rect_record_matches_contract(
    record: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["positioning"]) == expected["positioning"]
        and _numeric_sequence_equal(bindings["xPos"], expected["xPos"])
        and _numeric_sequence_equal(bindings["yPos"], expected["yPos"])
        and _numeric_sequence_equal(bindings["width"], expected["width"])
        and _numeric_sequence_equal(bindings["height"], expected["height"])
        and bool(bindings["clip"]) is bool(expected["clip"])
        and str(bindings["Fill/color"]) == expected["fill_color"]
        and bool(bindings["Fill/hide"]) is bool(expected["fill_hide"])
        and _numeric_setting_equal(
            bindings["Fill/transparency"],
            expected["fill_transparency"],
        )
        and bool(bindings["Border/hide"]) is bool(expected["border_hide"])
    )


def _line_record_matches_contract(
    record: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["positioning"]) == expected["positioning"]
        and str(bindings["xAxis"]) == expected["x_axis"]
        and str(bindings["yAxis"]) == expected["y_axis"]
        and str(bindings["mode"]) == expected["mode"]
        and _numeric_sequence_equal(bindings["xPos"], expected["xPos"])
        and _numeric_sequence_equal(bindings["yPos"], expected["yPos"])
        and _numeric_sequence_equal(bindings["xPos2"], expected["xPos2"])
        and _numeric_sequence_equal(bindings["yPos2"], expected["yPos2"])
        and bool(bindings["clip"]) is bool(expected["clip"])
        and not bool(bindings["hide"])
        and str(bindings["Line/color"]) == expected["line_color"]
        and _distance_matches_pt(
            bindings["Line/width"],
            expected["line_width_pt"],
        )
        and str(bindings["Line/style"]) == expected["line_style"]
        and _numeric_setting_equal(
            bindings["Line/transparency"],
            expected["line_transparency"],
        )
        and bool(bindings["Line/hide"]) is bool(expected["line_hide"])
        and str(bindings["arrowleft"]) == expected["arrow_left"]
        and str(bindings["arrowright"]) == expected["arrow_right"]
        and bool(bindings["Fill/hide"]) is bool(expected["fill_hide"])
    )


def _direct_label_record_matches_contract(
    record: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["label"])
        == str(expected["literal_label"])
        and str(bindings["positioning"]) == expected["positioning"]
        and str(bindings["xAxis"]) == expected["x_axis"]
        and str(bindings["yAxis"]) == expected["y_axis"]
        and _numeric_sequence_equal(bindings["xPos"], [expected["x"]])
        and _numeric_sequence_equal(bindings["yPos"], [expected["y"]])
        and str(bindings["alignHorz"]) == expected["align"]
        and str(bindings["alignVert"]) == expected["valign"]
        and _numeric_setting_equal(
            bindings["angle"],
            expected["angle_degrees"],
        )
        and _distance_matches_pt(
            bindings["margin"],
            expected["margin_pt"],
        )
        and bool(bindings["clip"]) is bool(expected["clip"])
        and _distance_matches_pt(
            bindings["Text/size"],
            expected["text_size_pt"],
        )
        and str(bindings["Text/color"]) == expected["text_color"]
        and bool(bindings["Text/hide"]) is bool(expected["text_hide"])
        and str(bindings["Background/color"])
        == expected["background_color"]
        and _numeric_setting_equal(
            bindings["Background/transparency"],
            expected["background_transparency"],
        )
        and bool(bindings["Background/hide"])
        is bool(expected["background_hide"])
        and str(bindings["Border/color"]) == expected["border_color"]
        and _distance_matches_pt(
            bindings["Border/width"],
            expected["border_width_pt"],
        )
        and str(bindings["Border/style"]) == expected["border_style"]
        and _numeric_setting_equal(
            bindings["Border/transparency"],
            expected["border_transparency"],
        )
        and bool(bindings["Border/hide"])
        is bool(expected["border_hide"])
    )


def _expected_contour_records(
    *,
    data_name: str,
    visual: dict[str, Any],
) -> list[tuple[Any, ...]]:
    expected: list[tuple[Any, ...]] = []

    def append(
        *,
        name: str,
        levels: object,
        color: object,
        line_style: object,
        line_width: object,
        show_labels: bool,
    ) -> None:
        numeric_levels = (
            list(levels)
            if isinstance(levels, list | tuple)
            else []
        )
        if not numeric_levels:
            return
        line = str(
            (
                str(line_style),
                f"{float(line_width):g}pt",
                str(color),
                False,
            )
        )
        expected.append(
            (
                name,
                data_name,
                "manual",
                tuple(float(value) for value in numeric_levels),
                len(numeric_levels),
                (line,),
                False,
                True,
                True,
                not show_labels,
                False,
            )
        )

    if visual["show_contours"] is True:
        append(
            name="field_contours",
            levels=visual["contour_levels"],
            color=visual["contour_color"],
            line_style=visual["contour_line_style"],
            line_width=visual["contour_line_width_pt"],
            show_labels=bool(visual["contour_labels"]),
        )
    append(
        name="field_highlight_contours",
        levels=visual["highlight_contour_levels"],
        color=visual["highlight_contour_color"],
        line_style=visual["highlight_contour_line_style"],
        line_width=visual["highlight_contour_line_width_pt"],
        show_labels=False,
    )
    return expected


def _actual_contour_record(record: dict[str, Any]) -> tuple[Any, ...]:
    bindings = record["bindings"]
    return (
        str(record["name"]),
        str(bindings["data"]),
        str(bindings["scaling"]),
        tuple(float(value) for value in bindings["manualLevels"]),
        int(bindings["numLevels"]),
        tuple(str(value) for value in bindings["Lines/lines"]),
        bool(bindings["Lines/hide"]),
        bool(bindings["Fills/hide"]),
        bool(bindings["SubLines/hide"]),
        bool(bindings["ContourLabels/hide"]),
        bool(bindings["keyLevels"]),
    )


def audit_spec_data(document_path: Path, spec_path: Path) -> dict[str, Any]:
    """Prove that an exact-current VSZ still consumes its rendered data spec."""

    from PyQt6 import QtWidgets

    from sciplot_core.scalar_visual import opaque_color_to_veusz_rgba
    from sciplot_core.studio import (
        _ensure_veusz_loader_compat,
        _ensure_veusz_on_path,
        _categorical_line_contracts,
        _reference_guide_line_contracts,
        _reference_guide_rect_contracts,
        _veusz_literal_text,
    )

    resolved_document = document_path.expanduser().resolve()
    resolved_spec = spec_path.expanduser().resolve()
    if not resolved_document.is_file():
        raise FileNotFoundError(
            f"Veusz document not found: {resolved_document}"
        )
    if not resolved_spec.is_file():
        raise FileNotFoundError(
            f"Veusz specification not found: {resolved_spec}"
        )
    spec = json.loads(resolved_spec.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"Expected JSON object: {resolved_spec}")

    _ensure_veusz_on_path()
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        _ensure_veusz_loader_compat()
        from veusz import dataimport, document, widgets

        _ = dataimport, widgets
        loaded_document = document.Document()
        loaded_document.load(str(resolved_document))
        units: list[dict[str, Any]] = []
        seen_identities: set[str] = set()
        allowed_xy_records: set[tuple[str, str, str]] = set()
        expected_xy_order: list[tuple[str, str, str, str]] = []
        allowed_boxplot_records: set[
            tuple[str, tuple[str, ...], tuple[float, ...]]
        ] = set()
        expected_boxplot_order: list[
            tuple[str, tuple[str, ...], tuple[float, ...]]
        ] = []
        categorical = spec.get("categorical")
        categorical_groups = {
            str(group.get("y_name") or ""): group
            for group in (
                categorical.get("groups", [])
                if isinstance(categorical, dict)
                else []
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
            setting_names=("xData", "yData", "labels", "key"),
        )
        boxplot_records = _visible_data_bindings(
            loaded_document,
            widget_type="boxplot",
            setting_names=("values", "posn"),
        )
        axes = spec.get("axes")
        if (
            not isinstance(axes, dict)
            or not isinstance(axes.get("x"), dict)
            or not isinstance(axes.get("y"), dict)
        ):
            raise ValueError(
                "Veusz specification has no closed x/y axis inventory."
            )
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
            or not _axis_record_matches_spec(
                axis_records[0],
                axes["x"],
                axis_name="x",
            )
            or not _axis_record_matches_spec(
                axis_records[1],
                axes["y"],
                axis_name="y",
            )
        ):
            raise ValueError(
                "Exact-current Veusz x/y axis labels, scales, bounds, ticks, "
                "visibility, or order differ from the rendered specification."
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
                if (
                    raw_series is None
                    or str(group.get("label") or "")
                    != str(raw_series.get("label") or "")
                ):
                    raise ValueError(
                        "Categorical group labels do not match their rendered "
                        "series identities."
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
                    "Categorical axis labels do not match the ordered series "
                    "identity mapping."
                )
        for index, raw_series in enumerate(series, start=1):
            if not isinstance(raw_series, dict):
                raise ValueError(f"Veusz specification series {index} is invalid.")
            name = str(raw_series.get("name") or "").strip()
            x_name = str(raw_series.get("x_name") or "").strip()
            y_name = str(raw_series.get("y_name") or "").strip()
            identity = f"series:{name}"
            if (
                not name
                or not x_name
                or not y_name
                or identity in seen_identities
            ):
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
                    _veusz_literal_text(raw_series.get("label")),
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
                and str(record["bindings"]["yData"]) == y_name
                and str(record["bindings"]["key"])
                == _veusz_literal_text(raw_series.get("label"))
            ]
            if len(matching_xy) != 1:
                raise ValueError(
                    f"Exact-current Veusz document does not contain exactly "
                    f"one bound xy widget for series {name!r}."
                )
            consumers: list[str] = []
            presentation_kind = str(
                raw_series.get("presentation_kind") or "curve"
            )
            group = categorical_groups.get(y_name)
            raw_points_required = (
                raw_series.get("raw_points_visible") is not False
            )
            if presentation_kind != "categorical_replicates":
                if not matching_xy[0]["mark_channels"]:
                    raise ValueError(
                        f"Exact-current Veusz series {name!r} has no visible "
                        "line, marker, or fill channel."
                    )
                consumers.append(str(matching_xy[0]["path"]))
            else:
                if not isinstance(group, dict):
                    raise ValueError(
                        f"Categorical series {name!r} has no group contract."
                    )
                if raw_points_required:
                    if "marker" not in matching_xy[0]["mark_channels"]:
                        raise ValueError(
                            f"Categorical series {name!r} requires visible "
                            "raw-point markers."
                        )
                    consumers.append(str(matching_xy[0]["path"]))
                if group.get("boxplot_eligible") is True:
                    expected_box_name = expected_box_name_by_y[y_name]
                    expected_position = (float(group["position"]),)
                    expected_values = (y_name,)
                    allowed_boxplot_records.add(
                        (
                            expected_box_name,
                            expected_values,
                            expected_position,
                        )
                    )
                    expected_boxplot_order.append(
                        (
                            expected_box_name,
                            expected_values,
                            expected_position,
                        )
                    )
                    matching_boxes = [
                        record
                        for record in boxplot_records
                        if record["name"] == expected_box_name
                        and tuple(record["bindings"]["values"])
                        == expected_values
                        and tuple(
                            float(value)
                            for value in record["bindings"]["posn"]
                        )
                        == expected_position
                    ]
                    if (
                        len(matching_boxes) != 1
                        or not matching_boxes[0]["mark_channels"]
                    ):
                        raise ValueError(
                            f"Categorical series {name!r} requires its exact "
                            "visible native boxplot."
                        )
                    consumers.append(str(matching_boxes[0]["path"]))
            if not consumers:
                raise ValueError(
                    f"Exact-current Veusz document does not visibly consume "
                    f"series {name!r}."
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
                (
                    "category_axis_label_provider",
                    "category_axis_x",
                    "category_axis_y",
                    "",
                )
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
                "Exact-current Veusz xy object and legend-key order differs "
                "from the rendered series order."
            )
        actual_boxplot_order = [
            (
                str(record["name"]),
                tuple(
                    str(value)
                    for value in record["bindings"]["values"]
                ),
                tuple(
                    float(value)
                    for value in record["bindings"]["posn"]
                ),
            )
            for record in boxplot_records
        ]
        if actual_boxplot_order != expected_boxplot_order:
            raise ValueError(
                "Exact-current Veusz boxplot object order differs from the "
                "rendered categorical order."
            )

        legend = spec.get("legend")
        legend = legend if isinstance(legend, dict) else {}
        visible_keys = _visible_data_bindings(
            loaded_document,
            widget_type="key",
            setting_names=("title",),
        )
        expected_legend = legend.get("show") is True
        if expected_legend:
            if (
                len(visible_keys) != 1
                or visible_keys[0]["name"] != "key1"
                or str(visible_keys[0]["bindings"]["title"]) != ""
            ):
                raise ValueError(
                    "Exact-current Veusz document does not contain its exact "
                    "visible legend."
                )
        elif visible_keys:
            raise ValueError(
                "Exact-current Veusz document contains an unapproved visible "
                "legend."
            )

        direct_labels = spec.get("direct_labels")
        if not isinstance(direct_labels, list):
            raise ValueError("Veusz specification has no direct-label inventory.")
        expected_direct_labels: list[dict[str, Any]] = []
        seen_direct_label_names: set[str] = set()
        for raw_label in direct_labels:
            if not isinstance(raw_label, dict):
                raise ValueError(
                    "Veusz specification contains an invalid direct label."
                )
            label_name = str(raw_label.get("name") or "").strip()
            series_match = re.fullmatch(r"label_(\d+)", label_name)
            category_match = re.fullmatch(r"category_label_(\d+)", label_name)
            if series_match is not None:
                label_index = int(series_match.group(1)) - 1
                expected_label = (
                    str(series[label_index].get("label") or "")
                    if 0 <= label_index < len(series)
                    else None
                )
            elif category_match is not None and isinstance(categorical, dict):
                label_index = int(category_match.group(1)) - 1
                x_axis = (
                    spec.get("axes", {}).get("x")
                    if isinstance(spec.get("axes"), dict)
                    and isinstance(spec["axes"].get("x"), dict)
                    else {}
                )
                category_labels = list(x_axis.get("category_labels") or [])
                expected_label = (
                    str(category_labels[label_index])
                    if 0 <= label_index < len(category_labels)
                    else None
                )
            else:
                expected_label = None
            if (
                expected_label is None
                or str(raw_label.get("label") or "") != expected_label
                or label_name in seen_direct_label_names
            ):
                raise ValueError(
                    "Veusz direct label does not match its rendered series."
                )
            seen_direct_label_names.add(label_name)
            expected_direct_labels.append(
                {
                    **raw_label,
                    "path": f"/page1/graph1/{label_name}",
                    "literal_label": _veusz_literal_text(
                        raw_label.get("label")
                    ),
                }
            )
        visible_direct_labels = _visible_data_bindings(
            loaded_document,
            widget_type="label",
            setting_names=(
                "label",
                "positioning",
                "xAxis",
                "yAxis",
                "xPos",
                "yPos",
                "alignHorz",
                "alignVert",
                "angle",
                "margin",
                "clip",
                "Text/size",
                "Text/color",
                "Text/hide",
                "Background/color",
                "Background/transparency",
                "Background/hide",
                "Border/color",
                "Border/width",
                "Border/style",
                "Border/transparency",
                "Border/hide",
            ),
        )
        if (
            len(visible_direct_labels) != len(expected_direct_labels)
            or any(
                not _direct_label_record_matches_contract(
                    record,
                    expected=expected,
                )
                for record, expected in zip(
                    visible_direct_labels,
                    expected_direct_labels,
                    strict=True,
                )
            )
        ):
            raise ValueError(
                "Exact-current Veusz direct-label text, geometry, style, or "
                "ordered inventory differs from its series-bound contract."
            )

        if isinstance(categorical, dict):
            groups = [
                group
                for group in categorical.get("groups", [])
                if isinstance(group, dict)
            ]
            x_axis = spec["axes"]["x"]
            category_positions = [
                float(value)
                for value in x_axis.get("category_positions", [])
            ]
            expected_category_labels = [
                _veusz_literal_text(value)
                for value in x_axis.get("category_labels", [])
            ]
            if _text_dataset_values(
                loaded_document,
                dataset_name="category_axis_labels",
            ) != expected_category_labels:
                raise ValueError(
                    "Exact-current Veusz category text dataset does not match "
                    "the ordered series labels."
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
                expected_values=[
                    float(group["descriptive_statistics"]["median"])
                    for group in groups
                ],
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
                    for value in x_axis_records[0]["bindings"][
                        "MajorTicks/manualTicks"
                    ]
                ]
                != category_positions
            ):
                raise ValueError(
                    "Exact-current Veusz categorical axis does not expose the "
                    "ordered label positions."
                )

        scalar = spec.get("scalar_field")
        allowed_scalar_dataset: str | None = None
        if isinstance(scalar, dict):
            visual = scalar_visual_contract(
                scalar,
                label="Veusz scalar-field specification",
            )
            data_name = str(scalar.get("data_name") or "").strip()
            allowed_scalar_dataset = data_name
            identity = "scalar_field"
            if not data_name or identity in seen_identities:
                raise ValueError(
                    "Veusz scalar-field specification has no unique data identity."
                )
            dataset = _dataset_evidence(
                loaded_document,
                dataset_name=data_name,
                expected_values=scalar.get("z_values"),
                dimensions=2,
            )
            loaded_dataset = loaded_document.data[data_name]
            x_centres, y_centres = loaded_dataset.getPixelCentres()
            x_evidence = _numeric_digest(x_centres)
            y_evidence = _numeric_digest(y_centres)
            if (
                x_evidence
                != _numeric_digest(
                    scalar.get("x_values"),
                    expected_persisted=True,
                )
                or y_evidence
                != _numeric_digest(
                    scalar.get("y_values"),
                    expected_persisted=True,
                )
            ):
                raise ValueError(
                    "Exact-current Veusz scalar-field coordinates differ from "
                    "the rendered specification."
                )
            dataset["x_value_sha256"] = x_evidence
            dataset["y_value_sha256"] = y_evidence
            image_records = _visible_data_bindings(
                loaded_document,
                widget_type="image",
                setting_names=(
                    "data",
                    "min",
                    "max",
                    "colorScaling",
                    "colorMap",
                    "colorInvert",
                    "mapping",
                    "drawMode",
                    "transparency",
                ),
            )
            if (
                len(image_records) != 1
                or not _scalar_image_matches_contract(
                    image_records[0],
                    data_name=data_name,
                    visual=visual,
                )
            ):
                raise ValueError(
                    "Exact-current Veusz scalar image differs from its "
                    "range, scaling, colormap, inversion, mapping, or draw "
                    "contract."
                )
            expected_colormap = [
                list(opaque_color_to_veusz_rgba(value))
                for value in visual["colormap_colors"]
            ]
            matching_colormaps = [
                json_safe(value)
                for name, value in loaded_document.evaluate.def_colormaps
                if str(name) == str(visual["colormap_name"])
            ]
            if matching_colormaps != [expected_colormap]:
                raise ValueError(
                    "Exact-current Veusz custom colormap differs from the "
                    "rendered scalar-field contract."
                )
            contour_records = _visible_data_bindings(
                loaded_document,
                widget_type="contour",
                setting_names=(
                    "data",
                    "scaling",
                    "manualLevels",
                    "numLevels",
                    "Lines/lines",
                    "Lines/hide",
                    "Fills/hide",
                    "SubLines/hide",
                    "ContourLabels/hide",
                    "keyLevels",
                ),
            )
            if [
                _actual_contour_record(record)
                for record in contour_records
            ] != _expected_contour_records(
                data_name=data_name,
                visual=visual,
            ):
                raise ValueError(
                    "Exact-current Veusz contour inventory differs from the "
                    "rendered scalar-field contract."
                )
            units.append(
                {
                    "identity": identity,
                    "kind": "scalar_field",
                    "datasets": [dataset],
                    "consumer_paths": [
                        str(image_records[0]["path"]),
                        *[
                            str(record["path"])
                            for record in contour_records
                        ],
                    ],
                    "scalar_visual": visual,
                }
            )
        colorbar_records = _visible_data_bindings(
            loaded_document,
            widget_type="colorbar",
            setting_names=(
                "label",
                "widgetName",
                "min",
                "max",
                "direction",
                "horzPosn",
                "vertPosn",
                "horzManual",
                "vertManual",
                "width",
                "height",
                "TickLabels/format",
                "MajorTicks/manualTicks",
                "Label/size",
                "TickLabels/size",
                "Line/width",
                "Border/width",
                "MajorTicks/width",
                "MajorTicks/length",
                "MinorTicks/width",
                "MinorTicks/length",
                "Label/hide",
                "TickLabels/hide",
                "MajorTicks/hide",
                "MinorTicks/hide",
                "Line/hide",
                "Border/hide",
                "Line/transparency",
                "Border/transparency",
                "MajorTicks/transparency",
                "MinorTicks/transparency",
                "Line/color",
                "Border/color",
                "Label/color",
                "TickLabels/color",
            ),
        )
        visual: dict[str, Any] | None = None
        if isinstance(scalar, dict) and scalar.get("show_colorbar") is True:
            visual = scalar_visual_contract(
                scalar,
                label="Veusz scalar-field specification",
            )
        expected_colorbar_count = 1 if visual is not None else 0
        if (
            len(colorbar_records) != expected_colorbar_count
            or (
                visual is not None
                and not _colorbar_record_matches_contract(
                    colorbar_records[0],
                    scalar=scalar,
                    visual=visual,
                )
            )
        ):
            raise ValueError(
                "Exact-current Veusz colorbar dimensions, text, ticks, "
                "colors, or placement differ from the rendered scalar-field "
                "contract."
            )
        rect_records = _visible_data_bindings(
            loaded_document,
            widget_type="rect",
            setting_names=(
                "positioning",
                "xPos",
                "yPos",
                "width",
                "height",
                "clip",
                "Fill/color",
                "Fill/hide",
                "Fill/transparency",
                "Border/hide",
            ),
        )
        expected_rects: list[dict[str, Any]] = [
            {
                "path": "/page1/page_export_background",
                "name": "page_export_background",
                "positioning": "relative",
                "xPos": [0.5],
                "yPos": [0.5],
                "width": [1.0],
                "height": [1.0],
                "clip": True,
                "fill_color": "white",
                "fill_hide": False,
                "fill_transparency": 0,
                "border_hide": True,
            }
        ]
        expected_rects.extend(
            {
                **contract,
                "path": f"/page1/graph1/{contract['name']}",
            }
            for contract in _reference_guide_rect_contracts(spec)
        )
        if (
            visual is not None
            and str(visual["colorbar_background_color"]).strip()
        ):
            expected_rects.append(
                {
                    "path": "/page1/graph1/field_colorbar_background",
                    "name": "field_colorbar_background",
                    "positioning": "relative",
                    "xPos": [visual["colorbar_background_x_fraction"]],
                    "yPos": [visual["colorbar_background_y_fraction"]],
                    "width": [visual["colorbar_background_width_fraction"]],
                    "height": [visual["colorbar_background_height_fraction"]],
                    "clip": True,
                    "fill_color": visual["colorbar_background_color"],
                    "fill_hide": False,
                    "fill_transparency": visual[
                        "colorbar_background_transparency"
                    ],
                    "border_hide": True,
                }
            )
        actual_rects_by_path = {
            str(record["path"]): record for record in rect_records
        }
        expected_rects_by_path = {
            str(record["path"]): record for record in expected_rects
        }
        if (
            len(actual_rects_by_path) != len(rect_records)
            or set(actual_rects_by_path) != set(expected_rects_by_path)
            or any(
                not _rect_record_matches_contract(
                    actual_rects_by_path[path],
                    expected=expected,
                )
                for path, expected in expected_rects_by_path.items()
            )
        ):
            raise ValueError(
                "Exact-current Veusz shape inventory differs from the closed "
                "page, reference-guide, and scalar colorbar-background contract."
            )
        line_records = _visible_data_bindings(
            loaded_document,
            widget_type="line",
            setting_names=(
                "positioning",
                "xAxis",
                "yAxis",
                "mode",
                "xPos",
                "yPos",
                "xPos2",
                "yPos2",
                "clip",
                "hide",
                "Line/color",
                "Line/width",
                "Line/style",
                "Line/transparency",
                "Line/hide",
                "arrowleft",
                "arrowright",
                "Fill/hide",
            ),
        )
        expected_lines = [
            {
                **contract,
                "path": f"/page1/graph1/{contract['name']}",
            }
            for contract in (
                _categorical_line_contracts(spec)
                + _reference_guide_line_contracts(spec)
            )
        ]
        actual_lines_by_path = {
            str(record["path"]): record for record in line_records
        }
        expected_lines_by_path = {
            str(record["path"]): record for record in expected_lines
        }
        if (
            len(actual_lines_by_path) != len(line_records)
            or set(actual_lines_by_path) != set(expected_lines_by_path)
            or any(
                not _line_record_matches_contract(
                    actual_lines_by_path[path],
                    expected=expected,
                )
                for path, expected in expected_lines_by_path.items()
            )
        ):
            raise ValueError(
                "Exact-current Veusz native line inventory differs from its "
                "closed categorical/reference geometry and style contract."
            )
        if not units:
            raise ValueError(
                "Veusz specification contains no auditable rendered data units."
            )
        if isinstance(categorical, dict):
            allowed_xy_records.add(
                (
                    "category_axis_label_provider",
                    "category_axis_x",
                    "category_axis_y",
                )
            )
        for record in xy_records:
            bindings = record["bindings"]
            identity = (
                str(record["name"]),
                str(bindings["xData"]),
                str(bindings["yData"]),
            )
            if identity not in allowed_xy_records:
                raise ValueError(
                    "Exact-current Veusz document contains an unapproved "
                    f"visible xy data binding at {record['path']}: "
                    f"{identity!r}."
                )
            allowed_dataset_paths = {"xData", "yData"}
            if record["name"] == "category_axis_label_provider":
                allowed_dataset_paths.add("labels")
                expected_provider_labels = "category_axis_labels"
                if bindings["labels"] != expected_provider_labels:
                    raise ValueError(
                        "Categorical axis provider does not consume its exact "
                        "label dataset."
                    )
            if set(record["dataset_bindings"]) - allowed_dataset_paths:
                raise ValueError(
                    "Exact-current Veusz xy widget contains unapproved data "
                    f"settings at {record['path']}."
                )
        actual_boxplot_records: set[
            tuple[str, tuple[str, ...], tuple[float, ...]]
        ] = set()
        for record in boxplot_records:
            if set(record["dataset_bindings"]) - {"values", "posn"}:
                raise ValueError(
                    "Exact-current Veusz boxplot contains unapproved data "
                    f"settings at {record['path']}."
                )
            values = tuple(str(value) for value in record["bindings"]["values"])
            positions = tuple(
                float(value) for value in record["bindings"]["posn"]
            )
            identity = (str(record["name"]), values, positions)
            if record["mark_channels"]:
                actual_boxplot_records.add(identity)
                if identity not in allowed_boxplot_records:
                    raise ValueError(
                        "Exact-current Veusz document contains an unapproved "
                        f"visible boxplot data binding at {record['path']}."
                    )
        if actual_boxplot_records != allowed_boxplot_records:
            raise ValueError(
                "Exact-current Veusz document does not contain the exact "
                "visible categorical boxplot inventory."
            )
        for widget_type in ("image", "contour"):
            for record in _visible_data_bindings(
                loaded_document,
                widget_type=widget_type,
                setting_names=("data",),
            ):
                data_binding = str(record["bindings"]["data"])
                if (
                    allowed_scalar_dataset is None
                    or data_binding != allowed_scalar_dataset
                ):
                    raise ValueError(
                        "Exact-current Veusz document contains an unapproved "
                        f"visible {widget_type} data binding at "
                        f"{record['path']}: {data_binding!r}."
                    )
                if set(record["dataset_bindings"]) - {"data"}:
                    raise ValueError(
                        f"Exact-current Veusz {widget_type} contains "
                        f"unapproved data settings at {record['path']}."
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
                and str(getattr(node, "name", ""))
                == "category_axis_tick_label_provider"
            ):
                # This zero-width, hidden-style native bar exists only so
                # Veusz can source categorical tick labels for boxplots.
                return
            if not _node_is_visible(node):
                return
            if widget_type in {"xy", "boxplot", "image", "contour"}:
                return
            if widget_type in {
                "ellipse",
                "imagefile",
                "polygon",
                "svgfile",
            }:
                unapproved_overlay_widgets.append(f"{path}:{widget_type}")
            if bool(getattr(node, "isplotter", False)):
                unapproved_plotters.append(f"{path}:{widget_type}")
            if (
                widget_type in other_data_widget_types
                and _dataset_setting_bindings(getattr(node, "settings", None))
            ):
                unapproved_data_widgets.append(f"{path}:{widget_type}")

        loaded_document.walkNodes(inspect_widget, nodetypes=("widget",))
        if (
            unapproved_plotters
            or unapproved_data_widgets
            or unapproved_overlay_widgets
        ):
            offenders = sorted(
                set(
                    unapproved_plotters
                    + unapproved_data_widgets
                    + unapproved_overlay_widgets
                )
            )
            raise ValueError(
                "Exact-current Veusz document contains an unapproved visible "
                f"data-bearing or overlay widget: {offenders[0]}."
            )
        return {
            "kind": "sciplot_veusz_spec_data_audit",
            "version": 1,
            "status": "passed",
            "document": {
                "path": str(resolved_document),
                "sha256": file_sha256(resolved_document),
            },
            "spec": {
                "path": str(resolved_spec),
                "sha256": file_sha256(resolved_spec),
            },
            "units": units,
            "unit_count": len(units),
        }
    finally:
        if existing_app is None:
            app.quit()


def save_spec(document_path: Path, spec_path: Path) -> dict[str, Any]:
    """Create a VSZ from an already-materialized SciPlot Veusz spec."""

    from sciplot_core.studio import _save_veusz_document_from_spec

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"Expected JSON object: {spec_path}")
    resolved_document = document_path.expanduser().resolve()
    _save_veusz_document_from_spec(
        resolved_document,
        spec,
        spec_path=spec_path.expanduser().resolve(),
    )
    return {
        "kind": "sciplot_veusz_save_spec",
        "document": str(resolved_document),
        "exists": resolved_document.exists(),
    }


def _split_formats(value: str) -> list[str]:
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    return formats or ["pdf", "tiff_300"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Internal SciPlot Veusz export worker."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser(
        "export", help="Generate and export a Veusz document from a request."
    )
    export_parser.add_argument("request", type=Path)
    export_parser.add_argument("--formats", default="pdf,tiff_300")
    export_document_parser = subparsers.add_parser(
        "export-document", help="Export an existing Veusz document."
    )
    export_document_parser.add_argument("document", type=Path)
    export_document_parser.add_argument("--formats", default="pdf,tiff_300")
    export_document_parser.add_argument("--out", type=Path)
    audit_parser = subparsers.add_parser(
        "audit-documents", help="Audit exact current Veusz documents."
    )
    audit_parser.add_argument("documents", nargs="+", type=Path)
    spec_data_audit_parser = subparsers.add_parser(
        "audit-spec-data",
        help="Verify that an exact-current VSZ consumes one SciPlot data spec.",
    )
    spec_data_audit_parser.add_argument("document", type=Path)
    spec_data_audit_parser.add_argument("spec", type=Path)
    save_spec_parser = subparsers.add_parser(
        "save-spec", help="Generate a VSZ from a SciPlot Veusz spec."
    )
    save_spec_parser.add_argument("document", type=Path)
    save_spec_parser.add_argument("spec", type=Path)
    inspect_state_parser = subparsers.add_parser(
        "inspect-document-state",
        help="Reopen a VSZ and materialize its widget settings.",
    )
    inspect_state_parser.add_argument("document", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "export":
        payload = export_request(args.request, formats=_split_formats(args.formats))
    elif args.command == "export-document":
        payload = export_document(
            args.document,
            formats=_split_formats(args.formats),
            output_dir=args.out,
        )
    elif args.command == "audit-documents":
        payload = audit_documents(args.documents)
    elif args.command == "audit-spec-data":
        payload = audit_spec_data(args.document, args.spec)
    elif args.command == "inspect-document-state":
        payload = inspect_document_state(args.document)
    else:
        payload = save_spec(args.document, args.spec)
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "audit_documents",
    "audit_spec_data",
    "export_document",
    "export_request",
    "inspect_document_state",
    "main",
    "save_spec",
]
