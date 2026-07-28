"""Normalize and validate primitive values used by mapping contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from sciplot_core.json_contract import (
    require_json_int,
    require_json_list,
    require_json_object,
)

from sciplot_core.mapping_contract.constants import (
    _SAFE_ID,
    _SHA256,
    _FORBIDDEN_EXECUTABLE_KEYS,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _absolute_path(value: object, label: str) -> str:
    text = _required_text(value, label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path.")
    return str(path.resolve())


def _timestamp(value: object, label: str) -> str:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset.")
    return text


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


def _free_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    return value.strip()


def _text_parameter(
    parameters: dict[str, Any],
    key: str,
    *,
    default: str,
    label: str,
) -> str:
    if key not in parameters:
        return default
    return _required_text(parameters[key], label)


def _safe_id(value: object, label: str) -> str:
    text = _required_text(value, label)
    if _SAFE_ID.fullmatch(text) is None:
        raise ValueError(
            f"{label} must use 1-96 ASCII letters, digits, dot, underscore, or dash."
        )
    return text


def _sha256(value: object, label: str) -> str:
    digest = _required_text(value, label).casefold()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _relative_source_path(value: object) -> str:
    text = _required_text(value, "relative_path")
    if "\\" in text:
        raise ValueError("Data source relative_path must use POSIX separators.")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(
            "Data source relative_path must remain inside the declared source root."
        )
    return path.as_posix()


def _text_list(
    value: object,
    *,
    label: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = require_json_list(value, label=label)
    result = tuple(_required_text(item, f"{label} item") for item in items)
    if not allow_empty and not result:
        raise ValueError(f"{label} must not be empty.")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain unique values.")
    return result


def _int_list(value: object, *, label: str) -> tuple[int, ...]:
    items = require_json_list(value, label=label)
    result = tuple(require_json_int(item, label=f"{label} item") for item in items)
    if any(item < 0 for item in result):
        raise ValueError(f"{label} values must be non-negative.")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain unique values.")
    return result


def _reject_executable_keys(value: Any, *, path: str = "parameters") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in _FORBIDDEN_EXECUTABLE_KEYS:
                raise ValueError(
                    f"{path}.{key} is executable content and is not allowed."
                )
            _reject_executable_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_executable_keys(item, path=f"{path}[{index}]")


def _string_mapping(value: object, *, label: str) -> dict[str, str]:
    payload = require_json_object(value, label=label)
    result = {
        _required_text(key, f"{label} key"): _required_text(item, f"{label}[{key!r}]")
        for key, item in payload.items()
    }
    if not result:
        raise ValueError(f"{label} must not be empty.")
    return result
