"""Preview and adopt explicitly selected new source data in the same project."""

from __future__ import annotations

from sciplot_core.data_mapping.execution_directories import mapping_tree_reads, mapping_immutable_reads
from sciplot_core.studio_core.project_command_scope import project_command_runtime

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.delivery.package_transaction import _protect_editable_documents
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.studio_core.source_update_commit import (
    file_inventory,
    project_inventory,
    prior_source_update_result,
    reject_symlink_path,
)
from sciplot_core.studio_core.source_update_review import (
    compare_figures,
    payload_hash,
    project_figures,
)
from sciplot_core.studio_core.source_update_staging import (
    prepare_candidate,
    verify_project_science,
)
from sciplot_core.studio_core.source_update_annotations import transfer_annotations
from sciplot_core.studio_core.source_update_styles import capture_project_styles, transfer_project_styles
from sciplot_core.studio_core.annotation_contracts import annotation_records
from sciplot_core.studio_core.annotation_rebinding import relocate_annotation_evidence
from sciplot_core.project_commands import PreparedSource, InputRead, SourceTreeRead

from sciplot_core.studio_core.source_update_state import (
    _delivery_inventory as _delivery_inventory, _check_external_state as _check_external_state,
    _applied_result as _applied_result,
)

def _selected_worksheet(request: dict[str, Any], worksheet: str | None) -> str | None:
    if worksheet is not None:
        return worksheet.strip() or None
    old = {
        str(c["sheet"])
        for c in request.get("column_confirmations", [])
        if c.get("sheet_selected") is True and c.get("sheet")
    }
    if len(old) > 1:
        raise ValueError(
            "Select one current worksheet explicitly before updating this project."
        )
    return next(iter(old), None)





@contextmanager
def _prepared_update(project_dir: Path, source_path: Path, worksheet: str | None,
                     mapping_request: dict[str, Any] | None = None,
                     annotation_decisions: list[dict[str, Any]] | None = None) -> Iterator[tuple[Path, dict[str, Any], tuple[PreparedSource, ...], dict[str, Any]]]:
    from sciplot_core.studio_core.project_command_scope import project_store, adopt_saved_native
    from sciplot_core.studio_core.project_query_paths import project_snapshot
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core.source_update_sources import baseline_scope

    project = project_dir.expanduser().resolve()
    repository = project_store(project, with_snapshot=True)
    snapshot = repository.snapshot(import_legacy=True)
    figures = project_figures(project)
    for _document, spec in figures.values():
        annotation_records(json.loads(spec.read_text()))
    with project_runtime(repository), baseline_scope(repository, snapshot, specs=[spec for _doc, spec in figures.values()]):
        for selected in project_snapshot(project)[2]:
            if selected["status"] == "ready":
                adopt_saved_native(project, selected)
    with project_runtime(repository), _prepared_update_current(project, source_path, worksheet, mapping_request, annotation_decisions) as prepared:
        yield prepared


