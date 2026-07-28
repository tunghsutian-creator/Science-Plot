"""Prepare all documents declared by a Studio figure queue."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4
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

from sciplot_core.studio_core.figure_set_state import (
    _read_studio_figure_set,
    _figure_registry_entry,
)

from sciplot_core.studio_core.figure_set_storage import (
    _commit_studio_figure_set_transaction,
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
    _studio_figure_set_path,
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
    preserve_existing: bool,
    queue_override: list[dict[str, Any]] | None = None,
    path_replacer: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any] | None:
    queue = (
        list(queue_override)
        if queue_override is not None
        else _rheology_frequency_figure_queue(request)
    )
    if not queue:
        return None
    figures_dir = project_dir / "studio" / "figures"
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
    primary_id = (
        str(queue[0]["id"])
        if queue_override is not None
        else next(item["id"] for item in queue if item["y_metric"] == "storage_modulus")
    )
    try:
        for figure in queue:
            figure_id = str(figure["id"])
            is_primary = figure_id == primary_id
            document_path = (
                primary_document if is_primary else figures_dir / f"{figure_id}.vsz"
            )
            prior = prior_by_id.get(figure_id, {})
            registered_hash = (
                primary_generated_hash
                if is_primary and primary_generated_hash
                else str(prior.get("generated_hash") or "").strip() or None
            )
            if is_primary and document_path.is_file():
                generated_hash = registered_hash or _registered_generated_hash(
                    project_dir
                )
                entries.append(
                    _figure_registry_entry(
                        figure=figure,
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
                        figure=figure,
                        document_path=document_path,
                        generated_hash=registered_hash,
                        series_count=_count_veusz_series(document_path),
                    )
                )
                continue
            spec_path = _veusz_spec_path(document_path)
            figure_request = (
                _impact_condition_figure_request(request, figure)
                if queue_override is not None
                else _rheology_frequency_figure_request(request, figure)
            )
            staged_document = document_path.with_name(
                f".sciplot-figure-set-transaction-{uuid4().hex}.vsz"
            )
            staged_spec = _veusz_spec_path(staged_document)
            try:
                series, axis_info, _steps, _source = _series_from_request(
                    figure_request,
                    base_dir=request_path.parent,
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
                        figure=figure,
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
                    figure=figure,
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
    registry = {
        "kind": "sciplot_studio_figure_set",
        "version": 1,
        "rule_id": str(request.get("rule_id") or ""),
        "status": (
            "ready"
            if all(item.get("status") == "ready" for item in entries)
            else "partially_available"
        ),
        "primary_figure_id": primary_id,
        "primary_document": str(primary_document),
        "document_policy": "independent_single_page_vsz",
        "publication_layout_inferred": False,
        "composite_figure": False,
        "figures": entries,
        "export_contract": {
            "kind": "sciplot_figure_set_export_scope",
            "version": 2,
            "status": "full_figure_set_exact_current",
            "scope": "full_figure_set_project_delivery",
            "primary_figure_id": primary_id,
            "supported_figure_ids": [
                str(item["figure_id"])
                for item in entries
                if item.get("status") == "ready"
            ],
            "blocked_figure_ids": [],
            "blocker": None,
            "secondary_receipt_scope": "same_project_delivery",
            "full_figure_set_delivery_complete": all(
                item.get("status") == "ready" for item in entries
            ),
        },
        "generated_from": str(request_path),
        "registry_path": str(_studio_figure_set_path(project_dir)),
    }
    _commit_studio_figure_set_transaction(
        project_dir=project_dir,
        replacements=replacements,
        manual_archive_requests=manual_archive_requests,
        registry=registry,
        path_replacer=path_replacer,
    )
    return registry
