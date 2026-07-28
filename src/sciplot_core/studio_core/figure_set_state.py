"""Read and describe the registered multi-figure Studio state."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_render.template_resolution import (
    _request_template,
)

from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.figure_requests import (
    _rheology_frequency_figure_queue,
)

from sciplot_core.studio_core.registry_state import (
    _studio_figure_set_path,
    _veusz_spec_path,
    _studio_document_state,
)


def _read_studio_figure_set(project_dir: Path) -> dict[str, Any] | None:
    request_path = project_dir / "plot_request.json"
    if request_path.is_file():
        try:
            request = _read_json(request_path)
        except (OSError, ValueError, json.JSONDecodeError):
            request = {}
        if (
            str(request.get("rule_id") or "").strip() == "impact_metric"
            and _request_template(request) == "point_line"
        ):
            # Intake may have materialized the default per-condition box
            # registry before the explicit point-line override was applied.
            # It is stale for the one-document comparison and must not leak
            # into exact-current export or delivery.
            return None
    path = _studio_figure_set_path(project_dir)
    if not path.is_file():
        return None
    try:
        payload = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("kind") != "sciplot_studio_figure_set":
        return None
    primary_id = str(payload.get("primary_figure_id") or "").strip()
    figures = payload.get("figures") if isinstance(payload.get("figures"), list) else []
    normalized_figures: list[dict[str, Any]] = []
    for value in figures:
        if not isinstance(value, dict):
            continue
        figure_id = str(value.get("figure_id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", figure_id):
            continue
        document = (
            project_dir / "studio" / "document.vsz"
            if figure_id == primary_id
            else project_dir / "studio" / "figures" / f"{figure_id}.vsz"
        )
        normalized_figures.append(
            {
                **value,
                "document": str(document.resolve()),
                "spec": str(_veusz_spec_path(document).resolve()),
            }
        )
    payload["figures"] = normalized_figures
    payload["primary_document"] = str(
        (project_dir / "studio" / "document.vsz").resolve()
    )
    payload["generated_from"] = str((project_dir / "plot_request.json").resolve())
    payload["registry_path"] = str(path.resolve())
    return payload


def _studio_figure_set_export_scope(
    project_dir: Path,
    *,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the all-or-nothing project scope for an independent figure set."""

    registry = _read_studio_figure_set(project_dir)
    queue = _rheology_frequency_figure_queue(request)
    if registry is None and not queue:
        return None
    has_registry = registry is not None
    registry = registry or {}
    request_rule_id = str(request.get("rule_id") or "").strip()
    expected_frequency_primary = next(
        (
            str(item["id"])
            for item in queue
            if item.get("y_metric") == "storage_modulus"
        ),
        "",
    )
    if queue and has_registry:
        if str(registry.get("rule_id") or "").strip() != request_rule_id:
            return None
        if (
            str(registry.get("primary_figure_id") or "").strip()
            != expected_frequency_primary
        ):
            return None
    figures = [
        item
        for item in registry.get("figures", [])
        if isinstance(item, dict) and str(item.get("figure_id") or "").strip()
    ]
    primary_id = (
        expected_frequency_primary
        or str(registry.get("primary_figure_id") or "").strip()
    )
    if not primary_id:
        return None
    planned_ids = [str(item["id"]) for item in queue]
    if has_registry:
        if not figures:
            return None
        registry_ids = [str(item["figure_id"]) for item in figures]
        if len(registry_ids) != len(set(registry_ids)):
            return None
        if any(item.get("status") not in {"ready", "unavailable"} for item in figures):
            return None
        if planned_ids:
            if set(registry_ids) != set(planned_ids):
                return None
        else:
            planned_ids = registry_ids
        available_ids = [
            str(item["figure_id"]) for item in figures if item.get("status") == "ready"
        ]
        unavailable_ids = [
            str(item["figure_id"])
            for item in figures
            if item.get("status") == "unavailable"
        ]
    else:
        available_ids = []
        unavailable_ids = []
        for figure_id in planned_ids:
            document = (
                project_dir / "studio" / "document.vsz"
                if figure_id == primary_id
                else project_dir / "studio" / "figures" / f"{figure_id}.vsz"
            )
            target = available_ids if document.is_file() else unavailable_ids
            target.append(figure_id)
    planned_set = set(planned_ids)
    available_set = set(available_ids)
    unavailable_set = set(unavailable_ids)
    if (
        primary_id not in available_set
        or available_set & unavailable_set
        or available_set | unavailable_set != planned_set
        or unavailable_set
    ):
        return None
    export_contract = (
        registry.get("export_contract")
        if isinstance(registry.get("export_contract"), dict)
        else {}
    )
    return {
        **json_safe(export_contract),
        "kind": "sciplot_figure_set_export_scope",
        "version": 2,
        "status": "full_figure_set_exact_current",
        "scope": "full_figure_set_project_delivery",
        "primary_figure_id": primary_id,
        "supported_figure_ids": list(dict.fromkeys(available_ids)),
        "blocked_figure_ids": [],
        "planned_figure_ids": list(dict.fromkeys(planned_ids or available_ids)),
        "available_figure_ids": list(dict.fromkeys(available_ids)),
        "unavailable_figure_ids": list(dict.fromkeys(unavailable_ids)),
        "secondary_receipt_scope": "same_project_delivery",
        "full_figure_set_delivery_complete": True,
        "blocker": None,
    }