@contextmanager
def _prepared_update_current(
    project_dir: Path, source_path: Path, worksheet: str | None,
    mapping_request: dict[str, Any] | None = None,
    annotation_decisions: list[dict[str, Any]] | None = None,
) -> Iterator[tuple[Path, dict[str, Any], tuple[PreparedSource, ...], dict[str, Any]]]:
    reject_symlink_path(project_dir.expanduser())
    reject_symlink_path(source_path.expanduser())
    project, source = (
        project_dir.expanduser().resolve(),
        source_path.expanduser().resolve(),
    )
    if not (project / "plot_request.json").is_file():
        raise ValueError("Source update requires an existing SciPlot project.")
    if source == project or project.is_relative_to(source):
        raise ValueError(
            "Select a source file or a dedicated data directory, not the project or its parent."
        )
    from sciplot_core.studio_core.project_command_scope import project_store

    repository = project_store(project, with_snapshot=True)
    before_snapshot = repository.snapshot()
    original_state = project_inventory(project)
    source_state = file_inventory(source)
    request = json.loads((project / "plot_request.json").read_text())
    selected_sheet = _selected_worksheet(request, worksheet)
    delivery = requested_delivery_root({"request": request}, run_output=project)
    delivery_state = _delivery_inventory(delivery)
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.studio_core.source_update_commands import prior_source_preview, _public_review
    from sciplot_core.studio_core.source_update_replay import frozen_source_candidate
    from sciplot_core.studio_core.source_update_sources import baseline_scope, incoming_scope

    tree = ({"kind": "file", "content_sha256": next(iter(source_state.values()))} if source.is_file() else
            {"kind": "directory", "files": [{"path": name, "content_sha256": digest} for name, digest in sorted(source_state.items())]})
    intent = {"source": str(source), "source_kind": "file" if source.is_file() else "directory",
              "source_files": source_state, "source_tree_sha256": canonical_json_sha256(tree, allow_nan=False),
              "worksheet": selected_sheet, "mapping_request": mapping_request,
              "annotation_decisions": annotation_decisions or [], "project_sha256": payload_hash(original_state),
              "delivery_sha256": payload_hash(delivery_state)}
    existing = prior_source_preview(repository, before_snapshot, intent)
    if existing is not None:
        with incoming_scope(repository, before_snapshot, source, source_state), frozen_source_candidate(repository, before_snapshot, existing) as candidate:
            yield candidate, _public_review(project, existing), (), before_snapshot
        return

    figures = project_figures(project)
    from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
    from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution
    from sciplot_core.data_mapping.execution_directories import mapping_live_trees

    baseline_sources: tuple[PreparedSource, ...] = ()
    baseline_roles: tuple[InputRead, ...] = ()
    baseline_trees: tuple[SourceTreeRead, ...] = ()
    with baseline_scope(repository, before_snapshot, specs=[spec for _doc, spec in figures.values()]), \
            mapping_input_reads(request.get("data_mapping_execution")) as baseline_mapping:
        if baseline_mapping is not None:
            load_data_mapping_execution(baseline_mapping.execution)
            baseline_sources = tuple(item for item in baseline_mapping.prepared_sources(before_snapshot)
                if item.locator in baseline_mapping.metadata or item.version not in before_snapshot["sources"].get(item.source_id, {}))
            baseline_roles = baseline_mapping.input_reads(before_snapshot)
            baseline_trees = mapping_live_trees(baseline_mapping)
        for document, spec in figures.values():
            annotation_records(json.loads(spec.read_text()))
            _audit_exact_document_data(
                document_path=document, spec_path=spec, check_presentation=False
            )
        old_styles = capture_project_styles(project)
    with incoming_scope(repository, before_snapshot, source, source_state), prepare_candidate(project, source, project.parent, worksheet=selected_sheet, snapshot=before_snapshot,
            **({"mapping_request": mapping_request} if mapping_request else {})) as (private, confirmations):
        private.mapping_baseline_sources = baseline_sources
        private.mapping_baseline_roles = baseline_roles
        private.mapping_baseline_trees = baseline_trees
        candidate = private.project_dir
        if delivery and delivery.is_dir():
            # An unmerged visible edit must be recovered first; update cannot
            # make that edit disappear as a side effect of replacing the source.
            _protect_editable_documents(delivery, candidate)
        styles = transfer_project_styles(candidate, old_styles)
        annotations = transfer_annotations(project, candidate, annotation_decisions or [])
        if (
            project_inventory(project) != original_state
            or file_inventory(source) != source_state
            or _delivery_inventory(delivery) != delivery_state
        ):
            raise ValueError(
                "Project, selected source, or visible delivery changed during preview; inspect again."
            )
        from sciplot_core.studio_core.preparation_commands import audit_studio_candidate
        payload: dict[str, Any] = {"document": str(candidate / "studio/document.vsz")}
        from sciplot_core.studio_core.project_query_paths import project_snapshot

        _, _, candidate_figures = project_snapshot(candidate)
        payload["figure_set"] = {"figures": candidate_figures}
        _audits, prepared_sources = audit_studio_candidate(private, payload, check_presentation=False)
        private.finalize()
        private.capture()  # Reject any private nested authority or changed original raw/source member.
        review = {
            "kind": "sciplot_project_source_update",
            "version": 1,
            "status": "ready",
            "project": str(project),
            "source": str(source),
            "source_kind": "directory" if source.is_dir() else "file",
            "worksheet": selected_sheet,
            "project_sha256": payload_hash(original_state),
            "source_files": source_state,
            "source_tree_sha256": (source_tree_sha256(source, expected_file_sha256=next(iter(source_state.values())))
                                   if source.is_file() else source_tree_sha256(source)),
            "annotation_decisions": annotation_decisions or [],
            "delivery_sha256": payload_hash(delivery_state),
            "changes": compare_figures(project, candidate),
            "styles": styles,
            "columns": [
                {"sheet": c.get("sheet"), "columns": c.get("columns")}
                for c in confirmations
            ],
            "requires_confirmation": True,
            "notes": [
                "The previous active project files will be archived.",
                "Scientific labels and axis limits are recalculated for the new data.",
                "Apply adopts the source revision; Save and Export then updates the delivery.",
            ],
        }
        if mapping_request is not None:
            review["mapping_request"] = mapping_request
            review["mapping"] = json.loads((candidate / "plot_request.json").read_text())["data_mapping_plan_binding"]
        if mapping_tree_reads(private.mapping_inputs.values(), private.mapping_baseline_trees):
            review["mapping_source_trees"] = [tree.to_payload() for tree in mapping_tree_reads(private.mapping_inputs.values(), private.mapping_baseline_trees)]
        if annotations:
            review["annotation_review"] = annotations
            review["annotation_decisions"] = annotation_decisions or []
            if any(item["requires_choice"] for item in annotations):
                review["status"] = "needs_annotation_choices"
        yield candidate, review, tuple(prepared_sources), before_snapshot


