"""Source-bound TTS suite lifecycle with exact native re-export."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from sciplot_core.project_commands import ProjectMutation
from sciplot_core.project_store import FileProjectStore

from sciplot_core.workflow.native_suite_runtime import current_store, delivery_path, literal_directory, literal_resource, native_path, native_runtime
from sciplot_core.workflow.rheology_tts_tables import write_json, write_methods, write_plot_tables


# Compatibility names forward to the sole leaf owners.
from sciplot_core.workflow.rheology_tts_saved_state import (
    _active_receipts as _active_receipts,
    _bound_sources as _bound_sources,
    _check_sources as _check_sources,
    _compiled_figures as _compiled_figures,
    _export_receipts as _export_receipts,
    _figure_folder as _figure_folder,
    _selected_documents as _selected_documents,
    _sha as _sha,
)
from sciplot_core.workflow.rheology_tts_delivery_files import (
    _launcher as _launcher,
    _output_paths as _output_paths,
    _publish as _publish,
    launcher_bytes as launcher_bytes,
)


@native_runtime(repair=True, role="analysis_request")
def create_suite(request_path: Path, *, resume: bool = False) -> dict[str, Any]:
    from sciplot_core.workflow.native_suite_creation import create_project
    request_path = request_path.expanduser().resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    from sciplot_core.workflow.rheology_tts_contract import validate_creation_request
    validate_creation_request(request)
    source = Path(request["frequency_source"]).expanduser().resolve()
    store = current_store()
    delivery, workspace = ((store.locations["delivery"], store.root) if store is not None else
        _output_paths(source, request.get("out", source.parent / "TTS_SciPlot")))
    from sciplot_core.project_store.runtime import literal_runtime_path
    request_file = {"path": literal_runtime_path(request_path), "sha256": _sha(request_path)}
    sources = _bound_sources(request)
    original = {"adapter": "analysis_native_suite", "request": request, "request_file": request_file,
                "binding": {"workspace": str(workspace), "delivery": str(delivery), "sources": sources}}
    if store is not None:
        matching = [item["metadata"]["request"] for item in store.commands()
                    if item.get("metadata", {}).get("request", {}).get("adapter") == "analysis_native_suite"
                    and item["metadata"]["request"].get("request_file") == request_file
                    and "continuation_of" not in item["metadata"]["request"]]
        if len(matching) != 1 or matching[0]["request"] != request or matching[0]["binding"]["sources"] != sources:
            raise ValueError("The analysis request/source binding differs from its original native command.")
        original = matching[0]
    return create_project(workspace, delivery, original,
        [*sources, {"path": request_file["path"], "sha256": request_file["sha256"]}],
        lambda candidate_workspace, candidate_delivery:
        _create_suite_candidate(request_path, output_paths=(candidate_delivery, candidate_workspace)), resume=resume,
        recover_prepare=lambda old_workspace, _old_delivery, new_workspace, new_delivery:
        _create_suite_candidate(request_path, output_paths=(new_delivery, new_workspace), known_workspace=old_workspace))


def _create_suite_candidate(request_path: Path, *, output_paths: tuple[Path, Path],
                            known_workspace: Path | None = None) -> dict[str, Any]:
    from sciplot_core.semantic_sources.rheology_tts import analyze_tts_request
    from sciplot_core.workflow.rheology_tts_figures import build_tts_figures
    from sciplot_core.rheology_tts_render import render_tts_figures

    request = json.loads(request_path.expanduser().resolve().read_text(encoding="utf-8"))
    from sciplot_core.workflow.rheology_tts_contract import validate_creation_request
    validate_creation_request(request)
    delivery, workspace = output_paths
    if delivery.exists() or workspace.exists():
        raise FileExistsError("Delivery or evidence workspace already exists; re-export the saved suite or select a new name.")
    sources = _bound_sources(request)
    if known_workspace is None:
        analysis = analyze_tts_request({k: v for k, v in request.items()
                                       if k not in {"out", "figure_layout", "expected_contract_sha256"}})
    else:
        if json.loads((known_workspace / "request.json").read_bytes()) != request:
            raise ValueError("The original analysis request changed; preserve its native effect.")
        analysis = json.loads((known_workspace / "analysis.json").read_bytes())
    _check_sources(sources)
    layout = request.get("figure_layout", "legacy")
    spec = build_tts_figures(analysis, layout=layout)
    spec["source_binding"] = {"sources": sources, "request": request}
    if known_workspace is not None and json.loads((known_workspace / "figure_plan.json").read_bytes()) != spec:
        raise ValueError("The original analysis/spec binding changed; native reanalysis is refused.")
    workspace.mkdir(parents=True)
    write_json(workspace / "request.json", request)
    write_json(workspace / "analysis.json", analysis)
    write_json(workspace / "figure_plan.json", spec)
    if known_workspace is None:
        native_result = render_tts_figures(spec, workspace / "initial_render")
    else:
        from sciplot_core.rheology_tts_spec import compile_tts_spec
        from sciplot_core.rheology_tts_render_creation import check_native_continuation
        from sciplot_core.workflow.native_suite_creation_projection import _remap
        from sciplot_core.workflow.native_suite_generation import candidate_file
        from sciplot_core.project_store.runtime import resolve_runtime_path, literal_runtime_path
        original = known_workspace / "initial_render"
        continued = check_native_continuation(compile_tts_spec(spec), original, completed=True)
        if continued is None:
            raise ValueError("The original native effect has no complete verified receipt.")
        native_result = continued
        out = workspace / "initial_render"
        out.mkdir()
        for item in native_result["figures"]:
            for key in ("document", "spec_path", "native_audit_path"):
                path = resolve_runtime_path(item[key])
                expected = item["document_sha256"] if key == "document" else _sha(path)
                captured = candidate_file(path, expected)
                target = out / path.name
                target.write_bytes(captured.data)
                target.chmod(captured.mode)
            for exported in item["exports"]:
                path = resolve_runtime_path(exported["path"], expected_sha256=exported["sha256"])
                captured = candidate_file(path, exported["sha256"])
                target = out / path.name
                target.write_bytes(captured.data)
                target.chmod(captured.mode)
        native_result = _remap(native_result, ((Path(literal_runtime_path(original)), out),))
        for item in native_result["figures"]:
            write_json(Path(item["native_audit_path"]), item["native_audit"])
    for figure in native_result["figures"]:
        figure["spec_sha256"] = _sha(Path(figure["spec_path"]))
    if known_workspace is None:
        from sciplot_core.rheology_tts_native_invocation import native_result_received
        from sciplot_core.rheology_tts_spec import compile_tts_spec
        native_result_received(compile_tts_spec(spec), workspace / "initial_render", native_result)
    _check_sources(sources)
    delivery.mkdir()
    documents = _publish(workspace / "initial_render", delivery, spec, native_result)
    data = delivery / "data"
    write_plot_tables(spec, data)
    write_json(data / "analysis.json", analysis)
    write_json(data / "figure_plan.json", spec)
    from sciplot_core.workflow.rheology_tts_figures import write_analysis_tables
    write_analysis_tables(analysis, data)
    if layout == "separate_polymer_modulus":
        from sciplot_core.workflow.rheology_tts_revision_tables import write_revision_tables, write_revision_methods
        write_revision_tables(analysis, data)
    else:
        write_methods(delivery / "README.txt", analysis)
    manifest = {"version": 1, "kind": "sciplot_rheology_tts_suite", "delivery": str(delivery), "workspace": str(workspace),
                "sources": sources, "documents": documents, "native_result": native_result,
                "visual_authority": "visible editable/*.vsz; initial_render is historical creation evidence",
                "figure_layout": layout,
                "scientific_scope": "empirical_superposition_not_strict_TTS_certification"}
    write_json(workspace / "suite.json", manifest)
    write_json(data / "delivery_manifest.json", manifest)
    _launcher(delivery / "Open_in_SciPlot.command", ["studio", documents[0]["path"]])
    _launcher(delivery / "Open_in_Veusz.command", ["studio", documents[0]["path"]])
    _launcher(delivery / "Update_exports.command", ["rheology", "export", str(workspace), "--json"])
    if layout == "separate_polymer_modulus":
        write_revision_methods(delivery, analysis, spec)
    from sciplot_core.studio_core.source_update_commit import file_inventory
    from sciplot_core.workflow.native_suite_creation_projection import creation_inventory
    expected_files = creation_inventory(workspace, delivery, native_result, file_inventory(delivery),
        {"request.json": request, "analysis.json": analysis, "figure_plan.json": spec})
    return {"_candidate_files": expected_files, "status": "ready", "delivery": str(delivery), "workspace": str(workspace), "figures": len(documents),
            "manual_edit": str(delivery / "Open_in_SciPlot.command"), "native_result": native_result,
            "scientific_scope": manifest["scientific_scope"]}


@native_runtime(repair=True)
def export_suite(workspace: Path, *, figure_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
    return _export_saved_suite(workspace.expanduser().resolve(), figure_ids=figure_ids)


@native_runtime(repair=True)
def _export_saved_suite(workspace: Path, *, figure_ids: tuple[str, ...] | None = None,
                        command_key: str | None = None) -> dict[str, Any]:
    from sciplot_core.project_commands import ProjectCommands
    from sciplot_core.workflow.native_suite_generation import command_for, command_key as make_key, open_store, saved_command, suite_paths
    from sciplot_core.workflow.rheology_tts_style_update import _load

    workspace, manifest = _load(workspace, native_display=True, repair=True)
    store = open_store(workspace, delivery_path(manifest))
    from sciplot_core.workflow.native_suite_generation import adopt_saved_native
    adopt_saved_native(store, manifest, figure_ids)
    request = {"adapter": "native_suite_export", "figures": list(figure_ids) if figure_ids else None,
               "native": {item["id"]: _sha(native_path(manifest, item)) for item in _selected_documents(manifest, figure_ids)}}
    key = command_key or make_key("native_export", request)
    app = ProjectCommands(store)
    command = saved_command(app, key, request)
    if command is not None:
        app.resume(command)  # Publish an already sealed immediate candidate without export replay.
    if command is None:
        reads, writes = suite_paths(workspace, manifest, figure_ids)
        command = command_for(store, "native_export", key, request=request, reads=reads, writes=writes,
                              figure_ids=figure_ids, whole=figure_ids is None)
    with tempfile.TemporaryDirectory(prefix="sciplot-native-export-") as temporary:
        record = app.execute(command, lambda: _prepare_saved_export(workspace, figure_ids=figure_ids, store=store, stage=Path(temporary).resolve()))
    from copy import deepcopy
    public = deepcopy(record["result"])
    public["delivery"] = str(delivery_path(manifest))
    for exported in public.get("exports", []):
        exported["path"] = str(delivery_path(manifest) / Path(exported["path"]).relative_to(Path(manifest["delivery"])))
    return {**public, "generation": record["generation"], "replayed": record.get("replayed", False)}


@native_runtime()
def _prepare_saved_export(workspace: Path, *, figure_ids: tuple[str, ...] | None,
                          store: FileProjectStore, stage: Path) -> ProjectMutation:
    from sciplot_core.rheology_tts_render import export_tts_documents
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, snapshot

    manifest_path = workspace / "suite.json"
    baseline = snapshot([manifest_path])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    active = current_store()
    if manifest.get("kind") != "sciplot_rheology_tts_suite" or (active.root if active is not None else Path(manifest["workspace"]).resolve()) != workspace:
        raise ValueError("Expected a bound rheology suite workspace.")
    _check_sources(manifest["sources"])
    delivery = delivery_path(manifest).resolve()
    visible_manifest = delivery / "data/delivery_manifest.json"
    baseline.update(snapshot([visible_manifest]))
    if json.loads(visible_manifest.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Visible and hidden suite manifests disagree.")
    documents = _selected_documents(manifest, figure_ids)
    by_id = (_compiled_figures(manifest) if figure_ids is None
             else _compiled_figures(manifest, figure_ids=figure_ids))
    receipts = _active_receipts(manifest)
    receipts = [receipt for receipt in receipts if receipt["id"] in by_id]
    from sciplot_core.project_store.runtime import resolve_runtime_path
    dependencies = [resolve_runtime_path(source["path"], expected_sha256=source["sha256"], source_id=source.get("source_id")) for source in manifest["sources"]]
    dependencies.extend(resolve_runtime_path(receipt["spec_path"], expected_sha256=receipt["spec_sha256"]) for receipt in receipts)
    for document in documents:
        path = native_path(manifest, document)
        if path.resolve() != delivery / "editable" / f"{document['id']}.vsz":
            raise ValueError("Native document path is outside the bound visible editable directory.")
        dependencies.append(path)
        folder = _figure_folder(delivery, document["id"])
        expected_exports = {folder / f"{document['id']}{suffix}" for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png")}
        if {delivery / Path(p).relative_to(Path(manifest["delivery"])) for p in document["exports"]} != expected_exports or len(document["exports"]) != 3:
            raise ValueError("Saved export inventory differs from the bound suite figure.")
        # Missing exports may be recovered, but existing artifacts remain protected.
        dependencies.extend(p for p in [*expected_exports, folder / f"{document['id']}.native-audit.json"]
                            if p.exists() or p.is_symlink())
    baseline.update(snapshot(dependencies))
    for receipt in receipts:
        if baseline[str(resolve_runtime_path(receipt["spec_path"], expected_sha256=receipt["spec_sha256"]))] != receipt["spec_sha256"]:
            raise ValueError("Compiled figure specification changed before suite export.")
    check_snapshot(baseline, label="suite export baseline")
    # One native worker audits the whole current set before private staged exports.
    reject_symlink_path(stage)
    native_results = export_tts_documents([
        (native_path(manifest, document), stage / "exports" / document["id"], by_id[document["id"]])
        for document in documents])
    results, updates, candidates, generated_audits = [], [], {}, {}
    for document, result in zip(documents, native_results, strict=True):
        path = native_path(manifest, document)
        identifier = document["id"]
        if (Path(result["document"]).resolve() != path.resolve()
                or result["document_sha256"] != baseline[str(path.resolve())]):
            raise ValueError("Saved document changed during suite export; no delivery published.")
        folder = _figure_folder(delivery, identifier)
        exported_paths = set()
        for exported in result["exports"]:
            source = Path(exported["path"])
            target = folder / source.name
            if source.parent != stage / "exports" or literal_resource(target) not in document["exports"]:
                raise ValueError("Candidate export target differs from the bound suite export inventory.")
            exported_paths.add(literal_resource(target))
            updates.append((source, target))
            candidates[str(source.resolve())] = exported["sha256"]
            exported["path"] = literal_resource(target)
        if exported_paths != set(document["exports"]) or len(result["exports"]) != 3:
            raise ValueError("Incomplete candidate suite export inventory.")
        audit_source = stage / "published_audits" / f"{identifier}.native-audit.json"
        audit_target = folder / audit_source.name
        result["native_audit"]["document"] = literal_resource(path)
        from sciplot_core.workflow.native_suite_generation import json_bytes
        generated_audits[audit_target] = json_bytes(result["native_audit"])
        write_json(audit_source, result["native_audit"])
        updates.append((audit_source, audit_target))
        candidates.update(snapshot([audit_source]))
        result["document"] = literal_resource(path)
        result["native_audit"]["document"] = literal_resource(path)
        result["export_dir"] = literal_directory(folder)
        result["native_audit_path"] = literal_resource(audit_target)
        document["sha256"] = result["document_sha256"]
        results.append(result)
    _check_sources(manifest["sources"])
    check_snapshot(baseline, label="suite export baseline")
    current = _export_receipts(manifest)
    current.update({Path(item["document"]).stem: item for item in results})
    manifest["last_export"] = [current[document["id"]] for document in manifest["documents"]]
    staged_manifest = stage / "suite.json"
    write_json(staged_manifest, manifest)
    candidates.update(snapshot([staged_manifest]))
    updates.extend([(staged_manifest, manifest_path), (staged_manifest, visible_manifest)])
    from sciplot_core.workflow.native_suite_generation import candidate_bytes, json_bytes, mutation
    # Consume the finite private candidates inside the same command publication.
    check_snapshot(candidates, label="suite export candidates")
    result = {"status": "ready", "delivery": str(delivery), "figures": len(results), "exact_saved_export": True,
            "selected_figures": [document["id"] for document in documents],
            "exports": [exported for result in results for exported in result["exports"]],
            "transform_execution": {"executed": [], "reused": []}}
    writes = {target: candidate_bytes(source, candidates[str(source.resolve())]) for source, target in updates}
    writes.update(generated_audits)
    writes[manifest_path] = json_bytes(manifest)
    writes[visible_manifest] = json_bytes(manifest)
    return mutation(store, writes, result, sources=manifest["sources"])
