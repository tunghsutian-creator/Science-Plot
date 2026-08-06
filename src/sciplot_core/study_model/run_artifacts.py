"""Attach verified run artifacts to a study model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.policy import canonical_figure_stem

from sciplot_core.study_model.normalization import (
    normalize_study_model,
)


def _figure_artifact_key(path: str) -> str:
    return canonical_figure_stem(path)


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
    resolved_figure_plan: dict[str, Any] | None = None,
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
    figure_plan = resolved_figure_plan_from_payload(resolved_figure_plan)
    if figure_plan is not None:
        outcome_by_id = {outcome.figure_id: outcome for outcome in figure_plan.outcomes}
        plan_task_ids = set(figure_plan.selected_figure_ids)
        impact_expansion = figure_plan.rule_id == "impact_metric" and not any(
            isinstance(figure, dict) and str(figure.get("id") or "") in plan_task_ids
            for figure in queue
        )
        if figure_plan.rule_id == "rheology_frequency_sweep":
            queued_ids = {
                str(figure.get("id") or "")
                for figure in queue
                if isinstance(figure, dict)
            }
            queue.extend(
                {
                    "id": task.figure_id,
                    "order": task.order,
                    "status": "planned",
                    "title": task.title,
                    "metric": task.y_metric,
                    "x_metric": task.x_metric,
                    "y_metric": task.y_metric,
                    "default_template": task.template,
                    "resolved_from_figure_plan": True,
                }
                for task in figure_plan.tasks
                if task.figure_id not in queued_ids
            )
        for figure in queue:
            if not isinstance(figure, dict):
                continue
            figure_id = str(figure.get("id") or "")
            outcome = outcome_by_id.get(figure_id)
            if outcome is not None:
                figure["status"] = (
                    "rendered" if outcome.status == "ready" else "planned"
                )
                figure["artifacts"] = _artifact_records(outcome.artifacts)
            elif impact_expansion and figure_id == "impact_strength_by_sample":
                figure["status"] = "rendered" if figure_plan.complete else "planned"
                figure["resolved_figure_ids"] = list(figure_plan.selected_figure_ids)
                figure["artifacts"] = [
                    artifact
                    for outcome in figure_plan.outcomes
                    for artifact in _artifact_records(outcome.artifacts)
                ]
            else:
                figure["status"] = "planned"
                figure["artifacts"] = []
                figure.pop("resolved_figure_ids", None)
        updated["figure_queue"] = queue
        bound_paths = {
            str(Path(path).expanduser().resolve())
            for outcome in figure_plan.outcomes
            for path in outcome.artifacts
        }
        updated["run"] = {
            "output": str(output_dir),
            "figure_artifacts": [
                artifact for group in grouped_artifacts for artifact in group
            ],
            "unbound_figure_artifacts": [
                artifact
                for group in grouped_artifacts
                for artifact in group
                if str(Path(str(artifact["path"])).expanduser().resolve())
                not in bound_paths
            ],
            "artifact_binding_policy": "resolved_figure_plan",
            "resolved_figure_plan_id": figure_plan.plan_id,
            "resolved_figure_plan_sha256": figure_plan.plan_sha256,
            "figure_outcomes": [
                outcome.to_payload() for outcome in figure_plan.outcomes
            ],
            "analysis_metrics": analysis_metrics or [],
            "qa": qa or {},
        }
        return updated
    bound_keys: set[str] = set()
    bindable_figures = [figure for figure in queue if isinstance(figure, dict)]
    for figure in bindable_figures:
        figure_id = str(figure.get("id") or "")
        normalized_id = _figure_artifact_key(figure_id) if figure_id else ""
        semantic_tokens = {
            token.casefold()
            for field in ("id", "metric", "y_metric")
            if (token := str(figure.get(field) or "").strip())
        }
        candidate_keys = [
            key
            for key in artifact_groups
            if key == normalized_id
            or (
                normalized_id
                and (key.endswith(normalized_id) or normalized_id.endswith(key))
            )
            or any(token in key for token in semantic_tokens)
        ]
        matched_key = candidate_keys[0] if len(candidate_keys) == 1 else None
        if (
            matched_key is None
            and len(bindable_figures) == 1
            and len(artifact_groups) == 1
        ):
            matched_key = next(iter(artifact_groups))
        artifacts = (
            artifact_groups.get(matched_key, []) if matched_key is not None else []
        )
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
        "figure_artifacts": [
            artifact for group in grouped_artifacts for artifact in group
        ],
        "unbound_figure_artifacts": unbound_artifacts,
        "artifact_binding_policy": "stable_figure_id_or_unbound",
        "analysis_metrics": analysis_metrics or [],
        "qa": qa or {},
    }
    return updated


def _artifact_records(paths: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "name": Path(path).name,
            "format": Path(path).suffix.lower().lstrip("."),
        }
        for path in paths
    ]
