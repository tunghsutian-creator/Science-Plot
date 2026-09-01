"""Closed contracts and metrics for the R0 automation baseline probe."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from sciplot_core.automation_baseline_schema import (
    AUTOMATION_BASELINE_KIND,
    AUTOMATION_BASELINE_SCENARIOS,
    AUTOMATION_BASELINE_VERSION,
    METRIC_FIELDS as _METRIC_FIELDS,
)
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_values import json_safe


def canonical_json_bytes(value: object) -> int:
    """Return the canonical compact UTF-8 size of a JSON-safe value."""

    payload = json.dumps(
        json_safe(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return len(payload.encode("utf-8"))


def payload_measurement_projection(value: Any) -> Any:
    """Remove machine-local path length from an owner-payload measurement."""

    if isinstance(value, Mapping):
        return {
            str(key): payload_measurement_projection(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [payload_measurement_projection(item) for item in value]
    if isinstance(value, str):
        filesystem_roots = (
            "/Users/",
            "/home/",
            "/private/",
            "/tmp/",
            "/var/folders/",
            "/Volumes/",
            "/workspace/",
            "/workspaces/",
            "/mnt/",
        )
        if value.startswith(filesystem_roots) or re.match(
            r"^[A-Za-z]:[\\/]", value
        ):
            return "<absolute-path>"
        if value == ".tmp_verify" or value.startswith(".tmp_verify/"):
            return "<development-evidence-path>"
    return deepcopy(value)


def figure_plan_fact_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project immutable plan facts while excluding outcome lifecycle state."""

    return {
        "plan_id": payload.get("plan_id"),
        "plan_sha256": payload.get("plan_sha256"),
        "rule_id": payload.get("rule_id"),
        "selection_policy": payload.get("selection_policy"),
        "primary_figure_id": payload.get("primary_figure_id"),
        "source_sha256": payload.get("source_sha256"),
        "selected_figure_ids": deepcopy(payload.get("selected_figure_ids")),
        "tasks": deepcopy(payload.get("tasks")),
    }


def figure_plan_evidence_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Hash task details before persisting the immutable plan identity."""

    identity = figure_plan_fact_identity(payload)
    tasks = identity.pop("tasks")
    identity["tasks_sha256"] = canonical_json_sha256(tasks, allow_nan=False)
    return identity


def metric_distribution(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize every closed numeric metric with P50 and P95 values."""

    result: dict[str, Any] = {}
    for field in sorted(_METRIC_FIELDS):
        raw_values = [sample[field] for sample in samples]
        values = [float(value) for value in raw_values if value is not None]
        result[field] = {
            "values": raw_values,
            "p50": _percentile(values, 0.50) if values else None,
            "p95": _percentile(values, 0.95) if values else None,
        }
    return result


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot summarize an empty metric sequence.")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    weight = position - lower
    return round(ordered[lower] * (1.0 - weight) + ordered[upper] * weight, 3)


__all__ = [
    "AUTOMATION_BASELINE_KIND",
    "AUTOMATION_BASELINE_SCENARIOS",
    "AUTOMATION_BASELINE_VERSION",
    "canonical_json_bytes",
    "figure_plan_evidence_identity",
    "figure_plan_fact_identity",
    "metric_distribution",
    "payload_measurement_projection",
]
