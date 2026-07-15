from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

STUDY_MODEL_KIND = "sciplot_study_model"
STUDY_MODEL_VERSION = 2

REPLICATE_MODES: dict[str, dict[str, str]] = {
    "mean": {
        "label": "Mean",
        "description": "Average compatible replicate files into one sample trace or metric.",
    },
    "representative": {
        "label": "Representative",
        "description": "Keep one representative replicate for the sample.",
    },
    "individual": {
        "label": "All",
        "description": "Render each replicate trace or metric without averaging.",
    },
}

_REPLICATE_MODE_ALIASES = {
    "average": "mean",
    "avg": "mean",
    "best": "representative",
    "all": "individual",
}

_DEFAULT_FIGURE_QUEUE = (
    {
        "id": "primary_curve",
        "title": "Primary curve",
        "metric": "primary",
        "x_metric": "x",
        "y_metric": "y",
        "default_template": "curve",
    },
)

_TENSILE_DESCRIPTIVE_STATISTICS = {
    "kind": "sciplot_statistics_method_contract",
    "version": 1,
    "status": "confirmed",
    "auto_inference_allowed": False,
    "significance_required": False,
    "method_id": "descriptive_median_iqr_raw_points",
    "method_version": "1",
    "source": "tensile_curve rule",
    "n_definition": "one independently tested specimen",
    "center": "median",
    "spread_or_interval": "interquartile range",
    "test": "none",
    "multiple_comparisons": "none",
    "parameters": {"raw_points_visible": True},
}

