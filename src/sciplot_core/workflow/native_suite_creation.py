"""First native creation: seal private effects, then publish the entire project.

Native creation and publication are explicit commands in the same repository.
A reply lost after native completion discovers its sealed artifacts. An unknown
native command never executes again; active originals were never native inputs.
"""
from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import PreparedFile, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.errors import ProjectCommandUnknown
from sciplot_core.workflow.native_suite_generation import (
    command_for, command_key, mutation, open_store, saved_command,
)


from sciplot_core.workflow.native_suite_creation_projection import _path, _remap
from sciplot_core.workflow.native_suite_creation_facts import (
    _prepared_mutation, _seal_native_fact, _verify_native_fact, _finish_saved_exports,
)


def create_project(workspace: Path, delivery: Path, request: dict[str, Any], sources: list[dict[str, Any]],
                   prepare: Callable[[Path, Path], dict[str, Any]], *, resume: bool = False,
                   recover_prepare: Callable[[Path, Path, Path, Path], dict[str, Any]] | None = None) -> dict[str, Any]:
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources

    for path in (workspace, delivery):
        reject_symlink_path(path)
    store_exists = (workspace / ".sciplot_store/head.json").is_file()
    if store_exists and not resume:
        raise FileExistsError("A recorded native creation already exists; explicitly resume its exact request or export the saved suite.")
    if not store_exists and (workspace.exists() or delivery.exists()):
        raise FileExistsError("Existing native creation evidence requires explicit inspection/import; it cannot be recreated.")
    workspace.mkdir(parents=True, exist_ok=True)
    delivery.mkdir(parents=True, exist_ok=True)
    key = command_key("native_create", request)
    if store_exists:
        # Exact saved identity is checked before recovery may install a view.
        from sciplot_core.project_store import FileProjectStore
        from sciplot_core.workflow.native_suite_runtime import current_store
        active = current_store()
        store = active if active is not None and active.root == workspace else FileProjectStore(workspace, locations={"delivery": delivery})
        app = ProjectCommands(store)
        command = saved_command(app, key, request)
        if command is None:
            raise FileExistsError("No matching native creation owns this selected request; no recovery performed.")
        store.recover()
    else:
        store = open_store(workspace, delivery)
        app = ProjectCommands(store)
        command = None
    prior = None
    unknown = False
    if command is not None:
        try:
            prior = app.resume(command)
        except ProjectCommandUnknown:
            prior, unknown = app.query(key), True
        assert prior is not None
        continuation_record = app.query(key + ":not-started") if unknown else None
        if continuation_record is not None:
            from sciplot_core.project_commands import ProjectCommand
            command = ProjectCommand.from_payload(continuation_record["metadata"])
            try:
                prior, unknown = app.resume(command), False
            except ProjectCommandUnknown:
                prior, unknown = continuation_record, True
        frozen_sources = prior.get("draft", {}).get("sources", {})
        if frozen_sources:
            sources = [{"source_id": identity, "path": entry["locator"], "sha256": version}
                       for identity, versions in frozen_sources.items() for version, entry in versions.items()]
    if command is None:
        if resume or store.snapshot()["files"]:
            raise FileExistsError("No matching sealed native creation command exists; preserve the project.")
        command = command_for(store, "native_create", key, request=request, reads=[], writes=[], whole=True)
        store.reserve(command.key, command.command_digest, expected_generation=command.expected_generation,
            read_set=dict(command.read_set), write_set=command.write_set, metadata=command.to_payload(),
            projected_reads=[item.to_payload() for item in command.projected_reads])
    # Freeze admitted source versions before native dispatch. This is the same
    # repository's finite source map, including cold recovery with originals gone.
    input_key = command.key + ":inputs"
    input_record = app.query(input_key)
    if input_record is None:
        candidate = _prepared_mutation(store, ProjectMutation({},
            {"adapter": "native_suite_creation_inputs", "original_command": command.command_digest,
             "source_bindings": [{"path": item["path"], "sha256": item["sha256"]} for item in sources]}), sources)
        input_request = {"adapter": "native_suite_creation_inputs", "original_command": command.command_digest,
                         "prepared_digest": candidate.prepared_digest}
        inputs = command_for(store, "attachment_import", input_key, request=input_request, reads=[], writes=[])
        app.publish_prepared(inputs, candidate)
    else:
        from sciplot_core.project_commands import ProjectCommand
        inputs = ProjectCommand.from_payload(input_record["metadata"])
        if inputs.to_payload()["request"].get("original_command") != command.command_digest:
            raise ValueError("Creation inputs belong to another exact original command.")
        sealed_inputs = app.resume(inputs)
        expected_sources = [{"path": item["path"], "sha256": item["sha256"]} for item in sources]
        if sealed_inputs.get("result", {}).get("source_bindings") != expected_sources:
            raise ValueError("Original creation source versions changed; no native continuation is admitted.")
        if sealed_inputs["phase"] != "complete":
            raise ProjectCommandUnknown()
    # The claimed directory is part of the admitted command, not a disposable
    # temp path. A failed native operation retains its exact artifacts/inode.
    def native_prepare() -> ProjectMutation:
        assert command is not None
        root = store.claim_native_workspace(command.key, command.command_digest, "native_suite_create_v1")
        candidate_workspace, candidate_delivery = root / "workspace", root / "delivery"
        from sciplot_core.rheology_tts_native_invocation import observe_native_creation
        def completed_native(compiled: dict[str, Any], out: Path, result: dict[str, Any]) -> None:
            _seal_native_fact(store, command, compiled, out, result, sources)
        from sciplot_core.project_store.runtime import project_runtime
        with project_runtime(store), observe_native_creation(completed_native) as observation:
            try:
                result = dict(prepare(candidate_workspace, candidate_delivery))
            except Exception as exc:
                try:
                    store.append_native_failure(command.key, command.command_digest,
                        original_error=(type(exc).__name__ + ": " + str(exc))[:16384],
                        renderer_dispatch_entered=observation.dispatch_entered,
                        owned_invocation_closed=observation.owned_invocation_closed)
                except Exception as recording_error:
                    try:
                        exc.add_note("Native failure record could not be persisted: " + str(recording_error))
                    except Exception:
                        pass
                raise
        return collect(result, candidate_workspace, candidate_delivery)

    def collect(result: dict[str, Any], candidate_workspace: Path, candidate_delivery: Path) -> ProjectMutation:
        expected_files = result.pop("_candidate_files")
        seen = set()
        io_pairs = ((candidate_workspace, workspace), (candidate_delivery, delivery))
        origins = store.snapshot()["locators"]
        pairs = ((candidate_workspace, Path(origins[""])), (candidate_delivery, Path(origins["delivery"])))
        artifacts, modes = {}, {}
        for source_root, target_root in io_pairs:
            for source in source_root.rglob("*"):
                relative = source.relative_to(source_root)
                # Candidate-only effect/checkpoint/backup history is sealed
                # evidence, not a second active project journal or head.
                if any(name in {".creation", "publication_stages", ".sciplot_session_locks", "logs"}
                       for name in relative.parts) or source.name == "creation_checkpoint.json":
                    continue
                if not source.is_file() or source.is_symlink():
                    if source.is_symlink():
                        raise ValueError("Native creation candidates must contain ordinary files.")
                    continue
                logical = store.logical_path(target_root / relative)
                from sciplot_core.workflow.native_suite_generation import candidate_file
                captured = candidate_file(source, expected_files[str(source)])
                data = captured.data
                seen.add(str(source))
                if source.suffix == ".json":
                    value = json.loads(data)
                    mapped = _remap(value, pairs)
                    if mapped != value and source.name.endswith(".spec.json"):
                        raise ValueError("Scientific sidecars cannot contain private candidate locators.")
                    if mapped != value:
                        data = (json.dumps(mapped, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
                elif source.suffix == ".command":
                    from sciplot_core.workflow.rheology_tts_delivery_files import launcher_bytes
                    if source.name == "Update_exports.command":
                        data = launcher_bytes(["rheology", "export", str(workspace), "--json"])
                    elif source.name.startswith("Open_") and source.parent.name == "editable":
                        identifier = source.stem[len("Open_"):]
                        data = launcher_bytes(["studio", str(delivery / "editable" / (identifier + ".vsz"))])
                    elif source.name in {"Open_in_SciPlot.command", "Open_in_Veusz.command"}:
                        manifest = json.loads((candidate_workspace / "suite.json").read_bytes())
                        data = launcher_bytes(["studio", _path(manifest["documents"][0]["path"], pairs)])
                    elif any(str(before).encode() in data for before, _after in pairs):
                        raise ValueError("An unknown launcher cannot publish private candidate paths.")
                    if not source.stat().st_mode & 0o100:
                        raise ValueError("A native launcher candidate must retain executable permission.")
                mode = captured.mode
                artifacts[logical] = PreparedFile(data, mode)
                modes[logical] = mode
        if seen != set(expected_files):
            raise ValueError("Creation candidate inventory is incomplete or contains undeclared files.")
        _check_sources(sources)
        return mutation(store, {}, {"adapter": "native_suite_create", "result": _remap(result, pairs),
            "files": modes, "publication_key": key + ":publish", "commit_status": "pending"},
            sources=sources, artifacts=artifacts)
    recovered = None
    if unknown:
        previous_import = app.query(command.key + ":verified")
        if previous_import is not None:
            from sciplot_core.project_commands import ProjectCommand
            imported_command = ProjectCommand.from_payload(previous_import["metadata"])
            imported_request = imported_command.to_payload()["request"]
            if (imported_request.get("adapter") != "native_suite_verified_effect_import"
                    or imported_request.get("original_command") != command.command_digest):
                raise ValueError("Verified native recovery belongs to another exact original command.")
            recovered = app.resume(imported_command)
            if recovered["phase"] == "needs_review":
                if recovered.get("review", {}).get("publication") != "prepared_storage":
                    raise ProjectCommandUnknown()
                recovered = app.decide(imported_command, decision_id=recovered["decision_id"], accept=True)
            unknown = False
    if unknown:
        assert prior is not None
        root = store.claim_native_workspace(command.key, command.command_digest, "native_suite_create_v1")
        original_workspace, original_delivery = root / "workspace", root / "delivery"
        fact = app.query(command.key + ":native-fact")
        failures = prior.get("native_failures", [])
        closed = bool(failures and failures[-1]["owned_invocation_closed"])
        if fact is not None:
            from sciplot_core.project_commands import ProjectCommand
            fact_command = ProjectCommand.from_payload(fact["metadata"])
            fact_request = fact_command.to_payload()["request"]
            if (fact_request.get("adapter") != "native_suite_renderer_fact"
                    or fact_request.get("original_command") != command.command_digest
                    or fact.get("review", {}).get("publication") != "prepared_storage"):
                raise ValueError("The saved native fact is not this command's exact prepared evidence.")
            if fact["phase"] == "needs_review":
                fact = app.decide(fact_command, decision_id=fact["decision_id"], accept=True)
            else:
                fact = app.resume(fact_command)
            _verify_native_fact(fact, original_workspace / "initial_render")
        elif not closed:
            raise ProjectCommandUnknown()
        native_files = list(original_workspace.rglob("*.vsz"))
        if not native_files:
            if (not closed or failures[-1]["renderer_dispatch_entered"]
                    or (original_workspace / "initial_render").exists()):
                raise ProjectCommandUnknown()
            # A new admitted identity is allowed only by proven pre-dispatch,
            # closed, zero-effect evidence. The original command stays unknown.
            continuation_request = {**request, "continuation_of": command.command_digest}
            continuation_key = command.key + ":not-started"
            continuation = saved_command(app, continuation_key, continuation_request)
            if continuation is None:
                continuation = command_for(store, "native_create", continuation_key,
                    request=continuation_request, reads=[], writes=[], whole=True)
            command = continuation
            native = app.execute(command, native_prepare)
        else:
            if recover_prepare is None:
                raise ProjectCommandUnknown()
            # Read-only domain proof runs against the exact original renderer
            # receipt, then only pure publication is rebuilt in a fresh directory.
            import tempfile
            recovery = Path(tempfile.mkdtemp(prefix="publication-", dir=root))
            try:
                _finish_saved_exports(store, command, original_workspace, sources)
                result = recover_prepare(original_workspace, original_delivery,
                                         recovery / "workspace", recovery / "delivery")
                candidate = collect(dict(result), recovery / "workspace", recovery / "delivery")
                candidate = _prepared_mutation(store, candidate, sources)
                recovery_request = {"adapter": "native_suite_verified_effect_import",
                    "original_command": command.command_digest, "prepared_digest": candidate.prepared_digest}
                recovery_key = command.key + ":verified"
                recovery_command = saved_command(app, recovery_key, recovery_request)
                if recovery_command is None:
                    recovery_command = command_for(store, "attachment_import", recovery_key,
                        request=recovery_request, reads=[], writes=[], whole=True)
                native = app.publish_prepared(recovery_command, candidate)
            finally:
                import shutil
                shutil.rmtree(recovery)
    else:
        native = recovered if recovered is not None else app.execute(command, native_prepare)
    publish_request = {"adapter": "native_suite_create_publication", "parent": command.command_digest,
                       "candidate": native["decision_id"]}
    publication = saved_command(app, key + ":publish", publish_request)
    targets = [workspace / name if not name.startswith("@delivery/") else delivery / name[len("@delivery/"):]
               for name in native["result"]["files"]]
    if publication is None:
        publication = command_for(store, "create", key + ":publish", request=publish_request,
                                  reads=[], writes=targets, whole=True)
    def publish_prepare() -> ProjectMutation:
        updates = {}
        for logical, mode in native["result"]["files"].items():
            sealed = Path(native["artifact_paths"][logical])
            target = workspace / logical if not logical.startswith("@delivery/") else delivery / logical[len("@delivery/"):]
            updates[target] = PreparedFile(sealed.read_bytes(), mode)
        _check_sources(sources)
        return mutation(store, updates, native["result"]["result"], sources=sources)
    staged = app.preview(publication, publish_prepare)
    completed = app.decide(publication, decision_id=staged["decision_id"], accept=True)
    _check_sources(sources)
    current = store.snapshot()
    if current["projection_status"] != "current":
        raise ValueError("Created project resources changed before the current result could be returned.")
    result = completed["result"]
    if result.pop("_creation_handles", False) or "plot_objects" in result:
        from sciplot_core.workflow.rheology_tts_creation_handles import created_object_handles
        from sciplot_core.workflow.rheology_tts_saved_state import _compiled_figures
        from sciplot_core.project_store.runtime import project_runtime
        with project_runtime(store):
            manifest = json.loads(store.read_bytes("suite.json"))
            result = {**result, "plot_objects": created_object_handles(manifest,
                      {"figures": list(_compiled_figures(manifest).values())})}
    result.update(workspace=str(workspace), delivery=str(delivery))
    if "manual_edit" in result:
        result["manual_edit"] = str(delivery / "Open_in_SciPlot.command")
    return {**result, "generation": completed["generation"], "resumed": resume}
