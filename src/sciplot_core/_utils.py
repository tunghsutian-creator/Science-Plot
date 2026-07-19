from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.ingest import decode_text_file


def clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def token(value: object) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", clean_text(value).casefold())


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._-")
    return cleaned[:80] or "sciplot_project"


def safe_filename(value: str) -> str:
    name = Path(value).name
    cleaned = re.sub(r"[/:\\]+", "_", name).strip() or "file"
    return cleaned[:120]


def unique_path(directory: Path, filename: str) -> Path:
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def existing_file_sha256(path: Path) -> str | None:
    return file_sha256(path) if path.is_file() else None


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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
            json.dump(
                payload,
                handle,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return target


def decode_text(path: Path) -> str:
    return decode_text_file(path)


class suppress_decode:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> bool:
        return exc_type in {UnicodeError, OSError, ValueError}


def text_preview(path: Path, *, lines: int = 40) -> str:
    if path.is_dir():
        parts = [path.as_posix()]
        preview_files = [
            child
            for child in sorted(path.rglob("*"))
            if child.is_file() and child.suffix.lower() in {".csv", ".tsv", ".txt"}
        ]
        for child in preview_files[:3]:
            with suppress_decode():
                parts.append("\n".join(decode_text(child).splitlines()[:lines]))
        return "\n".join(parts)
    if not path.is_file():
        return path.as_posix()
    with suppress_decode():
        return "\n".join(decode_text(path).splitlines()[:lines])
    return path.as_posix()


__all__ = [
    "atomic_write_json",
    "clean_text",
    "decode_text",
    "existing_file_sha256",
    "file_sha256",
    "json_safe",
    "read_json_object",
    "safe_filename",
    "slug",
    "suppress_decode",
    "text_preview",
    "token",
    "unique_path",
]
