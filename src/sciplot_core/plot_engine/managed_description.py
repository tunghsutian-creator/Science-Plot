"""Project-local graph invalidation and explicit managed artifact authority."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_document import build_keys, invalidated_nodes

from .backend import PlotBackend
from .errors import EngineError
from .external_mutation import authority_status


def describe_managed(root: Path, head: dict[str, Any], result: dict[str, Any], backend: PlotBackend, *,
                     description: dict[str, Any] | None = None) -> dict[str, Any]:
    document, binding = head["document"], head["binding"]
    from sciplot_core.plot_backends.figure_plan import capability_profile
    from sciplot_core.plot_ir.figure_document import (
        figure_spec,
        is_figure,
        template_schema,
    )

    spec = None
    if is_figure(document):
        spec = figure_spec(document)
        if description is None:
            from .figure_updates import patch_capabilities

            result["figure_edit_contract"] = patch_capabilities(spec)
            result.update(figure_spec=figure_spec(document), figure_template_schema=template_schema(),
                          backend_capabilities=capability_profile(), plot_ir_version=2)
        else:
            result["plot_ir_version"] = 2
    changed = set(result["changed_inputs"])
    graph = binding["graph"]
    dirty = ["source:" + item["source_id"] for item in document["scientific"]["data_sources"] if item["path"] in changed]
    registry = document["scientific"]["provenance"]["managed"].get("executors", {})
    source_paths = {item["path"] for item in document["scientific"]["data_sources"]}
    external_paths = {executor[field] for executor in registry.values() for field in ("script", "executable")}
    builtin_changes = changed & (set(binding["fingerprint"]["files"]) - source_paths - external_paths)
    for node in document["scientific"]["transforms"]:
        executor = registry.get(node["executor"].get("id"))
        if executor and {executor["script"], executor["executable"]} & changed:
            dirty.append("transform:" + node["id"])
        if node["executor"]["kind"] == "builtin" and builtin_changes:
            dirty.append("transform:" + node["id"])
    native = Path(binding["document"])
    if str(native) in changed or not native.is_file():
        dirty.append("render")
    dependencies = {"nodes": graph["nodes"]} if description is None else {}
    if description is None:
        dependencies["build_keys"] = build_keys(graph)
    dependencies["invalidated"] = invalidated_nodes(graph, list(dict.fromkeys(dirty)))
    result.update({"authority": authority_status("ManagedPlot"), "ir_hash": binding["ir_hash"],
        "ir": binding["ir_path"], "artifact": str(native),
        "artifact_status": "missing" if not native.exists() else "changed" if str(native) in changed else "current",
        "dependencies": dependencies})
    if str(native) in changed:
        if description is not None and description["scope"] == "summary":
            # A compact rebuild read must not launch the native inspector merely
            # to explain why the current artifact is stale. Explicit resolution
            # still uses the existing review flow and complete-state audit.
            result["external_mutation_unavailable"] = {
                "reason_code": "native_inspection_deferred",
                "message": "Read-only summary did not inspect the changed native artifact."}
        else:
            from .managed_external import inspect_managed_mutation

            owner = getattr(backend, "managed", None)
            if owner is not None and not changed - {str(native)}:
                try:
                    result["external_mutation"] = inspect_managed_mutation(root, binding, owner.compiler)
                except ValueError as exc:
                    result["external_mutation_unavailable"] = {"reason_code": getattr(exc, "reason_code", "native_inspection_failed"),
                                                              "message": str(exc)[:240]}
        result["next_step"] = {"action": "resolve_external_mutation", "automatic_adoption": False}
    elif not native.is_file() and not changed:
        result["status"] = "dirty"
        result["next_step"] = {"action": "plot.export", "plot": str(root), "reason": "rebuild_disposable_artifacts"}
    elif dirty:
        result["next_step"] = {"action": "refresh_builtin_executor" if builtin_changes else "refresh_scientific_binding",
                               "requires_intent_class": "scientific"}
        if builtin_changes:
            from sciplot_core.plot_transforms import builtin_executor

            result["next_step"].update({"property": "transform.executor", "targets": [
                "transform:" + node["id"] for node in document["scientific"]["transforms"] if node["executor"]["kind"] == "builtin"]})
            try:
                result["next_step"]["value"] = builtin_executor()
            except OSError:
                result["next_step"].update({"action": "restore_builtin_executor", "implementation_available": False})
    if description is not None:
        return _scoped_description(result, document, binding, spec, description)
    return result


def _scoped_description(result: dict[str, Any], document: dict[str, Any], binding: dict[str, Any], spec: dict[str, Any] | None,
                        description: dict[str, Any]) -> dict[str, Any]:
    """Project only advertised edit state; keep every safety and currentness guard."""
    kept = ("kind", "version", "status", "plot_type", "plot", "plot_id", "revision",
            "scientific_hash", "presentation_hash", "coverage", "authority", "changed_inputs",
            "pending", "ir_hash", "artifact", "artifact_status", "plot_ir_version",
            "next_step", "recovery", "external_mutation", "external_mutation_unavailable")
    compact = {key: result[key] for key in kept if key in result}
    compact["dependencies"] = {"invalidated": result["dependencies"]["invalidated"]}
    objects = document["presentation"]["objects"]
    if spec is not None:
        from .figure_updates import figure_property_names

        property_names = figure_property_names(spec)
    else:
        property_names = {target: list(obj["capabilities"]) for target, obj in objects.items()}
    compact["description_scope"] = description["scope"]
    if description["scope"] == "summary":
        from .managed_rebuild_explanation import explain_rebuild

        compact["rebuild_explanation"] = explain_rebuild(result, document, binding)
        compact["edit_targets"] = {target: {"kind": objects[target]["kind"], "label": objects[target]["label"],
                                            "properties": properties} for target, properties in property_names.items()}
        if "next_step" not in compact and result["status"] == "current" and compact["pending"] is None and property_names:
            compact["next_step"] = {"action": "plot.describe", "plot": result["plot"],
                                    "description_scope": "edit", "choose_from": "edit_targets",
                                    "requires": ["target", "property"]}
        return compact

    target, property_name = description["target"], description["property"]
    if target not in property_names:
        raise EngineError("description_unknown_target", "Choose an exact stable target ID from a current summary.",
                          action="plot.describe", available_targets=list(property_names))
    if property_name not in property_names[target]:
        raise EngineError("description_unknown_property", "Choose a property advertised for this target in the current summary.",
                          action="plot.describe", target=target, available_properties=property_names[target])
    compact["edit_target"] = target
    compact["edit_property"] = property_name
    if spec is not None:
        from .figure_updates import current_edit_value, figure_edit_descriptor

        descriptor = figure_edit_descriptor(spec, target, property_name)
        compact["figure_edit_contract"] = {target: {property_name: descriptor}}
        compact["current_value"] = current_edit_value(spec, target, property_name)
        if property_name == "scale.domain":
            scale = next(scale for scale in spec["scales"] if scale["id"] == target)
            compact["target_context"] = {key: scale[key] for key in
                                         ("dimension", "quantity", "unit", "transform", "direction")}
        elif property_name in {"axis.ticks", "axis.label"}:
            axis = next(axis for view in spec["views"] for axis in view["axes"] if axis["id"] == target)
            scale = next(scale for scale in spec["scales"] if scale["id"] == axis["scale_id"])
            compact["target_context"] = {"scale_id": scale["id"], **{key: scale[key] for key in
                                         ("dimension", "quantity", "unit", "transform", "direction", "domain")}}
        elif property_name == "legend.location":
            guide = next(item for item in spec["guides"] if item["id"] == target)
            compact["target_context"] = {key: guide[key] for key in ("scope", "view_id") if key in guide}
        elif property_name in {"annotation.text", "annotation.x", "annotation.y"}:
            annotation = next(item for item in spec["annotations"] if item["id"] == target)
            compact["target_context"] = {key: annotation[key] for key in
                                         ("space", "view_id", "x_scale", "y_scale", "x", "y") if key in annotation}
        risk = descriptor["risk"]
    else:
        obj = objects[target]
        descriptor = obj["capabilities"][property_name]
        compact["object_edit_contract"] = {target: {property_name: descriptor}}
        compact["current_value"] = obj["properties"][property_name]
        risk = descriptor["risk"]
    if "next_step" not in compact and result["status"] == "current" and compact["pending"] is None:
        compact["next_step"] = {"action": "plot.patch", "plot": result["plot"], "plot_id": result["plot_id"],
                                "base_revision": result["revision"], "intent_class": risk,
                                "target": target, "property": property_name,
                                "requires": ["authorized_value", "idempotency_key"]}
    return compact
