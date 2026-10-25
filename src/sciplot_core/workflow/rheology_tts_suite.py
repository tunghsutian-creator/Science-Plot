"""Source-bound TTS suite lifecycle with exact native re-export."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
from pathlib import Path
import tempfile

from sciplot_core._paths import REPO_ROOT
from sciplot_core.workflow.native_suite_runtime import current_store, delivery_path, literal_directory, literal_resource, native_path, native_runtime
from sciplot_core.workflow.rheology_tts_tables import write_json, write_methods, write_plot_tables


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_sources(request: dict) -> list[dict]:
    paths = [Path(request["frequency_source"]).expanduser().resolve()]
    paths.extend(Path(s["tts_source"]).expanduser().resolve() for s in request["samples"] if s.get("tts_source"))
    return [{"path": str(p), "sha256": _sha(p)} for p in dict.fromkeys(paths)]


def _check_sources(sources: list[dict]) -> None:
    for source in sources:
        from sciplot_core.project_store.runtime import resolve_runtime_path
        path = resolve_runtime_path(source["path"], expected_sha256=source["sha256"], source_id=source.get("source_id"))
        if not path.is_file() or _sha(path) != source["sha256"]:
            raise ValueError(f"Original source changed: {path}; a new analysis is required.")


def _launcher(path: Path, arguments: list[str]) -> None:
    command = [str(REPO_ROOT / "skill/scripts/sciplot"), *arguments]
    path.write_text("#!/bin/zsh\nset -e\nexec " + " ".join(shlex.quote(v) for v in command) + "\n", encoding="utf-8")
    path.chmod(0o755)


def _figure_folder(delivery: Path, identifier: str) -> Path:
    if identifier.startswith("Figure_X"):
        return delivery
    return delivery / ("SI" if identifier.startswith("SI_") else "panels")


def _output_paths(source: Path, requested: str | Path) -> tuple[Path, Path]:
    """Allow new sibling suites and an explicit revision inside an existing suite."""
    delivery = Path(requested).expanduser().resolve()
    parent = source.parent
    if delivery.parent != parent:
        previous_manifest = delivery.parent / "data" / "delivery_manifest.json"
        if delivery.parent.parent != parent or not previous_manifest.is_file():
            raise ValueError("TTS output must be beside its original data or a new revision inside an existing source-adjacent suite.")
        previous = json.loads(previous_manifest.read_text(encoding="utf-8"))
        original_paths = {Path(s["path"]).resolve() for s in previous.get("sources", [])}
        if previous.get("kind") != "sciplot_rheology_tts_suite" or source not in original_paths:
            raise ValueError("Revision parent is not a source-bound suite for this frequency source.")
    if delivery == parent or ".sciplot" in delivery.relative_to(parent).parts:
        raise ValueError("Visible delivery must be a dedicated folder outside hidden evidence.")
    relative_name = "__".join(delivery.relative_to(parent).parts)
    return delivery, parent / ".sciplot" / relative_name


def _publish(stage: Path, delivery: Path, spec: dict, native_result: dict) -> list[dict]:
    """Copy known new outputs; visible native files become the sole edit authority."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

    reject_symlink_path(stage)
    reject_symlink_path(delivery)
    # Creation checkpoints retain sealed and failed exports below .creation.
    # Those historical bytes are not another candidate for visible publication.
    for item in stage.iterdir():
        reject_symlink_path(item)
        if item.is_dir() and item.name != ".creation":
            raise ValueError(f"Unexpected nested native publication output: {item}")

    def bound_file(name: str, receipt_path: str, digest: str) -> Path:
        path = stage / name
        reject_symlink_path(path)
        if (not path.is_file() or path.stat().st_nlink != 1
                or Path(receipt_path) != path or _sha(path) != digest):
            raise ValueError(f"Missing, changed or aliased receipt-bound native output: {path}")
        return path

    receipts = native_result["figures"]
    by_id = {r["id"]: r for r in receipts}
    expected_ids = [f["id"] for f in spec["figures"]]
    if len(by_id) != len(receipts) or set(by_id) != set(expected_ids):
        raise ValueError("Native render receipts do not match the selected figure set.")
    prepared = []
    # Check the complete set before publishing any figure, including missing TIFFs.
    for identifier in expected_ids:
        receipt = by_id[identifier]
        native = bound_file(identifier + ".vsz", receipt["document"], receipt["document_sha256"])
        expected_names = {identifier + suffix for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png")}
        exported = {Path(r["path"]).name: r for r in receipt["exports"]}
        if len(exported) != len(receipt["exports"]) or set(exported) != expected_names:
            raise ValueError(f"Expected exactly PDF, TIFF and PNG receipts for {identifier}.")
        sources = []
        for name in sorted(expected_names):
            digest = exported[name]["sha256"]
            sources.append((bound_file(name, exported[name]["path"], digest), digest))
        prepared.append((identifier, native, receipt["document_sha256"], sources))
    documents = []
    for identifier, source_native, native_sha, sources in prepared:
        native = delivery / "editable" / f"{identifier}.vsz"
        native.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_native, native)
        if _sha(native) != native_sha or _sha(source_native) != native_sha:
            raise RuntimeError(f"Native delivery byte mismatch: {native}")
        destination = _figure_folder(delivery, identifier)
        destination.mkdir(parents=True, exist_ok=True)
        files = []
        for path, digest in sources:
            target = destination / path.name
            shutil.copy2(path, target)
            if _sha(target) != digest or _sha(path) != digest:
                raise RuntimeError(f"Delivery byte mismatch: {target}")
            files.append(str(target))
        documents.append({"id": identifier, "path": str(native), "sha256": _sha(native), "exports": files})
        _launcher(delivery / "editable" / f"Open_{identifier}.command", ["studio", str(native)])
    return documents


