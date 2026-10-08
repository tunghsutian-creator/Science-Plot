"""Managed authority reuses Template/Binding/Theme without legacy native state."""

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document import instantiate_template, seal_document, validate_binding, validate_document, validate_theme
from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.patch import apply_patch
from sciplot_core.plot_document.schema import IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_transforms.schema import ordered_nodes

from .schema import layout_schema


def validate_managed(document: Any) -> dict[str, Any]:
    result = validate_document(document)
    if result.get("plot_type") != "ManagedPlot" or result["coverage"] != {"mode": "managed", "limitations": []}:
        fail("managed_authority_required", "Compilation from zero requires complete explicit ManagedPlot authority.", "/plot_type", "managed_authority")
    marker = result["scientific"]["provenance"].get("managed")
    validate_wire(marker, closed({"kind": {"const": "managed_scientific_model"}, "schema_version": {"const": 1},
        "template_id": IDENTIFIER, "rule_id": IDENTIFIER, "executors": {"type": "object", "propertyNames": IDENTIFIER,
        "additionalProperties": {"type": "object"}}}, ["kind", "schema_version", "template_id", "executors"]), code="managed_model_invalid")
    scientific = result["scientific"]
    validate_binding({"kind": "sciplot_binding", "schema_version": 1, "template_id": marker["template_id"],
        "data_sources": scientific["data_sources"], "slots": scientific["mappings"], "transforms": scientific["transforms"],
        "guards": scientific["guards"], "provenance": {}})
    ordered_nodes(scientific["transforms"], [source["source_id"] for source in scientific["data_sources"]])
    if scientific["guards"]:
        fail("managed_guard_unsupported", "Custom scientific guards require an implemented executor.", "/scientific/guards", "supported_guards")
    validate_wire(result["presentation"]["export_configuration"], closed({"formats": {"const": ["pdf", "tiff_300"]}}),
                  code="managed_export_unsupported")
    needed = {mapping[axis]["source_id"] for mapping in scientific["mappings"].values() for axis in ("x", "y")}
    for node in reversed(ordered_nodes(scientific["transforms"], [source["source_id"] for source in scientific["data_sources"]])):
        if node["output"] not in needed:
            fail("managed_unused_transform", "Managed documents cannot retain unreferenced scientific transforms.", "/scientific/transforms", "used_dependency")
        needed.update(node["inputs"])
    unused = [source["source_id"] for source in scientific["data_sources"] if source["source_id"] not in needed]
    if unused:
        fail("managed_unused_source", "Only sources used by the plot's dependency graph may be bound.", "/scientific/data_sources", "used_dependency", unused=unused)
    if any("table_selection" not in source for source in scientific["data_sources"]):
        fail("managed_table_selection_required", "Managed sources require explicit original table regions.", "/scientific/data_sources", "explicit_region")
    from .figure_document import is_figure, validate_figure_document

    if is_figure(result):
        validate_figure_document(result)
    else:
        validate_wire(result["presentation"]["layout"], layout_schema(), code="managed_layout_invalid")
    return result


def create_managed_document(template: Any, binding: Any, *, plot_id: str, theme: Any = None) -> dict[str, Any]:
    from .figure_document import create_figure_document

    if isinstance(template, dict) and template.get("kind") == "sciplot_figure_template":
        return validate_managed(create_figure_document(template, binding, plot_id=plot_id, theme=theme))
    result = instantiate_template(template, binding, plot_id=plot_id)
    result["plot_type"] = "ManagedPlot"
    result["coverage"] = {"mode": "managed", "limitations": []}
    original_styles = result["presentation"]["layout"].get("series_styles", {})
    result["presentation"]["layout"]["series_styles"] = {
        binding["slots"][name]["series_id"] if name in binding["slots"] else name: style
        for name, style in original_styles.items()}
    result["scientific"]["provenance"] = {"managed": {"kind": "managed_scientific_model", "schema_version": 1,
        "template_id": template["template_id"], "executors": {}}, "binding": deepcopy(binding["provenance"])}
    result["presentation"]["theme"] = {"kind": "managed_theme", "schema_version": 1,
        "base_objects": deepcopy(result["presentation"]["objects"]), "definition": None}
    result = validate_managed(seal_document(result))
    return apply_theme(result, theme) if theme is not None else result


def apply_theme(document: Any, theme: Any) -> dict[str, Any]:
    from .figure_document import apply_figure_theme, is_figure

    result = validate_managed(document)
    if is_figure(result):
        return apply_figure_theme(result, theme)
    checked = validate_theme(theme)
    state = result["presentation"]["theme"]
    if state.get("kind") != "managed_theme" or "base_objects" not in state:
        fail("managed_theme_baseline_missing", "The canonical presentation must retain its explicit template theme baseline.", "/presentation/theme", "template_baseline")
    previous = state.get("definition") or {"rules": []}
    objects, base = result["presentation"]["objects"], state["base_objects"]
    for rule in [*previous["rules"], *checked["rules"]]:
        for name in rule["target"]:
            if name in base and rule["property"] in base[name]["properties"]:
                objects[name]["properties"][rule["property"]] = deepcopy(base[name]["properties"][rule["property"]])
    result = seal_document(result)
    if checked["rules"]:
        result, _, risk = apply_patch(result, {"plot_id": result["plot_id"], "base_revision": result["revision"],
            "idempotency_key": "managed-theme", "intent_class": "presentation",
            "changes": [{"op": "set", **rule} for rule in checked["rules"]]})
        if risk != "presentation":
            fail("managed_theme_scientific_change", "Themes may change only safe presentation properties.", "/rules", "presentation_only")
    result["presentation"]["theme"]["definition"] = checked
    return seal_document(result)
