"""A fully resolved Cartesian plot contract, independent of any renderer."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.schema import DIGEST, IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_transforms.datasets import dataset_schema, validate_dataset

NUMBER = {"type": "number"}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
COLOR = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$"}
PAIR = {"type": "array", "minItems": 2, "maxItems": 2, "items": NUMBER}
FONT = {"font_family": {"type": "string", "minLength": 1}, "font_size_pt": POSITIVE}


def style_schema() -> dict[str, Any]:
    return closed({"line_color": COLOR, "line_width_pt": POSITIVE,
        "line_style": {"enum": ["solid", "dash", "dot"]}, "line_join": {"enum": ["bevel", "round", "miter"]},
        "marker": {"enum": ["circle", "square", "diamond", "triangle", "cross", "plus", "none"]},
        "marker_size_pt": POSITIVE, "marker_color": COLOR, "marker_line_width_pt": POSITIVE,
        "line_visible": {"type": "boolean"}, "marker_visible": {"type": "boolean"}})


def axis_schema() -> dict[str, Any]:
    return closed({"id": IDENTIFIER, "label": {"type": "string"}, "unit": {"type": "string"},
        "scale": {"enum": ["linear", "log"]}, "limits": PAIR, "ticks": {"type": "array", "items": NUMBER},
        **FONT, "visible": {"type": "boolean"}, "label_visible": {"type": "boolean"},
        "line_width_pt": POSITIVE, "line_color": COLOR, "tick_length_pt": POSITIVE,
        "tick_direction": {"enum": ["in", "out"]}})


def legend_schema() -> dict[str, Any]:
    return closed({"id": IDENTIFIER, "visible": {"type": "boolean"}, "position": PAIR, **FONT})


def annotation_schema() -> dict[str, Any]:
    return closed({"id": IDENTIFIER, "text": {"type": "string", "minLength": 1, "maxLength": 500},
        "visible": {"type": "boolean"}, "coordinate_mode": {"enum": ["relative", "axes"]},
        "position": PAIR, **FONT, "color": COLOR})


def layout_schema() -> dict[str, Any]:
    return closed({"kind": {"const": "cartesian"}, "dimensions": closed({"width_mm": POSITIVE, "height_mm": POSITIVE}),
        "margins_mm": closed({name: {"type": "number", "minimum": 0} for name in ("left", "right", "top", "bottom")}),
        "axes": closed({"x": axis_schema(), "y": axis_schema()}), "legend": legend_schema(),
        "annotations": {"type": "array", "items": annotation_schema()},
        "series_styles": {"type": "object", "propertyNames": IDENTIFIER, "additionalProperties": style_schema()},
        "background_color": COLOR})


def ir_schema(version: int = 1) -> dict[str, Any]:
    if version == 2:
        from sciplot_core.plot_grammar import ir_schema_v2

        return ir_schema_v2()
    if version != 1:
        raise ValueError("Unsupported PlotIR version.")
    series = closed({"id": IDENTIFIER, "label": {"type": "string"}, "dataset_id": IDENTIFIER,
        "x_column": IDENTIFIER, "y_column": IDENTIFIER,
        "x": {"type": "array", "items": {"type": ["number", "null"]}},
        "y": {"type": "array", "items": {"type": ["number", "null"]}}, "style": style_schema()})
    return closed({"kind": {"const": "sciplot_plot_ir"}, "schema_version": {"const": 1},
        "scientific_hash": DIGEST, "presentation_hash": DIGEST,
        "datasets": {"type": "object", "propertyNames": IDENTIFIER, "additionalProperties": dataset_schema()},
        "series": {"type": "array", "minItems": 1, "items": series},
        "axes": closed({"x": axis_schema(), "y": axis_schema()}),
        "dimensions": closed({"width_mm": POSITIVE, "height_mm": POSITIVE}),
        "layout": closed({"margins_mm": closed({name: {"type": "number", "minimum": 0} for name in ("left", "right", "top", "bottom")})}),
        "legend": legend_schema(), "annotations": {"type": "array", "items": annotation_schema()},
        "background_color": COLOR, "ir_hash": DIGEST},
        ["kind", "schema_version", "scientific_hash", "presentation_hash", "datasets", "series", "axes",
         "dimensions", "layout", "legend", "annotations", "background_color"])


def _validate(value: Any, verify: bool) -> dict[str, Any]:
    validate_wire(value, ir_schema(), code="plot_ir_invalid")
    assert isinstance(value, dict)
    for name, dataset in value["datasets"].items():
        validate_dataset(dataset)
        if name != dataset["id"]:
            fail("plot_ir_dataset_identity", "Dataset dictionary keys must match their stable IDs.", "/datasets", "stable_id")
    ids = [series["id"] for series in value["series"]]
    ids.extend(axis["id"] for axis in value["axes"].values())
    ids.append(value["legend"]["id"])
    ids.extend(annotation["id"] for annotation in value["annotations"])
    if len(ids) != len(set(ids)):
        fail("plot_ir_object_identity", "All resolved object IDs must be unique.", "/series", "unique_ids")
    for series in value["series"]:
        dataset = value["datasets"].get(series["dataset_id"])
        for axis in ("x", "y"):
            if dataset is None or series[axis + "_column"] not in dataset["columns"]:
                fail("plot_ir_dataset_reference", "A series references an absent dataset column.", "/series", "dataset_reference")
            column = dataset["columns"][series[axis + "_column"]]
            if series[axis] != column["values"] or column["unit"] != value["axes"][axis]["unit"]:
                fail("plot_ir_coordinate_mismatch", "Resolved coordinates and units must equal their dataset binding.", "/series", "exact_coordinates")
        if len(series["x"]) != len(series["y"]):
            fail("plot_ir_ragged_series", "Resolved XY coordinates must preserve their paired row count.", "/series", "paired_coordinates")
    dimensions, margins = value["dimensions"], value["layout"]["margins_mm"]
    if margins["left"] + margins["right"] >= dimensions["width_mm"] or margins["top"] + margins["bottom"] >= dimensions["height_mm"]:
        fail("plot_ir_empty_plot_area", "Figure margins must leave a positive plotting area.", "/layout", "positive_plot_area")
    for axis in value["axes"].values():
        low, high = sorted(axis["limits"])
        if low == high or axis["scale"] == "log" and low <= 0 or any(not low <= tick <= high for tick in axis["ticks"]):
            fail("plot_ir_axis_domain", "Axes require distinct finite limits and in-range ticks; logarithmic bounds must be positive.", "/axes", "axis_domain")
    for name in ("x", "y"):
        low, high = sorted(value["axes"][name]["limits"])
        if any(coordinate is not None and not low <= coordinate <= high for series in value["series"] for coordinate in series[name]):
            fail("plot_ir_data_clipping", "Managed axis bounds cannot hide original or derived coordinates.", "/axes/" + name, "no_clipping")
    relative = [value["legend"], *(item for item in value["annotations"] if item["coordinate_mode"] == "relative")]
    if any(not all(0 <= point <= 1 for point in item["position"]) for item in relative):
        fail("plot_ir_relative_position", "Relative placement stays inside the figure's normalized coordinate frame.", "/layout", "relative_bounds")
    result = deepcopy(value)
    expected = canonical_json_sha256({key: item for key, item in result.items() if key != "ir_hash"}, allow_nan=False)
    if verify and "ir_hash" in result and result["ir_hash"] != expected:
        fail("plot_ir_hash_mismatch", "Resolved IR bytes do not match their seal.", "/ir_hash", "content_hash")
    result["ir_hash"] = expected
    return result


def validate_ir(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema_version") == 2:
        from sciplot_core.plot_grammar import validate_ir_v2

        return validate_ir_v2(value)
    return _validate(value, True)


def seal_ir(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema_version") == 2:
        from sciplot_core.plot_grammar import seal_ir_v2

        return seal_ir_v2(value)
    return _validate(value, False)
