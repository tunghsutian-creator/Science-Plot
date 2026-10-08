"""Bounded transport errors; complete diagnostic text remains local and inspectable."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
import tempfile
from typing import Any

MESSAGE_LIMIT = 360


def short_error_message(message: str) -> str:
    """Bound narration, never the structured scientific fields that explain it."""
    return message if len(message) <= MESSAGE_LIMIT else message[:MESSAGE_LIMIT - 1] + "…"


def exception_feedback(exc: Exception, *, summary: str | None = None) -> dict[str, Any]:
    """Preserve long pre-task failures privately instead of discarding their tail."""
    message = str(exc) or type(exc).__name__
    display = message if summary is None else summary
    result: dict[str, Any] = {"message": short_error_message(display)}
    # A transport may already carry the original owner's saved diagnostics.
    # Preserve that reference even when its human-readable message is short.
    existing_diagnostics = getattr(exc, "diagnostics", None)
    if isinstance(existing_diagnostics, dict):
        result["diagnostics"] = deepcopy(existing_diagnostics)
    field = getattr(exc, "field", None)
    if field:
        result["field"] = "/" + str(field).lstrip("/")
    issues = getattr(exc, "issues", None)
    if isinstance(issues, list) and issues and getattr(exc, "repair", None) is None:
        result["issues"] = deepcopy(issues[:8])
        if len(issues) > 8:
            result["issues"].append({"remaining_issue_count": len(issues) - 8})
    if len(display) <= MESSAGE_LIMIT:
        return result
    diagnostic = existing_diagnostics or getattr(exc, "_sciplot_diagnostic", None)
    if diagnostic is None:
        name: str | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix="sciplot-error-", suffix=".json")
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"exception_type": type(exc).__name__,
                           "reason_code": getattr(exc, "reason_code", None),
                           "message": message}, stream, ensure_ascii=False)
            diagnostic = {"path": str(Path(name).resolve()), "json_pointer": "/message"}
            exc.__dict__["_sciplot_diagnostic"] = diagnostic
        except Exception as error:
            if name is not None:
                try:
                    Path(name).unlink(missing_ok=True)
                except OSError:
                    pass
            # Diagnostic storage is auxiliary: never replace the original failure
            # or silently lose its tail when a full local copy cannot be written.
            return {**result, "message": message,
                    "diagnostics_unavailable": short_error_message(str(error))}
        except BaseException:
            if name is not None:
                try:
                    Path(name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
    result["diagnostics"] = diagnostic
    return result
