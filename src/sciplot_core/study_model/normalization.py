"""Normalize and construct study-model contracts."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from sciplot_core.study_model.experiment_plans import (
    STUDY_MODEL_KIND,
    STUDY_MODEL_VERSION,
    REPLICATE_MODES,
)

from sciplot_core.study_model.recommendations import (
    normalize_replicate_mode,
    _unique_id,
    _experiment_plan,
    _metric_payloads,
    _source_file_payload,
    _statistics_method_contract,
)


def normalize_study_model(study_model: dict[str, Any]) -> dict[str, Any]:
    """Add publication evidence fields without discarding v1 or unknown data."""

    normalized = copy.deepcopy(study_model)
    if normalized.get("kind") != STUDY_MODEL_KIND:
        return normalized
    raw_version = normalized.get("version", 1)
    if isinstance(raw_version, int) and raw_version > STUDY_MODEL_VERSION:
        # A future schema is not ours to rewrite or silently downgrade.
        return normalized
    normalized["version"] = STUDY_MODEL_VERSION
    samples = (
        normalized.get("samples") if isinstance(normalized.get("samples"), list) else []
    )
    sample_refs = [
        str(sample.get("id"))
        for sample in samples
        if isinstance(sample, dict) and sample.get("id")
    ]
    source_refs = [
        str(replicate.get("id"))
        for sample in samples
        if isinstance(sample, dict)
        for replicate in sample.get("replicates", [])
        if isinstance(replicate, dict) and replicate.get("id")
    ]
    queue = (
        normalized.get("figure_queue")
        if isinstance(normalized.get("figure_queue"), list)
        else []
    )
    normalized_queue: list[Any] = []
    for index, value in enumerate(queue, start=1):
        if not isinstance(value, dict):
            # Preserve opaque extension entries. Consumers of the public model
            # must ignore entries they do not understand rather than deleting
            # them during an additive migration.
            normalized_queue.append(copy.deepcopy(value))
            continue
        figure = copy.deepcopy(value)
        panel_id = str(figure.get("id") or f"panel_{index}")
        metric_refs = [str(figure["metric"])] if figure.get("metric") else []
        evidence = (
            copy.deepcopy(figure.get("evidence_contract"))
            if isinstance(figure.get("evidence_contract"), dict)
            else {}
        )
        evidence.setdefault("kind", "sciplot_panel_evidence_contract")
        evidence.setdefault("version", 1)
        evidence.setdefault("panel_id", panel_id)
        evidence.setdefault(
            "role", "primary_evidence" if index == 1 else "supporting_evidence"
        )
        evidence.setdefault("claim_refs", [])
        evidence.setdefault("source_refs", source_refs)
        evidence.setdefault("sample_refs", sample_refs)
        evidence.setdefault("metric_refs", metric_refs)
        evidence.setdefault("transform_step_refs", [])
        evidence.setdefault(
            "confirmation_status", "inferred" if metric_refs else "pending"
        )
        figure["evidence_contract"] = evidence
        if not isinstance(figure.get("statistics_method"), dict):
            figure["statistics_method"] = _statistics_method_contract(figure)
        normalized_queue.append(figure)
    normalized["figure_queue"] = normalized_queue
    integrity = (
        copy.deepcopy(normalized.get("scientific_integrity"))
        if isinstance(normalized.get("scientific_integrity"), dict)
        else {}
    )
    integrity.setdefault("scientific_outcome_agnostic", True)
    integrity.setdefault("significance_required", False)
    integrity.setdefault("silent_data_omission_allowed", False)
    integrity.setdefault("statistics_must_be_explicit", True)
    normalized["scientific_integrity"] = integrity
    normalized.setdefault("publication_intent_ref", None)
    return normalized


def build_study_model(
    *,
    data_type: dict[str, Any],
    experiment: dict[str, Any],
    groups: list[dict[str, Any]],
    replicate_mode: str,
    render_options: dict[str, Any] | None = None,
    column_confirmations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    experiment_type_id = str(experiment.get("id") or "unknown")
    rule_id = str(experiment.get("rule_id") or "") or None
    plan = _experiment_plan(experiment_type_id=experiment_type_id, rule_id=rule_id)
    selected_mode = normalize_replicate_mode(
        replicate_mode, default=plan["default_replicate_mode"]
    )
    figure_queue = [
        {
            **figure,
            "order": index,
            "status": "planned",
        }
        for index, figure in enumerate(
            copy.deepcopy(list(plan["figure_queue"])), start=1
        )
    ]
    sample_ids: set[str] = set()
    replicate_ids: set[str] = set()
    samples: list[dict[str, Any]] = []
    for sample_order, group in enumerate(groups, start=1):
        sample_name = str(group.get("sample") or "").strip()
        sample_id = _unique_id("sample", sample_name, sample_ids)
        replicates: list[dict[str, Any]] = []
        for replicate_order, file_info in enumerate(group.get("files", []), start=1):
            if not isinstance(file_info, dict):
                continue
            source_file = _source_file_payload(file_info)
            replicate_label = (
                Path(source_file["original_name"]).stem
                or f"replicate_{replicate_order}"
            )
            replicates.append(
                {
                    "id": _unique_id(
                        f"{sample_id}_replicate", replicate_label, replicate_ids
                    ),
                    "name": replicate_label,
                    "order": replicate_order,
                    "source_file": source_file,
                }
            )
        samples.append(
            {
                "id": sample_id,
                "name": sample_name,
                "order": sample_order,
                "replicate_mode": selected_mode,
                "replicates": replicates,
            }
        )
    return normalize_study_model(
        {
            "kind": STUDY_MODEL_KIND,
            "version": STUDY_MODEL_VERSION,
            "experiment": {
                "data_type_id": str(data_type.get("id") or "unknown"),
                "data_type_label": str(data_type.get("label") or ""),
                "experiment_type_id": experiment_type_id,
                "experiment_label": str(experiment.get("label") or ""),
                "rule_id": rule_id,
                "chart": experiment.get("chart"),
                "template": experiment.get("template"),
            },
            "replicate_policy": {
                "mode": selected_mode,
                "default_mode": plan["default_replicate_mode"],
                "available_modes": [
                    {"id": key, **value} for key, value in REPLICATE_MODES.items()
                ],
            },
            "sample_order": [sample["name"] for sample in samples],
            "samples": samples,
            "metrics": _metric_payloads(figure_queue),
            "figure_queue": figure_queue,
            "render_defaults": dict(render_options or {}),
            "column_confirmation_required": bool(column_confirmations),
        }
    )
