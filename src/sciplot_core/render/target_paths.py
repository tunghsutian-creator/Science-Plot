"""Allocate deterministic Veusz worker and artifact paths."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
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
    TERMINAL_SOURCE_PREPARED_ENV,
    sealed_terminal_source_binding_from_payload,
)


def _veusz_target_base(
    source: Path, template: str, *, panel_index: int | None = None
) -> str:
    base = f"{source.stem}_{template}"
    if panel_index is not None:
        base = f"{base}_part{panel_index:02d}"
    return base


def validated_terminal_worker_environment_base(
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Remove only owner-validated private terminal transport values."""

    candidate = dict(environment)
    encoded = candidate.pop(TERMINAL_SOURCE_BINDING_ENV, None)
    prepared = candidate.pop(TERMINAL_SOURCE_PREPARED_ENV, None)
    if encoded is not None:
        if not isinstance(encoded, str):
            raise ValueError("Terminal worker binding environment is invalid.")
        try:
            payload = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ValueError("Terminal worker binding environment is invalid.") from exc
        sealed_terminal_source_binding_from_payload(payload)
    if prepared not in (None, "1"):
        raise ValueError("Terminal worker prepared environment is invalid.")
    return candidate


def _render_studio_exports(
    request_path: Path,
    export_formats: tuple[str, ...],
    *,
    _terminal_source_binding: SealedTerminalSourceBinding | None = None,
    _terminal_source_prepared: bool = False,
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
    environment.pop(TERMINAL_SOURCE_PREPARED_ENV, None)
    if _terminal_source_binding is not None:
        environment[TERMINAL_SOURCE_BINDING_ENV] = (
            _terminal_source_binding.to_environment_value()
        )
    if _terminal_source_prepared:
        environment[TERMINAL_SOURCE_PREPARED_ENV] = "1"
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )
    return json.loads(result.stdout)
