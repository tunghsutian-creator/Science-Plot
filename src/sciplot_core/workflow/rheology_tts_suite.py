"""Source-bound TTS suite lifecycle with exact native re-export."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
from pathlib import Path
from uuid import uuid4

from sciplot_core._paths import REPO_ROOT
from sciplot_core.workflow.rheology_tts_tables import write_json, write_methods, write_plot_tables


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_sources(request: dict) -> list[dict]:
    paths = [Path(request["frequency_source"]).expanduser().resolve()]
    paths.extend(Path(s["tts_source"]).expanduser().resolve() for s in request["samples"] if s.get("tts_source"))
    return [{"path": str(p), "sha256": _sha(p)} for p in dict.fromkeys(paths)]


def _check_sources(sources: list[dict]) -> None:
    for source in sources:
        path = Path(source["path"])
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
    from sciplot_core.semantic_sources.rheology_tts import analyze_tts_request
    from sciplot_core.workflow.rheology_tts_figures import build_tts_figures
    from sciplot_core.rheology_tts_render import render_tts_figures

    request = json.loads(request_path.expanduser().resolve().read_text(encoding="utf-8"))
    from sciplot_core.workflow.rheology_tts_contract import validate_creation_request
    validate_creation_request(request)
    source = Path(request["frequency_source"]).expanduser().resolve()
    delivery, workspace = _output_paths(source, request.get("out", source.parent / "TTS_SciPlot"))
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


def _compiled_figures(manifest: dict) -> dict:
    """Read creation-bound numeric baselines without accepting edited spec bytes."""
    by_id = {}
    receipts = manifest.get("presentation_revision", {}).get("figures") or manifest["native_result"]["figures"]
    for receipt in receipts:
        path = Path(receipt["spec_path"])
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
    document_ids = [d["id"] for d in manifest["documents"]]
    if len(set(document_ids)) != len(document_ids) or set(by_id) != set(document_ids):
        raise ValueError("Saved document identities disagree with compiled figure receipts.")
    return by_id


def export_suite(workspace: Path) -> dict:
    from sciplot_core.studio_core.project_session import external_project_session

    workspace = workspace.expanduser().resolve()
    with external_project_session(workspace):
        return _export_saved_suite(workspace)


def _export_saved_suite(workspace: Path) -> dict:
    from sciplot_core.rheology_tts_render import export_tts_documents
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, publish_files, snapshot

    manifest_path = workspace / "suite.json"
    baseline = snapshot([manifest_path])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "sciplot_rheology_tts_suite" or Path(manifest["workspace"]).resolve() != workspace:
        raise ValueError("Expected a bound rheology suite workspace.")
    _check_sources(manifest["sources"])
    delivery = Path(manifest["delivery"]).resolve()
    visible_manifest = delivery / "data/delivery_manifest.json"
    baseline.update(snapshot([visible_manifest]))
    if json.loads(visible_manifest.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Visible and hidden suite manifests disagree.")
    by_id = _compiled_figures(manifest)
    receipts = manifest.get("presentation_revision", {}).get("figures") or manifest["native_result"]["figures"]
    dependencies = [Path(source["path"]) for source in manifest["sources"]]
    dependencies.extend(Path(receipt["spec_path"]) for receipt in receipts)
    for document in manifest["documents"]:
        path = Path(document["path"])
        if path.resolve() != delivery / "editable" / f"{document['id']}.vsz":
            raise ValueError("Native document path is outside the bound visible editable directory.")
        dependencies.append(path)
        folder = _figure_folder(delivery, document["id"])
        expected_exports = {folder / f"{document['id']}{suffix}" for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png")}
        if {Path(p) for p in document["exports"]} != expected_exports or len(document["exports"]) != 3:
            raise ValueError("Saved export inventory differs from the bound suite figure.")
        # Missing exports may be recovered, but existing artifacts remain protected.
        dependencies.extend(p for p in [*expected_exports, folder / f"{document['id']}.native-audit.json"]
                            if p.exists() or p.is_symlink())
    baseline.update(snapshot(dependencies))
    for receipt in receipts:
        if baseline[str(Path(receipt["spec_path"]).resolve())] != receipt["spec_sha256"]:
            raise ValueError("Compiled figure specification changed before suite export.")
    check_snapshot(baseline, label="suite export baseline")
    # One native worker audits the whole current set before private staged exports.
    stage = workspace / "export_stages" / uuid4().hex
    reject_symlink_path(stage)
    native_results = export_tts_documents([
        (Path(document["path"]), stage / "exports" / document["id"], by_id[document["id"]])
        for document in manifest["documents"]])
    results, updates, candidates = [], [], {}
    for document, result in zip(manifest["documents"], native_results, strict=True):
        path = Path(document["path"])
        identifier = document["id"]
        if (Path(result["document"]).resolve() != path.resolve()
                or result["document_sha256"] != baseline[str(path.resolve())]):
            raise ValueError("Saved document changed during suite export; no delivery published.")
        folder = _figure_folder(delivery, identifier)
        exported_paths = set()
        for exported in result["exports"]:
            source = Path(exported["path"])
            target = folder / source.name
            if source.parent != stage / "exports" or str(target) not in document["exports"]:
                raise ValueError("Candidate export target differs from the bound suite export inventory.")
            exported_paths.add(str(target))
            updates.append((source, target))
            candidates[str(source.resolve())] = exported["sha256"]
            exported["path"] = str(target)
        if exported_paths != set(document["exports"]) or len(result["exports"]) != 3:
            raise ValueError("Incomplete candidate suite export inventory.")
        audit_source = stage / "published_audits" / f"{identifier}.native-audit.json"
        audit_target = folder / audit_source.name
        write_json(audit_source, result["native_audit"])
        updates.append((audit_source, audit_target))
        candidates.update(snapshot([audit_source]))
        result["export_dir"] = str(folder)
        result["native_audit_path"] = str(audit_target)
        document["sha256"] = result["document_sha256"]
        results.append(result)
    _check_sources(manifest["sources"])
    check_snapshot(baseline, label="suite export baseline")
    manifest["last_export"] = results
    staged_manifest = stage / "suite.json"
    write_json(staged_manifest, manifest)
    candidates.update(snapshot([staged_manifest]))
    updates.extend([(staged_manifest, manifest_path), (staged_manifest, visible_manifest)])
    publish_files(updates, stage / "backup", expected=baseline, candidates=candidates,
                  allowed_roots=(workspace, delivery))
    return {"status": "ready", "delivery": str(delivery), "figures": len(results), "exact_saved_export": True}
