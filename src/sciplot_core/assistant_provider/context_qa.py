"""Validate bounded structured QA context."""

from __future__ import annotations

from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_object,
)

from sciplot_core.assistant_provider.contracts import (
    _MAX_QA_IDS,
)

from sciplot_core.assistant_provider.text_validation import (
    _required_text,
)

from sciplot_core.assistant_provider.context_documents import (
    _text_list,
)


def _validate_qa(payload: object) -> dict[str, Any]:
    value = require_json_object(payload, label="context qa")
    reject_unknown_keys(
        value,
        {
            "structural_status",
            "structural_failed_ids",
            "structural_warning_ids",
            "ready_for_artifact_qa",
            "artifact_status",
            "ready_to_use",
        },
        label="context qa",
    )
    failed = _text_list(
        value.get("structural_failed_ids"),
        label="context structural_failed_ids",
        maximum_item_length=96,
    )
    warnings = _text_list(
        value.get("structural_warning_ids"),
        label="context structural_warning_ids",
        maximum_item_length=96,
    )
    if len(failed) > _MAX_QA_IDS or len(warnings) > _MAX_QA_IDS:
        raise ValueError("context QA contains too many check IDs.")
    ready_to_use = value.get("ready_to_use")
    if ready_to_use is not None:
        ready_to_use = require_json_bool(
            ready_to_use,
            label="context ready_to_use",
        )
    return {
        "structural_status": _required_text(
            value.get("structural_status"),
            "context structural_status",
            maximum=64,
        ),
        "structural_failed_ids": list(failed),
        "structural_warning_ids": list(warnings),
        "ready_for_artifact_qa": require_json_bool(
            value.get("ready_for_artifact_qa"),
            label="context ready_for_artifact_qa",
        ),
        "artifact_status": _required_text(
            value.get("artifact_status"),
            "context artifact_status",
            maximum=64,
        ),
        "ready_to_use": ready_to_use,
    }
