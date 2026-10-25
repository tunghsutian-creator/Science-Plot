"""Read-only evidence for a prepared creation's safe next step, never an executor."""
from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime, resolve_runtime_path, literal_runtime_path
import sciplot_core.rheology_tts_render_creation as native_creation
from sciplot_core.rheology_tts_spec import compile_tts_spec
from sciplot_core.studio_core.source_update_commit import reject_symlink_path
from sciplot_core.workflow.rheology_tts_creation_inputs import _publication_files
from sciplot_core.workflow.rheology_tts_saved_state import _check_sources


def _members(root: Path, *, skip: set[str] | None = None) -> dict[str, Path]:
    reject_symlink_path(root)
    result = {}
    def visit(directory: Path, prefix: str = "") -> None:
        for entry in os.scandir(directory):
            if not prefix and entry.name in (skip or set()):
                continue
            relative = prefix + entry.name
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                visit(Path(entry.path), relative + "/")
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o7000:
                result[relative] = Path(entry.path)
            else:
                raise ValueError("Creation evidence has a symbolic, aliased or special member.")
    visit(root)
    return result


def _check_views(store: FileProjectStore, records: tuple[dict[str, Any], ...], parent: dict[str, Any]) -> bool:
    publications = [record for record in records if record["command_id"] == parent["command_id"] + ":publish"]
    publication = publications[0] if len(publications) == 1 else None
    pending = any(record.get("projection_pending") for record in records)
    if pending:
        committed = publication if publication and publication.get("committed_generation") else None
        if committed is None:
            candidates = [record for record in records if record.get("committed_generation")
                          and not record["write_set"] and (record["command_id"] == parent["command_id"]
                          or record["metadata"].get("request", {}).get("original_command") == parent["command_digest"])]
            if len(candidates) != 1:
                raise ValueError("A different command requires explicit recovery; creation guidance cannot repair it.")
            committed = candidates[0]
        # Metadata query has already verified this sealed descriptor. Accept
        # only absent pre-creation members or these exact committed bytes.
        expected = committed["draft"]["writes"]
        roots = {"": store.root, **store.locations}
        for key, binding in committed["resource_roots"].items():
            info = roots[key].stat()
            if {"device": info.st_dev, "inode": info.st_ino} != binding:
                raise ValueError("The creation resource root changed ownership.")
    else:
        current = store.snapshot()
        if current["projection_status"] != "current":
            raise ValueError("Saved creation views changed; preserve the current native authority.")
        expected = current["files"]
    skip = {".sciplot_store"}
    if any(path.is_relative_to(store.root / ".sciplot_resources") for path in store.locations.values()):
        skip.add(".sciplot_resources")
    actual = _members(store.root, skip=skip)
    for key, root in store.locations.items():
        actual.update({"@" + key + "/" + name: path for name, path in _members(root).items()})
    if set(actual) - set(expected):
        raise ValueError("Unknown files exceed the exact creation publication.")
    for name, path in actual.items():
        entry = expected[name]
        if (entry is None or file_sha256(path) != entry["sha256"]
                or path.stat().st_mode & 0o777 != entry["mode"]):
            raise ValueError("The creation publication changed after native validation.")
    if not pending and set(actual) != {name for name, entry in expected.items() if entry is not None}:
        raise ValueError("The creation publication has missing evidence.")
    return bool(publication and publication["phase"] == "complete" and not pending)


def inspect_creation_continuation(request: Path, workspace: Path) -> dict[str, Any]:
    """Verify original request/source/spec/native facts without changing a phase."""
    probe = FileProjectStore(workspace)
    parents = [record for record in probe.commands()
               if record.get("metadata", {}).get("request", {}).get("adapter") == "prepared_native_suite"
               and "continuation_of" not in record["metadata"]["request"]]
    if len(parents) != 1:
        raise ValueError("The original prepared creation command is not uniquely bound.")
    parent = parents[0]
    original = parent["metadata"]["request"]
    cold = (workspace / ".sciplot_store/local_locations.json").is_file()
    store = probe if cold else FileProjectStore(workspace, locations={"delivery": Path(original["binding"]["delivery"])})
    records = store.commands()
    parent = next(record for record in records if record["command_id"] == parent["command_id"])
    pending = any(record.get("projection_pending") for record in records)
    runtime = nullcontext() if pending else project_runtime(store)
    with runtime:
        reject_symlink_path(request)
        value = json.loads(request.read_bytes())
        if (value != original["request"] or file_sha256(request) != original["request_file"]["sha256"]
                or literal_runtime_path(request) != original["request_file"]["path"]):
            raise ValueError("The original prepared request changed.")
        binding = original["binding"]
        from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
        if rheology_capabilities()["contract_sha256"] != binding["contract_sha256"]:
            raise ValueError("The prepared creation contract changed.")
        for source in [*binding["sources"], binding["prepared_input"]]:
            reject_symlink_path(Path(source["path"]))
        _check_sources([*binding["sources"], binding["prepared_input"]])
        plan = resolve_runtime_path(binding["prepared_input"]["path"], expected_sha256=binding["prepared_input"]["sha256"])
        if file_sha256(plan) != binding["prepared_input"]["sha256"]:
            raise ValueError("Prepared numerical bytes changed.")
        working = Path(parent["native_workspace_path"])
        private = working / "workspace"
        allowed = {"request.json", "figure_plan.json", "analysis.json", "suite.json", "initial_render", "logs", ".sciplot_session_locks"}
        if private.exists() and any(item.name not in allowed for item in private.iterdir()):
            raise ValueError("Unknown private creation evidence requires inspection.")
        spec_path = private / "figure_plan.json"
        reject_symlink_path(spec_path)
        spec = json.loads(spec_path.read_bytes())
        compiled = compile_tts_spec(spec)
        if canonical_json_sha256(compiled) != binding["compiled_sha256"]:
            raise ValueError("The private scientific plan changed.")
        origin = Path(binding["workspace"]) / working.relative_to(store.root)
        expected_request = {**value, "prepared_plan": binding["prepared_input"]["path"], "out": str(origin / "delivery")}
        if json.loads((private / "request.json").read_bytes()) != expected_request:
            raise ValueError("Private request bindings changed.")
        delivery = working / "delivery"
        if delivery.exists() and set(_members(delivery)) - _publication_files(binding["figure_ids"]):
            raise ValueError("Unknown private publication files require inspection.")
        complete = _check_views(store, records, parent)
        fact = store.query(parent["command_id"] + ":native-fact")
        if fact is None and parent["phase"] not in {"complete", "accepted"}:
            failures = parent.get("native_failures", [])
            if not failures or not failures[-1]["owned_invocation_closed"]:
                raise ValueError("The original native invocation has no recorded closure.")
            out = private / "initial_render"
            if out.exists():
                native_creation.check_saved_native_creation(compiled, out)
            elif failures[-1]["renderer_dispatch_entered"]:
                raise ValueError("Native dispatch started without a verified saved receipt.")
        elif (private / "initial_render").exists():
            native_creation.check_saved_native_creation(compiled, private / "initial_render")
        return {"command_id": parent["command_id"], "phase": parent["phase"], "complete": complete}
