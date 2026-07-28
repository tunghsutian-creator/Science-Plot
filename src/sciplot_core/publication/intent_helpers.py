"""Normalize figure, statistics, panel, and existing-intent fields."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _figure_height_mm(request: dict[str, Any]) -> float:
    options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    size = options.get("size")
    if isinstance(size, str) and "x" in size.casefold():
        try:
            return float(size.casefold().split("x", 1)[1])
        except ValueError:
            pass
    return 55.0


def _statistics_contract_for_figure(figure: dict[str, Any]) -> dict[str, Any]:
    template = str(figure.get("default_template") or "").casefold()
    figure_id = str(figure.get("id") or "").casefold()
    needs_method = template in {
        "bar",
        "box",
        "box_strip",
        "violin",
        "point_interval",
    } or ("statistics" in figure_id)
    return {
        "kind": "sciplot_statistics_method_contract",
        "version": 1,
        "status": "pending" if needs_method else "not_requested",
        "auto_inference_allowed": False,
        "significance_required": False,
        "method_id": None,
        "method_version": None,
        "n_definition": None,
        "center": None,
        "spread_or_interval": None,
        "test": None,
        "multiple_comparisons": None,
        "parameters": {},
    }


def _explicit_request_text(request: dict[str, Any], key: str) -> tuple[bool, str]:
    if key not in request:
        return False, ""
    return True, str(request.get(key) or "").strip()


def _merge_existing(
    defaults: dict[str, Any], existing: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge an existing contract additively, with existing values authoritative."""

    merged = deepcopy(defaults)
    if not isinstance(existing, dict):
        return merged
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_existing(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _merge_keyed_contracts(
    defaults: list[dict[str, Any]],
    existing: object,
    *,
    id_key: str,
) -> list[dict[str, Any]]:
    existing_items = (
        [deepcopy(item) for item in existing if isinstance(item, dict)]
        if isinstance(existing, list)
        else []
    )
    existing_by_id = {
        str(item.get(id_key)): item
        for item in existing_items
        if isinstance(item.get(id_key), str) and str(item[id_key]).strip()
    }
    merged: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for default in defaults:
        item_id = str(default.get(id_key) or "")
        prior = existing_by_id.get(item_id)
        merged.append(_merge_existing(default, prior))
        if prior is not None:
            consumed.add(item_id)
    merged.extend(
        item
        for item in existing_items
        if not isinstance(item.get(id_key), str)
        or str(item.get(id_key)) not in consumed
    )
    return merged


def _reference_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return deepcopy(value) if isinstance(value, list) else []


def _figure_contracts(
    study_model: dict[str, Any], existing: dict[str, Any]
) -> list[dict[str, Any]]:
    figures = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
    defaults: list[dict[str, Any]] = []
    for index, figure in enumerate(figures, start=1):
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("id") or f"figure_{index}")
        evidence = (
            figure.get("evidence_contract")
            if isinstance(figure.get("evidence_contract"), dict)
            else {}
        )
        defaults.append(
            {
                "figure_id": figure_id,
                "order": index,
                "title": str(figure.get("title") or ""),
                "role": "independent_figure_candidate",
                "question": "",
                "supported_claim_refs": _reference_list(evidence, "claim_refs"),
                "metric_refs": _reference_list(evidence, "metric_refs")
                or ([figure.get("metric")] if figure.get("metric") else []),
                "sample_refs": _reference_list(evidence, "sample_refs"),
                "source_refs": _reference_list(evidence, "source_refs"),
                "transform_step_refs": _reference_list(evidence, "transform_step_refs"),
                "confirmation_status": str(
                    evidence.get("confirmation_status") or "pending"
                ),
                "statistics_method": deepcopy(
                    figure.get("statistics_method")
                    if isinstance(figure.get("statistics_method"), dict)
                    else _statistics_contract_for_figure(figure)
                ),
            }
        )
    return _merge_keyed_contracts(
        defaults,
        existing.get("figure_contracts"),
        id_key="figure_id",
    )


def _panel_defaults_for_layout(
    layout: dict[str, Any] | None,
    existing_panels: object,
) -> list[dict[str, Any]]:
    if not isinstance(layout, dict):
        return []
    prior = (
        [item for item in existing_panels if isinstance(item, dict)]
        if isinstance(existing_panels, list)
        else []
    )
    defaults: list[dict[str, Any]] = []
    for index, slot in enumerate(layout.get("slots", []), start=1):
        if not isinstance(slot, dict):
            continue
        prior_id = prior[index - 1].get("panel_id") if index <= len(prior) else None
        panel_id = str(prior_id or slot.get("id") or f"panel_{index}")
        defaults.append(
            {
                "panel_id": panel_id,
                "order": index,
                "panel_label": str(
                    slot.get("panel_label") or chr(ord("a") + index - 1)
                ),
                "role": "primary_evidence" if index == 1 else "supporting_evidence",
                "slot_ref": str(slot.get("id") or ""),
                "question": "",
                "supported_claim_refs": [],
                "metric_refs": [],
                "sample_refs": [],
                "source_refs": [],
                "transform_step_refs": [],
                "confirmation_status": "pending",
                "statistics_method": _statistics_contract_for_figure({}),
            }
        )
    return defaults
