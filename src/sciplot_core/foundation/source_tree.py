"""Compute relocation-stable fingerprints for file or directory sources."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.foundation.source_locations import resolve_source_path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def source_tree_sha256(source: Path | None, *, expected_file_sha256: str | None = None) -> str | None:
    """Hash one file or a directory's ordered relative file set."""

    if source is None:
        return None
    resolved = resolve_source_path(source, expected_sha256=expected_file_sha256).expanduser().resolve()
    if resolved.is_file():
        content = file_sha256(resolved)
        if expected_file_sha256 is not None and content != expected_file_sha256:
            raise ValueError("The source file changed from its exact declared byte version.")
        payload: dict[str, object] = {
            "kind": "file",
            "content_sha256": content,
        }
    elif resolved.is_dir():
        if expected_file_sha256 is not None:
            raise ValueError("A directory composite cannot use a file content hash.")
        payload = {
            "kind": "directory",
            "files": [
                {
                    "path": path.relative_to(resolved).as_posix(),
                    "content_sha256": file_sha256(path),
                }
                for path in sorted(resolved.rglob("*"))
                if path.is_file()
            ],
        }
    else:
        return None
    return canonical_json_sha256(payload, allow_nan=False)


__all__ = ["source_tree_sha256"]
