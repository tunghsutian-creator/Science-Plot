"""Authorize loopback sessions and selected source paths."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from sciplot_core.foundation.path_names import safe_filename
from sciplot_core._paths import PACKAGE_ROOT, resolved_path_is_within


_STATIC_DIR = PACKAGE_ROOT / "intake" / "intake_static"


_MAX_JSON_BODY_BYTES = 128 * 1024 * 1024


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().strip("[]").casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _session_source_paths(output_root: Path, session_id: object) -> set[Path]:
    raw_session_id = str(session_id or "").strip()
    if not raw_session_id or safe_filename(raw_session_id) != raw_session_id:
        return set()
    session_path = output_root / "sessions" / f"{raw_session_id}.json"
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    try:
        recorded_root = (
            Path(str(payload.get("output_root") or "")).expanduser().resolve()
        )
    except (OSError, RuntimeError, ValueError):
        return set()
    if recorded_root != output_root:
        return set()
    allowed: set[Path] = set()
    groups = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        files = group.get("files") if isinstance(group.get("files"), list) else []
        for item in files:
            if not isinstance(item, dict):
                continue
            value = item.get("source_path")
            if not isinstance(value, str) or not value.strip():
                continue
            try:
                allowed.add(Path(value).expanduser().resolve())
            except (OSError, RuntimeError, ValueError):
                continue
    return allowed


def _authorized_source_path(
    value: object,
    *,
    output_root: Path,
    session_id: object = None,
) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Source path is required.")
    resolved = Path(text).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    if resolved_path_is_within(
        resolved, output_root
    ) or resolved in _session_source_paths(output_root, session_id):
        return resolved
    raise PermissionError(
        "Browser source paths must belong to the active CLI-created session "
        "or the configured SciPlot output root."
    )
