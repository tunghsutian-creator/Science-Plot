from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, safe_filename, slug, unique_path
from sciplot_core.canvas.composition import (
    CompositionProject,
    CompositionSourceModule,
    CompositionVariant,
    apply_composition_batch,
    clone_composition_variant,
    new_composition_project,
    preview_composition_batch,
)
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.persistence import (
    COMPOSITION_FILENAME,
    append_operation_journal,
    atomic_write_json,
    load_composition_project,
    save_composition_project,
)

COMPOSITION_SOURCE_MANIFEST_KIND = "sciplot_composition_source_manifest"
COMPOSITION_SOURCE_MANIFEST_VERSION = 1
COMPOSITION_COMPILE_MANIFEST_KIND = "sciplot_composition_compile_manifest"
COMPOSITION_COMPILE_MANIFEST_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def _within(root: Path, candidate: Path, *, label: str) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the composition workspace.") from exc
    return resolved


@dataclass(frozen=True)
class CompositionWorkspace:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    @property
    def composition_path(self) -> Path:
        return self.root / COMPOSITION_FILENAME

    @property
    def source_manifest_path(self) -> Path:
        return self.root / "source_manifest.json"

    @property
    def journal_path(self) -> Path:
        return self.root / "operation_journal.jsonl"

    @property
    def history_root(self) -> Path:
        return self.root / ".composition_history"

    def load(self) -> CompositionProject:
        if not self.composition_path.is_file():
            raise FileNotFoundError(
                f"Composition project is missing {COMPOSITION_FILENAME}: {self.root}"
            )
        return load_composition_project(self.composition_path)

    def save(self, project: CompositionProject) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return save_composition_project(self.composition_path, project)

    def source_path(self, module: CompositionSourceModule) -> Path:
        return _within(
            self.root,
            self.root / module.source_ref,
            label=f"source module {module.module_id}",
        )

    def variant_root(self, variant_id: str) -> Path:
        return _within(
            self.root,
            self.root / "variants" / variant_id,
            label="variant root",
        )

    def variant_document_path(self, variant_id: str) -> Path:
        return self.variant_root(variant_id) / "studio" / "document.vsz"

    def variant_compile_manifest_path(self, variant_id: str) -> Path:
        return self.variant_root(variant_id) / "compile_manifest.json"

    def variant_export_root(self, variant_id: str) -> Path:
        return self.variant_root(variant_id) / "exports"

    def variant_delivery_root(self, variant_id: str) -> Path:
        return self.variant_root(variant_id) / "delivery"

    def resolve_document_ref(self, document_ref: str) -> Path:
        return _within(
            self.root,
            self.root / document_ref,
            label="compiled document",
        )


def resolve_composition_workspace(target: Path) -> CompositionWorkspace:
    resolved = target.expanduser().resolve()
    if resolved.is_file():
        if resolved.name != COMPOSITION_FILENAME:
            raise ValueError(
                "Composition workspace files must be named composition.json."
            )
        workspace = CompositionWorkspace(resolved.parent)
    else:
        workspace = CompositionWorkspace(resolved)
    workspace.load()
    return workspace


