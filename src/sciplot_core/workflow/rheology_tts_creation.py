"""Explicit, source-bound recovery of one prepared suite's first creation."""

from __future__ import annotations

from copy import deepcopy
import ctypes
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4
from urllib.parse import quote

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.studio_core.source_update_commit import file_inventory, reject_symlink_path
from sciplot_core.workflow.rheology_tts_suite import _check_sources, _compiled_figures, _launcher, _publish
from sciplot_core.workflow.rheology_tts_tables import write_json, write_plot_tables
from sciplot_core.workflow.rheology_tts_creation_repair import PreparedCreationBlocked as PreparedCreationBlocked, _blocked

CHECKPOINT = "creation_checkpoint.json"


def _existing(request: Path, workspace: Path, delivery: Path) -> None:
    hidden, visible = workspace / "suite.json", delivery / "data/delivery_manifest.json"
    if hidden.is_file() and visible.is_file():
        try:
            manifest = json.loads(hidden.read_text())
            if (manifest == json.loads(visible.read_text()) and manifest["workspace"] == str(workspace)
                    and manifest["delivery"] == str(delivery)):
                _compiled_figures(manifest)
                if all(Path(d["path"]).is_file() for d in manifest["documents"]):
                    raise _blocked("A complete suite already exists; use rheology export with this workspace.",
                                   "prepared_creation_exists", request, workspace, "export_saved_suite")
        except (KeyError, TypeError, json.JSONDecodeError, ValueError):
            pass
    if (workspace / CHECKPOINT).is_file():
        raise _blocked("Prepared creation already has a checkpoint; inspect the returned recovery guidance.",
                       "prepared_creation_resume_required", request, workspace)
    raise _blocked("Existing output has no supported creation checkpoint; preserve it and inspect its evidence. Do not recreate or overwrite it.",
                   "prepared_creation_unknown_partial", request, workspace)


def _input_file(path: Path, value: dict, *, create: bool = True) -> None:
    expected = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    reject_symlink_path(path)
    if path.exists():
        if path.read_bytes() != expected:
            raise ValueError(f"Prepared creation input evidence changed: {path}")
    elif create:
        atomic_write_json(path, value)


def _publication_files(identifiers: list[str]) -> set[str]:
    names = {"index.html", "README.txt", "Open_in_SciPlot.command", "Update_exports.command",
             "data/figure_plan.json", "data/delivery_manifest.json"}
    for identifier in identifiers:
        folder = "" if identifier.startswith("Figure_X") else ("SI/" if identifier.startswith("SI_") else "panels/")
        names.update({f"editable/{identifier}.vsz", f"editable/Open_{identifier}.command", f"data/{identifier}.csv"})
        names.update(f"{folder}{identifier}{suffix}" for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png"))
    return names


def _validate_checkpoint(checkpoint: dict, workspace: Path) -> None:
    phase = checkpoint["phase"]
    required = {"kind", "version", "binding", "phase", "attempts"}
    if phase != "initialized":
        required.add("native_result")
    if phase in {"publication_ready", "completed"}:
        required.add("publication")
    attempts = checkpoint.get("attempts")
    if (set(checkpoint) != required or type(checkpoint["version"]) is not int
            or not isinstance(attempts, list) or any(not isinstance(name, str)
                or re.fullmatch(r"[a-f0-9]{32}", name) is None for name in attempts)
            or len(set(attempts)) != len(attempts) or (phase == "initialized" and attempts)):
        raise ValueError("Invalid prepared creation checkpoint fields; preserve and inspect.")
    if phase != "initialized":
        if not isinstance(checkpoint["native_result"], dict):
            raise ValueError("Invalid prepared native creation receipt.")
    if phase != "initialized" or (workspace / "initial_render").exists():
        if any(not (workspace / name).is_file() for name in ("request.json", "figure_plan.json")):
            raise ValueError("Prepared creation input evidence is missing; preserve and inspect.")
    if "publication" in required:
        publication = checkpoint["publication"]
        expected = _publication_files(checkpoint["binding"]["figure_ids"])
        if (not isinstance(publication, dict) or set(publication) != {"attempt", "files", "manifest_sha256"}
                or not attempts or publication["attempt"] != attempts[-1]
                or not isinstance(publication["files"], dict) or set(publication["files"]) != expected
                or any(not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                       for digest in [publication["manifest_sha256"], *publication["files"].values()])):
            raise ValueError("Invalid sealed prepared publication fields; preserve and inspect.")


def _ordinary_tree(root: Path) -> None:
    reject_symlink_path(root)
    for path in root.rglob("*"):
        reject_symlink_path(path)
        if not path.is_dir() and (not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError(f"Prepared creation requires ordinary unaliased files: {path}")


def _known_workspace(workspace: Path, checkpoint: dict) -> None:
    allowed = {CHECKPOINT, "request.json", "figure_plan.json", "initial_render", "publication_stages",
               "logs", ".sciplot_session_locks"}
    if checkpoint["phase"] in {"publication_ready", "completed"}:
        allowed.add("suite.json")
    if any(path.name not in allowed for path in workspace.iterdir()):
        raise ValueError("Unknown files in prepared creation workspace; no recovery writes performed.")
    directories = {"initial_render", "publication_stages", "logs", ".sciplot_session_locks"}
    if any((path.is_dir() if path.name not in directories else not path.is_dir()) for path in workspace.iterdir()):
        raise ValueError("Prepared creation workspace path types changed; preserve and inspect.")
    _ordinary_tree(workspace)
    locks = workspace / ".sciplot_session_locks"
    name = hashlib.sha256(str(workspace / "initial_render").encode()).hexdigest() + ".lock"
    if locks.exists() and any(path.name != name or not path.is_file() for path in locks.iterdir()):
        raise ValueError("Unknown prepared creation session lock.")
    logs = workspace / "logs"
    if logs.exists() and any(path.name != "veusz_export_stderr.log" or not path.is_file() for path in logs.iterdir()):
        raise ValueError("Unknown prepared creation log.")
    stages = workspace / "publication_stages"
    if stages.exists() and any(path.name not in checkpoint["attempts"] or not path.is_dir() for path in stages.iterdir()):
        raise ValueError("Unknown prepared publication stage.")
    allowed_files = {"suite.json", *("delivery/" + name for name in
                                      _publication_files(checkpoint["binding"]["figure_ids"]))}
    for name in checkpoint["attempts"]:
        stage = stages / name
        for path in stage.rglob("*"):
            relative = path.relative_to(stage).as_posix()
            if ((path.is_file() and relative not in allowed_files)
                    or (path.is_dir() and not any(item.startswith(relative + "/") for item in allowed_files))):
                raise ValueError("Unknown file in prepared publication stage.")


def _install_delivery(candidate: Path, delivery: Path) -> None:
    """Atomically rename a new directory without replacing even an empty target."""
    reject_symlink_path(candidate)
    reject_symlink_path(delivery)
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(candidate), os.fsencode(delivery), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(candidate), -100, os.fsencode(delivery), 1)  # RENAME_NOREPLACE
    else:
        raise RuntimeError("Atomic non-replacing directory installation is unavailable on this platform.")
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(delivery))


