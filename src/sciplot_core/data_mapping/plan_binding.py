"""Bind a public creation plan to one verified confirmed mapping execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.contracts import _read_json
from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution
from sciplot_core.data_mapping.request_resolution import resolve_data_mapping_request
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.materials_rules import get_rule


def resolve_mapping_plan_request(
    source: Path, request: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recover scientific fields from the immutable receipt, never caller overrides."""

    source = source.expanduser().resolve()
    reference = request.get("data_mapping_execution")
    proposal_id = request.get("data_mapping_proposal_id")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("A mapping plan requires its confirmed execution path.")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise ValueError("A mapping plan requires its exact proposal identity.")
    execution = load_data_mapping_execution(reference)
    if execution.get("handoff_allowed") is not True:
        raise ValueError("A mapping plan requires a current path-bound confirmation.")
    if execution["proposal_id"] != proposal_id:
        raise ValueError("The mapping plan refers to another proposal.")
    seed = _read_json(Path(execution["request_seed"]))
    original = seed.get("input")
    if not isinstance(original, str) or Path(original).expanduser().resolve() != source:
        raise ValueError("The mapping request does not target the original task source.")
    outputs = execution.get("outputs") or []
    if not source.is_file() or len(outputs) != 1:
        raise ValueError("Mapped creation currently requires one source file and one output table.")
    output = outputs[0]
    recorded_source = (
        Path(execution["source_root"]) / output["source_relative_path"]
    ).resolve()
    if recorded_source != source or len(execution["source_hashes"]) != 1:
        raise ValueError("The confirmed mapping does not cover exactly the task source.")
    for key in ("rule_id", "template"):
        selected = seed.get(key)
        if not isinstance(selected, str) or not selected:
            raise ValueError(f"The confirmed mapping request is missing {key}.")
        if key in request and request[key] != selected:
            raise ValueError(f"The mapping plan cannot override confirmed {key}.")
    rule = get_rule(seed["rule_id"])
    if rule.scientific_source_adapter != "registered_paired_curve":
        raise ValueError("Mapped creation currently supports registered paired-curve rules only.")
    effective, application = resolve_data_mapping_request(
        seed, base_dir=Path(execution["request_seed"]).parent
    )
    if application is None:
        raise ValueError("The immutable mapping request lost its execution binding.")
    effective_input = Path(effective["input"]).expanduser().resolve()
    original_hash = source_tree_sha256(source)
    effective_hash = source_tree_sha256(effective_input)
    if original_hash is None or effective_hash is None:
        raise ValueError("A mapping plan source is unavailable.")
    binding = {
        "data_mapping_execution": str(Path(application["execution"]).resolve()),
        "data_mapping_proposal_id": proposal_id,
        "proposal_sha256": execution["proposal_sha256"],
        "confirmation_id": execution["confirmation_id"],
        "request_seed_sha256": execution["request_seed_sha256"],
        "original_input": str(source),
        "original_input_sha256": original_hash,
        "effective_input": str(effective_input),
        "effective_input_sha256": effective_hash,
        "expected_sample_labels": application["expected_sample_labels"],
    }
    return seed, binding


def verify_mapping_sample_identity(
    binding: dict[str, Any], scientific_transform: dict[str, Any] | None
) -> None:
    """File-safe output naming must never rename confirmed scientific samples."""

    output = scientific_transform.get("output") if scientific_transform else None
    actual = output.get("series_order") if isinstance(output, dict) else None
    if actual != binding["expected_sample_labels"]:
        raise ValueError(
            "Mapped scientific sample labels do not match the confirmed labels: "
            f"expected {binding['expected_sample_labels']!r}, found {actual!r}."
        )


__all__ = ["resolve_mapping_plan_request", "verify_mapping_sample_identity"]
