"""Project-local graph invalidation and explicit managed artifact authority."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_document import build_keys, invalidated_nodes
from sciplot_core.plot_transforms import builtin_files

from .backend import PlotBackend
from .errors import EngineError
from .external_mutation import authority_status
from .managed_source_revision import source_descriptor, source_value


def describe_managed(root: Path, head: dict[str, Any], result: dict[str, Any], backend: PlotBackend, *,
                     description: dict[str, Any] | None = None) -> dict[str, Any]:
    document, binding = head["document"], head["binding"]
    from sciplot_core.project_lifecycle.context import capability_profile
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
            from .managed_source_append import append_descriptor, append_targets

            result["figure_edit_contract"] = patch_capabilities(spec)
            for target in append_targets(document, root=root):
                result["figure_edit_contract"][target]["source.append"] = append_descriptor()
            result.update(figure_spec=figure_spec(document), figure_template_schema=template_schema(),
                          backend_capabilities=capability_profile(), plot_ir_version=2)
        else:
            result["plot_ir_version"] = 2
    source_targets = ["source:" + source["source_id"] for source in document["scientific"]["data_sources"]]
    if description is None:
        contract = result.setdefault("figure_edit_contract" if spec is not None else "object_edit_contract", {})
        for target in source_targets:
            contract.setdefault(target, {})["source.sha256"] = source_descriptor(document, target, root=root)
    changed = set(result["changed_inputs"])
    canonical_changed = {str(Path(path).resolve()) for path in changed}
    graph = binding["graph"]
    dirty = ["source:" + item["source_id"] for item in document["scientific"]["data_sources"]
             if str(Path(item["path"]).resolve()) in canonical_changed]
    registry = document["scientific"]["provenance"]["managed"].get("executors", {})
    builtin_targets = []
    for node in document["scientific"]["transforms"]:
        executor = registry.get(node["executor"].get("id"))
        if executor and {executor["script"], executor["executable"]} & changed:
            dirty.append("transform:" + node["id"])
        if node["executor"]["kind"] == "builtin":
            try:
                implementation = builtin_files(node["kind"], node["executor"])
            except ValueError:
                implementation = {}
                builtin_targets.append("transform:" + node["id"])
            if canonical_changed & {str(Path(path).resolve()) for path in implementation}:
                builtin_targets.append("transform:" + node["id"])
    dirty.extend(builtin_targets)
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
        result["next_step"] = {"action": "restore_builtin_executor" if builtin_targets else "refresh_scientific_binding",
                               "requires_intent_class": "scientific"}
        if builtin_targets:
            result["next_step"].update({"targets": builtin_targets, "automatic_refresh": False})
        elif any(target in dirty for target in source_targets):
            result["next_step"].update(action="plot.describe", description_scope="edit",
                                       property="source.sha256", targets=[target for target in source_targets if target in dirty],
                                       plot=str(root), description={"scope": "edit", "property": "source.sha256",
                                           "target": next(target for target in source_targets if target in dirty)})
    if description is not None:
        return _scoped_description(result, document, binding, spec, description, root=root)
    return result


def _scoped_description(result: dict[str, Any], document: dict[str, Any], binding: dict[str, Any], spec: dict[str, Any] | None,
                        description: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Project only advertised edit state; keep every safety and currentness guard."""
    kept = ("kind", "version", "status", "plot_type", "plot", "plot_id", "revision",
            "scientific_hash", "presentation_hash", "revision_token", "coverage", "authority", "changed_inputs",
            "pending", "ir_hash", "artifact", "artifact_status", "plot_ir_version",
            "next_step", "recovery", "external_mutation", "external_mutation_unavailable", "export_current")
    compact = {key: result[key] for key in kept if key in result}
    if spec is not None and "domain_semantics" in spec:
        compact["domain_semantics"] = spec["domain_semantics"]
    compact["dependencies"] = {"invalidated": result["dependencies"]["invalidated"]}
    objects = document["presentation"]["objects"]
    if spec is not None:
        from .figure_updates import figure_property_names
        from .managed_source_append import append_targets

        property_names = figure_property_names(spec)
        for target in append_targets(document, root=root):
            property_names[target].append("source.append")
    else:
        property_names = {target: list(obj["capabilities"]) for target, obj in objects.items()}
    source_labels = {"source:" + source["source_id"]: source["source_id"] for source in document["scientific"]["data_sources"]}
    for target in source_labels:
        property_names.setdefault(target, []).append("source.sha256")
    compact["description_scope"] = description["scope"]
    if description["scope"] == "summary":
        from .managed_rebuild_explanation import explain_rebuild

        compact["rebuild_explanation"] = explain_rebuild(result, document, binding)
        compact["edit_targets"] = {target: {"kind": objects[target]["kind"] if target in objects else "source",
                                            "label": objects[target]["label"] if target in objects else source_labels[target],
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
    if property_name == "source.sha256":
        descriptor = source_descriptor(document, target, root=root)
        compact["current_value"] = source_value(document, target, root=root)
        compact["target_context"] = {"sources": [{key: source[key] for key in ("source_id", "path", "sha256", "table_selection")}
            for source in document["scientific"]["data_sources"] if source["source_id"] in compact["current_value"]["bindings"]]}
        compact["figure_edit_contract" if spec is not None else "object_edit_contract"] = {target: {property_name: descriptor}}
        risk = descriptor["risk"]
    elif spec is not None:
        from .figure_updates import current_edit_value, figure_edit_descriptor

        if property_name == "source.append":
            from .managed_source_append import append_descriptor, append_targets

            descriptor = append_descriptor()
            compact["target_context"] = append_targets(document, root=root)[target]
            compact["current_value"] = None
        else:
            descriptor = figure_edit_descriptor(spec, target, property_name)
            compact["current_value"] = current_edit_value(spec, target, property_name)
        compact["figure_edit_contract"] = {target: {property_name: descriptor}}
        if property_name == "scale.domain":
            scale = next(scale for scale in spec["scales"] if scale["id"] == target)
            compact["target_context"] = {key: scale[key] for key in
                                         ("dimension", "quantity", "unit", "transform", "direction")}
            if "domain_semantics" in spec:
                compact["target_context"]["domain"] = scale["domain"]
        elif property_name in {"axis.ticks", "axis.label"}:
            axis = next(axis for view in spec["views"] for axis in view["axes"] if axis["id"] == target)
            scale = next(scale for scale in spec["scales"] if scale["id"] == axis["scale_id"])
            compact["target_context"] = {"scale_id": scale["id"], **{key: scale[key] for key in
                                         ("dimension", "quantity", "unit", "transform", "direction", "domain")}}
            if property_name == "axis.ticks" and "domain_semantics" in spec:
                compact["target_context"]["ticks"] = axis["ticks"]
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
    source_refresh = (property_name == "source.sha256" and compact["pending"] is None
                      and compact.get("next_step", {}).get("action") == "plot.describe"
                      and compact["next_step"].get("property") == property_name
                      and target in compact["next_step"].get("targets", []))
    if source_refresh or ("next_step" not in compact and result["status"] == "current" and compact["pending"] is None):
        compact["next_step"] = {"action": "plot.patch", "plot": result["plot"], "plot_id": result["plot_id"],
                                "base_revision": result["revision"], "intent_class": risk,
                                "target": target, "property": property_name,
                                "requires": ["authorized_value", "idempotency_key"]}
    return compact