def create_suite(request_path: Path) -> dict:
    from sciplot_core.workflow.native_suite_creation import create_project
    request_path = request_path.expanduser().resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    from sciplot_core.workflow.rheology_tts_contract import validate_creation_request
    validate_creation_request(request)
    source = Path(request["frequency_source"]).expanduser().resolve()
    delivery, workspace = _output_paths(source, request.get("out", source.parent / "TTS_SciPlot"))
    return create_project(workspace, delivery, {"adapter": "analysis_native_suite", "request": request},
        [*_bound_sources(request), {"path": str(request_path), "sha256": _sha(request_path)}], lambda candidate_workspace, candidate_delivery:
        _create_suite_candidate(request_path, output_paths=(candidate_delivery, candidate_workspace)))


def _create_suite_candidate(request_path: Path, *, output_paths: tuple[Path, Path]) -> dict:
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
    analysis = analyze_tts_request({k: v for k, v in request.items()
                                   if k not in {"out", "figure_layout", "expected_contract_sha256"}})
    _check_sources(sources)
    layout = request.get("figure_layout", "legacy")
    spec = build_tts_figures(analysis, layout=layout)
    spec["source_binding"] = {"sources": sources, "request": request}
    workspace.mkdir(parents=True)
    write_json(workspace / "request.json", request)
    write_json(workspace / "analysis.json", analysis)
    write_json(workspace / "figure_plan.json", spec)
    native_result = render_tts_figures(spec, workspace / "initial_render")
    for figure in native_result["figures"]:
        figure["spec_sha256"] = _sha(Path(figure["spec_path"]))
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
    return {"status": "ready", "delivery": str(delivery), "workspace": str(workspace), "figures": len(documents),
            "manual_edit": str(delivery / "Open_in_SciPlot.command"), "native_result": native_result,
            "scientific_scope": manifest["scientific_scope"]}


def _selected_documents(manifest: dict, figure_ids: tuple[str, ...] | None = None) -> list[dict]:
    documents = manifest["documents"]
    identifiers = [document["id"] for document in documents]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Saved document identities are not unique.")
    if figure_ids is None:
        return documents
    if (not isinstance(figure_ids, tuple) or not figure_ids or len(set(figure_ids)) != len(figure_ids)
            or any(identifier not in identifiers for identifier in figure_ids)):
        raise ValueError("Select exact, unique existing figure IDs before native execution.")
    return [document for document in documents if document["id"] in figure_ids]


def _active_receipts(manifest: dict) -> list[dict]:
    """Select the active spec per figure; unrelated overlays never erase it."""
    original = {item["id"]: item for item in manifest["native_result"]["figures"]}
    overlay = manifest.get("presentation_revision", {}).get("figures", [])
    if len({item["id"] for item in overlay}) != len(overlay):
        raise ValueError("Active compiled figure identities are not unique.")
    original.update({item["id"]: item for item in overlay})
    return [original[document["id"]] for document in manifest["documents"]]


