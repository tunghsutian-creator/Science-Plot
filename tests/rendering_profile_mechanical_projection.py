"""Declared mechanical roles projected from reopened native state and paint.

Legacy stacked bars overpaint opaque rectangles. Only that explicitly checked
opaque case admits last-paint-wins projection; every native primitive is still
retained by the capture. Generic polygons and segments are compared in actual
painted physical coordinates, independently of the compiler's proposed IR.
"""

from math import isfinite

from rendering_profiles_helpers import project_xy_snapshot, selected_groups
from sciplot_core.plot_backends.figure_marks import graph_path, mark_path
from sciplot_core.plot_backends.native_primitives import dataset_name, native_name


def _array(payload, reference):
    return payload["datasets"][reference]["data"] if isinstance(reference, str) else reference


def _finite(values):
    return [value for value in values if isinstance(value, (int, float)) and isfinite(value)]


def _rgba(value):
    if isinstance(value, dict):
        return value
    if value.startswith("#") and len(value) == 7:
        return {"rgba16": [int(value[start:start + 2], 16) * 257 for start in (1, 3, 5)] + [65535]}
    raise AssertionError(f"Unsupported categorical color representation: {value}")


def _bounds(points):
    xs, ys = zip(*points, strict=True)
    bounds = [min(xs), min(ys), max(xs), max(ys)]
    assert len(points) == 4 and len(set(xs)) == len(set(ys)) == 2, "Nonrectangular bar needs a distinct profile"
    return bounds


def _line(payload, path):
    node = payload["inventory"][path]
    value = node["settings"]
    assert node["type"] == "line" and not value["hide"] and not value["Line/hide"]
    assert value["mode"] == "point-to-point" and value["arrowleft"] == value["arrowright"] == "none"
    primitives = [item for item in payload["painted_primitives"] if item["widget_path"] == path]
    assert len(primitives) == 1 and primitives[0]["kind"] == "line"
    return {"points_mm": sorted(primitives[0]["points_mm"]), "clip": value["clip"],
            "stroke": selected_groups(value, ["Line"])}


def _legacy_fill(payload, path):
    value = payload["inventory"][path]["settings"]
    assert value["direction"] == "vertical" and value["mode"] == "stacked" and value["errorstyle"] == "none"
    assert not value["hide"] and all(line[3] for line in value["BarLine/lines"])
    final = {}
    for item in payload["painted_primitives"]:
        if item["widget_path"] != path:
            continue
        fill = value["BarFill/fills"][item["data_index"]]
        assert fill[0] == "solid" and fill[2] is False and fill[3] == 0, "Only opaque solid bar overlays are covered"
        bounds = _bounds(item["points_mm"])
        final[tuple(bounds)] = {"bounds_mm": bounds, "color": _rgba(fill[1]), "opacity": 1.0}
    return sorted(final.values(), key=lambda item: item["bounds_mm"][0])


def _polygon_fill(payload, path):
    node = payload["inventory"][path]
    value = node["settings"]
    assert node["type"] == "polygon" and not value["hide"] and value["Line/hide"]
    assert not value["Fill/hide"] and value["Fill/style"] == "solid"
    primitives = [item for item in payload["painted_primitives"] if item["widget_path"] == path]
    assert len(primitives) == 1
    return {"bounds_mm": _bounds(primitives[0]["points_mm"]), "color": value["Fill/color"],
            "opacity": 1 - value["Fill/transparency"] / 100}


def _categories(payload, graph):
    result = []
    for path, node in payload["inventory"].items():
        value = node["settings"]
        if not path.startswith(graph + "/") or node["type"] != "xy" or not value["labels"]:
            continue
        labels = value["labels"]
        labels = payload["datasets"][labels]["data"] if labels in payload["datasets"] else [labels]
        positions = _array(payload, value["xData"])
        assert len(labels) == len(positions)
        result.extend({"position": position, "label": label} for position, label in zip(positions, labels, strict=True))
    return sorted(result, key=lambda item: item["position"])


