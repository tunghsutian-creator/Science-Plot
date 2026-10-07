"""Bounded, machine-readable adapter failures without traceback disclosure."""

from __future__ import annotations

import logging
from typing import Any

from jsonschema.exceptions import ValidationError

from sciplot_core.task_error_feedback import exception_feedback, short_error_message


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
    # ValidationError.__str__ repeats the whole public schema even for a tiny
    # field typo. Its constraint message carries the actual rejected value.
    feedback = exception_feedback(exc, summary=message if isinstance(exc, ValidationError) else None)
    repair = getattr(exc, "repair", None)
    return {
        "kind": "sciplot_control_error",
        "version": 1,
        "status": "error",
        "error": {"code": code, "message": (feedback["message"] if "diagnostics_unavailable" in feedback
                                              else short_error_message(message)),
                  **({"field": feedback["field"]} if "field" in feedback else {})},
        **({"diagnostics": feedback["diagnostics"]} if "diagnostics" in feedback else {}),
        **({"diagnostics_unavailable": feedback["diagnostics_unavailable"]} if "diagnostics_unavailable" in feedback else {}),
        **({"issues": feedback["issues"]} if "issues" in feedback else {}),
        **({"repair": repair} if repair is not None else {}),
        "ready_to_use": False,
    }
