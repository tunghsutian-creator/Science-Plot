"""Project-local graph invalidation and explicit managed artifact authority."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_document import build_keys, invalidated_nodes

from .backend import PlotBackend
from .external_mutation import authority_status


def describe_managed(root: Path, head: dict[str, Any], result: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    document, binding = head["document"], head["binding"]
    from sciplot_core.plot_ir.figure_document import is_figure, figure_spec, template_schema
    from sciplot_core.plot_backends.figure_plan import capability_profile

    if is_figure(document):
        from .figure_updates import patch_capabilities

        result["figure_edit_contract"] = patch_capabilities(figure_spec(document))
        result.update(figure_spec=figure_spec(document), figure_template_schema=template_schema(),
                      backend_capabilities=capability_profile(), plot_ir_version=2)
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
    result.update({"authority": authority_status("ManagedPlot"), "ir_hash": binding["ir_hash"],
        "ir": binding["ir_path"], "artifact": str(native),
        "artifact_status": "missing" if not native.exists() else "changed" if str(native) in changed else "current",
        "dependencies": {"nodes": graph["nodes"], "build_keys": build_keys(graph),
                         "invalidated": invalidated_nodes(graph, list(dict.fromkeys(dirty)))}})
    if str(native) in changed:
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
    return result
