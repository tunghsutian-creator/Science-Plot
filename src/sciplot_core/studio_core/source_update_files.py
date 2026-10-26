"""Exact source/project file inventories without command application imports."""
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256


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
