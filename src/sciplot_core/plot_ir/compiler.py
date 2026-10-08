"""Pure semantic resolution; no native backend, source reader or file access."""

from copy import deepcopy
import re
from typing import Any

from sciplot_core.plot_document.errors import fail
from sciplot_core.style_values import normalize_physical_size

from .managed import validate_managed
from .schema import seal_ir


def _points(value: str) -> float:
    normalized = normalize_physical_size(value)
    match = re.fullmatch(r"([0-9.]+)(pt|mm|cm|in|inch)", normalized)
    assert match is not None
    return float(match[1]) * {"pt": 1, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72, "inch": 72}[match[2]]


def _color(value: str) -> str:
    colors = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "blue": "#0000ff",
              "green": "#008000", "gray": "#808080", "grey": "#808080", "yellow": "#ffff00"}
    result = colors.get(value.casefold(), value)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", result):
        fail("managed_color_unresolved", "Use an explicit hexadecimal color in the managed theme.", "/presentation/objects", "resolved_color")
    return result.lower()


def _properties(objects: dict[str, Any], identifier: str, kind: str) -> dict[str, Any]:
    obj = objects.get(identifier)
    if obj is None or obj["kind"] != kind:
        fail("managed_object_missing", "Every resolved object must have a corresponding stable semantic identity.", "/presentation/objects", "object_identity", target=identifier)
    allowed = {"series": {"style.line.width", "style.line.color"}, "axis": {"font.size", "axis.limits"},
               "legend": {"font.size", "legend.visible", "legend.position"},
               "title": {"font.size", "title.visible", "title.text"},
               "annotation": {"font.size", "annotation.visible", "annotation.text", "annotation.position"}}[kind]
    if set(obj["properties"]) - allowed:
        fail("managed_property_uncompiled", "A property has no managed semantic lowering.", "/presentation/objects", "supported_property", target=identifier)
    return dict(obj["properties"])


