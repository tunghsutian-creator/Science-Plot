"""Build study models from requests and synchronize sample identities."""

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
    experiment_recommendation_payload,
    _metric_payloads,
)

from sciplot_core.study_model.normalization import (
    normalize_study_model,
)


def study_model_from_request(
    *,
    request: dict[str, Any],
    semantic: dict[str, Any],
    input_path: Path,
) -> dict[str, Any]:
    existing = request.get("study_model")
    if isinstance(existing, dict) and existing.get("kind") == STUDY_MODEL_KIND:
        return normalize_study_model(existing)

    rule_id = str(semantic.get("rule_id") or "") or None
    semantic_family = str(semantic.get("semantic_family") or "unknown")
    recommendation = experiment_recommendation_payload(
        rule_id=rule_id, semantic_family=semantic_family
    )
    plan = _experiment_plan(rule_id=rule_id, semantic_family=semantic_family)
    replicate_mode = normalize_replicate_mode(
        request.get("replicate_mode"), default=plan["default_replicate_mode"]
    )
    series_order = request.get("series_order")
    if isinstance(series_order, list | tuple):
        sample_names = [str(item).strip() for item in series_order if str(item).strip()]
    else:
        sample_names = []
    if not sample_names:
        sample_names = [input_path.stem if input_path.is_file() else input_path.name]

    sample_ids: set[str] = set()
    samples = [
        {
            "id": _unique_id("sample", sample, sample_ids),
            "name": sample,
            "order": index,
            "replicate_mode": replicate_mode,
            "replicates": [],
        }
        for index, sample in enumerate(sample_names, start=1)
    ]
    figure_queue = [
        {**figure, "order": index, "status": "planned"}
        for index, figure in enumerate(
            copy.deepcopy(recommendation["figure_queue"]), start=1
        )
    ]
    return normalize_study_model(
        {
            "kind": STUDY_MODEL_KIND,
            "version": STUDY_MODEL_VERSION,
            "experiment": {
                "data_type_id": None,
                "data_type_label": "",
                "experiment_type_id": recommendation["experiment_type_id"],
                "experiment_label": "",
                "rule_id": rule_id,
                "semantic_family": semantic_family,
                "chart": None,
                "template": request.get("template") or semantic.get("template"),
            },
            "replicate_policy": {
                "mode": replicate_mode,
                "default_mode": plan["default_replicate_mode"],
                "available_modes": [
                    {"id": key, **value} for key, value in REPLICATE_MODES.items()
                ],
            },
            "sample_order": sample_names,
            "samples": samples,
            "metrics": _metric_payloads(figure_queue),
            "figure_queue": figure_queue,
            "render_defaults": dict(request.get("render_options") or {}),
            "column_confirmation_required": bool(request.get("column_confirmations")),
        }
    )


def sync_study_model_samples(
    study_model: dict[str, Any] | None,
    *,
    sample_order: list[str] | None,
) -> dict[str, Any] | None:
    if not isinstance(study_model, dict) or study_model.get("kind") != STUDY_MODEL_KIND:
        return study_model
    study_model = normalize_study_model(study_model)
    if not sample_order:
        return copy.deepcopy(study_model)
    selected = [str(item).strip() for item in sample_order if str(item).strip()]
    if not selected:
        return copy.deepcopy(study_model)
    selected_set = set(selected)
    synced = copy.deepcopy(study_model)
    samples = [
        sample
        for sample in synced.get("samples", [])
        if str(sample.get("name") or "") in selected_set
    ]
    order = {sample: index for index, sample in enumerate(selected, start=1)}
    samples.sort(
        key=lambda sample: order.get(str(sample.get("name") or ""), len(order) + 1)
    )
    for index, sample in enumerate(samples, start=1):
        sample["order"] = index
    synced["samples"] = samples
    synced["sample_order"] = [sample["name"] for sample in samples]
    valid_sample_refs = {
        str(sample.get("id"))
        for sample in samples
        if isinstance(sample, dict) and sample.get("id")
    }
    valid_source_refs = {
        str(replicate.get("id"))
        for sample in samples
        if isinstance(sample, dict)
        for replicate in sample.get("replicates", [])
        if isinstance(replicate, dict) and replicate.get("id")
    }
    for figure in synced.get("figure_queue", []):
        if not isinstance(figure, dict):
            continue
        evidence = figure.get("evidence_contract")
        if not isinstance(evidence, dict):
            continue
        sample_refs = evidence.get("sample_refs")
        if isinstance(sample_refs, list):
            evidence["sample_refs"] = [
                str(ref) for ref in sample_refs if str(ref) in valid_sample_refs
            ]
        source_refs = evidence.get("source_refs")
        if isinstance(source_refs, list):
            evidence["source_refs"] = [
                str(ref) for ref in source_refs if str(ref) in valid_source_refs
            ]
    return synced
