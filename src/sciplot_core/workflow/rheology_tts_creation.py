"""Explicit, source-bound recovery of one prepared suite's first creation."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.workflow.rheology_tts_saved_state import _check_sources
from sciplot_core.workflow.rheology_tts_delivery_files import _launcher, _publish
from sciplot_core.workflow.rheology_tts_tables import write_json, write_plot_tables
from sciplot_core.workflow.rheology_tts_creation_repair import PreparedCreationBlocked as PreparedCreationBlocked, _blocked

from sciplot_core.workflow.rheology_tts_creation_inputs import (
    CHECKPOINT as CHECKPOINT, _input_file, _creation_binding as _creation_binding,
)
from sciplot_core.workflow.rheology_tts_creation_history import _existing, check_prepared_continuation


def _result(manifest: dict, *, compiled: dict, resumed: bool, include_handles: bool = True) -> dict:
    from sciplot_core.workflow.rheology_tts_creation_handles import created_object_handles

    return {"status": "ready", "delivery": manifest["delivery"], "workspace": manifest["workspace"],
        "figures": len(manifest["documents"]), "numerical_processing": False,
        "prepared_plan_sha256": manifest["prepared_input"]["sha256"],
        "manual_edit": str(Path(manifest["delivery"]) / "Open_in_SciPlot.command"),
        "native_result": manifest["native_result"], "scientific_scope": manifest["scientific_scope"],
        **({"plot_objects": created_object_handles(manifest, compiled)} if include_handles else {"_creation_handles": True}),
        **({"resumed": True} if resumed else {})}


def create_prepared_suite(request_path: Path, request: dict, spec: dict, compiled: dict,
                          delivery: Path, workspace: Path, *, contract_sha256: str, resume: bool) -> dict:
    from sciplot_core.workflow.native_suite_creation import create_project

    # An already open legacy/native session must refuse before allocating any
    # new active workspace or delivery. The store still owns actual admission.
    workspace.parent.mkdir(parents=True, exist_ok=True)
    from sciplot_core.foundation.project_session_lease import external_project_session
    with external_project_session(workspace):
        pass
    request_path = request_path.expanduser().resolve()
    if not (workspace / ".sciplot_store/head.json").is_file() and (workspace.exists() or delivery.exists()):
        if not resume:
            _existing(request_path, workspace, delivery)
        binding = _creation_binding(request, spec, compiled, delivery, workspace, contract_sha256)
        checkpoint = check_prepared_continuation(request_path, request, spec, compiled, delivery, workspace, binding)
        if checkpoint["phase"] == "completed":
            return _result(read_json_object(workspace / "suite.json"), compiled=compiled, resumed=True)
        raise _blocked("Legacy creation evidence is read-only; preserve its exact candidate and original failure for inspection.",
                       "prepared_creation_legacy_inspection_required", request_path, workspace)
    if not resume and (workspace / ".sciplot_store/head.json").is_file():
        raise _blocked("Native creation already has an admitted command; explicitly resume its saved identity.",
                       "prepared_creation_resume_required", request_path, workspace,
                       "export_saved_suite" if (workspace / "suite.json").is_file() else "resume_prepared_creation")
    from sciplot_core.project_store.runtime import literal_runtime_path
    request_file = {"path": literal_runtime_path(request_path), "sha256": file_sha256(request_path)}
    original = {"adapter": "prepared_native_suite", "request": request, "request_file": request_file,
                "binding": _creation_binding(request, spec, compiled, delivery, workspace, contract_sha256)}
    from sciplot_core.workflow.native_suite_runtime import current_store
    active = current_store()
    if active is not None:
        matching = [item for item in active.commands()
                    if item.get("metadata", {}).get("request", {}).get("adapter") == "prepared_native_suite"
                    and item["metadata"]["request"].get("request") == request
                    and "continuation_of" not in item["metadata"]["request"]]
        if len(matching) > 1:
            raise ValueError("Prepared creation identity is ambiguous; preserve its original commands.")
        if matching:
            saved = matching[0]["metadata"]["request"]
            binding = saved["binding"]
            if (saved.get("request_file") != request_file
                    or binding["compiled_sha256"] != canonical_json_sha256(compiled)
                    or binding["sources"] != spec["source_binding"]["sources"]
                    or binding["prepared_input"]["sha256"] != spec["source_binding"]["prepared_plan"]["sha256"]
                    or binding["contract_sha256"] != contract_sha256):
                raise ValueError("Prepared creation source/spec bindings changed; do not recreate native work.")
            original = saved
    def prepare(candidate_workspace: Path, candidate_delivery: Path) -> dict:
        binding = _creation_binding(request, spec, compiled, candidate_delivery, candidate_workspace, contract_sha256)
        return _prepare_candidate(request_path, request, spec, compiled, candidate_delivery, candidate_workspace, binding)
    inputs = [*spec["source_binding"]["sources"],
              {"path": spec["source_binding"]["prepared_plan"]["path"],
               "sha256": spec["source_binding"]["prepared_plan"]["sha256"]},
              {"path": request_file["path"], "sha256": request_file["sha256"]}]
    def recover(old_workspace: Path, old_delivery: Path, new_workspace: Path, new_delivery: Path) -> dict:
        origin_workspace, origin_delivery = old_workspace, old_delivery
        if active is not None:
            origin_workspace = Path(active.snapshot()["locators"][""]) / old_workspace.relative_to(active.root)
            origin_delivery = origin_workspace.parent / "delivery"
        binding = _creation_binding(request, spec, compiled, origin_delivery, origin_workspace, contract_sha256)
        _input_file(old_workspace / "request.json", binding["request"], create=False)
        _input_file(old_workspace / "figure_plan.json", spec, create=False)
        from sciplot_core.rheology_tts_render_creation import check_native_continuation
        native = check_native_continuation(compiled, old_workspace / "initial_render", completed=True)
        if native is None:
            raise ValueError("No complete verified native effect exists; preserve its unknown command.")
        return _prepare_candidate(request_path, request, spec, compiled, new_delivery, new_workspace,
            _creation_binding(request, spec, compiled, new_delivery, new_workspace, contract_sha256),
            known_native=(old_workspace / "initial_render", native))
    try:
        return create_project(workspace, delivery, original, inputs, prepare, resume=resume, recover_prepare=recover)
    except FileExistsError as exc:
        raise _blocked(str(exc), "prepared_creation_binding_changed", request_path, workspace) from exc


def _prepare_candidate(request_path: Path, request: dict, spec: dict, compiled: dict,
                       delivery: Path, workspace: Path, binding: dict, *,
                       known_native: tuple[Path, dict] | None = None) -> dict:
    """Private creation/pure publication; no workflow checkpoint is an owner."""
    from sciplot_core.rheology_tts_render import render_tts_figures
    from sciplot_core.rheology_tts_native_invocation import native_result_received
    from sciplot_core.workflow.native_suite_creation_projection import _remap, creation_inventory
    from sciplot_core.workflow.native_suite_generation import candidate_file
    if workspace.exists() or delivery.exists():
        raise FileExistsError("Private creation output already exists; preserve its admitted evidence.")
    workspace.mkdir(parents=True)
    _input_file(workspace / "request.json", binding["request"])
    _input_file(workspace / "figure_plan.json", spec)
    _check_sources(binding["sources"])
    if known_native is None:
        native = render_tts_figures(spec, workspace / "initial_render")
        for figure in native["figures"]:
            figure["spec_sha256"] = file_sha256(Path(figure["spec_path"]))
        native_result_received(compiled, workspace / "initial_render", native)
    else:
        original, prior = known_native
        out = workspace / "initial_render"
        out.mkdir()
        from sciplot_core.project_store.runtime import resolve_runtime_path
        for figure in prior["figures"]:
            paths = [(resolve_runtime_path(figure["document"], expected_sha256=figure["document_sha256"]), figure["document_sha256"]),
                     (resolve_runtime_path(figure["spec_path"]), file_sha256(resolve_runtime_path(figure["spec_path"]))),
                     (resolve_runtime_path(figure["native_audit_path"]), file_sha256(resolve_runtime_path(figure["native_audit_path"]))),
                     *((resolve_runtime_path(item["path"], expected_sha256=item["sha256"]), item["sha256"]) for item in figure["exports"])]
            for path, digest in paths:
                captured = candidate_file(path, digest)
                target = out / path.name
                target.write_bytes(captured.data)
                target.chmod(captured.mode)
        from sciplot_core.project_store.runtime import literal_runtime_path
        native = _remap(prior, ((Path(literal_runtime_path(original)), out),))
        for figure in native["figures"]:
            figure["spec_sha256"] = file_sha256(Path(figure["spec_path"]))
            # The audit receipt has only declared host path fields rewritten;
            # numeric/spec/source values are preserved byte-for-byte.
            write_json(Path(figure["native_audit_path"]), figure["native_audit"])
    delivery.mkdir()
    documents = _publish(workspace / "initial_render", delivery, spec, native)
    write_plot_tables(spec, delivery / "data")
    write_json(delivery / "data/figure_plan.json", spec)
    _write_index(delivery, spec, documents)
    manifest = {"version": 1, "kind": "sciplot_rheology_tts_suite", "delivery": str(delivery),
        "workspace": str(workspace), "sources": binding["sources"], "documents": documents, "native_result": native,
        "prepared_input": binding["prepared_input"], "figure_layout": spec.get("figure_layout", "prepared"),
        "contract_sha256": binding["contract_sha256"],
        "visual_authority": "visible editable/*.vsz; initial_render is historical creation evidence",
        "scientific_scope": "Externally processed coordinates; no scientific calculations or interpretation performed by plot."}
    write_json(workspace / "suite.json", manifest)
    write_json(delivery / "data/delivery_manifest.json", manifest)
    _launcher(delivery / "Open_in_SciPlot.command", ["studio", documents[0]["path"]])
    _launcher(delivery / "Update_exports.command", ["rheology", "export", str(workspace), "--json"])
    _check_sources(binding["sources"])
    result = _result(manifest, compiled=compiled, resumed=False, include_handles=False)
    result["_candidate_files"] = creation_inventory(workspace, delivery, native, file_inventory(delivery),
        {"request.json": binding["request"], "figure_plan.json": spec})
    return result

def _write_index(delivery: Path, spec: dict, documents: list[dict]) -> None:
    rows = []
    for document in documents:
        files = [*document["exports"], document["path"], str(delivery / "data" / f"{document['id']}.csv")]
        links = " · ".join(f'<a href="{quote(Path(p).relative_to(delivery).as_posix())}">{html.escape(Path(p).suffix.lstrip("."))}</a>' for p in files)
        rows.append(f"<tr><td>{html.escape(document['id'])}</td><td>{links}</td></tr>")
    (delivery / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Prepared figures</title>'
        '<h1>Prepared figures</h1><p>AI-processed coordinates, rendered using the shared template contract.</p>'
        '<table><tr><th>Figure</th><th>Files</th></tr>' + "".join(rows) + '</table>'
        '<p><a href="data/figure_plan.json">Numeric plan and template roles</a></p>', encoding="utf-8")
    (delivery / "README.txt").write_text(
        "AI processing / local plotting boundary\n\n"
        "The external AI supplies scientific coordinates, units, selections, fits and transformations.\n"
        "The local plot command performs no scientific calculations. It preserves those coordinates,\n"
        "resolves declared series roles through shared templates and exports native Veusz documents.\n"
        "Creation audits data fidelity and resolved native appearance; this is not scientific validity certification.\n"
        "Open index.html for individual files. Editable VSZ is visual authority after delivery.\n"
        "Save and close native edits, then run Update_exports.command. Exact export records template\n"
        "differences without resetting saved native edits. Original sources remain unchanged.\n\n"
        + json.dumps(spec.get("transform_ledger", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
