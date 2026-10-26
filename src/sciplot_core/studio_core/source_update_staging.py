"""Prepare a fresh source request inside the existing project's private image."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections.abc import Iterator
from contextlib import contextmanager, AbstractContextManager

from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import get_rule
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.source_coverage.managed_documents import (
    verify_managed_document_sources,
)
from sciplot_core.source_coverage.managed_task_sources import registered_task_snapshot_sources
from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate
from sciplot_core.studio_core.source_update_review import project_figures


def verify_project_science(project: Path) -> dict[str, Any]:
    request = json.loads((project / "plot_request.json").read_text())
    _, application = resolve_data_mapping_request(request, base_dir=project)
    documents = [item[0] for item in project_figures(project).values()]
    sources = registered_task_snapshot_sources(
        request=request, project_dir=project, documents=documents,
        existing_sources=[project / "source", project / "studio" / "processed"],
        data_mapping_application=application,
    )
    return verify_managed_document_sources(
        {
            "veusz_documents": [str(path) for path in documents],
            "data_snapshot_sources": [str(path) for path in sources],
            "template": request.get("template"),
        },
        mapping_application=application,
    )


def _worksheet_confirmation(
    source: Path, worksheet: str | None, rule_id: str
) -> list[dict[str, Any]]:
    from sciplot_core.intake.table_preview import preview_table_payload

    if not worksheet:
        return []
    if get_rule(rule_id).scientific_source_adapter != "registered_paired_curve":
        raise ValueError(
            f"{rule_id} owns its worksheet/condition interpretation; no worksheet can be silently omitted."
        )
    if not source.is_file() or source.suffix.casefold() not in {".xls", ".xlsx"}:
        raise ValueError("Explicit worksheet selection requires one Excel workbook.")
    table = preview_table_payload(
        name=source.name, source_path=source, selected_sheet=worksheet
    )
    return [
        {
            "file_name": source.name,
            "source_path": str(source),
            "source_sha256": file_sha256(source),
            "sheet": worksheet,
            "sheet_selected": True,
            "columns": [
                {
                    "index": c["index"],
                    "name": c["name"],
                    "role": c["suggested_role"],
                    "confirmed_type": c["inferred_type"],
                }
                for c in table["columns"]
            ],
        }
    ]


def current_source_update_request(
    project: Path, mapping_request: dict[str, Any] | None, *, snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Admit current scientific intent before new-source IO or a project writer."""
    from sciplot_core.foundation.canonical_paths import canonical_path
    from sciplot_core.project_host_factory import _admitted_request
    from sciplot_core.project_manifest_locations import admitted_project_generation
    from sciplot_core.project_store import ProjectConflict

    project = canonical_path(project)
    has_head = (project / ".sciplot_store/head.json").is_file()
    if not has_head and not (project / "plot_request.json").is_file():
        raise ValueError("Source update requires an existing SciPlot project.")
    if has_head:
        # New source preparation always belongs to current intent, even within
        # a legitimate historical read runtime. Reuse the host's preimage check
        # under this same readonly lock when checking an explicit generation.
        with admitted_project_generation(project) as (_primary, _io, current):
            previous = _admitted_request(project)
            if snapshot is not None and (snapshot.get("project_id") != current["project_id"]
                    or snapshot.get("generation") != current["generation"]):
                raise ProjectConflict("Source update preparation requires the current project generation.")
    else:
        if snapshot is not None:
            raise ProjectConflict("Source update preparation requires the current project generation.")
        previous = _admitted_request(project)
    # Without an admitted head, the host factory's supported unimported
    # legacy request remains the explicit fallback; no store was imported.
    if not isinstance(previous, dict):
        raise ValueError("The canonical project request must be an object")
    rule_id = str(previous.get("rule_id") or "")
    if mapping_request is None:
        if (not rule_id or previous.get("data_mapping") or previous.get("data_mapping_application")
                or any(key in previous for key in ("data_mapping_execution", "data_mapping_proposal_id", "data_mapping_plan_binding"))):
            raise ValueError("This source needs a fresh explicit data mapping before it can replace the project source.")
    elif mapping_request.get("rule_id") != rule_id or mapping_request.get("template") != previous.get("template"):
        raise ValueError("Fresh mapping must preserve the project's confirmed experiment and template.")
    return previous


