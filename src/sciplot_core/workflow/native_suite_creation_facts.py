"""Seal source-bound native completion facts and finish saved exports without Save replay."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.project_commands.errors import ProjectCommandUnknown
from sciplot_core.workflow.native_suite_generation import command_for, mutation, saved_command

def _prepared_mutation(store: Any, candidate: ProjectMutation, sources: list[dict[str, Any]]) -> ProjectMutation:
    from sciplot_core.project_commands import PreparedSource
    from sciplot_core.workflow.native_suite_generation import candidate_file, source_versions
    prepared = []
    for source in source_versions(store, sources):
        registered = store.snapshot()["sources"].get(source["source_id"], {}).get(source["version"])
        path = (store.resolve_path(source["path"], expected_sha256=source["version"], source_id=source["source_id"])
                if registered is not None else Path(source["path"]))
        captured = candidate_file(path, source["version"], unaliased=False)
        prepared.append(PreparedSource(source["source_id"], source["path"], source["version"], captured.data,
                                       mode=registered["mode"] if registered else captured.mode))
    return ProjectMutation(candidate.writes, candidate.result, review=candidate.review,
                           artifacts=candidate.artifacts, prepared_sources=tuple(prepared))


def _seal_native_fact(store: Any, command: Any, compiled: dict[str, Any], out: Path, result: dict[str, Any],
                      sources: list[dict[str, Any]]) -> None:
    from sciplot_core.workflow.native_suite_generation import candidate_file, canonical_sha
    from sciplot_core.rheology_tts_render_creation import check_native_continuation
    from sciplot_core.foundation.file_hashing import file_sha256
    before = {path.relative_to(out).as_posix(): file_sha256(path) for path in out.rglob("*") if path.is_file()}
    verified = check_native_continuation(compiled, out, completed=True)
    if verified is None:
        raise ValueError("A native fact requires complete source/spec/audit-bound renderer evidence.")
    from sciplot_core.project_store.runtime import resolve_runtime_path
    for item in verified["figures"]:
        item["spec_sha256"] = file_sha256(resolve_runtime_path(item["spec_path"]))
    if verified != result:
        raise ValueError("Renderer reply differs from its complete read-only native proof.")
    artifacts, inventory, modes = {}, {}, {}
    for source in out.rglob("*"):
        if source.is_symlink():
            raise ValueError("Native fact contains a symbolic entry.")
        if source.is_file():
            name = source.relative_to(out).as_posix()
            captured = candidate_file(source, before[name])
            artifacts[name] = captured
            inventory[name] = canonical_sha(captured.data)
            modes[name] = captured.mode
    if set(inventory) != set(before):
        raise ValueError("Native fact inventory changed during its read-only proof.")
    candidate = _prepared_mutation(store, ProjectMutation({},
        {"adapter": "native_suite_renderer_fact", "original_command": command.command_digest,
         "native_result": result, "inventory": inventory, "modes": modes}, artifacts=artifacts), sources)
    request = {"adapter": "native_suite_renderer_fact", "original_command": command.command_digest,
               "prepared_digest": candidate.prepared_digest}
    app = ProjectCommands(store)
    key = command.key + ":native-fact"
    fact = saved_command(app, key, request)
    if fact is None:
        fact = command_for(store, "attachment_import", key, request=request, reads=[], writes=[])
    app.publish_prepared(fact, candidate)


def _verify_native_fact(fact: dict[str, Any], out: Path) -> None:
    from sciplot_core.workflow.native_suite_generation import candidate_file
    if fact.get("phase") != "complete":
        raise ProjectCommandUnknown()
    expected = fact["result"]["inventory"]
    files = {path.relative_to(out).as_posix(): path for path in out.rglob("*") if path.is_file()}
    if set(files) != set(expected):
        raise ValueError("The original sealed native fact inventory changed.")
    for name, path in files.items():
        if candidate_file(path, expected[name]).mode != fact["result"]["modes"][name]:
            raise ValueError("The sealed native file mode changed before recovery.")


def _finish_saved_exports(store: Any, parent: Any, workspace: Path, sources: list[dict[str, Any]]) -> None:
    from sciplot_core.rheology_tts_spec import compile_tts_spec
    from sciplot_core.rheology_tts_render_creation import check_native_continuation, check_saved_native_creation
    from sciplot_core.rheology_tts_render import complete_tts_creation_exports
    from sciplot_core.project_store.runtime import project_runtime
    out = workspace / "initial_render"
    with project_runtime(store):
        compiled = compile_tts_spec(json.loads((workspace / "figure_plan.json").read_bytes()))
        try:
            check_native_continuation(compiled, out, completed=True)
            return
        except ValueError:
            proof = check_saved_native_creation(compiled, out)
        request = {"adapter": "native_suite_creation_exports", "original_command": parent.command_digest,
                   "saved_native": proof}
        app = ProjectCommands(store)
        key = parent.key + ":exports"
        command = saved_command(app, key, request)
        if command is None:
            command = command_for(store, "native_export", key, request=request, reads=[], writes=[])
        else:
            app.resume(command)  # unsealed unknown export never reexecutes
        def prepare() -> ProjectMutation:
            result = complete_tts_creation_exports(compiled, out)
            for item in result["figures"]:
                from sciplot_core.project_store.runtime import resolve_runtime_path
                from sciplot_core.foundation.file_hashing import file_sha256
                item["spec_sha256"] = file_sha256(resolve_runtime_path(item["spec_path"]))
            _seal_native_fact(store, parent, compiled, out, result, sources)
            return mutation(store, {}, {"export_status": "completed", "native_command": parent.key}, sources=sources)
        app.execute(command, prepare)

