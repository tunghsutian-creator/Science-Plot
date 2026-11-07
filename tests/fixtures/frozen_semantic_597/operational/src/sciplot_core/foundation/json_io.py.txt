from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol


class _JsonFile(Protocol):
    def write(self, text: str, /) -> int: ...
    def flush(self) -> None: ...
    def fileno(self) -> int: ...


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_json_object(handle: _JsonFile, payload: dict[str, Any]) -> None:
    """Write the shared JSON encoding and fsync a caller-owned file stream."""
    json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Durably replace one JSON object without exposing a partial target."""

    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            write_json_object(handle, payload)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return target


__all__ = ["atomic_write_json", "read_json_object", "write_json_object"]