@contextmanager
def prepare_candidate(
    project: Path, source: Path, temporary: Path, *, worksheet: str | None,
    mapping_request: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> Iterator[tuple[StudioPreparationCandidate, list[dict[str, Any]]]]:
    from sciplot_core.data_mapping.execution_inputs import mapping_input_reads

    previous = current_source_update_request(project, mapping_request, snapshot=snapshot)
    reference = mapping_request.get("data_mapping_execution") if mapping_request is not None else None
    with mapping_input_reads(reference, expected_source=source):
        with _prepare_candidate(project, source, temporary, worksheet=worksheet,
                previous=previous, mapping_request=mapping_request, snapshot=snapshot) as result:
            yield result


def _prepare_candidate(
    project: Path, source: Path, temporary: Path, *, worksheet: str | None,
    previous: dict[str, Any],
    mapping_request: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> AbstractContextManager[tuple[StudioPreparationCandidate, list[dict[str, Any]]]]:
    """Validate a fresh scientific request before allocating its private image."""
    rule_id = str(previous.get("rule_id") or "")
    delivery = requested_delivery_root({"request": previous}, run_output=project)
    confirmations = _worksheet_confirmation(source, worksheet, rule_id)
    if mapping_request is not None:
        from sciplot_core.plan_preview import build_plan_preview
        from sciplot_core.data_mapping.plan_binding import verify_replicate_source_expansion
        from sciplot_core.studio_core.project_creation import request_from_verified_plan

        plan = dict(build_plan_preview(source, request=mapping_request))
        if plan["status"] != "planned":
            raise ValueError(f"Fresh source mapping cannot prepare this project: {plan.get('blocker')}")
        try:
            verify_replicate_source_expansion(previous, source, mapping_request, plan)
        except ValueError as exc:
            raise ValueError(f"Fresh source mapping cannot prepare this project: {exc}") from exc
        request = request_from_verified_plan(source, verified=plan, project_dir=project, delivery_root=delivery)
    else:
        # Scientific labels, ranges, units, plans and transformations are derived
        # afresh from the confirmed incoming source. Existing raw/source members
        # remain historical original bytes in the same project generation.
        request = {"recipe": "auto", "input": str(source), "output": previous.get("output", str(project / "runs/run_001")),
                   "rule_id": rule_id, "template": previous["template"],
                   "explicit_template_selection": True, "exports": previous.get("exports", ["pdf", "tiff_300"]),
                   "replicate_mode": previous.get("replicate_mode", "raw"), "delivery_output": str(delivery)}
        options = {key: value for key, value in previous.get("render_options", {}).items()
                   if key in {"size", "style_preset", "visual_theme_id", "palette_preset"}}
        if options:
            request["render_options"] = options
    if confirmations:
        request["column_confirmations"] = confirmations
    return _build_source_candidate(project, request, confirmations, snapshot=snapshot)


@contextmanager
def _build_source_candidate(project: Path, request: dict[str, Any], confirmations: list[dict[str, Any]], *,
                            snapshot: dict[str, Any] | None = None) -> Iterator[tuple[StudioPreparationCandidate, list[dict[str, Any]]]]:
    from sciplot_core.studio_core.project_command_scope import project_store
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_core.preparation_commands import prepare_studio_candidate

    repository = project_store(project, with_snapshot=True)
    with studio_preparation_candidate(repository, snapshot=snapshot) as candidate:
        candidate.write_request(request)
        payload = prepare_studio_candidate(candidate, request_target=True, regenerate_generated=True)
        if payload.get("document") is None:
            raise ValueError("The replacement source cannot produce a complete current figure set")
        from sciplot_core.data_mapping.execution_inputs import mapping_execution_path, mapping_input_scope

        reference = request.get("data_mapping_execution")
        readset = candidate.mapping_inputs.get(str(mapping_execution_path(reference))) if reference else None
        with mapping_input_scope(readset):
            yield candidate, confirmations



__all__ = ["current_source_update_request", "prepare_candidate", "verify_project_science"]
