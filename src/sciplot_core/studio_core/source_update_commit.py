"""Source-installation planning and shared generation publication; no direct writer."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, query_for_apply, whole_memberships

def reject_symlink_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"Source update cannot follow symbolic links: {part}")


def file_inventory(root: Path) -> dict[str, str]:
    reject_symlink_path(root)
    if root.is_symlink() or not root.exists():
        raise ValueError(f"Source update requires a real, existing path: {root}")
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    result = {}
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"Source update cannot follow symbolic links: {path}")
        if path.is_file():
            result[path.name if root.is_file() else str(path.relative_to(root))] = (
                file_sha256(path)
            )
    if not result:
        raise ValueError(f"Source update has no readable files: {root}")
    return result


def project_inventory(project: Path) -> dict[str, str]:
    reject_symlink_path(project)
    result = {}
    for path in sorted(project.iterdir()):
        if path.name in {"runs", "delivery", ".sciplot_store", ".sciplot_resources"}:
            continue
        if path.is_dir() and not any(path.iterdir()):
            continue
        result.update(
            {
                f"{path.name}/{name}" if path.is_dir() else name: digest
                for name, digest in file_inventory(path).items()
            }
        )
    return result


def relocate_metadata(value: Any, source: Path, target: Path) -> Any:
    if isinstance(value, dict):
        return {k: relocate_metadata(v, source, target) for k, v in value.items()}
    if isinstance(value, list):
        return [relocate_metadata(v, source, target) for v in value]
    if isinstance(value, str) and (
        value == str(source) or value.startswith(str(source) + "/")
    ):
        return str(target / Path(value).relative_to(source))
    return value


def _outcome_path(project: Path, review: dict[str, Any]) -> Path:
    identity = canonical_json_sha256(review, allow_nan=False)
    path = project.parent / ".source_update_operations" / project.name / identity / "outcome.json"
    reject_symlink_path(path)
    return path


def prior_source_update_result(project: Path, review: dict[str, Any], *, validate: Callable[[], object]) -> Path | None:
    """Query the shared receipt, or import proven legacy evidence without writing it."""
    app = ProjectCommands(project_store(project))
    key = canonical_json_sha256(review, allow_nan=False)
    record = query_for_apply(app, key)
    if record is not None:
        record = app.resume(ProjectCommand.from_payload(record["metadata"]))
        if record["phase"] == "reserved":
            return None
        validate()
        return Path(record["artifact_root"]) / "before"
    path = _outcome_path(project, review)
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record.get("review") != review or record.get("project") != str(project):
        raise ValueError("The historical source-update evidence changed")
    archive = Path(record["archive"])
    if archive.parent != project.parent / ".source_update_history" / project.name:
        raise ValueError("The historical source-update archive is not bound to this project")
    current = project_inventory(project)
    if current == record["result_files"] and record.get("status") != "rolled_back":
        if project_inventory(archive) != record["archived_files"]:
            raise ValueError("The historical source-update archive changed")
        validate()
        return archive
    if current == record["base_files"]:
        return None
    from sciplot_core.studio_core.source_update_recovery import restore_legacy_generation

    restore_legacy_generation(project, record, review)
    return None


def install_source_update(project: Path, candidate: Path, *, expected: dict[str, str],
                          validate: Callable[[], object], precommit: Callable[[], None] | None = None,
                          review: dict[str, Any] | None = None,
                          relocate_companion: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None) -> Path:
    """Compatibility admission for old reviewed calls; one new generation writer."""
    reject_symlink_path(project)
    file_inventory(candidate)
    if project_inventory(project) != expected:
        raise ValueError("The project changed after preview; inspect again before updating")
    if precommit is not None:
        precommit()
    # Domain validation runs against the complete isolated candidate before any
    # active path is replaced. New v2 previews freeze this same result at preview.
    validate()
    from sciplot_core.studio_core.source_update_commands import source_mutation

    repository = project_store(project, with_snapshot=True)
    snapshot = repository.snapshot(import_legacy=True)
    binding = {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
               "files": {name: value["sha256"] for name, value in snapshot["files"].items()},
               "read_memberships": whole_memberships(repository, snapshot)}
    evidence = review or {"kind": "source_update_compatibility", "base_files": expected,
                          "candidate_files": project_inventory(candidate)}
    writes, artifacts = source_mutation(project, candidate, evidence,
                                        relocate_companion=relocate_companion, expected=expected, store=repository)
    key = canonical_json_sha256(evidence, allow_nan=False)
    command = command_for_binding(repository, binding, kind="source_update", key=key,
                                   writes=list(writes), request={"review_sha256": key})
    completed = ProjectCommands(repository).execute(command,
        lambda: ProjectMutation(writes, {"status": "updated", "review_sha256": key}, artifacts=artifacts))
    return Path(completed["artifact_root"]) / "before"
