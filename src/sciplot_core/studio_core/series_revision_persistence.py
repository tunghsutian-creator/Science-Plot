"""Commit one native series selection across a complete Studio figure set."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_TASK_VERSION,
)
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set
from sciplot_core.studio_core.figure_set_storage import (
    _commit_studio_figure_set_transaction,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.persistence import stage_veusz_document
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
from sciplot_core.studio_core.registry_state import (
    _studio_document_state,
    _veusz_spec_path,
)
from sciplot_core.studio_core.runtime import _ensure_veusz_on_path
from sciplot_core.studio_core.series_presentation import (
    persist_series_selection,
    series_selection_payload,
    spec_source_series_order,
)
from sciplot_core.studio_core.veusz_series_revision import (
    apply_veusz_series_revision,
    inspect_veusz_series_revision,
    revert_veusz_series_revision,
)
from sciplot_core.veusz_worker.spec_audit import audit_spec_data


def commit_project_series_revision(
    *,
    project_dir: Path,
    active_order: Sequence[str],
    live_documents: Mapping[Path, Any] | None = None,
    path_replacer: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    """Persist one visible sample order across every ready project figure."""

    project = project_dir.expanduser().resolve()
    request_path = project / "plot_request.json"
    registry = _read_studio_figure_set(project)
    if (
        registry is None
        or registry.get("version") != STUDIO_FIGURE_SET_TASK_VERSION
        or registry.get("status") != "ready"
    ):
        raise RuntimeError(
            "Series revision commit requires one ready task-aware figure set."
        )
    entries = [
        item
        for item in registry.get("figures", [])
        if isinstance(item, dict) and item.get("status") == "ready"
    ]
    if not entries or len(entries) != len(registry.get("figures", [])):
        raise RuntimeError("Every planned figure must be ready before revision commit.")

    specs: dict[Path, dict[str, Any]] = {}
    source_order: list[str] | None = None
    for entry in entries:
        document_path = Path(str(entry["document"])).expanduser().resolve()
        spec_path = _veusz_spec_path(document_path)
        spec = _read_json(spec_path)
        labels = spec_source_series_order(spec)
        if source_order is None:
            source_order = labels
        elif labels != source_order:
            raise RuntimeError(
                "All figures must share one source series order for project revision."
            )
        specs[document_path] = spec
    assert source_order is not None
    selection = series_selection_payload(source_order, active_order)
    target_order = list(selection["active_order"])

    provided = {
        Path(path).expanduser().resolve(): document
        for path, document in (live_documents or {}).items()
    }
    documents: dict[Path, Any] = {}
    replacements: list[dict[str, Any]] = []
    staged_paths: list[Path] = []
    updated_specs: dict[Path, dict[str, Any]] = {}
    updated_entries: list[dict[str, Any]] = []
    auto_applied: list[tuple[Path, Any, bool]] = []
    try:
        for entry in entries:
            document_path = Path(str(entry["document"])).expanduser().resolve()
            document = provided.get(document_path) or _load_veusz_document(
                document_path
            )
            documents[document_path] = document
            state = inspect_veusz_series_revision(document, document_path)
            if state["source_order"] != source_order:
                raise RuntimeError(
                    f"Live series inventory disagrees for {document_path.name}."
                )
            if state["current_order"] != target_order:
                was_modified = bool(document.isModified())
                apply_veusz_series_revision(document, document_path, target_order)
                auto_applied.append((document_path, document, was_modified))

            staged_document = stage_veusz_document(document, document_path)
            if staged_document.get("status") != "passed":
                raise RuntimeError(
                    f"Could not structurally reopen staged figure {document_path.name}."
                )
            staged_document_path = Path(str(staged_document["staged"]))
            staged_paths.append(staged_document_path)
            replacements.append(
                {
                    "staged": staged_document_path,
                    "target": document_path,
                    "expected_hash": str(staged_document["sha256"]),
                    "kind": "document",
                }
            )

            spec = persist_series_selection(
                specs[document_path],
                source_order=source_order,
                active_order=target_order,
            )
            spec_path = _veusz_spec_path(document_path)
            staged_spec = _stage_json(spec_path, spec)
            staged_paths.append(staged_spec)
            spec_hash = existing_file_sha256(staged_spec)
            assert spec_hash is not None
            replacements.append(
                {
                    "staged": staged_spec,
                    "target": spec_path,
                    "expected_hash": spec_hash,
                    "kind": "spec",
                }
            )
            try:
                audit_spec_data(staged_document_path, staged_spec)
            except Exception as exc:
                raise RuntimeError(
                    f"Staged series revision audit failed for {document_path.name}: {exc}"
                ) from exc
            updated_specs[document_path] = spec

            prior_generated_hash = (
                str(entry.get("generated_hash") or "").strip() or None
            )
            document_state = _studio_document_state(
                staged_document_path,
                generated_hash=prior_generated_hash,
            )
            updated_entries.append(
                persist_series_selection(
                    {
                        **entry,
                        "document_authority": document_state["authority"],
                        "document_state": document_state,
                    },
                    source_order=source_order,
                    active_order=target_order,
                )
            )

        request = persist_series_selection(
            _read_json(request_path),
            source_order=source_order,
            active_order=target_order,
        )
        staged_request = _stage_json(request_path, request)
        staged_paths.append(staged_request)
        request_hash = existing_file_sha256(staged_request)
        assert request_hash is not None
        replacements.append(
            {
                "staged": staged_request,
                "target": request_path,
                "expected_hash": request_hash,
                "kind": "request",
            }
        )

        updated_registry = {**registry, "figures": updated_entries}
        _commit_studio_figure_set_transaction(
            project_dir=project,
            replacements=replacements,
            manual_archive_requests=[],
            registry=updated_registry,
            path_replacer=path_replacer,
        )
    except Exception:
        for document_path, document, was_modified in reversed(auto_applied):
            revert_veusz_series_revision(document, document_path)
            document.setModified(was_modified)
        raise
    finally:
        for path in staged_paths:
            path.unlink(missing_ok=True)

    for document_path, document in documents.items():
        document.filename = str(document_path)
        document.setModified(False)
    return {
        "kind": "sciplot_project_series_revision_commit",
        "version": 1,
        "status": "committed",
        "project": str(project),
        "active_order": target_order,
        "figure_ids": [str(entry["figure_id"]) for entry in updated_entries],
        "document_count": len(updated_entries),
        "spec_count": len(updated_specs),
    }


def _stage_json(target: Path, payload: Mapping[str, Any]) -> Path:
    staged = target.with_name(f".sciplot-series-revision-{uuid4().hex}.json")
    staged.write_text(
        json.dumps(json_safe(dict(payload)), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return staged


def _load_veusz_document(path: Path) -> Any:
    _ensure_veusz_on_path()
    ensure_veusz_loader_compat()
    from veusz import dataimport, document, widgets

    _ = dataimport, widgets
    loaded = document.Document()
    loaded.load(str(path))
    return loaded


__all__ = ["commit_project_series_revision"]
