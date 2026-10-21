"""Source-bound categorical questions inside the existing ordinary task journal."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from sciplot_core.categorical_plan import build_categorical_preview
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.mapping_contract.categorical import categorical_binding_schema
from sciplot_core.studio_render.categorical_bindings import categorical_table_facts
from sciplot_core.data_mapping.table_choice import source_table_snapshot
from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.task_categorical_contract import categorical_response_schema
from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_missing_values import require_missing_policy


def _question(state: dict[str, Any], *, binding: dict[str, Any], evidence: dict[str, Any],
              code: str, message: str, missing: bool = False) -> None:
    question: dict[str, Any] = {"field": "missing_values" if missing else "categorical",
        "reason_code": code, "message": message, "source_sha256": state["source_sha256"],
        "evidence": evidence, "categorical": binding,
        "selection": {"rule_id": None, "template": "point_line" if binding.get("mode") == "given_values" else "bar"}}
    question["question_id"] = canonical_json_sha256(question, allow_nan=False)
    question["response_template"] = {"expected_question_id": question["question_id"],
        **({"missing_values": "exclude"} if missing else {"categorical": binding})}
    if not missing:
        question["response_schema"] = categorical_response_schema()
    state.update(status="needs_input", phase="scientific_choice", question=question)
    state.pop("blocker", None)


def plan_categorical_task(state: dict[str, Any]) -> dict[str, Any] | None:
    """Preflight choices without reserving output or inventing an experiment."""
    source = Path(state["request"]["source"])
    if source_tree_sha256(source) != state["source_sha256"]:
        raise TaskControlError("source_changed", "The categorical source changed since this task began; its original choices cannot be replayed against new bytes.")
    binding = deepcopy(state.get("categorical_choice", state["request"]["categorical"]))
    binding.setdefault("source_identity_version", 1)
    binding["source_namespace"] = str(source.resolve())
    binding.setdefault("source_sha256", file_sha256(source))
    state["categorical_choice"] = binding
    try:
        facts = categorical_table_facts(source, binding)
    except ValueError as exc:
        _question(state, binding=binding, evidence=source_table_snapshot(source) or {},
            code=getattr(exc, "reason_code", "invalid_categorical_table_selection"), message=str(exc))
        return None
    if not Draft202012Validator(categorical_binding_schema(complete=True)).is_valid(binding):
        _question(state, binding=binding, evidence=facts, code="categorical_binding_required",
            message="Choose the original table_selection, sample/optional condition/value column indices and mode. Confirm each selected value quantity/unit with source-bound metadata evidence when absent. No raw arrays or derived tables are needed.")
        return None
    try:
        missing = state["request"].get("missing_values")
        if binding["mode"] != "given_values":
            from sciplot_core.categorical_disclosure import categorical_replicate_evidence

            evidence = categorical_replicate_evidence(source, binding)
            declaration = state.get("categorical_missing_declaration", {})
            if (declaration.get("binding_sha256") == canonical_json_sha256(binding, allow_nan=False)
                    and declaration.get("source_sha256") == state["source_sha256"]):
                state["missing_value_confirmation"] = {"missing_values": "exclude",
                    "source_sha256": state["source_sha256"], "question_id": declaration["question_id"],
                    "evidence_sha256": canonical_json_sha256(evidence, allow_nan=False)}
            missing = require_missing_policy(state, evidence)
            if missing is None:
                return None
        plan = build_categorical_preview(source, request={"categorical_binding": binding,
            **({"missing_values": missing} if missing is not None else {})})
    except (StudioPreparationBlocked, ValueError) as exc:
        _question(state, binding=binding, evidence=facts, code=getattr(exc, "reason_code", "categorical_binding_invalid"), message=str(exc),
                  missing=False)
        return None
    state.pop("question", None)
    state["categorical_plan"] = plan
    state["scientific_presentation"] = {"rule_id": None, "template": plan["template"],
        "curve_display": "raw_overlay" if binding["mode"] == "given_values" else "mean_sample_sd",
        "summary_statistic": "raw_only" if binding["mode"] == "given_values" else binding["mode"],
        "summary_calculation": "none" if binding["mode"] == "given_values" else "arithmetic_mean_sample_sd_ddof_1",
        "missing_values": missing or "none_present",
        "source_sha256": binding["source_sha256"], "table_selection": binding["table_selection"]}
    return dict(plan)


def accept_categorical_response(state: dict[str, Any], response: dict[str, Any]) -> None:
    question = state.get("question", {})
    if question.get("field") not in {"categorical", "missing_values"} or state.get("status") != "needs_input":
        raise TaskControlError("invalid_task_response", "This categorical task has no current source-choice question.")
    if response.get("expected_question_id") != question.get("question_id"):
        raise TaskControlError("stale_task_question", "Use this task's current categorical question ID.")
    if source_tree_sha256(Path(state["request"]["source"])) != state["source_sha256"]:
        raise TaskControlError("source_changed", "The original source changed while its categorical choices were pending.")
    if question["field"] == "missing_values" and set(response) == {"expected_question_id", "missing_values"}:
        if response["missing_values"] != "exclude":
            raise TaskControlError("invalid_task_response", "Explicitly choose missing_values='exclude'; no missing observation is zero-filled.")
    elif Draft202012Validator(categorical_response_schema()).is_valid(response):
        state["categorical_choice"] = deepcopy(response["categorical"])
    else:
        raise TaskControlError("invalid_task_response", "Reply with categorical choices and the current expected_question_id, or answer the current missing_values question.")
    if "missing_values" in response:
        state["categorical_missing_declaration"] = {"missing_values": "exclude",
            "binding_sha256": canonical_json_sha256(state["categorical_choice"], allow_nan=False),
            "source_sha256": state["source_sha256"], "question_id": question["question_id"]}
    state["categorical_answers"] = [*state.get("categorical_answers", []),
        {"question_id": question["question_id"], "source_sha256": state["source_sha256"], "response": deepcopy(response)}]
