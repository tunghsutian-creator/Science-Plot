"""Install reviewed source, document, and metadata together with rollback."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.project_manifest import locked_intake_project_manifest
from sciplot_core.studio_core.launchers import _write_veusz_launcher


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
        if path.name in {"runs", "delivery"}:
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


def prior_source_update_result(
    project: Path, review: dict[str, Any], *, validate: Callable[[], object],
) -> Path | None:
    """Recover only byte-proven completion or an untouched baseline.

    A hard interruption during the multi-part installation is deliberately not
    interpreted as success. Its archived original files remain available for
    explicit recovery; normal exceptions use the existing rollback below.
    """
    path = _outcome_path(project, review)
    if not path.exists():
        return None
    with locked_intake_project_manifest(project):
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(record, dict) or record.get("review") != review
            or record.get("project") != str(project)
            or record.get("status") not in {"pending", "applied", "rolled_back"}
        ):
            raise ValueError("The source-update recovery record changed; preserve its evidence.")
        archive = Path(record["archive"])
        expected_parent = project.parent / ".source_update_history" / project.name
        if archive.parent != expected_parent or len(archive.name) != 32:
            raise ValueError("The source-update archive has an invalid recorded location.")
        reject_symlink_path(archive)
        current = project_inventory(project)
        if current == record["result_files"] and record["status"] != "rolled_back":
            if not archive.is_dir() or project_inventory(archive) != record["archived_files"]:
                raise ValueError("The source-update archive changed; preserve its evidence.")
            validate()
            if project_inventory(project) != current:
                raise ValueError("The project changed during source-update recovery.")
            record["status"] = "applied"
            atomic_write_json(path, record)
            return archive
        if (
            current == record["base_files"] and record["status"] != "applied"
            and (not archive.exists() or not any(archive.iterdir()))
        ):
            return None
        raise ValueError(
            "The source update is interrupted or its result has changed. "
            f"Preserve the project and archive for recovery: {archive}"
        )


def install_source_update(
    project: Path,
    candidate: Path,
    *,
    expected: dict[str, str],
    validate: Callable[[], object],
    precommit: Callable[[], None] | None = None,
    review: dict[str, Any] | None = None,
) -> Path:
    """Keep old runtime history; atomically replace each reviewed active part."""
    reject_symlink_path(project)
    file_inventory(candidate)
    archive = project.parent / ".source_update_history" / project.name / uuid4().hex
    reject_symlink_path(archive)
    staged_paths = [
        p for p in candidate.iterdir() if p.name not in {"runs", "delivery"}
    ]
    names = sorted(p.name for p in staged_paths)
    if not {"plot_request.json", "studio", "source", "raw"}.issubset(names):
        raise ValueError(
            "Prepared source update is missing required active project parts."
        )
    for path in [*candidate.glob("*.json"), *(candidate / "studio").rglob("*.json")]:
        value = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(
            json.dumps(
                relocate_metadata(value, candidate, project),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if (candidate / "Open_in_Veusz.command").exists():
        _write_veusz_launcher(candidate, project / "studio" / "document.vsz")
    with locked_intake_project_manifest(project):
        if project_inventory(project) != expected:
            raise ValueError(
                "The project changed after preview; inspect it again before updating."
            )
        if precommit is not None:
            precommit()
        outcome_path = _outcome_path(project, review) if review is not None else None
        record: dict[str, Any] | None = None
        if outcome_path is not None:
            replaced_names = set(names)
            archived_files = {
                key: digest for key, digest in expected.items()
                if key.split("/", 1)[0] in replaced_names
            }
            record = {
                "kind": "sciplot_source_update_outcome", "version": 1,
                "status": "pending", "project": str(project), "review": review,
                "archive": str(archive), "base_files": expected,
                "archived_files": archived_files,
                "result_files": {
                    **{key: digest for key, digest in expected.items() if key not in archived_files},
                    **project_inventory(candidate),
                },
            }
            atomic_write_json(outcome_path, record)
        archive.mkdir(parents=True)
        moved: list[str] = []
        installed: list[str] = []
        try:
            for name in names:
                original = project / name
                if original.exists():
                    os.replace(original, archive / name)
                    moved.append(name)
                os.replace(candidate / name, original)
                installed.append(name)
            validate()
        except BaseException as exc:
            errors = []
            for name in reversed(installed):
                try:
                    os.replace(project / name, candidate / name)
                except OSError as error:
                    errors.append(str(error))
            for name in reversed(moved):
                try:
                    os.replace(archive / name, project / name)
                except OSError as error:
                    errors.append(str(error))
            if errors:
                raise RuntimeError(
                    f"Source update rollback needs recovery from {archive}: {errors}"
                ) from exc
            shutil.rmtree(archive)
            if outcome_path is not None and record is not None:
                record["status"] = "rolled_back"
                atomic_write_json(outcome_path, record)
            raise
        if outcome_path is not None and record is not None:
            # This write is outside the rollback block. A lost receipt after a
            # validated install is recoverable from the already durable intent.
            record["status"] = "applied"
            atomic_write_json(outcome_path, record)
    return archive


__all__ = [
    "file_inventory",
    "project_inventory",
    "relocate_metadata",
    "install_source_update",
    "prior_source_update_result",
]
