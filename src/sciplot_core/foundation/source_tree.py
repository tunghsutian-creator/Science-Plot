"""Compute relocation-stable fingerprints for file or directory sources."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def source_tree_sha256(source: Path | None) -> str | None:
    """Hash one file or a directory's ordered relative file set."""

    if source is None:
        return None
    resolved = source.expanduser().resolve()
    if resolved.is_file():
        payload: dict[str, object] = {
            "kind": "file",
            "content_sha256": file_sha256(resolved),
        }
    elif resolved.is_dir():
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
