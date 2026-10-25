"""Read and validate preserved v1 creation history without installing or restarting it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import re
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.studio_core.source_update_commit import file_inventory, reject_symlink_path
from sciplot_core.workflow.rheology_tts_saved_state import _check_sources, _compiled_figures
from sciplot_core.workflow.rheology_tts_creation_inputs import CHECKPOINT, _input_file, _publication_files, _creation_binding
from sciplot_core.workflow.rheology_tts_creation_repair import _blocked

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


def _validate_checkpoint(checkpoint: dict[str, Any], workspace: Path) -> None:
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


def _known_workspace(workspace: Path, checkpoint: dict[str, Any]) -> None:
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


def _verify_bound_native(workspace: Path, checkpoint: dict[str, Any], compiled: dict[str, Any], *, read_only: bool = False) -> None:
    from sciplot_core.rheology_tts_render_creation import check_native_continuation, verify_native_creation

    native = (check_native_continuation(compiled, workspace / "initial_render", completed=True) if read_only
              else verify_native_creation(compiled, workspace / "initial_render"))
    if native is None:
        raise ValueError("Native creation has no complete source-bound receipt.")
    for item in native["figures"]:
        item["spec_sha256"] = file_sha256(Path(item["spec_path"]))
    if native != checkpoint["native_result"]:
        raise ValueError("Sealed native creation receipts changed before publication.")
    _check_sources(checkpoint["binding"]["sources"])
    prepared = checkpoint["binding"]["prepared_input"]
    if file_sha256(Path(prepared["path"])) != prepared["sha256"]:
        raise ValueError("Prepared numerical plan changed before publication.")


def _publication_inventory(root: Path, checkpoint: dict[str, Any]) -> dict[str, str]:
    _ordinary_tree(root)
    expected = _publication_files(checkpoint["binding"]["figure_ids"])
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_dir() and not any(name.startswith(relative + "/") for name in expected):
            raise ValueError("Unknown directory in prepared publication.")
        if path.suffix == ".command" and not path.stat().st_mode & 0o100:
            raise ValueError("Prepared publication launcher is not executable.")
    return file_inventory(root)


def _publication_evidence(workspace: Path, delivery: Path, checkpoint: dict[str, Any], compiled: dict[str, Any],
                          *, read_only: bool = False) -> tuple[Path, dict[str, Any]]:
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


def _resume_checkpoint(request_path: Path, workspace: Path, delivery: Path, binding: dict[str, Any]) -> dict[str, Any]:
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


def check_prepared_continuation(request_path: Path, request: dict[str, Any], spec: dict[str, Any], compiled: dict[str, Any],
                                delivery: Path, workspace: Path, binding: dict[str, Any]) -> dict[str, Any]:
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

