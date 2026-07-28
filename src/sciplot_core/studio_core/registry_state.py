"""Describe registered Studio document, specification, figure-set, and run state."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.operation_modes import normal_mode_payload

from sciplot_core.studio_core.runtime import (
    upstream_status,
)

from sciplot_core.studio_core.json_files import (
    _read_json,
)


def _studio_figure_set_path(project_dir: Path) -> Path:
    return project_dir / "studio" / "figure_set.json"


def _veusz_spec_path(document_path: Path) -> Path:
    if document_path.name == "document.vsz":
        return document_path.parent / "spec.json"
    return document_path.with_suffix(".spec.json")


def _veusz_spec_reference(document_path: Path) -> dict[str, Any]:
    expected_path = _veusz_spec_path(document_path)
    exists = expected_path.is_file()
    return {
        "kind": "sciplot_veusz_spec_reference",
        "path": str(expected_path) if exists else None,
        "expected_path": str(expected_path),
        "exists": exists,
        "required_for_exact_current_export": False,
        "required_for_regeneration": True,
        "role": "optional_sciplot_generation_metadata",
    }


def _studio_document_state(
    document_path: Path, *, generated_hash: str | None
) -> dict[str, Any]:
    current_hash = existing_file_sha256(document_path)
    manual_edit_detected = bool(
        generated_hash and current_hash and current_hash != generated_hash
    )
    if manual_edit_detected:
        authority = "veusz_manual"
    elif generated_hash and current_hash == generated_hash:
        authority = "sciplot_generated"
    else:
        authority = "veusz_document"
    regeneration_requires_archive = bool(
        current_hash and (manual_edit_detected or generated_hash is None)
    )
    return {
        "kind": "sciplot_vsz_document_state",
        "authority": authority,
        "generated_hash": generated_hash,
        "current_hash": current_hash,
        "manual_edit_detected": manual_edit_detected,
        "preserve_on_open": True,
        "export_exact_current_document": True,
        "regeneration_requires_archive": regeneration_requires_archive,
    }


def _registered_generated_hash(project_dir: Path) -> str | None:
    for manifest_path in [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]:
        if not manifest_path.exists():
            continue
        try:
            payload = _read_json(manifest_path)
        except Exception:
            continue
        studio = (
            payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        )
        value = studio.get("generated_hash")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _studio_block(
    *,
    document_path: Path,
    spec_path: Path,
    launcher: Path,
    veusz_launcher: Path,
    export_edited_launcher: Path,
    request_path: Path,
    series_count: int,
    generated_hash: str | None,
    figure_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document_state = _studio_document_state(
        document_path, generated_hash=generated_hash
    )
    block = {
        "kind": "sciplot_studio_document",
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "status": "ready",
        "document": str(document_path),
        "spec": str(spec_path),
        "launcher": str(launcher),
        "veusz_launcher": str(veusz_launcher),
        "export_edited_launcher": str(export_edited_launcher),
        "generated_from": str(request_path),
        "series_count": series_count,
        "generated_hash": generated_hash,
        "manual_edit_hash": document_state["current_hash"],
        "document_authority": document_state["authority"],
        "manual_edit_detected": document_state["manual_edit_detected"],
        "document_state": document_state,
        "upstream": upstream_status()["veusz"],
        "operation_mode": normal_mode_payload(route="studio"),
    }
    if figure_set is not None:
        block["figure_set"] = json_safe(figure_set)
        block["figure_set_registry"] = str(
            _studio_figure_set_path(document_path.parent.parent)
        )
    return block
