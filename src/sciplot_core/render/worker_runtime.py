"""Prepare Veusz worker environment and recover terminal transform evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.veusz_runtime import veusz_worker_environment


def _veusz_worker_env() -> dict[str, str]:
    return veusz_worker_environment()


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _terminal_transform_steps(request_path: Path) -> list[dict[str, Any]]:
    """Read the runtime lineage persisted by the terminal Studio compiler."""

    request = _read_json_if_exists(request_path)
    ledger = (
        request.get("transform_ledger")
        if isinstance(request.get("transform_ledger"), dict)
        else {}
    )
    steps = ledger.get("steps") if isinstance(ledger.get("steps"), list) else []
    return [json_safe(step) for step in steps if isinstance(step, dict)]


def _extend_unique_transform_steps(
    target: list[dict[str, Any]],
    steps: object,
) -> None:
    if not isinstance(steps, list):
        return
    fingerprints = {
        json.dumps(json_safe(step), sort_keys=True, ensure_ascii=False)
        for step in target
    }
    for step in steps:
        if not isinstance(step, dict):
            continue
        normalized = json_safe(step)
        fingerprint = json.dumps(
            normalized,
            sort_keys=True,
            ensure_ascii=False,
        )
        if fingerprint in fingerprints:
            continue
        target.append(normalized)
        fingerprints.add(fingerprint)