def _result(manifest: dict, *, resumed: bool) -> dict:
    return {"status": "ready", "delivery": manifest["delivery"], "workspace": manifest["workspace"],
        "figures": len(manifest["documents"]), "numerical_processing": False,
        "prepared_plan_sha256": manifest["prepared_input"]["sha256"],
        "manual_edit": str(Path(manifest["delivery"]) / "Open_in_SciPlot.command"),
        "native_result": manifest["native_result"], "scientific_scope": manifest["scientific_scope"],
        **({"resumed": True} if resumed else {})}


def _verify_bound_native(workspace: Path, checkpoint: dict, compiled: dict, *, read_only: bool = False) -> None:
    from sciplot_core.rheology_tts_render_creation import check_native_continuation, verify_native_creation

    native = (check_native_continuation(compiled, workspace / "initial_render", completed=True) if read_only
              else verify_native_creation(compiled, workspace / "initial_render"))
    for item in native["figures"]:
        item["spec_sha256"] = file_sha256(Path(item["spec_path"]))
    if native != checkpoint["native_result"]:
        raise ValueError("Sealed native creation receipts changed before publication.")
    _check_sources(checkpoint["binding"]["sources"])
    prepared = checkpoint["binding"]["prepared_input"]
    if file_sha256(Path(prepared["path"])) != prepared["sha256"]:
        raise ValueError("Prepared numerical plan changed before publication.")


def _publication_inventory(root: Path, checkpoint: dict) -> dict[str, str]:
    _ordinary_tree(root)
    expected = _publication_files(checkpoint["binding"]["figure_ids"])
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_dir() and not any(name.startswith(relative + "/") for name in expected):
            raise ValueError("Unknown directory in prepared publication.")
        if path.suffix == ".command" and not path.stat().st_mode & 0o100:
            raise ValueError("Prepared publication launcher is not executable.")
    return file_inventory(root)


def _publication_evidence(workspace: Path, delivery: Path, checkpoint: dict, compiled: dict,
                          *, read_only: bool = False) -> tuple[Path, dict]:
    publication = checkpoint["publication"]
    if publication["attempt"] not in checkpoint["attempts"]:
        raise ValueError("Prepared publication is not a recorded stage.")
    stage = workspace / "publication_stages" / publication["attempt"]
    candidate = stage / "delivery"
    if checkpoint["phase"] == "completed" and (not delivery.is_dir() or not (workspace / "suite.json").is_file()):
        raise ValueError("Completed prepared delivery or manifest is missing; preserve and inspect.")
    manifest = json.loads((stage / "suite.json").read_text())
    if file_sha256(stage / "suite.json") != publication["manifest_sha256"]:
        raise ValueError("Prepared publication manifest changed.")
    _verify_bound_native(workspace, checkpoint, compiled, read_only=read_only)
    if delivery.exists():
        if candidate.exists() or _publication_inventory(delivery, checkpoint) != publication["files"]:
            raise ValueError("Visible delivery already exists or changed; creation recovery cannot overwrite it.")
    else:
        if _publication_inventory(candidate, checkpoint) != publication["files"]:
            raise ValueError("Prepared publication candidate changed.")
    _input_file(workspace / "suite.json", manifest, create=False)
    if json.loads(((delivery if delivery.exists() else candidate) / "data/delivery_manifest.json").read_text()) != manifest:
        raise ValueError("Prepared suite manifests disagree before installation.")
    return candidate, manifest