def _figure_set_export_review_note(scope: dict[str, Any]) -> str:
    included = [
        str(value)
        for value in scope.get("supported_figure_ids", [])
        if str(value).strip()
    ]
    figure_text = ", ".join(f"`{value}`" for value in included) or "none"
    return (
        "Figure-set delivery scope: one project receipt and one minimal delivery "
        f"contain every registered figure ({figure_text}), with one exact-current "
        "VSZ and matching PDF/TIFF pair per figure."
    )


def _registered_figure_generated_hash(
    project_dir: Path,
    document_path: Path,
) -> str | None:
    registry = _read_studio_figure_set(project_dir)
    if registry is None:
        return None
    resolved = document_path.expanduser().resolve()
    for figure in registry.get("figures", []):
        if not isinstance(figure, dict):
            continue
        value = figure.get("document")
        if not isinstance(value, str) or not value.strip():
            continue
        if Path(value).expanduser().resolve() != resolved:
            continue
        generated_hash = figure.get("generated_hash")
        if isinstance(generated_hash, str) and generated_hash.strip():
            return generated_hash
    return None


def _figure_registry_entry(
    *,
    figure: dict[str, Any],
    document_path: Path,
    generated_hash: str | None,
    series_count: int,
    status: str = "ready",
    unavailable: dict[str, Any] | None = None,
    state_document_path: Path | None = None,
) -> dict[str, Any]:
    document_state = _studio_document_state(
        state_document_path or document_path,
        generated_hash=generated_hash,
    )
    entry = {
        "figure_id": str(figure["id"]),
        "title": str(figure.get("title") or figure["id"]),
        "metric": str(figure["y_metric"]),
        "x_metric": str(figure["x_metric"]),
        "y_metric": str(figure["y_metric"]),
        "order": int(figure.get("order") or 0),
        "status": status,
        "document": str(document_path),
        "spec": str(_veusz_spec_path(document_path)),
        "generated_hash": generated_hash,
        "series_count": int(series_count),
        "size_mm": [60, 55],
        "single_page": True,
        "document_authority": document_state["authority"],
        "document_state": document_state,
    }
    if unavailable is not None:
        entry["unavailable"] = json_safe(unavailable)
    return entry


def _replace_studio_figure_set_path(source: Path, target: Path) -> None:
    """Replace one canonical figure-set member through an injectable boundary."""

    os.replace(source, target)


build_studio_figure_set_export_scope = _studio_figure_set_export_scope
