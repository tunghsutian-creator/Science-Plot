"""Build experiment, metric, source, and statistics recommendation payloads."""

from __future__ import annotations

import copy
import re
from typing import Any

from sciplot_core.study_model.experiment_plans import (
    REPLICATE_MODES,
    _REPLICATE_MODE_ALIASES,
    _DEFAULT_FIGURE_QUEUE,
    _EXPERIMENT_PLANS,
)


def normalize_replicate_mode(value: object, *, default: str = "mean") -> str:
    selected = str(value or default).strip().casefold()
    selected = _REPLICATE_MODE_ALIASES.get(selected, selected)
    return selected if selected in REPLICATE_MODES else default


def _token(value: object) -> str:
    text = re.sub(r"[^0-9A-Za-z]+", "_", str(value or "").strip().casefold())
    return text.strip("_") or "item"


def _unique_id(prefix: str, value: object, used: set[str]) -> str:
    base = f"{prefix}_{_token(value)}" if prefix else _token(value)
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _experiment_plan(
    *,
    experiment_type_id: str | None = None,
    rule_id: str | None = None,
    semantic_family: str | None = None,
) -> dict[str, Any]:
    for key in (experiment_type_id, rule_id, semantic_family):
        if isinstance(key, str) and key in _EXPERIMENT_PLANS:
            return copy.deepcopy(_EXPERIMENT_PLANS[key])
    return {
        "default_replicate_mode": "mean",
        "figure_queue": copy.deepcopy(_DEFAULT_FIGURE_QUEUE),
    }


def experiment_recommendation_payload(
    *,
    rule_id: str | None = None,
    semantic_family: str | None = None,
    experiment_type_id: str | None = None,
) -> dict[str, Any]:
    plan = _experiment_plan(
        experiment_type_id=experiment_type_id,
        rule_id=rule_id,
        semantic_family=semantic_family,
    )
    return {
        "kind": "sciplot_experiment_recommendation",
        "experiment_type_id": experiment_type_id
        or rule_id
        or semantic_family
        or "unknown",
        "rule_id": rule_id,
        "semantic_family": semantic_family,
        "default_replicate_mode": plan["default_replicate_mode"],
        "figure_count": len(plan["figure_queue"]),
        "figure_queue": copy.deepcopy(list(plan["figure_queue"])),
    }


def _metric_payloads(figure_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for figure in figure_queue:
        metric = str(figure.get("metric") or "").strip()
        if not metric or metric in seen:
            continue
        seen.add(metric)
        metrics.append(
            {
                "id": metric,
                "label": str(figure.get("title") or metric),
                "role": "figure_metric",
            }
        )
    return metrics


def _source_file_payload(file_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "original_name": str(
            file_info.get("original_name") or file_info.get("name") or ""
        ),
        "raw_path": str(file_info.get("raw_path") or ""),
        "source_path": str(file_info.get("source_path") or ""),
        "size_bytes": int(file_info.get("size_bytes") or 0),
        "sha256": str(file_info.get("sha256") or ""),
    }


def _statistics_method_contract(figure: dict[str, Any]) -> dict[str, Any]:
    template = str(figure.get("default_template") or "").casefold()
    figure_id = str(figure.get("id") or "").casefold()
    method_required = template in {
        "bar",
        "box",
        "box_strip",
        "violin",
        "point_interval",
    } or ("statistics" in figure_id)
    return {
        "kind": "sciplot_statistics_method_contract",
        "version": 1,
        "status": "pending" if method_required else "not_requested",
        "auto_inference_allowed": False,
        "significance_required": False,
        "method_id": None,
        "method_version": None,
        "source": None,
        "n_definition": None,
        "center": None,
        "spread_or_interval": None,
        "test": None,
        "multiple_comparisons": None,
        "parameters": {},
    }
