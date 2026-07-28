"""Build transform steps and complete lineage ledgers."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.publication.profiles import (
    TRANSFORM_LEDGER_KIND,
    TRANSFORM_LEDGER_VERSION,
)

from sciplot_core.publication.artifacts import (
    artifact_record,
)


def build_transform_step(
    *,
    step_id: str,
    operation: str,
    input_path: str | Path,
    output_path: str | Path | None,
    implementation_ref: str,
    parameters: dict[str, Any] | None = None,
    additional_outputs: Iterable[str | Path] = (),
) -> dict[str, Any]:
    input_artifact = artifact_record(
        input_path, artifact_id=f"{step_id}_input", role="input"
    )
    output_artifacts: list[dict[str, Any]] = []
    if output_path is not None:
        output_artifacts.append(
            artifact_record(output_path, artifact_id=f"{step_id}_output", role="output")
        )
    for index, path in enumerate(additional_outputs, start=1):
        output_artifacts.append(
            artifact_record(
                path,
                artifact_id=f"{step_id}_output_{index + 1}",
                role="supporting_output",
            )
        )
    return {
        "id": step_id,
        "operation": operation,
        "implementation_ref": implementation_ref,
        "input_refs": [input_artifact["id"]],
        "output_refs": [artifact["id"] for artifact in output_artifacts],
        "input_artifacts": [input_artifact],
        "output_artifacts": output_artifacts,
        "parameters": deepcopy(parameters or {}),
        "input_shape": input_artifact.get("table_shape"),
        "output_shape": output_artifacts[0].get("table_shape")
        if output_artifacts
        else None,
        "confirmation_status": "runtime_recorded",
        "silent_omission_allowed": False,
        "outcome_strength_gate_applied": False,
    }


def build_transform_ledger(
    study_model: dict[str, Any],
    *,
    request: dict[str, Any] | None,
    input_path: str | Path,
    steps: Iterable[dict[str, Any]] = (),
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = request if isinstance(request, dict) else {}
    existing = deepcopy(existing) if isinstance(existing, dict) else {}
    recorded_steps = [deepcopy(step) for step in steps if isinstance(step, dict)]
    if not recorded_steps and isinstance(existing.get("steps"), list):
        recorded_steps = [
            deepcopy(step) for step in existing["steps"] if isinstance(step, dict)
        ]
    if not recorded_steps:
        recorded_steps = [
            build_transform_step(
                step_id="identity_source",
                operation="identity",
                input_path=input_path,
                output_path=input_path,
                implementation_ref="sciplot_core.workflow.run_request",
                parameters={
                    "reason": "No deterministic data transformation was applied before rendering."
                },
            )
        ]
    unresolved_step_ids = [
        str(step.get("id") or "")
        for step in recorded_steps
        if str(step.get("confirmation_status") or "runtime_recorded")
        not in {"runtime_recorded", "confirmed", "not_applicable"}
    ]
    first_step_inputs = (
        recorded_steps[0].get("input_artifacts")
        if isinstance(recorded_steps[0].get("input_artifacts"), list)
        else []
    )
    first_source_path = next(
        (
            str(artifact.get("path"))
            for artifact in first_step_inputs
            if isinstance(artifact, dict)
            and isinstance(artifact.get("path"), str)
            and str(artifact.get("path")).strip()
        ),
        str(Path(input_path).expanduser().resolve()),
    )
    payload = {
        "kind": TRANSFORM_LEDGER_KIND,
        "version": TRANSFORM_LEDGER_VERSION,
        "status": "needs_human_confirmation"
        if unresolved_step_ids
        else "runtime_recorded",
        "source_root": str(Path(first_source_path).expanduser().resolve()),
        "replicate_policy": deepcopy(study_model.get("replicate_policy") or {}),
        "column_confirmations": deepcopy(request.get("column_confirmations") or []),
        "steps": recorded_steps,
        "unresolved_step_ids": unresolved_step_ids,
        "policy": {
            "raw_sources_preserved": True,
            "silent_data_omission_allowed": False,
            "selection_must_be_recorded": True,
            "unit_conversion_must_be_recorded": True,
            "input_output_shape_preferred": True,
            "scientific_outcome_agnostic": True,
        },
    }
    for key, value in existing.items():
        if key not in payload:
            payload[key] = deepcopy(value)
    return payload


def link_intent_to_transform_ledger(
    publication_intent: dict[str, Any],
    transform_ledger: dict[str, Any],
) -> dict[str, Any]:
    linked = deepcopy(publication_intent)
    step_refs = [
        str(step.get("id"))
        for step in transform_ledger.get("steps", [])
        if isinstance(step, dict) and step.get("id")
    ]
    valid_refs = set(step_refs)
    for contract_key in ("panels", "figure_contracts"):
        contracts = (
            linked.get(contract_key)
            if isinstance(linked.get(contract_key), list)
            else []
        )
        structured = [contract for contract in contracts if isinstance(contract, dict)]
        for contract in structured:
            existing_refs = contract.get("transform_step_refs")
            if isinstance(existing_refs, list) and existing_refs:
                contract["transform_step_refs"] = [
                    str(ref) for ref in existing_refs if str(ref) in valid_refs
                ]
                contract["transform_binding_status"] = (
                    "explicit_validated"
                    if contract["transform_step_refs"]
                    else "pending_explicit_binding"
                )
            elif len(structured) == 1 and step_refs:
                contract["transform_step_refs"] = step_refs
                contract["transform_binding_status"] = "single_figure_shared_source"
            else:
                contract["transform_step_refs"] = []
                contract["transform_binding_status"] = "pending_explicit_binding"
    linked["transform_ledger_ref"] = "transform_ledger.json"
    return linked
