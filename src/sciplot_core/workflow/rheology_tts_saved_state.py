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
    from .native_suite_bindings import source_references

    for source in source_references(sources):
        from sciplot_core.project_store.runtime import resolve_runtime_path
        try:
            path = resolve_runtime_path(source.locator, expected_sha256=source.version, source_id=source.source_id)
        except SourceVersionMismatch as exc:
            if (exc.literal, exc.expected_sha256) != (source.locator, source.version):
                raise
            raise ValueError(f"Original source changed: {source.locator}; a new analysis is required.") from exc
        if not path.is_file() or _sha(path) != source.version:
            raise ValueError(f"Original source changed: {path}; a new analysis is required.")


def _figure_folder(delivery: Path, identifier: str) -> Path:
    from sciplot_core.project_commands.native_suite_projections import native_suite_figure_folder
    return Path(native_suite_figure_folder(str(delivery), identifier))


def _selected_documents(manifest: dict[str, Any], figure_ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    from .native_suite_bindings import parse_suite_catalog
    selected = {row["id"] for row in parse_suite_catalog(manifest).documents(figure_ids)}
    # Existing candidate editors update these declared rows in place before
    # freezing their mutation; the parser owns selection, not a second draft.
    return [row for row in manifest["documents"] if row["id"] in selected]


def _active_receipts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    from .native_suite_bindings import parse_suite_catalog
    return parse_suite_catalog(manifest).active_receipts()


def _export_receipts(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from .native_suite_bindings import parse_suite_catalog
    return parse_suite_catalog(manifest).export_receipts()


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
