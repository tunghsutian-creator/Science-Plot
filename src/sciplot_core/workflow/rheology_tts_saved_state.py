"""Read exact saved suite sources, selected receipts and scientific specifications."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from sciplot_core.workflow.native_suite_runtime import current_store

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_sources(request: dict[str, Any]) -> list[dict[str, Any]]:
    paths = [Path(request["frequency_source"]).expanduser().resolve()]
    paths.extend(Path(s["tts_source"]).expanduser().resolve() for s in request["samples"] if s.get("tts_source"))
    from sciplot_core.project_store.runtime import resolve_runtime_path
    store = current_store()
    result = []
    for path in dict.fromkeys(paths):
        if store is None:
            version = _sha(path)
        else:
            versions = {version for entries in store.snapshot()["sources"].values() for version, entry in entries.items()
                        if entry.get("locator") == str(path)}
            if len(versions) != 1:
                raise ValueError("Analysis continuation requires its exact registered original source version.")
            version = versions.pop()
            if _sha(resolve_runtime_path(path, expected_sha256=version)) != version:
                raise ValueError("The original analysis source version changed.")
        result.append({"path": str(path), "sha256": version})
    return result


def _check_sources(sources: list[dict[str, Any]]) -> None:
    from sciplot_core.foundation.source_errors import SourceVersionMismatch

    for source in sources:
        from sciplot_core.project_store.runtime import resolve_runtime_path
        try:
            path = resolve_runtime_path(source["path"], expected_sha256=source["sha256"], source_id=source.get("source_id"))
        except SourceVersionMismatch as exc:
            if (exc.literal, exc.expected_sha256) != (source["path"], source["sha256"]):
                raise
            raise ValueError(f"Original source changed: {source['path']}; a new analysis is required.") from exc
        if not path.is_file() or _sha(path) != source["sha256"]:
            raise ValueError(f"Original source changed: {path}; a new analysis is required.")


def _figure_folder(delivery: Path, identifier: str) -> Path:
    if identifier.startswith("Figure_X"):
        return delivery
    return delivery / ("SI" if identifier.startswith("SI_") else "panels")


def _selected_documents(manifest: dict[str, Any], figure_ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = manifest["documents"]
    identifiers = [document["id"] for document in documents]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Saved document identities are not unique.")
    if figure_ids is None:
        return documents
    if (not isinstance(figure_ids, tuple) or not figure_ids or len(set(figure_ids)) != len(figure_ids)
            or any(identifier not in identifiers for identifier in figure_ids)):
        raise ValueError("Select exact, unique existing figure IDs before native execution.")
    return [document for document in documents if document["id"] in figure_ids]


def _active_receipts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Select the active spec per figure; unrelated overlays never erase it."""
    original = {item["id"]: item for item in manifest["native_result"]["figures"]}
    overlay = manifest.get("presentation_revision", {}).get("figures", [])
    if len({item["id"] for item in overlay}) != len(overlay):
        raise ValueError("Active compiled figure identities are not unique.")
    original.update({item["id"]: item for item in overlay})
    return [original[document["id"]] for document in manifest["documents"]]


def _export_receipts(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Overlay sparse latest export facts on complete immutable creation facts.

    An explicit pending/empty export row overrides creation evidence. Missing
    overlay rows retain their original facts; no files or successful exports
    are inferred by this read-only projection.
    """
    identifiers = [item["id"] for item in manifest["documents"]]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Saved document identities are not unique.")
    result: dict[str, dict[str, Any]] = {}
    for rows in (manifest["native_result"]["figures"], manifest.get("last_export", [])):
        seen = set()
        for item in rows:
            identifier = Path(item["document"]).stem
            if identifier not in identifiers or identifier in seen or item.get("id", identifier) != identifier:
                raise ValueError("Saved export receipts require unique bound figure identities.")
            seen.add(identifier)
            result[identifier] = item
    if set(result) != set(identifiers):
        raise ValueError("Saved export receipts lack a creation-bound figure.")
    return result


def _compiled_figures(manifest: dict[str, Any], *, figure_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Read creation-bound numeric baselines without accepting edited spec bytes."""
    by_id = {}
    selected = {document["id"] for document in _selected_documents(manifest, figure_ids)}
    receipts = _active_receipts(manifest)
    for receipt in receipts:
        if receipt["id"] not in selected:
            continue
        from sciplot_core.project_store.runtime import resolve_runtime_path
        path = resolve_runtime_path(receipt["spec_path"], expected_sha256=receipt.get("spec_sha256"))
        digest = receipt.get("spec_sha256")
        if not digest:
            raise ValueError("Compiled figure specification lacks its creation SHA; explicit receipt migration is required.")
        if not path.is_file() or _sha(path) != digest:
            raise ValueError(f"Compiled figure specification changed: {path}")
        spec = json.loads(path.read_text(encoding="utf-8"))
        if _sha(path) != digest:
            raise ValueError(f"Compiled figure specification changed while reading: {path}")
        identifier = receipt["id"]
        if identifier in by_id or spec["figure"]["id"] != identifier:
            raise ValueError("Compiled figure identities disagree with creation receipts.")
        if spec["source_binding"].get("sources") != manifest["sources"]:
            raise ValueError("Compiled figure source bindings disagree with suite sources.")
        by_id[identifier] = spec["figure"]
    if set(by_id) != selected:
        raise ValueError("Saved document identities disagree with compiled figure receipts.")
    return by_id