def _compiled_figures(manifest: dict, *, figure_ids: tuple[str, ...] | None = None) -> dict:
    """Read creation-bound numeric baselines without accepting edited spec bytes."""
    by_id = {}
    selected = {document["id"] for document in _selected_documents(manifest, figure_ids)}
    receipts = _active_receipts(manifest)
    for receipt in receipts:
        if receipt["id"] not in selected:
            continue
        from sciplot_core.project_store.runtime import resolve_runtime_path
        path = resolve_runtime_path(receipt["spec_path"], expected_sha256=receipt.get("spec_sha256"))
        digest = receipt.get("spec_sha256")
        if not digest:
            raise ValueError("Compiled figure specification lacks its creation SHA; explicit receipt migration is required.")
        if not path.is_file() or _sha(path) != digest:
            raise ValueError(f"Compiled figure specification changed: {path}")
        spec = json.loads(path.read_text(encoding="utf-8"))
        if _sha(path) != digest:
            raise ValueError(f"Compiled figure specification changed while reading: {path}")
        identifier = receipt["id"]
        if identifier in by_id or spec["figure"]["id"] != identifier:
            raise ValueError("Compiled figure identities disagree with creation receipts.")
        if spec["source_binding"].get("sources") != manifest["sources"]:
            raise ValueError("Compiled figure source bindings disagree with suite sources.")
        by_id[identifier] = spec["figure"]
    if set(by_id) != selected:
        raise ValueError("Saved document identities disagree with compiled figure receipts.")
    return by_id


@native_runtime(repair=True)
def export_suite(workspace: Path, *, figure_ids: tuple[str, ...] | None = None) -> dict:
    return _export_saved_suite(workspace.expanduser().resolve(), figure_ids=figure_ids)


@native_runtime(repair=True)
def _export_saved_suite(workspace: Path, *, figure_ids: tuple[str, ...] | None = None,
                        command_key: str | None = None) -> dict:
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
                              figure_id=figure_ids[0] if figure_ids and len(figure_ids) == 1 else None)
    with tempfile.TemporaryDirectory(prefix="sciplot-native-export-") as temporary:
        record = app.execute(command, lambda: _prepare_saved_export(workspace, figure_ids=figure_ids, store=store, stage=Path(temporary).resolve()))
    from copy import deepcopy
    public = deepcopy(record["result"])
    public["delivery"] = str(delivery_path(manifest))
    for exported in public.get("exports", []):
        exported["path"] = str(delivery_path(manifest) / Path(exported["path"]).relative_to(Path(manifest["delivery"])))
    return {**public, "generation": record["generation"], "replayed": record.get("replayed", False)}


@native_runtime()
def _prepare_saved_export(workspace: Path, *, figure_ids: tuple[str, ...] | None, store, stage: Path):
    from sciplot_core.rheology_tts_render import export_tts_documents
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, snapshot

    manifest_path = workspace / "suite.json"
    baseline = snapshot([manifest_path])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "sciplot_rheology_tts_suite" or (current_store().root if current_store() is not None else Path(manifest["workspace"]).resolve()) != workspace:
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
    results, updates, candidates = [], [], {}
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
    current = {Path(item["document"]).stem: item for item in
               manifest.get("last_export", manifest["native_result"]["figures"])}
    current.update({Path(item["document"]).stem: item for item in results})
    manifest["last_export"] = [current[document["id"]] for document in manifest["documents"]]
    staged_manifest = stage / "suite.json"
    write_json(staged_manifest, manifest)
    candidates.update(snapshot([staged_manifest]))
    updates.extend([(staged_manifest, manifest_path), (staged_manifest, visible_manifest)])
    from sciplot_core.workflow.native_suite_generation import mutation
    # Consume the finite private candidates inside the same command publication.
    check_snapshot(candidates, label="suite export candidates")
    result = {"status": "ready", "delivery": str(delivery), "figures": len(results), "exact_saved_export": True,
            "selected_figures": [document["id"] for document in documents],
            "exports": [exported for result in results for exported in result["exports"]],
            "transform_execution": {"executed": [], "reused": []}}
    return mutation(store, dict((target, source) for source, target in updates), result,
                    sources=manifest["sources"])
