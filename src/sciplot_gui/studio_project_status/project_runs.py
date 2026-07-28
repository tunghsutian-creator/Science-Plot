"""Load project manifests and select the latest registered Studio run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core._paths import resolved_path_is_within


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload


def _request_path_value(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _validate_project_request_pair(
    project_dir: Path | None,
    request_path: Path | None,
) -> None:
    if (project_dir is None) != (request_path is None):
        raise ValueError("project_dir and request_path must be provided together.")


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _project_manifest_payload(project_dir: Path) -> dict[str, Any]:
    candidates = [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            return _read_json(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return {}


def _registered_manifest_candidates(
    project_dir: Path,
    project_manifest: dict[str, Any],
) -> list[Path]:
    resolved_project = project_dir.expanduser().resolve()
    runs_root = (resolved_project / "runs").resolve()
    local_candidates = [
        candidate.resolve()
        for candidate in reversed(
            sorted((resolved_project / "runs").glob("studio_*/manifest.json"))
        )
    ]
    registered_candidates: list[Path] = []
    studio = (
        project_manifest.get("studio")
        if isinstance(project_manifest.get("studio"), dict)
        else {}
    )
    last_export = (
        studio.get("last_export_run")
        if isinstance(studio.get("last_export_run"), dict)
        else {}
    )
    last_run = (
        project_manifest.get("last_run")
        if isinstance(project_manifest.get("last_run"), dict)
        else {}
    )
    for value in (
        last_export.get("manifest"),
        Path(str(last_export["output"])) / "manifest.json"
        if last_export.get("output")
        else None,
        Path(str(last_run["output"])) / "manifest.json"
        if last_run.get("output")
        else None,
    ):
        if value is None:
            continue
        candidate = Path(str(value)).expanduser()
        if not candidate.is_absolute():
            candidate = resolved_project / candidate
        registered_candidates.append(candidate.resolve())
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in [*local_candidates, *registered_candidates]:
        if (
            candidate.name != "manifest.json"
            or not resolved_path_is_within(candidate, runs_root)
            or candidate in seen
        ):
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _latest_project_run(
    project_dir: Path,
    project_manifest: dict[str, Any],
    *,
    request: dict[str, Any],
) -> tuple[Path | None, dict[str, Any]]:
    request_digest = _canonical_json_sha256(request)
    for candidate in _registered_manifest_candidates(project_dir, project_manifest):
        if not candidate.is_file():
            continue
        snapshot_path = candidate.parent / "request_snapshot.json"
        try:
            snapshot = _read_json(snapshot_path)
            manifest = _read_json(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if _canonical_json_sha256(snapshot) != request_digest:
            continue
        manifest_request = manifest.get("request")
        if (
            isinstance(manifest_request, dict)
            and _canonical_json_sha256(manifest_request) != request_digest
        ):
            continue
        return candidate, manifest
    return None, {}
