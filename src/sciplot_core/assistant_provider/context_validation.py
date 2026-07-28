"""Validate the complete bounded assistant context."""

from __future__ import annotations

import json
from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_object,
)
from sciplot_core.assistant_selection import VeuszSelection
from sciplot_core.assistant_operations import (
    _validate_json_value,
)

from sciplot_core.assistant_provider.contracts import (
    ASSISTANT_CONTEXT_KIND,
    ASSISTANT_CONTEXT_COMPATIBLE_VERSIONS,
    _MAX_CONTEXT_BYTES,
)

from sciplot_core.assistant_provider.text_validation import (
    _required_text,
    _uuid_text,
)

from sciplot_core.assistant_provider.context_documents import (
    _validate_document_inventory,
    _validate_review,
)

from sciplot_core.assistant_provider.context_qa import (
    _validate_qa,
)

from sciplot_core.assistant_provider.capabilities import (
    _validate_editing_capabilities,
)


def _validate_context(context: dict[str, Any]) -> dict[str, Any]:
    value = require_json_object(context, label="assistant request context")
    version = require_json_int(
        value.get("version", 0), label="assistant request context version"
    )
    if version not in ASSISTANT_CONTEXT_COMPATIBLE_VERSIONS:
        raise ValueError("Assistant request context has an unsupported version.")
    allowed_keys = {
        "kind",
        "version",
        "project_id",
        "document_id",
        "revision",
        "state",
        "page",
        "selection",
        "selected_object",
        "document_inventory",
        "review",
        "qa",
        "raw_dataset_arrays_included",
        "explicit_selected_point_included",
    }
    if version >= 3:
        allowed_keys.add("editing_capabilities")
    reject_unknown_keys(
        value,
        allowed_keys,
        label="assistant request context",
    )
    if value.get("kind") != ASSISTANT_CONTEXT_KIND:
        raise ValueError("Assistant request context has an unsupported kind.")
    project_id = _required_text(
        value.get("project_id"),
        "context project_id",
        maximum=256,
    )
    document_id = _uuid_text(value.get("document_id"), "context document_id")
    revision = require_json_int(value.get("revision"), label="context revision")
    if revision < 0:
        raise ValueError("context revision must be non-negative.")
    state = _required_text(value.get("state"), "context state", maximum=64)
    page = require_json_int(value.get("page"), label="context page")
    if page < 0:
        raise ValueError("context page must be non-negative.")
    selection = VeuszSelection.from_dict(
        require_json_object(value.get("selection"), label="context selection")
    ).to_dict()
    selected = value.get("selected_object")
    normalized_selected: dict[str, Any] | None = None
    if selected is not None:
        selected_payload = require_json_object(
            selected, label="context selected_object"
        )
        reject_unknown_keys(
            selected_payload,
            {"object_id", "object_type", "display_name"},
            label="context selected_object",
        )
        selected_id = _uuid_text(
            selected_payload.get("object_id"),
            "selected object_id",
        )
        if selected_id != selection.get("primary_object_id"):
            raise ValueError(
                "context selected_object must match selection.primary_object_id."
            )
        normalized_selected = {
            "object_id": selected_id,
            "object_type": _required_text(
                selected_payload.get("object_type"),
                "selected object_type",
                maximum=64,
            ),
            "display_name": _required_text(
                selected_payload.get("display_name"),
                "selected display_name",
                maximum=256,
            ),
        }
    elif selection.get("primary_object_id") is not None:
        raise ValueError("context selected_object is required for a primary selection.")
    if require_json_bool(
        value.get("raw_dataset_arrays_included"),
        label="context raw_dataset_arrays_included",
    ):
        raise ValueError(
            "Assistant request context must not contain raw dataset arrays."
        )
    selected_point_included = require_json_bool(
        value.get("explicit_selected_point_included"),
        label="context explicit_selected_point_included",
    )
    if selected_point_included != (selection.get("data_point") is not None):
        raise ValueError(
            "context explicit_selected_point_included must match selection.data_point."
        )
    normalized = {
        "kind": ASSISTANT_CONTEXT_KIND,
        "version": version,
        "project_id": project_id,
        "document_id": document_id,
        "revision": revision,
        "state": state,
        "page": page,
        "selection": selection,
        "selected_object": normalized_selected,
        "document_inventory": _validate_document_inventory(
            value.get("document_inventory")
        ),
        "review": _validate_review(value.get("review")),
        "qa": _validate_qa(value.get("qa")),
        "raw_dataset_arrays_included": False,
        "explicit_selected_point_included": selected_point_included,
    }
    if version >= 3:
        normalized["editing_capabilities"] = _validate_editing_capabilities(
            value.get("editing_capabilities"),
            selection=selection,
        )
    _validate_json_value(normalized, path="assistant request context")
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_CONTEXT_BYTES:
        raise ValueError(
            f"Assistant request context exceeds {_MAX_CONTEXT_BYTES} bytes."
        )
    return json.loads(encoded.decode("utf-8"))
