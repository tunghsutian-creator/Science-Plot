"""Parse CLI values, validate input paths, and print JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _coerce_sheet(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value


def _resolve_input(path: Path, *, kind: str = "Input") -> Path:
    """Expand and existence-check a user-supplied path before handing it on.

    Produces a clear ``Input not found: PATH`` instead of leaking a raw
    ``[Errno 2]`` from deep in the loader.
    """
    resolved = path.expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"{kind} not found: {path}")
    return resolved


_RECOGNITION_ERROR_MARKERS = (
    "recognize",
    "numeric curve series",
    "unsupported file format",
    "must match",
    "no numeric",
)


def _cli_runtime_error_payload(
    exc: Exception,
    *,
    recovery_hint: str | None = None,
) -> dict[str, Any]:
    """Return the single machine-readable contract for CLI runtime failures."""

    expected = isinstance(exc, (OSError, ValueError))
    category = "expected_runtime_failure" if expected else "internal_error"
    payload: dict[str, Any] = {
        "kind": "sciplot_cli_runtime_error",
        "version": 1,
        "status": "failed",
        "category": category,
        "reason_code": f"cli_{category}",
        "exception_type": type(exc).__name__,
        "message": str(exc) or type(exc).__name__,
    }
    if recovery_hint:
        payload["recovery_hint"] = recovery_hint
    return payload


def _recovery_hint(input_path: Path | None) -> str:
    target = str(input_path) if input_path is not None else "<input>"
    return f"Hint: run `sciplot inspect {target} --json` to see how SciPlot read the table, reshape it as a 2-column curve / replicate / heatmap table, or prepare an editable Veusz project with `sciplot studio {target}`."


def _load_options(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    if value.startswith("@"):
        return json.loads(Path(value[1:]).expanduser().read_text(encoding="utf-8"))
    return json.loads(value)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
