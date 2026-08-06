"""Discover and copy editable Veusz project documents."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.path_names import slug


def _manifest_veusz_documents(manifest: dict[str, Any], output_dir: Path) -> list[Path]:
    explicit_values: list[object] = []
    explicit_values.extend(
        manifest.get("veusz_documents", [])
        if isinstance(manifest.get("veusz_documents"), list)
        else []
    )
    values: list[object] = []
    values.append(manifest.get("veusz_document"))
    for key in ("result", "studio"):
        payload = manifest.get(key) if isinstance(manifest.get(key), dict) else {}
        values.extend(
            payload.get("veusz_documents", [])
            if isinstance(payload.get("veusz_documents"), list)
            else []
        )
        values.extend([payload.get("veusz_document"), payload.get("document")])

    def existing_documents(candidates: list[object]) -> list[Path]:
        documents: list[Path] = []
        seen: set[Path] = set()
        for value in candidates:
            if not isinstance(value, str | Path) or not str(value).strip():
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = output_dir / candidate
            candidate = candidate.resolve()
            if candidate in seen or not candidate.exists() or not candidate.is_file():
                continue
            documents.append(candidate)
            seen.add(candidate)
        return documents

    documents = existing_documents(explicit_values)
    if documents:
        return documents
    documents = existing_documents(values)
    if documents:
        return documents
    fallback_values: list[object] = []
    fallback_values.extend(
        sorted((output_dir / "figures" / "_veusz").glob("**/studio/document.vsz"))
    )
    fallback_values.extend(sorted((output_dir / "studio").glob("*.vsz")))
    return existing_documents(fallback_values)


def _editable_project_name(document: Path, *, index: int) -> str:
    project_root = document.parent.parent
    candidate = (
        project_root.parent.name
        if project_root.name.startswith(("single", "panel_"))
        else project_root.name
    )
    if candidate in {"", "_veusz", "figures", "studio"}:
        candidate = (
            document.stem
            if document.stem not in {"", "document"}
            else f"figure_{index:02d}"
        )
    return slug(candidate) or f"figure_{index:02d}"


def _copy_project_documents(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    project_dir: Path,
) -> list[dict[str, Any]]:
    documents = _manifest_veusz_documents(manifest, output_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    used_names: set[str] = set()
    expected_hash = str(manifest.get("exported_document_hash") or "").strip()
    expected_hashes = {
        str(Path(path).expanduser().resolve()): str(value)
        for path, value in (
            manifest.get("veusz_document_hashes", {}).items()
            if isinstance(manifest.get("veusz_document_hashes"), dict)
            else []
        )
        if str(path).strip() and str(value).strip()
    }
    figure_ids = _document_figure_ids(manifest)
    for index, source_document in enumerate(documents, start=1):
        base_name = _editable_project_name(source_document, index=index)
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(name)
        destination = project_dir / f"{name}.vsz"
        shutil.copy2(source_document, destination)
        source_hash = existing_file_sha256(source_document)
        delivery_hash = existing_file_sha256(destination)
        document_expected_hash = expected_hashes.get(
            str(source_document.resolve()),
            expected_hash,
        )
        hash_matches_export = bool(
            source_hash
            and delivery_hash
            and source_hash == delivery_hash
            and (not document_expected_hash or delivery_hash == document_expected_hash)
        )
        records.append(
            {
                "kind": "sciplot_delivery_project_file",
                "id": name,
                "source": str(source_document),
                "path": str(destination),
                "relative_path": str(destination.relative_to(project_dir.parent)),
                "format": "vsz",
                "figure_id": figure_ids.get(str(source_document.resolve())),
                "source_sha256": source_hash,
                "expected_sha256": document_expected_hash or source_hash,
                "delivery_sha256": delivery_hash,
                "copy_hash_matches": bool(source_hash and source_hash == delivery_hash),
                "hash_matches_export": hash_matches_export,
                "exists": destination.exists(),
            }
        )
    return records


def _document_figure_ids(manifest: dict[str, Any]) -> dict[str, str]:
    plan = (
        manifest.get("resolved_figure_plan")
        if isinstance(manifest.get("resolved_figure_plan"), dict)
        else {}
    )
    outcomes = plan.get("outcomes") if isinstance(plan.get("outcomes"), list) else []
    values: dict[str, str] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        figure_id = str(outcome.get("figure_id") or "").strip()
        artifacts = (
            outcome.get("artifacts")
            if isinstance(outcome.get("artifacts"), list)
            else []
        )
        for value in artifacts:
            if (
                figure_id
                and isinstance(value, str)
                and Path(value).suffix.casefold() == ".vsz"
            ):
                values[str(Path(value).expanduser().resolve())] = figure_id
    return values
