"""Import byte-proven legacy interruption into one shared recovery generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, whole_memberships


def installation_identity(record: dict[str, Any]) -> str:
    return canonical_json_sha256({key: record[key] for key in (
        "project", "review", "archive", "base_files", "archived_files", "result_files", "replacement_names")}, allow_nan=False)


def restore_legacy_generation(project: Path, record: dict[str, Any], review: dict[str, Any]) -> None:
    from sciplot_core.studio_core.source_update_files import project_inventory, reject_symlink_path

    if (record.get("version") != 2 or record.get("status") not in {"pending", "recovering"}
            or record.get("installation_sha256") != installation_identity(record)):
        raise ValueError("The legacy source update needs inspection; preserve all evidence")
    archive = Path(record["archive"])
    reject_symlink_path(archive)
    current, archived = project_inventory(project), project_inventory(archive)
    base, result = record["base_files"], record["result_files"]
    names = record["replacement_names"]
    if (not isinstance(names, list)
            or any(not isinstance(name, str) or Path(name).name != name or name in {
                ".", "..", "runs", "delivery", ".sciplot_store", ".sciplot_resources"} for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("The legacy installation paths are invalid")
    writes: dict[str, bytes | Path | None] = {}
    artifacts: dict[str, bytes | Path] = {}
    for name in set(current) | set(base):
        actual = current.get(name)
        if name.split("/", 1)[0] not in names:
            if actual != base.get(name):
                raise ValueError("Unknown outside changes block legacy source recovery")
            continue
        if actual not in {base.get(name), result.get(name), None}:
            raise ValueError("Unknown native/source bytes block legacy recovery")
        if actual is not None:
            artifacts["interrupted/" + name] = (project / name).read_bytes()
        expected = base.get(name)
        if expected is None:
            writes[name] = None
        elif actual == expected:
            writes[name] = (project / name).read_bytes()
        elif archived.get(name) == expected:
            writes[name] = (archive / name).read_bytes()
        else:
            raise ValueError("The exact legacy baseline is not available for recovery")
    repository = project_store(project)
    snapshot = repository.snapshot(import_legacy=True)
    binding = {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
               "files": {name: value["sha256"] for name, value in snapshot["files"].items()},
               "read_memberships": whole_memberships(repository, snapshot)}
    key = "legacy-source-recovery:" + canonical_json_sha256(review)
    command = command_for_binding(repository, binding, kind="source_update", key=key,
        writes=list(writes), request={"legacy_installation": record["installation_sha256"], "recovery": "baseline"})
    ProjectCommands(repository).execute(command,
        lambda: ProjectMutation(writes, {"status": "baseline_restored"}, artifacts=artifacts))