def create_composition_workspace(
    sources: list[Path] | tuple[Path, ...],
    *,
    root: Path,
    name: str,
    layout_id: str | None = None,
    canvas_height_mm: float = 55.0,
    composition_id: str | None = None,
) -> tuple[CompositionWorkspace, CompositionProject]:
    resolved_sources = [path.expanduser().resolve() for path in sources]
    if not 1 <= len(resolved_sources) <= 12:
        raise ValueError(
            "Composition workspaces require one to twelve source VSZ files."
        )
    if len(set(resolved_sources)) != len(resolved_sources):
        raise ValueError("Composition source VSZ paths must be unique.")
    for source in resolved_sources:
        if not source.is_file() or source.suffix.casefold() != ".vsz":
            raise FileNotFoundError(f"Composition source VSZ not found: {source}")

    workspace = CompositionWorkspace(root)
    if workspace.composition_path.exists():
        raise FileExistsError(
            f"Composition workspace already exists: {workspace.composition_path}"
        )
    workspace.root.mkdir(parents=True, exist_ok=True)
    source_modules: list[CompositionSourceModule] = []
    source_records: list[dict[str, Any]] = []
    for index, source in enumerate(resolved_sources):
        module_id = f"module_{chr(ord('a') + index)}"
        snapshot = workspace.root / "sources" / module_id / "document.vsz"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, snapshot)
        source_hash = file_sha256(source)
        snapshot_hash = file_sha256(snapshot)
        if snapshot_hash != source_hash:
            raise RuntimeError(
                f"Composition source snapshot hash mismatch for {source}."
            )
        source_ref = snapshot.relative_to(workspace.root).as_posix()
        source_modules.append(
            CompositionSourceModule(
                module_id=module_id,
                title=source.stem,
                source_ref=source_ref,
                source_sha256=source_hash,
            )
        )
        source_records.append(
            {
                "module_id": module_id,
                "original_source": str(source),
                "original_source_sha256": source_hash,
                "snapshot_ref": source_ref,
                "snapshot_sha256": snapshot_hash,
                "snapshot_is_byte_identical": snapshot_hash == source_hash,
            }
        )
    project = new_composition_project(
        name=name,
        source_modules=tuple(source_modules),
        layout_id=layout_id,
        canvas_height_mm=canvas_height_mm,
        composition_id=(slug(composition_id) if composition_id else None),
    )
    workspace.save(project)
    atomic_write_json(
        workspace.source_manifest_path,
        {
            "kind": COMPOSITION_SOURCE_MANIFEST_KIND,
            "version": COMPOSITION_SOURCE_MANIFEST_VERSION,
            "composition_id": project.composition_id,
            "created_at": _now(),
            "sources": source_records,
            "authority": {
                "original_sources_mutated": False,
                "workspace_snapshots_are_immutable_inputs": True,
            },
        },
    )
    return workspace, project


def create_composition_variant(
    workspace: CompositionWorkspace,
    *,
    source_variant_id: str,
    name: str,
    variant_id: str | None = None,
) -> CompositionProject:
    project = workspace.load()
    base_id = variant_id or f"variant_{len(project.variants) + 1:02d}"
    candidate = base_id
    existing = {variant.variant_id for variant in project.variants}
    index = 2
    while candidate in existing:
        candidate = f"{base_id}_{index}"
        index += 1
    updated = clone_composition_variant(
        project,
        source_variant_id=source_variant_id,
        variant_id=candidate,
        name=name,
    )
    workspace.save(updated)
    append_operation_journal(
        workspace.journal_path,
        {
            "kind": "sciplot_composition_operation_journal_entry",
            "version": 1,
            "event": "composition_variant_created",
            "event_id": f"composition_variant_created:{candidate}:{_timestamp_slug()}",
            "recorded_at": _now(),
            "source_variant_id": source_variant_id,
            "variant_id": candidate,
            "name": name,
        },
    )
    return updated


def activate_composition_variant(
    workspace: CompositionWorkspace,
    variant_id: str,
) -> CompositionProject:
    project = workspace.load()
    project.variant(variant_id)
    if project.active_variant_id == variant_id:
        return project
    updated = replace(project, active_variant_id=variant_id, updated_at=_now())
    workspace.save(updated)
    append_operation_journal(
        workspace.journal_path,
        {
            "kind": "sciplot_composition_operation_journal_entry",
            "version": 1,
            "event": "composition_variant_activated",
            "event_id": f"composition_variant_activated:{variant_id}:{_timestamp_slug()}",
            "recorded_at": _now(),
            "variant_id": variant_id,
        },
    )
    return updated


