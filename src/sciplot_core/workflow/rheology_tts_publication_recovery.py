"""Seal a suite publication intent before install; recover exact installed bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot


def seal_publication(directory: Path, preview: dict[str, Any], updates: list[tuple[Path, Path]],
                     candidates: dict[str, str], result: dict[str, Any]) -> None:
    files = {str(target.resolve()): candidates[str(source.resolve())] for source, target in updates}
    if len(files) != len(updates):
        raise ValueError("Duplicate publication intent target.")
    intent = {"kind": "sciplot_rheology_publication_intent", "version": 1,
              "preview_sha256": canonical_json_sha256(preview), "published_files": files, "result": result}
    path = directory / "publication_intents" / (uuid4().hex + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, intent)
    path.with_suffix(".sha256").write_text(canonical_json_sha256(intent), encoding="ascii")


def recover_publication(directory: Path, preview: dict[str, Any]) -> dict[str, Any] | None:
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

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
        try:
            check_snapshot(intent["published_files"], label="exact installed presentation")
        except (ValueError, FileNotFoundError):
            continue
        applied = {"published_files": intent["published_files"], "result": intent["result"]}
        atomic_write_json(directory / "applied.json", applied)
        return {**intent["result"], "already_applied": True, "recovered_publication": True}
    return None
