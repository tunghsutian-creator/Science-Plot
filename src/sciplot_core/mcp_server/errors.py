"""Bounded, machine-readable adapter failures without traceback disclosure."""

from __future__ import annotations

import logging
from typing import Any

from jsonschema.exceptions import ValidationError


class AdapterError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def error_payload(exc: Exception) -> dict[str, Any]:
    reason_code = getattr(exc, "reason_code", None)
    if isinstance(exc, AdapterError):
        code, message = exc.code, str(exc)
    elif isinstance(exc, ValueError) and isinstance(reason_code, str):
        code, message = reason_code, str(exc)
    elif isinstance(exc, ValidationError):
        location = "/".join(str(part) for part in exc.absolute_path) or "arguments"
        code, message = "invalid_arguments", f"Invalid {location}: {exc.message}"
    elif isinstance(exc, FileNotFoundError):
        code, message = "path_not_found", str(exc)
    elif isinstance(exc, PermissionError):
        code, message = "path_access_denied", str(exc)
    elif isinstance(exc, ValueError):
        message = str(exc)
        lower = message.lower()
        if "stale" in lower or "changed" in lower:
            code = "stale_revision"
        elif "writable" in lower or "native window" in lower:
            code = "project_open_for_editing"
        elif "unit" in lower:
            code = "unit_mismatch"
        elif "ambiguous" in lower:
            code = "ambiguous_target"
        else:
            code = "operation_rejected"
    else:
        logging.getLogger(__name__).exception("SciPlot MCP operation failed")
        code = "execution_failed"
        message = "The local operation failed. Inspect the task or project before retrying."
    return {
        "kind": "sciplot_control_error",
        "version": 1,
        "status": "error",
        "error": {"code": code, "message": message[:1200]},
        "ready_to_use": False,
    }
