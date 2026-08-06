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
from sciplot_core.terminal_source_binding import (
    SealedTerminalSourceBinding,
)
from sciplot_core.terminal_source_binding_wire import (
    TERMINAL_SOURCE_BINDING_ENV,
)


def _veusz_target_base(
    source: Path, template: str, *, panel_index: int | None = None
) -> str:
    base = f"{source.stem}_{template}"
    if panel_index is not None:
        base = f"{base}_part{panel_index:02d}"
    return base


def _render_studio_exports(
    request_path: Path,
    export_formats: tuple[str, ...],
    *,
    _terminal_source_binding: SealedTerminalSourceBinding | None = None,
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
    environment = _veusz_worker_env()
    environment.pop(TERMINAL_SOURCE_BINDING_ENV, None)
    if _terminal_source_binding is not None:
        environment[TERMINAL_SOURCE_BINDING_ENV] = (
            _terminal_source_binding.to_environment_value()
        )
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )
    return json.loads(result.stdout)
