"""Commit one native series selection across a complete Studio figure set."""

from __future__ import annotations

import json
import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4
from tempfile import TemporaryDirectory

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_TASK_VERSION,
)
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set
from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, whole_memberships
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands.read_projections import projection_digest
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
    repository = project_store(project)
    original_generation = repository.snapshot(import_legacy=True)
    binding = {"project_id": original_generation["project_id"], "generation": original_generation["generation"],
               "files": {name: value["sha256"] for name, value in original_generation["files"].items()},
               "read_memberships": whole_memberships(repository, original_generation)}
    for live in (live_documents or {}).values():
        draft = getattr(live, "_sciplot_project_read_set", None)
        if draft is not None and (draft["project_id"] != binding["project_id"] or any(
                binding["files"].get(name) != digest for name, digest in draft["files"].items())):
            raise ValueError("A live native draft is stale for this figure-set commit")
        for read in (draft or {}).get("projected_reads", []):
            if projection_digest(repository.read_bytes(read["resource"]), kind=read["kind"], key=read["key"]) != read["sha256"]:
                raise ValueError("A live native draft's figure membership changed before this figure-set commit")
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
    temporary = TemporaryDirectory(prefix="sciplot-series-revision-")
    stage_root = Path(temporary.name)
    if path_replacer is not None:
        raise ValueError("Direct path replacers are retired; inject faults at the shared generation boundary")
    planned = ["plot_request.json", "studio/figure_set.json"]
    for document_path in specs:
        planned.extend((repository.logical_path(document_path), repository.logical_path(_veusz_spec_path(document_path))))
    intent = {"source_order": source_order, "active_order": target_order,
        "figure_ids": [str(entry["figure_id"]) for entry in entries],
        "live_changesets": {repository.logical_path(path): getattr(document, "changeset", None)
                            for path, document in provided.items()}}
    key = canonical_json_sha256({"kind": "series_revision", "project_id": binding["project_id"],
                                "files": binding["files"], "request": intent})
    command = command_for_binding(repository, binding, kind="figure_set", key=key, writes=planned, request=intent)

    def prepare() -> ProjectMutation:
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

            private_target = stage_root / document_path.relative_to(project)
            private_target.parent.mkdir(parents=True, exist_ok=True)
            staged_document = stage_veusz_document(document, private_target)
            if staged_document.get("status") != "passed":
                raise RuntimeError(
                    f"Could not structurally reopen staged figure {document_path.name}."
                )
            staged_document_path = Path(str(staged_document["staged"]))
            staged_document_path.chmod(document_path.stat().st_mode & 0o777)
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
            staged_spec = _stage_json(spec_path, spec, directory=stage_root)
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
        staged_request = _stage_json(request_path, request, directory=stage_root)
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
        writes: dict[str, bytes | Path | None] = {
            repository.logical_path(Path(item["target"])): Path(item["staged"]) for item in replacements}
        writes["studio/figure_set.json"] = json.dumps(json_safe(updated_registry), ensure_ascii=False, indent=2).encode()
        return ProjectMutation(writes,
            {"status": "committed", "active_order": target_order, "figure_ids": intent["figure_ids"]})

    try:
        committed = ProjectCommands(repository).execute(command, prepare)
    except Exception:
        for document_path, document, was_modified in reversed(auto_applied):
            revert_veusz_series_revision(document, document_path)
            document.setModified(was_modified)
        raise
    finally:
        for path in staged_paths:
            path.unlink(missing_ok=True)
        temporary.cleanup()

    for document_path, document in documents.items():
        document.filename = str(document_path)
        document.setModified(False)
        draft = getattr(document, "_sciplot_project_read_set", None)
        if draft is not None:
            snapshot = repository.snapshot()
            document._sciplot_project_read_set = {**draft, "generation": committed["generation"],
                "files": {name: snapshot["files"].get(name, {}).get("sha256") for name in draft["files"]}}
    return {
        "kind": "sciplot_project_series_revision_commit",
        "version": 1,
        "status": "committed",
        "project": str(project),
        "active_order": target_order,
        "figure_ids": committed["result"]["figure_ids"],
        "document_count": len(entries),
        "spec_count": len(entries),
        "project_command": {name: committed[name] for name in ("command_id", "phase", "project_id", "generation")},
    }


def _stage_json(target: Path, payload: Mapping[str, Any], *, directory: Path) -> Path:
    staged = directory / f"series-revision-{uuid4().hex}.json"
    staged.write_text(
        json.dumps(json_safe(dict(payload)), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if target.exists():
        staged.chmod(target.stat().st_mode & 0o777)
    return staged


def _load_veusz_document(path: Path) -> Any:
    _ensure_veusz_on_path()
    ensure_veusz_loader_compat()
    importlib.import_module("veusz.dataimport")
    importlib.import_module("veusz.widgets")
    document = importlib.import_module("veusz.document")
    loaded = document.Document()
    loaded.load(str(path))
    return loaded


__all__ = ["commit_project_series_revision"]