def compile_document(document: Any, datasets: dict[str, dict[str, Any]] | None = None,
                     *, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    document = validate_managed(document)
    if datasets is None:
        datasets = document["scientific"]["provenance"].get("datasets")
    if not isinstance(datasets, dict) or not datasets or "kind" in datasets:
        fail("managed_datasets_unresolved", "Resolve the sealed scientific dataset payload before compilation.", "/scientific/provenance/datasets", "resolved_datasets")
    expected_ids = {source["source_id"] for source in document["scientific"]["data_sources"]}
    expected_ids.update(node["output"] for node in document["scientific"]["transforms"])
    if set(datasets) != expected_ids:
        fail("managed_dataset_membership", "Resolved datasets must equal the declared source and transform outputs.", "/datasets", "exact_membership")
    stored = document["scientific"]["provenance"].get("datasets")
    if isinstance(stored, dict) and "kind" not in stored and stored != datasets:
        fail("managed_dataset_identity", "Supplied data differs from the canonical scientific payload.", "/datasets", "canonical_data")
    from .figure_document import is_figure, validate_figure_document

    if is_figure(document):
        from sciplot_core.plot_grammar import compile_figure

        return compile_figure(validate_figure_document(document), datasets, scientific_hash=document["scientific_hash"],
                              presentation_hash=document["presentation_hash"], capabilities=capabilities)
    presentation = document["presentation"]
    layout, objects = deepcopy(presentation["layout"]), presentation["objects"]
    series = []
    for identifier, mapping in document["scientific"]["mappings"].items():
        if mapping["x"]["source_id"] != mapping["y"]["source_id"]:
            fail("managed_cross_dataset_pair", "Each XY pair must bind one explicit dataset row region.", "/scientific/mappings", "paired_dataset")
        dataset_id = mapping["x"]["source_id"]
        dataset = datasets.get(dataset_id)
        if dataset is None:
            fail("managed_dataset_missing", "A scientific mapping references an unresolved dataset.", "/scientific/mappings", "dataset_reference")
        coordinate = {}
        for axis in ("x", "y"):
            ref = mapping[axis]
            column_id = "column:" + str(ref["column_index"]) if "column_index" in ref else ref["column"]
            column = dataset["columns"].get(column_id)
            if (column is None or column["unit"] != mapping[axis + "_unit"]
                    or "column_index" in ref and column["label"] != ref["column"]):
                fail("managed_column_binding", "A mapping must use its explicit dataset column and unchanged unit.", "/scientific/mappings", "column_identity")
            coordinate[axis + "_column"], coordinate[axis] = column_id, deepcopy(column["values"])
        if identifier not in layout["series_styles"]:
            fail("managed_style_missing", "Every series requires a fully resolved template style.", "/presentation/layout/series_styles", "complete_style")
        style = layout["series_styles"][identifier]
        props = _properties(objects, identifier, "series")
        for prop, value in props.items():
            if prop == "style.line.width":
                style["line_width_pt"] = _points(value)
            elif prop == "style.line.color":
                style["line_color"] = _color(value)
            else:
                fail("managed_property_uncompiled", "This advertised series property has no semantic lowering.", "/presentation/objects", "supported_property", property=prop)
        series.append({"id": identifier, "label": objects[identifier]["label"], "dataset_id": dataset_id, **coordinate, "style": style})
    claimed = {item["id"] for item in series}
    for axis in layout["axes"].values():
        props = _properties(objects, axis["id"], "axis")
        claimed.add(axis["id"])
        if "axis.limits" in props:
            axis["limits"] = props["axis.limits"]
        if "font.size" in props:
            axis["font_size_pt"] = _points(props["font.size"])
    legend = layout["legend"]
    props = _properties(objects, legend["id"], "legend")
    claimed.add(legend["id"])
    if "legend.visible" in props:
        legend["visible"] = props["legend.visible"]
    if "legend.position" in props:
        if props["legend.position"] is None:
            fail("managed_legend_unresolved", "Managed placement requires explicit coordinates, never a native preset.", "/presentation/objects", "resolved_position")
        legend["position"] = props["legend.position"]
    if "font.size" in props:
        legend["font_size_pt"] = _points(props["font.size"])
    for annotation in layout["annotations"]:
        obj = objects.get(annotation["id"], {})
        kind = obj.get("kind")
        if kind not in {"annotation", "title"}:
            fail("managed_annotation_missing", "Every annotation requires an explicit title or annotation object.", "/presentation/objects", "object_identity")
        props = _properties(objects, annotation["id"], kind)
        if "annotation.position" in props:
            capability = obj["capabilities"]["annotation.position"]
            mode = capability.get("coordinate_mode", "relative")
            if (mode != annotation["coordinate_mode"] or mode == "axes" and
                    capability["units"] != {name: layout["axes"][name]["unit"] for name in ("x", "y")}):
                fail("managed_coordinate_frame", "Annotation placement cannot switch coordinate frame or units implicitly.", "/presentation/objects", "coordinate_frame")
        claimed.add(annotation["id"])
        for semantic, field in ((kind + ".visible", "visible"), (kind + ".text", "text"), ("annotation.position", "position")):
            if semantic in props:
                annotation[field] = props[semantic]
        if "font.size" in props:
            annotation["font_size_pt"] = _points(props["font.size"])
    if set(objects) != claimed:
        fail("managed_unrepresented_object", "Managed compilation cannot omit an unrepresented semantic object.", "/presentation/objects", "complete_coverage", unrepresented=sorted(set(objects) - claimed))
    return seal_ir({"kind": "sciplot_plot_ir", "schema_version": 1,
        "scientific_hash": document["scientific_hash"], "presentation_hash": document["presentation_hash"],
        "datasets": deepcopy(datasets), "series": series, "axes": layout["axes"], "dimensions": layout["dimensions"],
        "layout": {"margins_mm": layout["margins_mm"]}, "legend": legend, "annotations": layout["annotations"],
        "background_color": layout["background_color"]})


class SemanticCompiler:
    def compile(self, document: Any, datasets: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        return compile_document(document, datasets)
