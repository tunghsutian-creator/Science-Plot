"""Resolve request inputs and allocate or archive Studio run paths."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def _canonical_publish_paths(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
) -> tuple[Path, Path, Path]:
    """Bind publication to one project's canonical request and primary VSZ."""

    project = project_dir.expanduser().resolve()
    request = request_path.expanduser().resolve()
    document = document_path.expanduser().resolve()
    if request != (project / "plot_request.json").resolve():
        raise RuntimeError(
            "A project delivery receipt can use only the canonical "
            "project/plot_request.json. A foreign or relocated request cannot "
            "publish into this project."
        )
    if document != (project / "studio" / "document.vsz").resolve():
        raise RuntimeError(
            "A project delivery receipt can be published only from the "
            "canonical project/studio/document.vsz. Registered secondary "
            "figures are exported automatically into the same project receipt."
        )
    return project, request, document


def _next_studio_run_dir(project_dir: Path) -> Path:
    runs_dir = project_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = runs_dir / f"studio_{index:03d}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            index += 1
        else:
            return candidate


def _resolve_request_input(request: dict[str, Any], *, base_dir: Path) -> Path | None:
    value = request.get("input")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _archive_studio_input(input_path: Path, output_dir: Path) -> dict[str, Any]:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / input_path.name
    if input_path.is_dir():
        shutil.copytree(input_path, destination)
        kind = "directory"
    else:
        shutil.copy2(input_path, destination)
        kind = "file"
    return {"kind": kind, "source": str(input_path), "path": str(destination)}
