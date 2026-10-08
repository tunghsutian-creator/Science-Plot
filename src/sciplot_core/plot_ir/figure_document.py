"""Figure grammar projections on the existing authoritative document lifecycle."""

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document import seal_document, validate_binding
from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.schema import IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.rendering_contract import contract_binding
from sciplot_core.plot_grammar import figure_spec_schema, merge_figure_spec, split_figure_spec, validate_figure_spec


def template_schema() -> dict[str, Any]:
    return closed({"kind": {"const": "sciplot_figure_template"}, "schema_version": {"const": 2},
                   "template_id": IDENTIFIER, "figure_spec": figure_spec_schema()})


def theme_schema() -> dict[str, Any]:
    return dict(figure_spec_schema()["properties"]["theme"])


def is_figure(document: dict[str, Any]) -> bool:
    return "figure_spec" in document["scientific"]["provenance"]


def figure_spec(document: dict[str, Any]) -> dict[str, Any]:
    return merge_figure_spec(document["scientific"]["provenance"]["figure_spec"],
                             document["presentation"]["layout"]["figure_spec"])


def object_index(spec: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    def add(item: dict[str, Any], kind: str) -> None:
        result[item["id"]] = {"kind": kind, "label": item.get("label", item.get("text", item["id"])),
                              "properties": {}, "capabilities": {}}

    add(spec, "figure")
    for scale in spec["scales"]:
        add(scale, "scale")
    for view in spec["views"]:
        add(view, "view")
        for axis in view["axes"]:
            add(axis, "axis")
        for layer in view["layers"]:
            add(layer, "layer")
            for mark in layer["marks"]:
                add(mark, "mark")
    for guide in spec["guides"]:
        add(guide, "legend")
    for annotation in spec["annotations"]:
        add(annotation, "annotation")
    return result


def store_spec(document: dict[str, Any], spec: Any) -> dict[str, Any]:
    spec = validate_figure_spec(spec)
    result = deepcopy(document)
    science, presentation = split_figure_spec(spec)
    result["scientific"]["provenance"]["figure_spec"] = science
    result["presentation"]["layout"] = {"figure_spec": presentation}
    result["presentation"]["theme"] = {}
    result["presentation"]["objects"] = object_index(spec)
    return seal_document(result)


def validate_figure_document(document: dict[str, Any]) -> dict[str, Any]:
    spec = figure_spec(document)
    if (document["presentation"]["objects"] != object_index(spec)
            or set(document["presentation"]["layout"]) != {"figure_spec"} or document["presentation"]["theme"]):
        fail("figure_unrepresented_state", "All figure presentation state must be represented in FigureSpec.",
             "/presentation", "complete_coverage")
    layers = {layer["id"]: layer for view in spec["views"] for layer in view["layers"]}
    mappings = document["scientific"]["mappings"]
    if set(layers) != set(mappings):
        fail("figure_binding_membership", "Bind each semantic layer exactly once.", "/scientific/mappings", "exact_membership")
    scales = {scale["id"]: scale for scale in spec["scales"]}
    for name, layer in layers.items():
        mapping = mappings[name]
        for axis in ("x", "y"):
            ref = mapping[axis]
            column = "column:" + str(ref["column_index"]) if "column_index" in ref else ref["column"]
            if (ref["source_id"] != layer["dataset_id"] or column != layer["mappings"][axis]
                    or mapping[axis + "_unit"] != scales[layer[axis + "_scale"]]["unit"]):
                fail("figure_binding_mismatch", "Figure layers must preserve explicit Binding dataset, column and unit identities.",
                     "/scientific/mappings", "exact_binding", target=name)
    return spec


def create_figure_document(template: Any, binding: Any, *, plot_id: str, theme: Any = None) -> dict[str, Any]:
    validate_wire(template, template_schema(), code="figure_template_invalid")
    binding = validate_binding(binding)
    if template["template_id"] != binding["template_id"]:
        fail("figure_template_binding", "Binding must name this FigureTemplate.", "/template_id", "template_identity")
    document: dict[str, Any] = {"kind": "sciplot_document", "schema_version": 1, "plot_id": plot_id,
        "revision": 0, "plot_type": "ManagedPlot", "coverage": {"mode": "managed", "limitations": []},
        "scientific": {key: deepcopy(binding[key]) for key in ("data_sources", "transforms", "guards")},
        "presentation": {"objects": {}, "layout": {}, "theme": {}, "export_configuration": {"formats": ["pdf", "tiff_300"]}}}
    document["scientific"].update(mappings={slot["series_id"]: slot for slot in binding["slots"].values()},
        provenance={"managed": {"kind": "managed_scientific_model", "schema_version": 1,
                    "template_id": template["template_id"], "executors": {}}, "binding": deepcopy(binding["provenance"])})
    spec = deepcopy(template["figure_spec"])
    spec.setdefault("rendering_contract", contract_binding())
    if spec["composition"]["kind"] != "single":
        spec.setdefault("composition_policy", contract_binding("sciplot-figure-composition-v1"))
    if theme is not None:
        validate_wire(theme, theme_schema(), code="figure_theme_invalid")
        spec["theme"] = deepcopy(theme)
    result = store_spec(document, spec)
    validate_figure_document(result)
    return result


def apply_figure_theme(document: dict[str, Any], theme: Any) -> dict[str, Any]:
    validate_wire(theme, theme_schema(), code="figure_theme_invalid")
    spec = figure_spec(document)
    spec["theme"] = deepcopy(theme)
    return store_spec(document, spec)
