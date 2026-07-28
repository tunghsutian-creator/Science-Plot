"""Declare autoplot state and result-path contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


AUTOPLOT_MODEL_KIND = "sciplot_autoplot_result"


AUTOPLOT_MODEL_VERSION = 2


_VALID_STATES = {"ready", "needs_human_confirmation", "needs_rule_repair"}


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _truthy_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _manifest_path(run_output: Path) -> Path:
    return run_output / "manifest.json"


def _one_step_status_path(run_output: Path) -> Path:
    return run_output / "one_step_status.json"


def _delivery_package(
    one_step: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    for payload in (one_step.get("delivery_package"), manifest.get("delivery_package")):
        if isinstance(payload, dict):
            return payload
    return {}
