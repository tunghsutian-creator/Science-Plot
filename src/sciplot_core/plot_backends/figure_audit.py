"""Exact source-array, scale binding and mark-geometry native evidence for IR v2."""

import math
from typing import Any

from sciplot_core.plot_backends.native_primitives import native_datasets, native_name
from sciplot_core.plot_backends.figure_marks import graph_path, scale_name, mark_path, mark_geometry
from sciplot_core.veusz_worker.numeric_evidence import _dataset_evidence


def _same(actual: Any, expected: Any) -> bool:
    if hasattr(actual, "tolist"):
        actual = actual.tolist()
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_same(a, b) for a, b in zip(actual, expected, strict=True))
    if isinstance(expected, float) and math.isnan(expected):
        return isinstance(actual, float) and math.isnan(actual)
    return bool(actual == expected)


def scientific_audit(ir: dict[str, Any], loaded: Any) -> dict[str, Any]:
    from sciplot_core.foundation.json_hashing import canonical_json_sha256 as content_hash

    loaded._sciplot_exact_1d = True
    arrays = native_datasets(ir)
    if set(loaded.data) != set(arrays):
        raise ValueError("Managed Figure has undeclared or missing native datasets.")
    for dataset in loaded.data.values():
        if (type(dataset).__module__, type(dataset).__name__) != ("veusz.datasets.oned", "Dataset") or getattr(dataset, "linked", None) is not None:
            raise ValueError("Managed Figure datasets must be plain numeric arrays without native expressions or links.")
        if any(getattr(dataset, field, None) is not None for field in ("serr", "nerr", "perr")):
            raise ValueError("Managed Figure native datasets must not contain hidden uncertainty channels.")
    dataset_evidence = [_dataset_evidence(loaded, dataset_name=name, expected_values=values, dimensions=1)
                        for name, values in arrays.items()]
    scale_records = {item["id"]: item for item in ir["scales"]}
    layers = []
    for view in ir["views"]:
        graph = loaded.resolveWidgetPath(None, graph_path(view["id"]))
        for scale_id in {layer[dimension + "_scale"] for layer in view["layers"] for dimension in ("x", "y")}:
            scale = scale_records[scale_id]
            axis = graph.getChild(scale_name(scale_id))
            domain = list(scale["domain"])
            if scale["direction"] == "descending":
                domain.reverse()
            expected_axis = {"min": domain[0], "max": domain[1], "log": scale["transform"] == "log",
                             "direction": "horizontal" if scale["dimension"] == "x" else "vertical"}
            if axis is None or any(not _same(axis.settings.get(key).get(), value) for key, value in expected_axis.items()):
                raise ValueError(f"Managed Figure scale {scale_id} has changed native mapping.")
        for layer in view["layers"]:
            marks = []
            for mark in layer["marks"]:
                base_path = mark_path(view["id"], layer["id"], mark["id"])
                base_name = native_name("mark", layer["id"] + "/" + mark["id"])
                geometry = mark_geometry(ir, view, layer, mark)
                actual_nodes = [child for child in graph.children if child.name == base_name or child.name.startswith(base_name + "_")]
                if len(actual_nodes) != len(geometry):
                    raise ValueError(f"Managed Figure mark {mark['id']} changed its scientific primitive count.")
                for index, expected_geometry in enumerate(geometry):
                    widget = loaded.resolveWidgetPath(None, base_path if index == 0 else f"{base_path}_{index}")
                    for key, value in {"xAxis": scale_name(layer["x_scale"]), "yAxis": scale_name(layer["y_scale"]), **expected_geometry}.items():
                        if not _same(widget.settings.get(key).get(), value):
                            raise ValueError(f"Managed Figure mark {mark['id']} changed scientific geometry channel {key}.")
                marks.append({"id": mark["id"], "type": mark["type"], "native_primitive_count": len(geometry),
                              "geometry_hash": content_hash(geometry), "geometry_checked": True})
            mappings = {channel: {"column_id": column, "values_hash": content_hash(ir["datasets"][layer["dataset_id"]]["columns"][column]["values"])}
                        for channel, column in layer["mappings"].items()}
            layers.append({"id": layer["id"], "view_id": view["id"], "dataset_id": layer["dataset_id"],
                           "x_scale": layer["x_scale"], "y_scale": layer["y_scale"], "mappings": mappings,
                           "marks": marks})
    return {"kind": "sciplot_managed_native_audit", "status": "passed", "schema_version": 2,
            "scientific_hash": ir["scientific_hash"], "ir_hash": ir["ir_hash"],
            "datasets": dataset_evidence, "layers": layers, "scales": list(scale_records.values()),
            "view_ids": [view["id"] for view in ir["views"]]}
