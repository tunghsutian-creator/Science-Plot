"""Preview and adopt explicitly selected new source data in the same project."""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.delivery.package_transaction import _protect_editable_documents
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.studio_core.source_update_commit import (
    file_inventory,
    install_source_update,
    project_inventory,
    reject_symlink_path,
)
from sciplot_core.studio_core.source_update_review import (
    compare_figures,
    payload_hash,
    project_figures,
)
from sciplot_core.studio_core.source_update_staging import (
    prepare_candidate,
    transfer_project_styles,
    verify_project_science,
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


def _delivery_inventory(delivery: Path) -> dict[str, str] | None:
    return file_inventory(delivery) if delivery.exists() else None


def _check_external_state(project: Path, source: Path, review: dict[str, Any]) -> None:
    request = json.loads((project / "plot_request.json").read_text())
    delivery = requested_delivery_root({"request": request}, run_output=project)
    if (
        file_inventory(source) != review["source_files"]
        or payload_hash(_delivery_inventory(delivery)) != review["delivery_sha256"]
    ):
        raise ValueError(
            "The selected source or visible delivery changed; preview it again before applying."
        )


@contextmanager
def _prepared_update(
    project_dir: Path, source_path: Path, worksheet: str | None
) -> Iterator[tuple[Path, dict[str, Any]]]:
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
    original_state = project_inventory(project)
    source_state = file_inventory(source)
    request = json.loads((project / "plot_request.json").read_text())
    selected_sheet = _selected_worksheet(request, worksheet)
    for document, spec in project_figures(project).values():
        _audit_exact_document_data(
            document_path=document, spec_path=spec, check_presentation=False
        )
    delivery = requested_delivery_root({"request": request}, run_output=project)
    delivery_state = _delivery_inventory(delivery)
    with tempfile.TemporaryDirectory(
        prefix=".sciplot-source-update-", dir=project.parent
    ) as temporary:
        candidate, confirmations = prepare_candidate(
            project, source, Path(temporary), worksheet=selected_sheet
        )
        if delivery and delivery.is_dir():
            # An unmerged visible edit must be recovered first; update cannot
            # make that edit disappear as a side effect of replacing the source.
            _protect_editable_documents(delivery, candidate)
        styles = transfer_project_styles(project, candidate)
        if (
            project_inventory(project) != original_state
            or file_inventory(source) != source_state
            or _delivery_inventory(delivery) != delivery_state
        ):
            raise ValueError(
                "Project, selected source, or visible delivery changed during preview; inspect again."
            )
        review = {
            "kind": "sciplot_project_source_update",
            "version": 1,
            "status": "ready",
            "project": str(project),
            "source": str(source),
            "worksheet": selected_sheet,
            "project_sha256": payload_hash(original_state),
            "source_files": source_state,
            "source_tree_sha256": source_tree_sha256(source),
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
        yield candidate, review


def preview_project_source_update(
    project_dir: Path, source: Path, *, worksheet: str | None = None
) -> dict[str, Any]:
    """Build and audit an isolated candidate without changing the active project."""
    try:
        with _prepared_update(project_dir, source, worksheet) as (_, preview):
            return preview
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
    """Recompute the reviewed candidate, reject stale choices, then adopt it."""
    if (
        preview.get("status") != "ready"
        or preview.get("kind") != "sciplot_project_source_update"
    ):
        raise ValueError(
            "A successful source-update preview must be explicitly reviewed before applying."
        )
    reject_symlink_path(project_dir.expanduser())
    project = project_dir.expanduser().resolve()
    with _prepared_update(
        project, Path(preview["source"]), preview.get("worksheet")
    ) as (candidate, current):
        if current != preview:
            raise ValueError(
                "The source-update preview is stale or changed; preview and confirm the current differences again."
            )
        expected = project_inventory(project)
        (candidate / "source_update.json").write_text(
            json.dumps(current, ensure_ascii=False, indent=2)
        )
        archive = install_source_update(
            project,
            candidate,
            expected=expected,
            validate=lambda: verify_project_science(project),
            precommit=lambda: _check_external_state(
                project, Path(preview["source"]), current
            ),
        )
    return {
        "kind": "sciplot_project_source_update",
        "version": 1,
        "status": "updated",
        "project": str(project),
        "document": str(project / "studio" / "document.vsz"),
        "archive": str(archive),
        "changes": preview["changes"],
        "styles": preview["styles"],
        "ready_to_use": False,
        "next_action": "save_and_export",
    }


__all__ = ["preview_project_source_update", "apply_project_source_update"]
