"""Content identities for copied source and relocatable release candidates."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_snapshot(repo: Path) -> dict[str, str]:
    """Cover copied application code, routing instructions and build tooling."""
    roots = ("src", "skill", "distribution", "third_party/veusz")
    files = [repo / name for name in ("pyproject.toml", "README.md", "LICENSE", "docs/THIRD_PARTY_NOTICES.md", "docs/PUBLIC_BETA.md")]
    for name in roots:
        files.extend((repo / name).rglob("*"))
    return {
        str(path.relative_to(repo)): file_hash(path)
        for path in sorted(files)
        if path.is_file() and not set(path.parts) & {"__pycache__", ".git", "build"}
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix != ".pyc" and path.name != ".DS_Store"
    }


def content_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def bundle_snapshot(app: Path) -> dict[str, dict]:
    """Include permissions and internal links; reject links outside the app."""
    root = app.resolve(strict=True)
    records = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(root):
                raise ValueError(f"Bundle link escapes application: {relative}")
            records[relative] = {"link": os.readlink(path)}
        elif path.is_file():
            records[relative] = {"sha256": file_hash(path), "mode": path.stat().st_mode & 0o777}
    if not records:
        raise ValueError("Application bundle is empty")
    return records
