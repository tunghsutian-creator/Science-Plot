"""Hash fixture files for evidence comparison."""

from __future__ import annotations

import hashlib
from pathlib import Path
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.evidence.json_sources import (
    _fixture_files,
)


def _fixture_hash_inventory(fixture: Path) -> tuple[list[dict[str, str]], str | None]:
    files = _fixture_files(fixture)
    inventory: list[dict[str, str]] = []
    tree_digest = hashlib.sha256()
    for path in files:
        relative = (
            path.name if fixture.is_file() else path.relative_to(fixture).as_posix()
        )
        sha256 = file_sha256(path)
        inventory.append({"path": relative, "sha256": sha256})
        tree_digest.update(relative.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(sha256.encode("ascii"))
        tree_digest.update(b"\n")
    return inventory, tree_digest.hexdigest() if inventory else None
