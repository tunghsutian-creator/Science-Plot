"""Load the owner-confirmed human daily-use validation record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core._paths import PACKAGE_ROOT
from sciplot_core.readiness.validation import (
    _closed_object,
    _required_int,
    _required_text,
    _text_list,
    _timestamp,
)


DEFAULT_HUMAN_DAILY_USE_VALIDATION = PACKAGE_ROOT / "human_daily_use_validation.json"

_REQUIRED_SCOPE = frozenset(
    {
        "veusz_first_daily_use",
        "owner_operated_validation",
    }
)


def load_human_daily_use_validation(
    path: Path | None = None,
) -> dict[str, Any]:
    resolved = (path or DEFAULT_HUMAN_DAILY_USE_VALIDATION).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Human daily-use validation record not found: {resolved}"
        )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Human daily-use validation record is not valid JSON."
        ) from exc
    parsed = _closed_object(
        payload,
        label="human daily-use validation",
        expected=frozenset(
            {
                "kind",
                "version",
                "status",
                "confirmed_at",
                "confirmed_by",
                "scope",
                "limitations",
            }
        ),
    )
    kind = _required_text(parsed["kind"], "human daily-use validation kind")
    if kind != "sciplot_human_daily_use_validation":
        raise ValueError("Human daily-use validation kind is not supported.")
    version = _required_int(
        parsed["version"],
        "human daily-use validation version",
        minimum=1,
    )
    if version != 1:
        raise ValueError(f"Unsupported human daily-use validation version {version}.")
    status = _required_text(
        parsed["status"],
        "human daily-use validation status",
    )
    if status != "passed":
        raise ValueError("Human daily-use validation status must be passed.")
    confirmed_by = _required_text(
        parsed["confirmed_by"],
        "human daily-use validation confirmed_by",
    )
    if confirmed_by != "project_owner":
        raise ValueError(
            "Human daily-use validation must be confirmed by the project owner."
        )
    scope = _text_list(parsed["scope"], "human daily-use validation scope")
    missing_scope = sorted(_REQUIRED_SCOPE - set(scope))
    if missing_scope:
        raise ValueError(
            "Human daily-use validation scope is incomplete: "
            + ", ".join(missing_scope)
        )
    return {
        "kind": kind,
        "version": version,
        "status": status,
        "confirmed_at": _timestamp(
            parsed["confirmed_at"],
            "human daily-use validation confirmed_at",
        ),
        "confirmed_by": confirmed_by,
        "scope": list(scope),
        "limitations": list(
            _text_list(
                parsed["limitations"],
                "human daily-use validation limitations",
                maximum_items=32,
                maximum_text=4096,
            )
        ),
    }
