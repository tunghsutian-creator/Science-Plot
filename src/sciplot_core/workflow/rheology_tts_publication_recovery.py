"""Seal a suite publication intent before install; recover exact installed bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot


def seal_publication(directory: Path, preview: dict[str, Any], updates: list[tuple[Path, Path]],
                     candidates: dict[str, str], result: dict[str, Any]) -> None:
    raise RuntimeError("Independent publication intents are retired; freeze the candidate in ProjectCommands.")


def _require_files(value: Any, expected: set[str] | None) -> None:
    if (not isinstance(value, dict) or not isinstance(value.get("result"), dict)
            or not isinstance(value.get("published_files"), dict)
            or any(not isinstance(name, str) or not isinstance(sha, str) or len(sha) != 64
                   or any(char not in "0123456789abcdef" for char in sha)
                   for name, sha in value["published_files"].items())):
        raise ValueError("Legacy installed publication lacks an exact typed file witness.")
    if expected is not None and set(value["published_files"]) != expected:
        raise ValueError("Legacy publication does not prove its exact installed resource set.")


def recover_publication(directory: Path, preview: dict[str, Any]) -> dict[str, Any] | None:
    installed = read_publication(directory, preview)
    if installed is None:
        return None
    evidence, _paths = installed
    return {**evidence["result"], "already_applied": True, "recovered_publication": True}


def read_publication(directory: Path, preview: dict[str, Any], *,
                     expected_files: set[str] | None = None) -> tuple[dict[str, Any], tuple[Path, ...]] | None:
    """Read preserved exact installed evidence; never install or rewrite it."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

    applied = directory / "applied.json"
    reject_symlink_path(applied)
    if applied.exists():
        value = json.loads(applied.read_text(encoding="utf-8"))
        _require_files(value, expected_files)
        check_snapshot(value["published_files"], label="previously applied presentation")
        return value, (applied,)
    intents = directory / "publication_intents"
    reject_symlink_path(intents)
    for path in sorted(intents.glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
        reject_symlink_path(path)
        seal = path.with_suffix(".sha256")
        reject_symlink_path(seal)
        if not seal.exists():
            # An interrupted intent write precedes publication; no installed
            # state can be claimed from this incomplete preparation.
            continue
        intent = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(intent, dict) or intent.get("kind") != "sciplot_rheology_publication_intent"
                or intent.get("version") != 1 or canonical_json_sha256(intent) != seal.read_text(encoding="ascii")
                or intent["preview_sha256"] != canonical_json_sha256(preview)):
            raise ValueError("Publication recovery intent changed; preserve and inspect.")
        _require_files(intent, expected_files)
        try:
            check_snapshot(intent["published_files"], label="exact installed presentation")
        except (ValueError, FileNotFoundError):
            continue
        return intent, (path, seal)
    return None