def mechanical_projection(roles, ir=None):
    """Return a projector for the four declared mean ± sample-SD groups."""
    if ir is None:
        graph, axes = roles["graph"], roles["axes"]
    else:
        view = ir["views"][0]
        graph = graph_path(view["id"])
        scales = {scale["id"]: scale for scale in ir["scales"]}
        axes = {scales[axis["scale_id"]]["dimension"]: graph + "/" + native_name("axis", axis["id"])
                for axis in view["axes"]}

    def project(payload):
        result = project_xy_snapshot(payload, {"graph": graph, "axes": axes, "series": []})
        assert not result["legends"], "This accepted mechanical profile has no legend"
        visible_points = 0
        for node in payload["inventory"].values():
            value = node["settings"]
            if node["type"] == "xy" and not value["hide"]:
                assert value["PlotLine/hide"], "An undeclared XY line became visible"
                if value["marker"] != "none" and (not value["MarkerLine/hide"] or not value["MarkerFill/hide"]):
                    visible_points += len(_finite(_array(payload, value["xData"])))
        assert visible_points == 0, "Raw replicates are retained but not drawn in this accepted profile"
        result.update(category_labels=_categories(payload, graph), individual_point_count=visible_points, groups=[])
        if ir is None:
            fills = _legacy_fill(payload, roles["categorical_bar"])
            assert len(fills) == len(roles["groups"]) == 4
            for declaration, fill in zip(roles["groups"], fills, strict=True):
                index = declaration["index_one_based"]
                outlines = [declaration["outline_prefix"] + str(i) for i in (1, 2, 3)]
                errors = [declaration["error_prefix"] + str(i) for i in (1, 3, 2)]
                raw = payload["datasets"][f"category_y_{index}"]["data"]
                mean = _finite(payload["datasets"][f"category_bar_mean_{index}"]["data"])
                assert len(mean) == 1
                position = payload["datasets"]["category_bar_positions"]["data"][index - 1]
                stem = payload["inventory"][errors[0]]["settings"]
                low, high = stem["yPos"][0], stem["yPos2"][0]
                result["groups"].append(_group(payload, declaration["id"], position, mean[0], low, high, raw, fill, outlines, errors))
        else:
            layers = {layer["id"]: layer for layer in ir["views"][0]["layers"]}
            for layer_id in roles["layer_ids"]:
                layer = layers[layer_id]
                marks = {mark["type"]: mark for mark in layer["marks"]}
                assert set(marks) == {"bar", "errorbar"}
                bar = mark_path(view["id"], layer_id, marks["bar"]["id"])
                error = mark_path(view["id"], layer_id, marks["errorbar"]["id"])
                outlines, errors = [bar, bar + "_1", bar + "_2"], [error, error + "_1", error + "_2"]
                native_data = {column: payload["datasets"][dataset_name(layer["dataset_id"], column)]["data"]
                               for column in {*layer["mappings"].values(), "column:4"}}
                channels = {channel: _finite(native_data[column]) for channel, column in layer["mappings"].items()}
                assert all(len(values) == 1 for values in channels.values())
                raw = native_data["column:4"]
                result["groups"].append(_group(payload, layer["label"], channels["x"][0], channels["y"][0],
                    channels["y_low"][0], channels["y_high"][0], raw, _polygon_fill(payload, bar + "_3"), outlines, errors))
        assert len([p for p in payload["painted_primitives"] if p["kind"] == "line"]) == 24
        assert len(result["category_labels"]) == len(result["groups"]) == 4
        return result

    return project


def _group(payload, identifier, position, mean, low, high, raw, fill, outlines, errors):
    assert len(raw) == 5 and len(_finite(raw)) == 5
    return {"id": identifier, "position": position, "mean": mean, "low": low, "high": high,
            "raw_replicate_count": len(raw), "raw_replicate_values": raw, "fill": fill,
            "outline": {name: _line(payload, path) for name, path in zip(("left", "right", "top"), outlines, strict=True)},
            "error": {name: _line(payload, path) for name, path in zip(("stem", "lower_cap", "upper_cap"), errors, strict=True)}}