@project_command_runtime
def preview_project_source_update(
    project_dir: Path, source: Path, *, worksheet: str | None = None,
    on_candidate: Callable[[Path, dict[str, Any]], None] | None = None,
    mapping_request: dict[str, Any] | None = None,
    annotation_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build and audit an isolated candidate without changing the active project."""
    try:
        with _prepared_update(project_dir, source, worksheet, mapping_request, annotation_decisions) as (candidate, preview, prepared_sources, before_snapshot):
            if on_candidate is not None:
                on_candidate(candidate, preview)
                project = Path(preview["project"])
                if payload_hash(project_inventory(project)) != preview["project_sha256"]:
                    raise ValueError("The project changed while rendering its source-update preview.")
                _check_external_state(project, Path(preview["source"]), preview)
            if preview.get("status") != "ready":
                return preview
            if preview.get("version") == 2:
                return preview
            from sciplot_core.studio_core.source_update_commands import stage_source_update
            from sciplot_core.studio_core.preparation_candidate import require_preparation_candidate

            return stage_source_update(Path(preview["project"]), candidate, preview,
                relocate_companion=relocate_annotation_evidence if preview.get("annotation_review") else None,
                prepared_sources=prepared_sources, logical_paths_bound=True, before_snapshot=before_snapshot,
                input_reads=mapping_immutable_reads(require_preparation_candidate(candidate).snapshot, require_preparation_candidate(candidate).mapping_inputs.values(), require_preparation_candidate(candidate).mapping_baseline_roles))
    except (ValueError, OSError, RuntimeError) as exc:
        return {
            "kind": "sciplot_project_source_update",
            "version": 1,
            "status": "blocked",
            "project": str(project_dir.expanduser().resolve()),
            "source": str(source.expanduser().resolve()),
            "reason": str(exc),
        }


def apply_project_source_update(
    project_dir: Path, preview: dict[str, Any]
) -> dict[str, Any]:
    """Adopt the exact reviewed frozen candidate, rejecting stale choices."""
    if preview.get("version") == 2:
        from sciplot_core.studio_core.source_update_commands import decide_source_update

        return decide_source_update(project_dir.expanduser().resolve(), preview)
    if (
        preview.get("status") != "ready"
        or preview.get("kind") != "sciplot_project_source_update"
    ):
        raise ValueError(
            "A successful source-update preview must be explicitly reviewed before applying."
        )
    reject_symlink_path(project_dir.expanduser())
    project = project_dir.expanduser().resolve()
    if preview.get("project") != str(project):
        raise ValueError("The source-update preview belongs to another project.")
    def validate_recovered() -> None:
        _check_external_state(project, Path(preview["source"]), preview)
        verify_project_science(project)

    prior = prior_source_update_result(project, preview, validate=validate_recovered)
    if prior is not None:
        return _applied_result(project, preview, prior, status="already_applied")
    raise ValueError("This legacy source preview has no frozen candidate; create and confirm a fresh source preview")


__all__ = ["preview_project_source_update", "apply_project_source_update"]