def verify_composition_sources(
    workspace: CompositionWorkspace,
    project: CompositionProject,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for module in project.source_modules:
        path = workspace.source_path(module)
        if not path.is_file():
            raise FileNotFoundError(
                f"Composition source snapshot is missing: {module.source_ref}"
            )
        current_hash = file_sha256(path)
        if current_hash != module.source_sha256:
            raise ValueError(f"Composition source snapshot changed: {module.module_id}")
        records.append(
            {
                "module_id": module.module_id,
                "source_ref": module.source_ref,
                "source_sha256": current_hash,
                "verified": True,
            }
        )
    return records


def composition_variant_authority_status(
    workspace: CompositionWorkspace,
    project: CompositionProject,
    variant_id: str,
) -> dict[str, Any]:
    """Describe whether the exact-current compiled VSZ still matches its authority."""

    variant = project.variant(variant_id)
    document = workspace.variant_document_path(variant.variant_id)
    recorded_ref = variant.compiled_document_ref
    recorded_hash = variant.compiled_document_sha256
    if recorded_ref is None or recorded_hash is None:
        return {
            "variant_id": variant.variant_id,
            "state": "draft_without_compiled_authority",
            "document": str(document),
            "document_exists": document.is_file(),
            "recorded_document_ref": None,
            "recorded_sha256": None,
            "current_sha256": file_sha256(document) if document.is_file() else None,
            "safe_to_mutate_composition": True,
            "manual_edit_detected": False,
        }
    resolved = workspace.resolve_document_ref(recorded_ref)
    if resolved != document.resolve():
        raise ValueError(
            "Composition authority points outside the active variant document path."
        )
    if not document.is_file():
        return {
            "variant_id": variant.variant_id,
            "state": "compiled_authority_missing",
            "document": str(document),
            "document_exists": False,
            "recorded_document_ref": recorded_ref,
            "recorded_sha256": recorded_hash,
            "current_sha256": None,
            "safe_to_mutate_composition": False,
            "manual_edit_detected": False,
        }
    current_hash = file_sha256(document)
    manual_edit_detected = current_hash != recorded_hash
    return {
        "variant_id": variant.variant_id,
        "state": (
            "edited_compiled_authority"
            if manual_edit_detected
            else "compiled_authority_current"
        ),
        "document": str(document),
        "document_exists": True,
        "recorded_document_ref": recorded_ref,
        "recorded_sha256": recorded_hash,
        "current_sha256": current_hash,
        "safe_to_mutate_composition": not manual_edit_detected,
        "manual_edit_detected": manual_edit_detected,
    }


def assert_composition_variant_mutable(
    workspace: CompositionWorkspace,
    project: CompositionProject,
    variant_id: str,
) -> dict[str, Any]:
    status = composition_variant_authority_status(
        workspace,
        project,
        variant_id,
    )
    if status["state"] == "compiled_authority_missing":
        raise RuntimeError(
            "The compiled composition authority is missing; recover or explicitly "
            "regenerate it before changing the layout."
        )
    if status["manual_edit_detected"]:
        raise RuntimeError(
            "The compiled composition VSZ contains manual edits. Preserve it as "
            "visual authority, or explicitly archive and regenerate it before "
            "changing the composition."
        )
    return status


def archive_variant_document(
    workspace: CompositionWorkspace,
    variant_id: str,
) -> dict[str, Any] | None:
    document = workspace.variant_document_path(variant_id)
    if not document.is_file():
        return None
    source_hash = file_sha256(document)
    archive_root = workspace.variant_root(variant_id) / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_name = safe_filename(f"document_{_timestamp_slug()}_{source_hash[:12]}.vsz")
    destination = unique_path(archive_root, archive_name)
    shutil.copy2(document, destination)
    archive_hash = file_sha256(destination)
    if archive_hash != source_hash:
        raise RuntimeError("Archived composition VSZ does not match its source.")
    return {
        "source": str(document),
        "source_sha256": source_hash,
        "archive": str(destination),
        "archive_ref": destination.relative_to(workspace.root).as_posix(),
        "archive_sha256": archive_hash,
        "byte_identical": True,
    }


def persist_composition_batch(
    workspace: CompositionWorkspace,
    batch: CanvasOperationBatch,
) -> tuple[CompositionProject, dict[str, Any]]:
    project = workspace.load()
    preview = preview_composition_batch(project, batch)
    variant = project.variant(str(preview["variant_id"]))
    authority_status = assert_composition_variant_mutable(
        workspace,
        project,
        variant.variant_id,
    )
    snapshot_root = workspace.history_root / variant.variant_id
    snapshot_root.mkdir(parents=True, exist_ok=True)
    current_hash = file_sha256(workspace.composition_path)
    snapshot = snapshot_root / (
        f"revision_{variant.revision:06d}_{current_hash[:12]}.json"
    )
    if not snapshot.exists():
        shutil.copy2(workspace.composition_path, snapshot)
    if file_sha256(snapshot) != current_hash:
        raise RuntimeError("Composition history snapshot hash mismatch.")
    updated, receipt = apply_composition_batch(project, batch)
    workspace.save(updated)
    updated_hash = file_sha256(workspace.composition_path)
    receipt = {
        **receipt,
        "preview": preview,
        "baseline_snapshot_ref": snapshot.relative_to(workspace.root).as_posix(),
        "baseline_snapshot_sha256": current_hash,
        "composition_sha256": updated_hash,
        "pre_apply_authority": authority_status,
    }
    append_operation_journal(
        workspace.journal_path,
        {
            "kind": "sciplot_composition_operation_journal_entry",
            "version": 1,
            "event": "composition_batch_applied",
            "event_id": f"composition_batch:{batch.batch_id}",
            "recorded_at": _now(),
            "receipt": receipt,
        },
    )
    return updated, receipt


def mark_composition_compiled(
    project: CompositionProject,
    *,
    variant_id: str,
    document_ref: str,
    document_sha256: str,
    resolved_sources: tuple[CompositionSourceModule, ...] | None = None,
) -> CompositionProject:
    working = (
        project.with_source_modules(resolved_sources)
        if resolved_sources is not None
        else project
    )
    variant = working.variant(variant_id)
    compiled = replace(
        variant,
        state="compiled",
        compiled_document_ref=document_ref,
        compiled_document_sha256=document_sha256,
        updated_at=_now(),
    )
    return working.with_variant(compiled)


def write_composition_compile_manifest(
    workspace: CompositionWorkspace,
    variant: CompositionVariant,
    payload: dict[str, Any],
) -> Path:
    manifest = {
        "kind": COMPOSITION_COMPILE_MANIFEST_KIND,
        "version": COMPOSITION_COMPILE_MANIFEST_VERSION,
        "composition": str(workspace.composition_path),
        "variant_id": variant.variant_id,
        "compiled_at": _now(),
        **payload,
    }
    return atomic_write_json(
        workspace.variant_compile_manifest_path(variant.variant_id),
        manifest,
    )


def read_composition_source_manifest(
    workspace: CompositionWorkspace,
) -> dict[str, Any]:
    payload = json.loads(workspace.source_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source_manifest.json must contain an object.")
    if payload.get("kind") != COMPOSITION_SOURCE_MANIFEST_KIND:
        raise ValueError("Not a SciPlot composition source manifest.")
    return payload


__all__ = [
    "COMPOSITION_COMPILE_MANIFEST_KIND",
    "COMPOSITION_COMPILE_MANIFEST_VERSION",
    "COMPOSITION_SOURCE_MANIFEST_KIND",
    "COMPOSITION_SOURCE_MANIFEST_VERSION",
    "CompositionWorkspace",
    "activate_composition_variant",
    "archive_variant_document",
    "assert_composition_variant_mutable",
    "composition_variant_authority_status",
    "create_composition_variant",
    "create_composition_workspace",
    "mark_composition_compiled",
    "persist_composition_batch",
    "read_composition_source_manifest",
    "resolve_composition_workspace",
    "verify_composition_sources",
    "write_composition_compile_manifest",
]