_EXPERIMENT_PLANS: dict[str, dict[str, Any]] = {
    "rheology_frequency_sweep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "storage_modulus_vs_frequency",
                "title": "Storage modulus vs frequency",
                "metric": "storage_modulus",
                "x_metric": "angular_frequency",
                "y_metric": "storage_modulus",
                "default_template": "point_line",
            },
            {
                "id": "loss_modulus_vs_frequency",
                "title": "Loss modulus vs frequency",
                "metric": "loss_modulus",
                "x_metric": "angular_frequency",
                "y_metric": "loss_modulus",
                "default_template": "point_line",
            },
            {
                "id": "loss_factor_vs_frequency",
                "title": "tan delta vs frequency",
                "metric": "loss_factor",
                "x_metric": "angular_frequency",
                "y_metric": "loss_factor",
                "default_template": "point_line",
            },
            {
                "id": "complex_viscosity_vs_frequency",
                "title": "Complex viscosity vs frequency",
                "metric": "complex_viscosity",
                "x_metric": "angular_frequency",
                "y_metric": "complex_viscosity",
                "default_template": "point_line",
            },
        ),
    },
    "rheology_temperature_sweep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "storage_modulus_vs_temperature",
                "title": "Storage modulus vs temperature",
                "metric": "storage_modulus",
                "x_metric": "temperature",
                "y_metric": "storage_modulus",
                "default_template": "point_line",
            },
            {
                "id": "tan_delta_vs_temperature",
                "title": "tan delta vs temperature",
                "metric": "tan_delta",
                "x_metric": "temperature",
                "y_metric": "tan_delta",
                "default_template": "point_line",
            },
        ),
    },
    "rheology_stress_relaxation": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "normalized_stress_vs_time",
                "title": "Normalized stress vs time",
                "metric": "normalized_stress",
                "x_metric": "time",
                "y_metric": "normalized_stress",
                "default_template": "curve",
            },
        ),
    },
    "rheology_creep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "creep_compliance_vs_time",
                "title": "Creep compliance vs time",
                "metric": "creep_compliance",
                "x_metric": "time",
                "y_metric": "creep_compliance",
                "default_template": "curve",
            },
        ),
    },
    "tensile_curve": {
        "default_replicate_mode": "representative",
        "figure_queue": (
            {
                "id": "stress_vs_strain",
                "title": "Stress vs strain",
                "metric": "stress",
                "x_metric": "strain",
                "y_metric": "stress",
                "default_template": "curve",
            },
            {
                "id": "tensile_strength_by_sample",
                "title": "Tensile strength by sample",
                "metric": "strength_MPa",
                "x_metric": "sample",
                "y_metric": "strength_MPa",
                "default_template": "box_strip",
                "statistics_method": copy.deepcopy(_TENSILE_DESCRIPTIVE_STATISTICS),
            },
            {
                "id": "strain_at_break_by_sample",
                "title": "Strain at break by sample",
                "metric": "strain_at_break_percent",
                "x_metric": "sample",
                "y_metric": "strain_at_break_percent",
                "default_template": "box_strip",
                "statistics_method": copy.deepcopy(_TENSILE_DESCRIPTIVE_STATISTICS),
            },
            {
                "id": "tensile_modulus_by_sample",
                "title": "Tensile modulus by sample",
                "metric": "modulus_MPa",
                "x_metric": "sample",
                "y_metric": "modulus_MPa",
                "default_template": "box_strip",
                "statistics_method": copy.deepcopy(_TENSILE_DESCRIPTIVE_STATISTICS),
            },
            {
                "id": "toughness_by_sample",
                "title": "Toughness by sample",
                "metric": "toughness_MJ_m3",
                "x_metric": "sample",
                "y_metric": "toughness_MJ_m3",
                "default_template": "box_strip",
                "statistics_method": copy.deepcopy(_TENSILE_DESCRIPTIVE_STATISTICS),
            },
        ),
    },
    "torque_curve": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "screw_torque_vs_time",
                "title": "Screw torque vs time",
                "metric": "screw_torque",
                "x_metric": "time",
                "y_metric": "screw_torque",
                "default_template": "curve",
            },
        ),
    },
    "impact_metric": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "impact_strength_by_sample",
                "title": "Impact strength by sample",
                "metric": "impact_strength",
                "x_metric": "sample",
                "y_metric": "impact_strength",
                "default_template": "box_strip",
            },
        ),
    },
    "torque_offset_stack": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "screw_torque_offset_stack",
                "title": "Screw torque offset stack",
                "metric": "screw_torque",
                "x_metric": "time",
                "y_metric": "screw_torque",
                "default_template": "stacked_curve",
            },
        ),
    },
    "ftir_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "ftir_intensity_vs_wavenumber",
                "title": "FTIR spectrum",
                "metric": "infrared_intensity",
                "x_metric": "wavenumber",
                "y_metric": "intensity",
                "default_template": "curve",
            },
        ),
    },
    "raman_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "raman_intensity_vs_shift",
                "title": "Raman spectrum",
                "metric": "raman_intensity",
                "x_metric": "raman_shift",
                "y_metric": "intensity",
                "default_template": "curve",
            },
        ),
    },
    "uvvis_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "uvvis_absorbance_vs_wavelength",
                "title": "UV-vis spectrum",
                "metric": "absorbance",
                "x_metric": "wavelength",
                "y_metric": "absorbance",
                "default_template": "curve",
            },
        ),
    },
    "xps_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "xps_intensity_vs_binding_energy",
                "title": "XPS spectrum",
                "metric": "xps_intensity",
                "x_metric": "binding_energy",
                "y_metric": "intensity",
                "default_template": "curve",
            },
        ),
    },
}


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
    return {"default_replicate_mode": "mean", "figure_queue": copy.deepcopy(_DEFAULT_FIGURE_QUEUE)}


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
        "experiment_type_id": experiment_type_id or rule_id or semantic_family or "unknown",
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
        "original_name": str(file_info.get("original_name") or file_info.get("name") or ""),
        "raw_path": str(file_info.get("raw_path") or ""),
        "source_path": str(file_info.get("source_path") or ""),
        "size_bytes": int(file_info.get("size_bytes") or 0),
        "sha256": str(file_info.get("sha256") or ""),
    }