def _finish(workspace: Path, delivery: Path, checkpoint: dict, compiled: dict, *, resumed: bool) -> dict:
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
    return _result(manifest, resumed=resumed)


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


def _creation_binding(request: dict, spec: dict, compiled: dict, delivery: Path,
                      workspace: Path, contract_sha256: str) -> dict:
    return {"request": {**request, "prepared_plan": spec["source_binding"]["prepared_plan"]["path"],
                            "out": str(delivery)},
        "delivery": str(delivery), "workspace": str(workspace),
        "prepared_input": {k: spec["source_binding"]["prepared_plan"][k] for k in ("path", "sha256")},
        "sources": spec["source_binding"]["sources"], "contract_sha256": contract_sha256,
        "compiled_sha256": canonical_json_sha256(compiled), "figure_ids": [f["id"] for f in compiled["figures"]]}


def _resume_checkpoint(request_path: Path, workspace: Path, delivery: Path, binding: dict) -> dict:
    if not (workspace / CHECKPOINT).is_file():
        raise _blocked("No supported prepared creation checkpoint exists; do not recreate uncertain work.",
                       "prepared_creation_unknown_partial", request_path, workspace)
    reject_symlink_path((workspace / CHECKPOINT))
    checkpoint = read_json_object((workspace / CHECKPOINT))
    if (not isinstance(checkpoint, dict)
            or checkpoint.get("kind") != "sciplot_prepared_creation" or checkpoint.get("version") != 1
            or checkpoint.get("binding") != binding or checkpoint.get("phase") not in
            ("initialized", "native_complete", "publication_ready", "completed")):
        raise _blocked("Prepared creation bindings changed; the original request, plan, sources and contract must match.",
                       "prepared_creation_binding_changed", request_path, workspace)
    _validate_checkpoint(checkpoint, workspace)
    _known_workspace(workspace, checkpoint)
    if delivery.exists() and checkpoint["phase"] not in {"publication_ready", "completed"}:
        raise _blocked("A visible directory already exists before sealed publication; it cannot be overwritten.",
                       "prepared_creation_visible_conflict", request_path, workspace)
    return checkpoint


def check_prepared_continuation(request_path: Path, request: dict, spec: dict, compiled: dict,
                                delivery: Path, workspace: Path, binding: dict) -> dict:
    """Use the same read-only guards for continuation and its error guidance."""
    from sciplot_core.rheology_tts_render_creation import check_native_continuation
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities

    reject_symlink_path(request_path)
    if json.loads(request_path.read_text(encoding="utf-8")) != request:
        raise ValueError("Prepared creation request changed during execution; inspect the request.")
    current = _creation_binding(request, spec, compiled, delivery, workspace,
                                rheology_capabilities()["contract_sha256"])
    if current != binding:
        raise ValueError("Prepared creation contract changed during execution; inspect its evidence.")
    checkpoint = _resume_checkpoint(request_path, workspace, delivery, binding)
    for source in [*binding["sources"], binding["prepared_input"]]:
        reject_symlink_path(Path(source["path"]))
    _input_file(workspace / "request.json", binding["request"], create=False)
    _input_file(workspace / "figure_plan.json", spec, create=False)
    if checkpoint["phase"] in {"publication_ready", "completed"}:
        _publication_evidence(workspace, delivery, checkpoint, compiled, read_only=True)
    elif checkpoint["phase"] == "native_complete":
        _verify_bound_native(workspace, checkpoint, compiled, read_only=True)
    else:
        check_native_continuation(compiled, workspace / "initial_render")
    return checkpoint


def create_prepared_suite(request_path: Path, request: dict, spec: dict, compiled: dict,
                          delivery: Path, workspace: Path, *, contract_sha256: str, resume: bool) -> dict:
    from sciplot_core.workflow.rheology_tts_creation_repair import attach_creation_repair

    binding = _creation_binding(request, spec, compiled, delivery, workspace, contract_sha256)
    reject_symlink_path(workspace)
    reject_symlink_path(delivery)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(workspace):
        try:
            return _create_locked(request_path, request, spec, compiled, delivery, workspace, binding, resume=resume)
        except Exception as exc:
            attach_creation_repair(exc, request_path, workspace, check=lambda: check_prepared_continuation(
                request_path, request, spec, compiled, delivery, workspace, binding))
            raise


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
        return _finish(workspace, delivery, checkpoint, compiled, resumed=resume)
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
    return _finish(workspace, delivery, checkpoint, compiled, resumed=resume)

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
