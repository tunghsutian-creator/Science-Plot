"""Prepare all documents declared by a Studio figure queue."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4
from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    editable_figure_plan,
    request_for_figure_task,
)
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
)

from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.figure_requests import (
    _rheology_frequency_figure_queue,
    _rheology_frequency_figure_request,
    _impact_condition_figure_request,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_task_from_queue_item,
    validate_figure_queue_against_plan,
    validate_veusz_spec_figure_task,
)

from sciplot_core.studio_core.figure_set_state import (
    _read_studio_figure_set,
    _figure_registry_entry,
)

from sciplot_core.studio_core.figure_set_storage import (
    _commit_studio_figure_set_transaction,
)
from sciplot_core.studio_core.figure_set_registry import (
    build_studio_figure_set_registry,
)

from sciplot_core.studio_core.export_execution import (
    _count_veusz_series,
)

from sciplot_core.studio_core.series_request import (
    _series_from_request,
)

from sciplot_core.studio_core.veusz_document import (
    _write_veusz_document,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_path,
    _registered_generated_hash,
)


def _prepare_studio_figure_set(
    *,
    project_dir: Path,
    request_path: Path,
    request: dict[str, Any],
    primary_document: Path,
    primary_series_count: int | None = None,
    primary_generated_hash: str | None = None,
    primary_prior_generated_hash: str | None = None,
    primary_staged_document: Path | None = None,
    primary_staged_spec: Path | None = None,
    staged_request: Path | None = None,
    preserve_existing: bool,
    queue_override: list[dict[str, Any]] | None = None,
    figure_plan: ResolvedFigurePlan | None = None,
    prepared_source_attestation: PreparationSourceAttestation | None = None,
    path_replacer: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any] | None:
    queue = (
        list(queue_override)
        if queue_override is not None
        else _rheology_frequency_figure_queue(
            request,
            figure_plan=figure_plan,
        )
    )
    task_aware_queue = any(
        isinstance(item, dict) and "resolved_figure_task" in item for item in queue
    )
    if task_aware_queue:
        if figure_plan is None:
            raise ValueError(
                "studio_figure_task_mismatch: a task-aware Studio queue "
                "requires its selected FigurePlan."
            )
        validate_figure_queue_against_plan(queue, figure_plan)
    figures_dir = project_dir / "studio" / "figures"
    if queue:
        figures_dir.mkdir(parents=True, exist_ok=True)
    prior_registry = _read_studio_figure_set(project_dir) or {}
    prior_by_id = {
        str(item.get("figure_id")): item
        for item in prior_registry.get("figures", [])
        if isinstance(item, dict) and item.get("figure_id")
    }
    entries: list[dict[str, Any]] = []
    replacements: list[dict[str, Any]] = []
    manual_archive_requests: list[dict[str, Any]] = []
    if primary_staged_document is not None or primary_staged_spec is not None:
        if primary_staged_document is None or primary_staged_spec is None:
            raise ValueError(
                "A staged primary Studio document and spec must be supplied together."
            )
        primary_document_hash = existing_file_sha256(primary_staged_document)
        primary_spec_hash = existing_file_sha256(primary_staged_spec)
        if not primary_document_hash or not primary_spec_hash:
            raise RuntimeError("The staged primary Studio document is incomplete.")
        replacements.extend(
            [
                {
                    "staged": primary_staged_document,
                    "target": primary_document,
                    "expected_hash": primary_document_hash,
                    "kind": "document",
                },
                {
                    "staged": primary_staged_spec,
                    "target": _veusz_spec_path(primary_document),
                    "expected_hash": primary_spec_hash,
                    "kind": "spec",
                },
            ]
        )
        manual_archive_requests.append(
            {
                "document": primary_document,
                "spec": _veusz_spec_path(primary_document),
                "generated_hash": primary_prior_generated_hash,
            }
        )
    if staged_request is not None:
        staged_request_hash = existing_file_sha256(staged_request)
        if not staged_request_hash:
            raise RuntimeError("The staged Studio request is empty.")
        _read_json(staged_request)
        replacements.append(
            {
                "staged": staged_request,
                "target": request_path,
                "expected_hash": staged_request_hash,
                "kind": "request",
            }
        )
    if not queue:
        _commit_studio_figure_set_transaction(
            project_dir=project_dir,
            replacements=replacements,
            manual_archive_requests=manual_archive_requests,
            registry=None,
            path_replacer=path_replacer,
        )
        return None
    primary_id = (
        figure_plan.primary_figure_id
        if figure_plan is not None
        else (
            str(queue[0]["id"])
            if queue_override is not None
            else next(
                item["id"] for item in queue if item["y_metric"] == "storage_modulus"
            )
        )
    )
    try:
        for figure in queue:
            figure_id = str(figure["id"])
            is_primary = figure_id == primary_id
            prior = prior_by_id.get(figure_id, {})
            figure_context = figure
            task = figure_task_from_queue_item(figure_context)
            if (
                task is None
                and not is_primary
                and str(prior.get("document_stem") or "").strip()
            ):
                figure_context = {
                    **figure,
                    "document_stem": str(prior["document_stem"]).strip(),
                }
            document_path = (
                primary_document
                if is_primary
                else figures_dir
                / f"{str(figure_context.get('document_stem') or figure_id)}.vsz"
            )
            registered_hash = (
                primary_generated_hash
                if is_primary and primary_generated_hash
                else str(prior.get("generated_hash") or "").strip() or None
            )
            if is_primary and primary_staged_document is not None:
                if task is None:
                    raise ValueError(
                        "studio_figure_task_mismatch: staged primary figure "
                        "is missing its exact FigureTask."
                    )
                assert primary_staged_spec is not None
                validate_veusz_spec_figure_task(
                    _read_json(primary_staged_spec),
                    expected=task,
                    source="staged primary Veusz spec",
                )
                entries.append(
                    _figure_registry_entry(
                        figure=figure_context,
                        document_path=document_path,
                        generated_hash=primary_generated_hash,
                        series_count=int(primary_series_count or 0),
                        state_document_path=primary_staged_document,
                    )
                )
                continue
            if is_primary and document_path.is_file():
                generated_hash = registered_hash or _registered_generated_hash(
                    project_dir
                )
                entries.append(
                    _figure_registry_entry(
                        figure=figure_context,
                        document_path=document_path,
                        generated_hash=generated_hash,
                        series_count=(
                            int(primary_series_count)
                            if primary_series_count is not None
                            else _count_veusz_series(document_path)
                        ),
                    )
                )
                continue
            if preserve_existing and document_path.is_file():
                entries.append(
                    _figure_registry_entry(
                        figure=figure_context,
                        document_path=document_path,
                        generated_hash=registered_hash,
                        series_count=_count_veusz_series(document_path),
                    )
                )
                continue
            spec_path = _veusz_spec_path(document_path)
            figure_request = (
                request_for_figure_task(request, task)
                if task is not None
                and figure_plan is not None
                and figure_plan.rule_id != "impact_metric"
                else _impact_condition_figure_request(request, figure_context)
                if queue_override is not None
                else _rheology_frequency_figure_request(request, figure_context)
            )
            staged_document = document_path.with_name(
                f".sciplot-figure-set-transaction-{uuid4().hex}.vsz"
            )
            staged_spec = _veusz_spec_path(staged_document)
            try:
                series, axis_info, _steps, _source = _series_from_request(
                    figure_request,
                    base_dir=request_path.parent,
                    _prepared_source_attestation=prepared_source_attestation,
                )
                _write_veusz_document(
                    staged_document,
                    request=figure_request,
                    series=series,
                    axis_info=axis_info,
                )
            except StudioPreparationBlocked as exc:
                staged_document.unlink(missing_ok=True)
                staged_spec.unlink(missing_ok=True)
                entries.append(
                    _figure_registry_entry(
                        figure=figure_context,
                        document_path=document_path,
                        generated_hash=registered_hash,
                        series_count=(
                            _count_veusz_series(document_path)
                            if document_path.is_file()
                            else 0
                        ),
                        status="unavailable",
                        unavailable={
                            "reason_code": exc.reason_code,
                            "message": str(exc),
                        },
                    )
                )
                continue
            except Exception:
                staged_document.unlink(missing_ok=True)
                staged_spec.unlink(missing_ok=True)
                raise
            try:
                document_hash = existing_file_sha256(staged_document)
                spec_hash = existing_file_sha256(staged_spec)
                spec_kind = _read_json(staged_spec).get("kind")
            except Exception:
                staged_document.unlink(missing_ok=True)
                staged_spec.unlink(missing_ok=True)
                raise
            if (
                not document_hash
                or not spec_hash
                or spec_kind != "sciplot_veusz_plot_spec"
            ):
                staged_document.unlink(missing_ok=True)
                staged_spec.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Staged figure generation was incomplete for {figure_id}."
                )
            if task is not None:
                validate_veusz_spec_figure_task(
                    _read_json(staged_spec),
                    expected=task,
                    source=f"staged Studio figure `{figure_id}` Veusz spec",
                )
            replacements.extend(
                [
                    {
                        "staged": staged_document,
                        "target": document_path,
                        "expected_hash": document_hash,
                        "kind": "document",
                    },
                    {
                        "staged": staged_spec,
                        "target": spec_path,
                        "expected_hash": spec_hash,
                        "kind": "spec",
                    },
                ]
            )
            manual_archive_requests.append(
                {
                    "document": document_path,
                    "spec": spec_path,
                    "generated_hash": registered_hash,
                }
            )
            entries.append(
                _figure_registry_entry(
                    figure=figure_context,
                    document_path=document_path,
                    generated_hash=document_hash,
                    series_count=len(series),
                    state_document_path=staged_document,
                )
            )
    except Exception:
        for replacement in replacements:
            Path(replacement["staged"]).unlink(missing_ok=True)
        raise
    verified_pending_targets = {
        Path(str(replacement["target"])).expanduser().resolve()
        for replacement in replacements
        if replacement.get("kind") in {"document", "spec"}
    }
    resolved_plan = (
        editable_figure_plan(
            figure_plan,
            entries,
            verified_pending_artifact_targets=verified_pending_targets,
        )
        if figure_plan is not None
        else None
    )
    registry = build_studio_figure_set_registry(
        project_dir=project_dir,
        request_path=request_path,
        request=request,
        primary_figure_id=primary_id,
        primary_document=primary_document,
        entries=entries,
        resolved_plan=resolved_plan,
    )
    _commit_studio_figure_set_transaction(
        project_dir=project_dir,
        replacements=replacements,
        manual_archive_requests=manual_archive_requests,
        registry=registry,
        path_replacer=path_replacer,
    )
    return registry