def _statistics_method_contract(figure: dict[str, Any]) -> dict[str, Any]:
    template = str(figure.get("default_template") or "").casefold()
    figure_id = str(figure.get("id") or "").casefold()
    method_required = template in {"bar", "box", "box_strip", "violin", "point_interval"} or (
        "statistics" in figure_id
    )
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
    samples = normalized.get("samples") if isinstance(normalized.get("samples"), list) else []
    sample_refs = [str(sample.get("id")) for sample in samples if isinstance(sample, dict) and sample.get("id")]
    source_refs = [
        str(replicate.get("id"))
        for sample in samples
        if isinstance(sample, dict)
        for replicate in sample.get("replicates", [])
        if isinstance(replicate, dict) and replicate.get("id")
    ]
    queue = normalized.get("figure_queue") if isinstance(normalized.get("figure_queue"), list) else []
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
        evidence.setdefault("role", "primary_evidence" if index == 1 else "supporting_evidence")
        evidence.setdefault("claim_refs", [])
        evidence.setdefault("source_refs", source_refs)
        evidence.setdefault("sample_refs", sample_refs)
        evidence.setdefault("metric_refs", metric_refs)
        evidence.setdefault("transform_step_refs", [])
        evidence.setdefault("confirmation_status", "inferred" if metric_refs else "pending")
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
    selected_mode = normalize_replicate_mode(replicate_mode, default=plan["default_replicate_mode"])
    figure_queue = [
        {
            **figure,
            "order": index,
            "status": "planned",
        }
        for index, figure in enumerate(copy.deepcopy(list(plan["figure_queue"])), start=1)
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
            replicate_label = Path(source_file["original_name"]).stem or f"replicate_{replicate_order}"
            replicates.append(
                {
                    "id": _unique_id(f"{sample_id}_replicate", replicate_label, replicate_ids),
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
    return normalize_study_model({
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
                {"id": key, **value}
                for key, value in REPLICATE_MODES.items()
            ],
        },
        "sample_order": [sample["name"] for sample in samples],
        "samples": samples,
        "metrics": _metric_payloads(figure_queue),
        "figure_queue": figure_queue,
        "render_defaults": dict(render_options or {}),
        "column_confirmation_required": bool(column_confirmations),
    })


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
    recommendation = experiment_recommendation_payload(rule_id=rule_id, semantic_family=semantic_family)
    plan = _experiment_plan(rule_id=rule_id, semantic_family=semantic_family)
    replicate_mode = normalize_replicate_mode(request.get("replicate_mode"), default=plan["default_replicate_mode"])
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
        for index, figure in enumerate(copy.deepcopy(recommendation["figure_queue"]), start=1)
    ]
    return normalize_study_model({
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
                {"id": key, **value}
                for key, value in REPLICATE_MODES.items()
            ],
        },
        "sample_order": sample_names,
        "samples": samples,
        "metrics": _metric_payloads(figure_queue),
        "figure_queue": figure_queue,
        "render_defaults": dict(request.get("render_options") or {}),
        "column_confirmation_required": bool(request.get("column_confirmations")),
    })


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
    samples = [sample for sample in synced.get("samples", []) if str(sample.get("name") or "") in selected_set]
    order = {sample: index for index, sample in enumerate(selected, start=1)}
    samples.sort(key=lambda sample: order.get(str(sample.get("name") or ""), len(order) + 1))
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


def _figure_artifact_key(path: str) -> str:
    stem = Path(path).stem
    if stem.endswith("_300dpi"):
        stem = stem[: -len("_300dpi")]
    return stem


def _json_contract_matches(path: Path, expected_kind: str) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("kind") == expected_kind


