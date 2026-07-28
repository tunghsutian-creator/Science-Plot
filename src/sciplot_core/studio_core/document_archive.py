"""Archive a manually edited document before generated replacement."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)

from sciplot_core.studio_core.figure_set_state import (
    _registered_figure_generated_hash,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_path,
    _registered_generated_hash,
)


def _archive_manual_document_if_needed(
    project_dir: Path,
    document_path: Path,
    *,
    generated_hash: str | None = None,
) -> None:
    if not document_path.exists():
        return
    current_hash = existing_file_sha256(document_path)
    generated_hash = generated_hash or (
        _registered_generated_hash(project_dir)
        if document_path.name == "document.vsz"
        else _registered_figure_generated_hash(project_dir, document_path)
    )
    if generated_hash and current_hash == generated_hash:
        return
    history_dir = document_path.parent / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + f"_{uuid4().hex[:8]}"
    destination = history_dir / f"{document_path.stem}_{stamp}{document_path.suffix}"
    shutil.copy2(document_path, destination)
    spec_path = _veusz_spec_path(document_path)
    if spec_path.exists():
        shutil.copy2(spec_path, history_dir / f"{document_path.stem}_{stamp}.spec.json")
