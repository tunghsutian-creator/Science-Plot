"""Historical v1 bytes for read-only compatibility rejection tests only.

These retired writers are not part of the application or a recovery entrypoint.
"""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.workflow.rheology_tts_creation import (
    _check_sources, _launcher, _publish, _result, _write_index,
    write_json, write_plot_tables,
)

from sciplot_core.workflow.rheology_tts_creation_inputs import CHECKPOINT, _input_file
from sciplot_core.workflow.rheology_tts_creation_history import (
    _existing, _known_workspace, _publication_evidence, _publication_inventory,
    _validate_checkpoint, _verify_bound_native, check_prepared_continuation,
)


def _install_delivery(candidate: Path, delivery: Path) -> None:
    """Retain the prepared-creation seam while sharing exclusive installation."""
    from sciplot_core.delivery.install import install_new_delivery

    install_new_delivery(candidate, delivery)


def _finish(workspace: Path, delivery: Path, checkpoint: dict, compiled: dict, *, spec: dict, resumed: bool) -> dict:
    candidate, manifest = _publication_evidence(workspace, delivery, checkpoint, compiled)
    publication = checkpoint["publication"]
    if not delivery.exists():
        _install_delivery(candidate, delivery)
    if _publication_inventory(delivery, checkpoint) != publication["files"]:
        raise ValueError("Installed prepared delivery differs from its sealed inventory.")
    _input_file(workspace / "suite.json", manifest)
    if json.loads((delivery / "data/delivery_manifest.json").read_text()) != manifest:
        raise ValueError("Prepared suite manifests disagree after installation.")
    _verify_bound_native(workspace, checkpoint, compiled)
    if _publication_inventory(delivery, checkpoint) != publication["files"]:
        raise ValueError("Installed prepared delivery changed before completion.")
    checkpoint["phase"] = "completed"
    atomic_write_json(workspace / CHECKPOINT, checkpoint)
    from sciplot_core.workflow.native_suite_creation_projection import creation_inventory
    result = _result(manifest, compiled=compiled, resumed=resumed)
    result["_candidate_files"] = creation_inventory(workspace, delivery, checkpoint["native_result"],
        publication["files"], {"request.json": checkpoint["binding"]["request"], "figure_plan.json": spec},
        suite_sha256=publication["manifest_sha256"])
    return result


def _build_publication(workspace: Path, delivery: Path, spec: dict, native: dict, binding: dict,
                       checkpoint: dict) -> None:
    attempt = uuid4().hex
    checkpoint["attempts"].append(attempt)
    atomic_write_json(workspace / CHECKPOINT, checkpoint)
    stage = workspace / "publication_stages" / attempt
    candidate = stage / "delivery"
    staged_documents = _publish(workspace / "initial_render", candidate, spec, native)
    write_plot_tables(spec, candidate / "data")
    write_json(candidate / "data/figure_plan.json", spec)
    _write_index(candidate, spec, staged_documents)
    documents = deepcopy(staged_documents)
    for item in documents:
        item["path"] = str(delivery / Path(item["path"]).relative_to(candidate))
        item["exports"] = [str(delivery / Path(path).relative_to(candidate)) for path in item["exports"]]
        _launcher(candidate / "editable" / f"Open_{item['id']}.command", ["studio", item["path"]])
    manifest = {"version": 1, "kind": "sciplot_rheology_tts_suite", "delivery": str(delivery),
        "workspace": str(workspace), "sources": binding["sources"], "documents": documents, "native_result": native,
        "prepared_input": binding["prepared_input"], "figure_layout": spec.get("figure_layout", "prepared"),
        "contract_sha256": binding["contract_sha256"],
        "visual_authority": "visible editable/*.vsz; initial_render is historical creation evidence",
        "scientific_scope": "Externally processed coordinates; no scientific calculations or interpretation performed by plot."}
    write_json(stage / "suite.json", manifest)
    write_json(candidate / "data/delivery_manifest.json", manifest)
    _launcher(candidate / "Open_in_SciPlot.command", ["studio", documents[0]["path"]])
    _launcher(candidate / "Update_exports.command", ["rheology", "export", str(workspace), "--json"])
    _check_sources(binding["sources"])
    checkpoint.update(phase="publication_ready", publication={"attempt": attempt,
        "files": file_inventory(candidate), "manifest_sha256": file_sha256(stage / "suite.json")})
    _validate_checkpoint(checkpoint, workspace)
    atomic_write_json(workspace / CHECKPOINT, checkpoint)


def _create_locked(request_path: Path, request: dict, spec: dict, compiled: dict, delivery: Path,
                   workspace: Path, binding: dict, *, resume: bool) -> dict:
    from sciplot_core.rheology_tts_render import render_tts_figures

    checkpoint_path = workspace / CHECKPOINT
    if not resume and (workspace.exists() or delivery.exists()):
        _existing(request_path, workspace, delivery)
    if resume:
        checkpoint = check_prepared_continuation(request_path, request, spec, compiled, delivery, workspace, binding)
    else:
        workspace.mkdir(parents=True)
        checkpoint = {"kind": "sciplot_prepared_creation", "version": 1, "binding": binding,
                      "phase": "initialized", "attempts": []}
        atomic_write_json(checkpoint_path, checkpoint)
    _check_sources(binding["sources"])
    _input_file(workspace / "request.json", binding["request"])
    _input_file(workspace / "figure_plan.json", spec)
    if checkpoint["phase"] in {"publication_ready", "completed"}:
        return _finish(workspace, delivery, checkpoint, compiled, spec=spec, resumed=resume)
    if checkpoint["phase"] == "native_complete":
        _verify_bound_native(workspace, checkpoint, compiled)
        native = checkpoint["native_result"]
    else:
        native = render_tts_figures(spec, workspace / "initial_render", resume=resume)
        for item in native["figures"]:
            item["spec_sha256"] = file_sha256(Path(item["spec_path"]))
        checkpoint.update(phase="native_complete", native_result=native)
        atomic_write_json(checkpoint_path, checkpoint)
    _build_publication(workspace, delivery, spec, native, binding, checkpoint)
    _known_workspace(workspace, checkpoint)
    return _finish(workspace, delivery, checkpoint, compiled, spec=spec, resumed=resume)
