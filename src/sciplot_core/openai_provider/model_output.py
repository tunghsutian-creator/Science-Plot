"""Validate and coerce the typed model proposal envelope."""

from __future__ import annotations

import json
import math
from typing import Any
from sciplot_core.assistant_provider import (
    ASSISTANT_CONTEXT_VERSION,
)

from sciplot_core.openai_provider.contracts import (
    _MAX_STREAM_TEXT_BYTES,
    _MAX_MODEL_OPERATIONS,
    _MAX_MODEL_WARNINGS,
    _WINDOWS_ABSOLUTE_PATH,
)

from sciplot_core.openai_provider.errors import (
    _AssistantContextUnavailable,
)

from sciplot_core.openai_provider.validation import (
    _required_text,
    _free_text,
)


def _json_loads_strict(value: str) -> Any:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"Non-finite JSON constant is not allowed: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def _model_envelope(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > _MAX_STREAM_TEXT_BYTES:
        raise ValueError("Model output exceeds the SciPlot size bound.")
    try:
        value = _json_loads_strict(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Model output is not valid finite JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Model output must be a JSON object.")
    expected = {
        "status",
        "understanding",
        "proposal_kind",
        "rationale",
        "operations",
        "warnings",
    }
    if set(value) != expected:
        raise ValueError("Model output does not match the closed response schema.")
    status = value.get("status")
    if status not in {
        "proposal",
        "needs_human_confirmation",
        "needs_rule_repair",
    }:
        raise ValueError("Model output has an unsupported status.")
    understanding = _required_text(
        value.get("understanding"),
        "Model understanding",
        maximum=2000,
    )
    proposal_kind = value.get("proposal_kind")
    if proposal_kind not in {"veusz_setting_operation_batch", "none"}:
        raise ValueError("Model output has an unsupported proposal kind.")
    rationale = _free_text(
        value.get("rationale"),
        "Model rationale",
        maximum=2000,
    )
    raw_operations = value.get("operations")
    if not isinstance(raw_operations, list):
        raise ValueError("Model operations must be a list.")
    if len(raw_operations) > _MAX_MODEL_OPERATIONS:
        raise ValueError("Model output contains too many operations.")
    operations: list[dict[str, str]] = []
    operation_keys = {
        "operation_type",
        "target_id",
        "setting_path",
        "value_json",
    }
    for item in raw_operations:
        if not isinstance(item, dict) or set(item) != operation_keys:
            raise ValueError("Model operation does not match the closed schema.")
        operation_type = item.get("operation_type")
        if operation_type != "set_setting":
            raise ValueError("Model operation type is not supported.")
        operations.append(
            {
                "operation_type": "set_setting",
                "target_id": _required_text(
                    item.get("target_id"),
                    "Model target_id",
                    maximum=96,
                ),
                "setting_path": _required_text(
                    item.get("setting_path"),
                    "Model setting_path",
                    maximum=1024,
                ),
                "value_json": _required_text(
                    item.get("value_json"),
                    "Model value_json",
                    maximum=16_384,
                ),
            }
        )
    raw_warnings = value.get("warnings")
    if not isinstance(raw_warnings, list) or len(raw_warnings) > _MAX_MODEL_WARNINGS:
        raise ValueError("Model warnings must be a bounded list.")
    warnings = tuple(
        _required_text(item, "Model warning", maximum=500) for item in raw_warnings
    )
    if len(set(warnings)) != len(warnings):
        raise ValueError("Model warnings must be unique.")
    if status == "proposal":
        if proposal_kind != "veusz_setting_operation_batch" or not operations:
            raise ValueError(
                "A proposal requires one or more Veusz setting operations."
            )
        if not rationale:
            raise ValueError("A proposal requires a rationale.")
    elif proposal_kind != "none" or operations:
        raise ValueError("A non-proposal response cannot contain operations.")
    return {
        "status": status,
        "understanding": understanding,
        "proposal_kind": proposal_kind,
        "rationale": rationale,
        "operations": operations,
        "warnings": warnings,
    }


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number


def _check_range(value: float, capability: dict[str, Any]) -> None:
    minimum = capability.get("minimum")
    maximum = capability.get("maximum")
    if minimum is not None and value < float(minimum):
        raise ValueError(f"Proposed value is below the allowed minimum {minimum}.")
    if maximum is not None and value > float(maximum):
        raise ValueError(f"Proposed value is above the allowed maximum {maximum}.")


def _coerce_value(capability: dict[str, Any], value: Any) -> Any:
    editor = capability["editor"]
    if editor == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Proposed boolean setting must be true or false.")
        return value
    if editor == "choice":
        if not isinstance(value, str) or value not in capability["choices"]:
            raise ValueError("Proposed choice is outside the advertised choices.")
        return value
    if editor == "text":
        if not isinstance(value, str):
            raise ValueError("Proposed text setting must be text.")
        if len(value) > 16_384:
            raise ValueError("Proposed text setting is too long.")
        return value
    if editor in {"color", "distance"}:
        return _required_text(value, "Proposed setting", maximum=256)
    if editor == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Proposed integer setting must be an integer.")
        _check_range(float(value), capability)
        return value
    if editor == "number":
        number = _finite_number(value, label="Proposed number")
        _check_range(number, capability)
        return number
    if editor == "number_or_auto":
        if isinstance(value, str) and value.strip().casefold() == "auto":
            return "Auto"
        number = _finite_number(value, label="Proposed number")
        _check_range(number, capability)
        return number
    if editor == "scalar_list":
        values = value if isinstance(value, list) else [value]
        if len(values) != 1:
            raise ValueError("Proposed scalar-list setting requires one value.")
        number = _finite_number(values[0], label="Proposed scalar-list value")
        _check_range(number, capability)
        return [number]
    if editor == "float_list":
        if not isinstance(value, list) or not value or len(value) > 128:
            raise ValueError("Proposed numeric list must contain 1 to 128 values.")
        values = [
            _finite_number(item, label="Proposed numeric-list value") for item in value
        ]
        for number in values:
            _check_range(number, capability)
        return values
    raise ValueError(f"Unsupported advertised editor: {editor!r}")


def _provider_safe_context(context: dict[str, Any]) -> None:
    if context.get("version") != ASSISTANT_CONTEXT_VERSION:
        raise _AssistantContextUnavailable(
            "This request predates the bounded editing-capability catalog."
        )
    project_id = str(context.get("project_id") or "")
    if project_id.startswith("/") or _WINDOWS_ABSOLUTE_PATH.match(project_id):
        raise ValueError("Assistant project_id must not be an absolute path.")
    if context.get("raw_dataset_arrays_included") is not False:
        raise ValueError("Assistant context must not contain raw dataset arrays.")
    capabilities = context.get("editing_capabilities")
    if not isinstance(capabilities, dict):
        raise _AssistantContextUnavailable(
            "Assistant context has no editing-capability catalog."
        )
