"""First native creation: seal private effects, then publish the entire project.

Native creation and publication are explicit commands in the same repository.
A reply lost after native completion discovers its sealed artifacts. An unknown
native command never executes again; active originals were never native inputs.
"""
from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import tempfile
from typing import Any

from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.workflow.native_suite_generation import (
    command_for, command_key, mutation, open_store, saved_command,
)


def _path(value: str, pairs: tuple[tuple[Path, Path], ...]) -> str:
    for before, after in pairs:
        if value == str(before) or value.startswith(str(before) + "/"):
            return str(after) + value[len(str(before)):]
    return value


def _remap(value: Any, pairs: tuple[tuple[Path, Path], ...]) -> Any:
    """Translate only declared native receipt/host path fields, never science."""
    fields = {"workspace", "delivery", "document", "export_dir", "native_audit_path", "spec_path",
              "path", "manual_edit", "plot", "out"}
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in fields and isinstance(item, str):
                result[key] = _path(item, pairs)
            elif key == "exports" and isinstance(item, list) and all(isinstance(entry, str) for entry in item):
                result[key] = [_path(entry, pairs) for entry in item]
            else:
                result[key] = _remap(item, pairs)
        return result
    if isinstance(value, list):
        return [_remap(item, pairs) for item in value]
    return value


def create_project(workspace: Path, delivery: Path, request: dict[str, Any], sources: list[dict[str, Any]],
                   prepare: Callable[[Path, Path], dict[str, Any]], *, resume: bool = False) -> dict[str, Any]:
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    from sciplot_core.workflow.rheology_tts_suite import _check_sources

    for path in (workspace, delivery):
        reject_symlink_path(path)
    store_exists = (workspace / ".sciplot_store/head.json").is_file()
    if not store_exists and (workspace.exists() or delivery.exists()):
        raise FileExistsError("Existing native creation evidence requires explicit inspection/import; it cannot be recreated.")
    workspace.mkdir(parents=True, exist_ok=True)
    delivery.mkdir(parents=True, exist_ok=True)
    store = open_store(workspace, delivery)
    app = ProjectCommands(store)
    key = command_key("native_create", request)
    command = saved_command(app, key, request)
    if command is not None:
        prior = app.resume(command)
        frozen_sources = prior.get("draft", {}).get("sources", {})
        if frozen_sources:
            sources = [{"source_id": identity, "path": entry["locator"], "sha256": version}
                       for identity, versions in frozen_sources.items() for version, entry in versions.items()]
    if command is None:
        if resume or store.snapshot()["files"]:
            raise FileExistsError("No matching sealed native creation command exists; preserve the project.")
        command = command_for(store, "native_create", key, request=request, reads=[], writes=[])
    with tempfile.TemporaryDirectory(prefix="sciplot-native-create-") as temporary:
        root = Path(temporary).resolve()
        candidate_workspace, candidate_delivery = root / "workspace", root / "delivery"
        def native_prepare() -> ProjectMutation:
            result = prepare(candidate_workspace, candidate_delivery)
            pairs = ((candidate_workspace, workspace), (candidate_delivery, delivery))
            artifacts, modes = {}, {}
            for source_root, target_root in pairs:
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
                    data = source.read_bytes()
                    if source.suffix == ".json":
                        value = json.loads(data)
                        mapped = _remap(value, pairs)
                        if mapped != value:
                            data = (json.dumps(mapped, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
                    elif source.suffix == ".command":
                        from sciplot_core.workflow.rheology_tts_suite import _launcher
                        if source.name == "Update_exports.command":
                            _launcher(source, ["rheology", "export", str(workspace), "--json"])
                        elif source.name.startswith("Open_") and source.parent.name == "editable":
                            identifier = source.stem[len("Open_"):]
                            _launcher(source, ["studio", str(delivery / "editable" / (identifier + ".vsz"))])
                        elif source.name in {"Open_in_SciPlot.command", "Open_in_Veusz.command"}:
                            manifest = json.loads((candidate_workspace / "suite.json").read_bytes())
                            _launcher(source, ["studio", _path(manifest["documents"][0]["path"], pairs)])
                        elif any(str(before).encode() in data for before, _after in pairs):
                            raise ValueError("An unknown launcher cannot publish private candidate paths.")
                        data = source.read_bytes()
                    artifacts[logical] = data
                    modes[logical] = source.stat().st_mode & 0o777
            _check_sources(sources)
            return mutation(store, {}, {"adapter": "native_suite_create", "result": _remap(result, pairs),
                "files": modes, "publication_key": key + ":publish", "commit_status": "pending"},
                sources=sources, artifacts=artifacts)
        native = app.execute(command, native_prepare)
        publish_request = {"adapter": "native_suite_create_publication", "parent": command.command_digest,
                           "candidate": native["decision_id"]}
        publication = saved_command(app, key + ":publish", publish_request)
        targets = [workspace / name if not name.startswith("@delivery/") else delivery / name[len("@delivery/"):]
                   for name in native["result"]["files"]]
        if publication is None:
            publication = command_for(store, "create", key + ":publish", request=publish_request,
                                      reads=[], writes=targets)
        def publish_prepare() -> ProjectMutation:
            updates = {}
            for index, (logical, mode) in enumerate(native["result"]["files"].items()):
                sealed = Path(native["artifact_paths"][logical])
                candidate = root / "publish" / str(index)
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_bytes(sealed.read_bytes())
                candidate.chmod(mode)
                target = workspace / logical if not logical.startswith("@delivery/") else delivery / logical[len("@delivery/"):]
                updates[target] = candidate
            _check_sources(sources)
            return mutation(store, updates, native["result"]["result"], sources=sources)
        staged = app.preview(publication, publish_prepare)
        completed = app.decide(publication, decision_id=staged["decision_id"], accept=True)
    result = completed["result"]
    if "plot_objects" in result:
        from sciplot_core.workflow.rheology_tts_creation_handles import created_object_handles
        from sciplot_core.workflow.rheology_tts_suite import _compiled_figures
        manifest = json.loads(store.read_bytes("suite.json"))
        result = {**result, "plot_objects": created_object_handles(manifest,
                  {"figures": list(_compiled_figures(manifest).values())})}
    return {**result, "generation": completed["generation"], "resumed": resume}