def attach_run_artifacts_to_study_model(
    study_model: dict[str, Any],
    *,
    output_dir: Path,
    figures: list[str],
    analysis_metrics: list[dict[str, Any]] | None = None,
    qa: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = normalize_study_model(study_model)
    artifact_groups: dict[str, list[dict[str, Any]]] = {}
    for figure in figures:
        artifact_groups.setdefault(_figure_artifact_key(figure), []).append(
            {
                "path": figure,
                "name": Path(figure).name,
                "format": Path(figure).suffix.lower().lstrip("."),
            }
        )
    grouped_artifacts = list(artifact_groups.values())
    queue = list(updated.get("figure_queue", []))
    bound_keys: set[str] = set()
    bindable_figures = [figure for figure in queue if isinstance(figure, dict)]
    for figure in bindable_figures:
        figure_id = str(figure.get("id") or "")
        normalized_id = _figure_artifact_key(figure_id) if figure_id else ""
        semantic_tokens = {
            token
            for field in ("id", "metric", "y_metric")
            if (token := str(figure.get(field) or "").strip())
        }
        candidate_keys = [
            key
            for key in artifact_groups
            if key == normalized_id
            or (normalized_id and (key.endswith(normalized_id) or normalized_id.endswith(key)))
            or any(token in key for token in semantic_tokens)
        ]
        matched_key = candidate_keys[0] if len(candidate_keys) == 1 else None
        if matched_key is None and len(bindable_figures) == 1 and len(artifact_groups) == 1:
            matched_key = next(iter(artifact_groups))
        artifacts = artifact_groups.get(matched_key, []) if matched_key is not None else []
        if matched_key is not None:
            bound_keys.add(matched_key)
        figure["status"] = "rendered" if artifacts else "planned"
        figure["artifacts"] = artifacts
    updated["figure_queue"] = queue
    unbound_artifacts = [
        artifact
        for key, group in artifact_groups.items()
        if key not in bound_keys
        for artifact in group
    ]
    updated["run"] = {
        "output": str(output_dir),
        "figure_artifacts": [artifact for group in grouped_artifacts for artifact in group],
        "unbound_figure_artifacts": unbound_artifacts,
        "artifact_binding_policy": "stable_figure_id_or_unbound",
        "analysis_metrics": analysis_metrics or [],
        "qa": qa or {},
    }
    return updated


def build_output_package_contract(output_dir: Path, *, manifest: dict[str, Any]) -> dict[str, Any]:
    figures = [Path(path) for path in manifest.get("figures", []) if isinstance(path, str)]
    required = [
        ("request_snapshot", output_dir / "request_snapshot.json"),
        ("manifest", output_dir / "manifest.json"),
        ("review_html", output_dir / "review.html"),
        ("revision_brief", output_dir / "revision_brief.md"),
    ]
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    analysis_metrics = result.get("analysis_metrics") if isinstance(result.get("analysis_metrics"), list) else []
    if analysis_metrics:
        required.append(("analysis_metrics", output_dir / "tables" / "analysis_metrics.csv"))
    raw_archive = manifest.get("raw_archive") if isinstance(manifest.get("raw_archive"), dict) else {}
    raw_path = raw_archive.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        required.append(("raw_archive", Path(raw_path)))
    publication_intent = (
        manifest.get("publication_intent")
        if isinstance(manifest.get("publication_intent"), dict)
        else {}
    )
    if publication_intent:
        required.extend(
            [
                ("publication_intent", output_dir / "publication_intent.json"),
                ("transform_ledger", output_dir / "transform_ledger.json"),
                ("journal_profile", output_dir / "journal_profile.json"),
                ("publication_qa", output_dir / "publication_qa.json"),
            ]
        )
    artifact_status = [
        {
            "id": artifact_id,
            "path": str(path),
            "exists": path.exists(),
        }
        for artifact_id, path in required
    ]
    has_pdf = any(path.suffix.lower() == ".pdf" and path.exists() for path in figures)
    has_tiff_300 = any(path.name.endswith("_300dpi.tiff") and path.exists() for path in figures)
    artifact_status.extend(
        [
            {"id": "pdf", "path": "", "exists": has_pdf},
            {"id": "tiff_300", "path": "", "exists": has_tiff_300},
            {
                "id": "qa",
                "path": "",
                "exists": bool(
                    isinstance(manifest.get("qa"), dict)
                    and manifest["qa"].get("status") == "passed"
                ),
            },
        ]
    )
    if publication_intent:
        transform_ledger = (
            manifest.get("transform_ledger")
            if isinstance(manifest.get("transform_ledger"), dict)
            else {}
        )
        artifact_status.append(
            {
                "id": "transform_lineage_reviewed",
                "path": str(output_dir / "transform_ledger.json"),
                "exists": transform_ledger.get("status") in {"runtime_recorded", "confirmed"},
            }
        )
        for filename, kind in {
            "publication_intent.json": "sciplot_publication_intent",
            "transform_ledger.json": "sciplot_transform_ledger",
            "journal_profile.json": "sciplot_publication_profile",
            "publication_qa.json": "sciplot_publication_qa",
        }.items():
            artifact_status.append(
                {
                    "id": f"{Path(filename).stem}_valid_contract",
                    "path": str(output_dir / filename),
                    "exists": _json_contract_matches(output_dir / filename, kind),
                }
            )
    if publication_intent.get("target_status") == "confirmed":
        publication_qa = (
            manifest.get("publication_qa")
            if isinstance(manifest.get("publication_qa"), dict)
            else {}
        )
        artifact_status.append(
            {
                "id": "publication_qa_passed",
                "path": str(output_dir / "publication_qa.json"),
                "exists": publication_qa.get("status") == "passed",
            }
        )
    return {
        "kind": "sciplot_output_package_contract",
        "version": 1,
        "complete": all(item["exists"] for item in artifact_status),
        "artifacts": artifact_status,
    }


__all__ = [
    "REPLICATE_MODES",
    "STUDY_MODEL_KIND",
    "STUDY_MODEL_VERSION",
    "attach_run_artifacts_to_study_model",
    "build_output_package_contract",
    "build_study_model",
    "experiment_recommendation_payload",
    "normalize_replicate_mode",
    "normalize_study_model",
    "study_model_from_request",
    "sync_study_model_samples",
]
