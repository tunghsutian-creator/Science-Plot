"""Read and describe the registered multi-figure Studio state."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.figure_plan.constants import REQUIRED_FIGURE_PLAN_RULE_IDS
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_KIND,
    STUDIO_FIGURE_SET_LEGACY_VERSION,
    STUDIO_FIGURE_SET_TASK_VERSION,
)
from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.figure_requests import (
    _rheology_frequency_figure_queue,
)
from sciplot_core.studio_core.figure_task_evidence import (
    validate_figure_registry_against_plan,
)
from sciplot_core.studio_core.figure_registry_entry import (
    _figure_registry_entry as _figure_registry_entry,
)

from sciplot_core.studio_core.registry_state import (
    _studio_figure_set_path,
    _veusz_spec_path,
)


def _read_studio_figure_set(project_dir: Path) -> dict[str, Any] | None:
    path = _studio_figure_set_path(project_dir)
    if not path.is_file():
        return None
    try:
        payload = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("kind") != STUDIO_FIGURE_SET_KIND:
        return None
    version = payload.get("version")
    if type(version) is not int or version not in {
        STUDIO_FIGURE_SET_LEGACY_VERSION,
        STUDIO_FIGURE_SET_TASK_VERSION,
    }:
        return None
    try:
        registry_plan = resolved_figure_plan_from_payload(
            payload.get("resolved_figure_plan")
        )
        if version == STUDIO_FIGURE_SET_LEGACY_VERSION:
            if registry_plan is not None or any(
                isinstance(value, dict) and "resolved_figure_task" in value
                for value in (
                    payload.get("figures")
                    if isinstance(payload.get("figures"), list)
                    else []
                )
            ):
                return None
        else:
            if registry_plan is None:
                return None
            validate_figure_registry_against_plan(payload, registry_plan)
    except (TypeError, ValueError):
        return None
    primary_id = str(payload.get("primary_figure_id") or "").strip()
    figures = payload.get("figures") if isinstance(payload.get("figures"), list) else []
    normalized_figures: list[dict[str, Any]] = []
    for value in figures:
        if not isinstance(value, dict):
            if version == STUDIO_FIGURE_SET_TASK_VERSION:
                return None
            continue
        figure_id = str(value.get("figure_id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", figure_id):
            if version == STUDIO_FIGURE_SET_TASK_VERSION:
                return None
            continue
        document_stem = str(value.get("document_stem") or figure_id).strip()
        if not re.fullmatch(
            r"[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9._\-\u4e00-\u9fff]*",
            document_stem,
        ):
            if version == STUDIO_FIGURE_SET_TASK_VERSION:
                return None
            continue
        document = (
            project_dir / "studio" / "document.vsz"
            if figure_id == primary_id
            else project_dir / "studio" / "figures" / f"{document_stem}.vsz"
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
    try:
        request_plan = resolved_figure_plan_from_payload(
            request.get("resolved_figure_plan")
        )
        registry_plan = resolved_figure_plan_from_payload(
            registry.get("resolved_figure_plan") if isinstance(registry, dict) else None
        )
    except (TypeError, ValueError):
        return None
    selected_supported_plan = (
        request_plan
        if request_plan is not None
        and request_plan.rule_id in REQUIRED_FIGURE_PLAN_RULE_IDS
        else None
    )
    if selected_supported_plan is not None:
        if (
            registry is None
            or registry.get("version") != STUDIO_FIGURE_SET_TASK_VERSION
            or registry_plan is None
        ):
            return None
        try:
            validate_figure_registry_against_plan(
                registry,
                selected_supported_plan,
            )
        except (TypeError, ValueError):
            return None
    if (
        request_plan is not None
        and registry_plan is not None
        and request_plan.plan_sha256 != registry_plan.plan_sha256
    ):
        return None
    effective_plan = request_plan or registry_plan
    queue = _rheology_frequency_figure_queue(
        request,
        figure_plan=effective_plan,
    )
    if registry is None and not queue:
        return None
    has_registry = registry is not None
    registry = registry or {}
    request_rule_id = str(request.get("rule_id") or "").strip()
    expected_frequency_primary = (
        effective_plan.primary_figure_id
        if effective_plan is not None
        and effective_plan.rule_id == "rheology_frequency_sweep"
        else next(
            (
                str(item["id"])
                for item in queue
                if item.get("y_metric") == "storage_modulus"
            ),
            "",
        )
    )
    if effective_plan is not None and has_registry:
        if (
            str(registry.get("rule_id") or "").strip() != effective_plan.rule_id
            or str(registry.get("primary_figure_id") or "").strip()
            != effective_plan.primary_figure_id
        ):
            return None
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
    planned_ids = (
        list(effective_plan.selected_figure_ids)
        if effective_plan is not None
        else [str(item["id"]) for item in queue]
    )
    if has_registry:
        if not figures:
            return None
        registry_ids = [str(item["figure_id"]) for item in figures]
        if len(registry_ids) != len(set(registry_ids)):
            return None
        if any(item.get("status") not in {"ready", "unavailable"} for item in figures):
            return None
        if planned_ids and registry_ids != planned_ids:
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
        document_stems = (
            {task.figure_id: task.document_stem for task in effective_plan.tasks}
            if effective_plan is not None
            else {
                str(item["id"]): str(item.get("document_stem") or item["id"])
                for item in queue
            }
        )
        for figure_id in planned_ids:
            document = (
                project_dir / "studio" / "document.vsz"
                if figure_id == primary_id
                else project_dir
                / "studio"
                / "figures"
                / f"{document_stems.get(figure_id, figure_id)}.vsz"
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
    scope = {
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
    if effective_plan is not None:
        if registry_plan is None or any(
            outcome.status != "editable" for outcome in registry_plan.outcomes
        ):
            return None
        scope["plan_id"] = effective_plan.plan_id
        scope["plan_sha256"] = effective_plan.plan_sha256
    return scope


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


def _replace_studio_figure_set_path(source: Path, target: Path) -> None:
    """Replace one canonical figure-set member through an injectable boundary."""

    os.replace(source, target)


build_studio_figure_set_export_scope = _studio_figure_set_export_scope
