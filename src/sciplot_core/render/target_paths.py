"""Allocate deterministic Veusz worker and artifact paths."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core.render.worker_runtime import (
    _veusz_worker_env,
)


def _veusz_target_base(
    source: Path, template: str, *, panel_index: int | None = None
) -> str:
    base = f"{source.stem}_{template}"
    if panel_index is not None:
        base = f"{base}_part{panel_index:02d}"
    return base


def _render_studio_exports(
    request_path: Path, export_formats: tuple[str, ...]
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "sciplot_core.veusz_worker",
        "export",
        str(request_path),
        "--formats",
        ",".join(export_formats),
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=True,
        env=_veusz_worker_env(),
    )
    return json.loads(result.stdout)
