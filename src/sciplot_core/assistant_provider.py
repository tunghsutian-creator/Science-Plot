from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from PIL import Image

from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_number,
    require_json_object,
)
from sciplot_core.mapping_contract import DataMappingProposal
from sciplot_core.assistant_selection import VeuszSelection
from sciplot_core.assistant_operations import (
    VeuszSettingOperationBatch,
    _validate_json_value,
)

ASSISTANT_PROVIDER_DESCRIPTOR_KIND = "sciplot_assistant_provider_descriptor"
ASSISTANT_PROVIDER_DESCRIPTOR_VERSION = 1
ASSISTANT_REQUEST_KIND = "sciplot_assistant_request"
ASSISTANT_REQUEST_VERSION = 1
ASSISTANT_PROGRESS_KIND = "sciplot_assistant_progress"
ASSISTANT_PROGRESS_VERSION = 1
ASSISTANT_RESPONSE_KIND = "sciplot_assistant_response"
ASSISTANT_RESPONSE_VERSION = 1
ASSISTANT_REQUEST_RECORD_KIND = "sciplot_assistant_request_record"
ASSISTANT_REQUEST_RECORD_VERSION = 2
ASSISTANT_REQUEST_RECORD_COMPATIBLE_VERSIONS = {
    1,
    ASSISTANT_REQUEST_RECORD_VERSION,
}
ASSISTANT_DATA_MAPPING_STATE_KIND = "sciplot_assistant_data_mapping_state"
ASSISTANT_DATA_MAPPING_STATE_VERSION = 2

ASSISTANT_PROPOSAL_KINDS = frozenset(
    {"veusz_setting_operation_batch", "data_mapping_proposal"}
)
ASSISTANT_PROVIDER_CAPABILITIES = frozenset({*ASSISTANT_PROPOSAL_KINDS, "cancellation"})
ASSISTANT_PROGRESS_STAGES = frozenset(
    {
        "queued",
        "understanding",
        "planning",
        "proposing",
        "validating",
        "waiting",
    }
)
ASSISTANT_RESPONSE_STATUSES = frozenset(
    {
        "proposal",
        "needs_human_confirmation",
        "needs_rule_repair",
        "cancelled",
    }
)
ASSISTANT_REQUEST_RECORD_STATUSES = frozenset(
    {
        "queued",
        "running",
        "cancel_requested",
        "proposal_ready",
        "needs_human_confirmation",
        "needs_rule_repair",
        "cancelled",
        "failed",
        "interrupted",
        "applied",
        "rejected",
    }
)
ASSISTANT_REQUEST_TERMINAL_STATUSES = frozenset(
    {
        "cancelled",
        "failed",
        "interrupted",
        "applied",
        "rejected",
    }
)
ASSISTANT_CONTEXT_KIND = "sciplot_veusz_assistant_context"
ASSISTANT_CONTEXT_VERSION = 3
ASSISTANT_CONTEXT_COMPATIBLE_VERSIONS = frozenset({2, ASSISTANT_CONTEXT_VERSION})
ASSISTANT_DATA_POLICY = "structured_context_no_raw_dataset_arrays"
ASSISTANT_VISUAL_PREVIEW_MAX_BYTES = 4 * 1024 * 1024

ASSISTANT_EDITABLE_FIELD_EDITORS = frozenset(
    {
        "boolean",
        "choice",
        "color",
        "distance",
        "float_list",
        "integer",
        "number",
        "number_or_auto",
        "scalar_list",
        "text",
    }
)

_SAFE_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
ASSISTANT_MAX_INTENT_LENGTH = 4000
_MAX_UNDERSTANDING_LENGTH = 2000
_MAX_PROGRESS_MESSAGE_LENGTH = 320
_MAX_WARNING_LENGTH = 500
_MAX_CONTEXT_BYTES = 256_000
_MAX_EVENTS = 128
_MAX_CONTEXT_OBJECTS = 100_000
_MAX_CONTEXT_OBJECT_TYPES = 128
_MAX_REVIEW_ANNOTATIONS = 128
_MAX_QA_IDS = 256
_MAX_EDITING_CAPABILITIES = 128
_MAX_CAPABILITY_CHOICES = 256
_MAX_CAPABILITY_VALUE_ITEMS = 128
_MAX_CAPABILITY_VALUE_BYTES = 16_384
_MAX_VISUAL_PREVIEW_BASE64_LENGTH = (
    (ASSISTANT_VISUAL_PREVIEW_MAX_BYTES + 2) // 3
) * 4

ASSISTANT_DATA_MAPPING_STATES = frozenset(
    {
        "proposed",
        "source_required",
        "previewing",
        "preview_ready",
        "confirmed",
        "executing",
        "executed",
        "rejected",
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(
    value: object,
    label: str,
    *,
    maximum: int | None = None,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    if maximum is not None and len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _optional_text(
    value: object,
    label: str,
    *,
    maximum: int | None = None,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, label, maximum=maximum)


def _free_text(
    value: object,
    label: str,
    *,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _uuid_text(value: object, label: str) -> str:
    text = _required_text(value, label)
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID.") from exc
    if str(parsed) != text.casefold():
        raise ValueError(f"{label} must use canonical UUID text.")
    return str(parsed)


def _provider_id(value: object, label: str = "provider_id") -> str:
    text = _required_text(value, label)
    if _SAFE_PROVIDER_ID.fullmatch(text) is None:
        raise ValueError(
            f"{label} must use 1-96 ASCII letters, digits, dot, underscore, or dash."
        )
    return text


def _timestamp(value: object, label: str) -> str:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset.")
    return text


def _sha256(value: object, label: str) -> str:
    digest = _required_text(value, label).casefold()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Assistant visual_preview must contain a PNG image.")
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format != "PNG":
                raise ValueError("Assistant visual_preview must contain a PNG image.")
            width, height = image.size
            image.verify()
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(
            "Assistant visual_preview must contain a structurally valid PNG image."
        ) from exc
    return int(width), int(height)


def _validate_visual_preview(
    value: object,
    *,
    base_revision: int,
) -> dict[str, Any] | None:
    if value is None:
        return None
    preview = require_json_object(value, label="Assistant visual_preview")
    fields = {"base64", "sha256", "width", "height", "revision"}
    reject_unknown_keys(preview, fields, label="Assistant visual_preview")
    missing = sorted(fields.difference(preview))
    if missing:
        raise ValueError(
            f"Assistant visual_preview is missing required fields: {missing!r}"
        )
    encoded = preview["base64"]
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("Assistant visual_preview base64 must be a non-empty string.")
    if len(encoded) > _MAX_VISUAL_PREVIEW_BASE64_LENGTH:
        raise ValueError("Assistant visual_preview must decode to at most 4 MiB.")
    try:
        encoded_bytes = encoded.encode("ascii")
        image = base64.b64decode(encoded_bytes, validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise ValueError(
            "Assistant visual_preview base64 must be canonical standard base64."
        ) from exc
    if base64.b64encode(image).decode("ascii") != encoded:
        raise ValueError(
            "Assistant visual_preview base64 must be canonical standard base64."
        )
    if not image or len(image) > ASSISTANT_VISUAL_PREVIEW_MAX_BYTES:
        raise ValueError(
            "Assistant visual_preview must decode to 1 byte through 4 MiB."
        )
    png_width, png_height = _png_dimensions(image)
    supplied_sha = _sha256(preview["sha256"], "visual_preview sha256")
    expected_sha = hashlib.sha256(image).hexdigest()
    if supplied_sha != expected_sha:
        raise ValueError(
            "Assistant visual_preview sha256 does not match the PNG bytes."
        )
    width = require_json_int(preview["width"], label="visual_preview width")
    height = require_json_int(preview["height"], label="visual_preview height")
    if width != png_width or height != png_height:
        raise ValueError(
            "Assistant visual_preview dimensions do not match the PNG IHDR."
        )
    revision = require_json_int(
        preview["revision"],
        label="visual_preview revision",
    )
    if revision < 0:
        raise ValueError("Assistant visual_preview revision must be non-negative.")
    if revision != base_revision:
        raise ValueError(
            "Assistant visual_preview revision must match base_revision."
        )
    return {
        "base64": encoded,
        "sha256": expected_sha,
        "width": width,
        "height": height,
        "revision": revision,
    }


def _text_list(
    value: object,
    *,
    label: str,
    allowed: frozenset[str] | None = None,
    maximum_item_length: int | None = None,
) -> tuple[str, ...]:
    items = require_json_list(value, label=label)
    result = tuple(
        _required_text(
            item,
            f"{label} item",
            maximum=maximum_item_length,
        )
        for item in items
    )
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain unique values.")
    if allowed is not None:
        unsupported = sorted(set(result) - set(allowed))
        if unsupported:
            raise ValueError(f"{label} contains unsupported values: {unsupported!r}")
    return result


def _validate_document_inventory(payload: object) -> dict[str, Any]:
    value = require_json_object(payload, label="context document_inventory")
    reject_unknown_keys(
        value,
        {"object_count", "object_types"},
        label="context document_inventory",
    )
    object_count = require_json_int(
        value.get("object_count"),
        label="context document_inventory object_count",
    )
    if not 0 <= object_count <= _MAX_CONTEXT_OBJECTS:
        raise ValueError(
            "context document_inventory object_count is outside the supported bound."
        )
    raw_types = require_json_object(
        value.get("object_types"),
        label="context document_inventory object_types",
    )
    if len(raw_types) > _MAX_CONTEXT_OBJECT_TYPES:
        raise ValueError("context document_inventory contains too many object types.")
    object_types: dict[str, int] = {}
    for key, item in raw_types.items():
        object_type = _required_text(
            key,
            "context document_inventory object type",
            maximum=64,
        )
        count = require_json_int(
            item,
            label=f"context document_inventory count for {object_type!r}",
        )
        if count < 0:
            raise ValueError("context document_inventory counts must be non-negative.")
        object_types[object_type] = count
    if sum(object_types.values()) != object_count:
        raise ValueError("context document_inventory counts must sum to object_count.")
    return {
        "object_count": object_count,
        "object_types": dict(sorted(object_types.items())),
    }


def _validate_review(payload: object) -> dict[str, Any]:
    value = require_json_object(payload, label="context review")
    reject_unknown_keys(
        value,
        {"active_count", "annotations"},
        label="context review",
    )
    active_count = require_json_int(
        value.get("active_count"),
        label="context review active_count",
    )
    annotations = require_json_list(
        value.get("annotations"),
        label="context review annotations",
    )
    if active_count != len(annotations):
        raise ValueError("context review active_count must match annotations.")
    if len(annotations) > _MAX_REVIEW_ANNOTATIONS:
        raise ValueError("context review contains too many annotations.")
    normalized: list[dict[str, Any]] = []
    annotation_ids: set[str] = set()
    for index, item in enumerate(annotations):
        annotation = require_json_object(
            item,
            label=f"context review annotations[{index}]",
        )
        reject_unknown_keys(
            annotation,
            {
                "annotation_id",
                "shape",
                "coordinate_space",
                "target_object_id",
                "text",
            },
            label=f"context review annotations[{index}]",
        )
        annotation_id = _required_text(
            annotation.get("annotation_id"),
            "context review annotation_id",
            maximum=96,
        )
        if annotation_id in annotation_ids:
            raise ValueError("context review annotation IDs must be unique.")
        annotation_ids.add(annotation_id)
        target = _optional_text(
            annotation.get("target_object_id"),
            "context review target_object_id",
            maximum=96,
        )
        normalized.append(
            {
                "annotation_id": annotation_id,
                "shape": _required_text(
                    annotation.get("shape"),
                    "context review shape",
                    maximum=32,
                ),
                "coordinate_space": _required_text(
                    annotation.get("coordinate_space"),
                    "context review coordinate_space",
                    maximum=32,
                ),
                "target_object_id": target,
                "text": _free_text(
                    annotation.get("text", ""),
                    "context review text",
                    maximum=2000,
                ),
            }
        )
    return {"active_count": active_count, "annotations": normalized}


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


def _validate_capability_value(value: object, *, label: str) -> Any:
    """Accept only bounded Inspector scalars or flat scalar lists."""

    if isinstance(value, dict):
        raise ValueError(f"{label} must not be an object.")
    if isinstance(value, list):
        if len(value) > _MAX_CAPABILITY_VALUE_ITEMS:
            raise ValueError(f"{label} contains too many values.")
        if any(isinstance(item, (dict, list)) for item in value):
            raise ValueError(f"{label} must be a flat scalar list.")
    _validate_json_value(value, path=label)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_CAPABILITY_VALUE_BYTES:
        raise ValueError(f"{label} is too large for Assistant context.")
    return json.loads(encoded.decode("utf-8"))


def _optional_capability_number(value: object, *, label: str) -> float | int | None:
    if value is None:
        return None
    return require_json_number(value, label=label)


def _validate_editing_capabilities(
    payload: object,
    *,
    selection: dict[str, Any],
) -> dict[str, Any]:
    value = require_json_object(payload, label="context editing_capabilities")
    reject_unknown_keys(
        value,
        {"scope", "target_object_id", "allowed_operations"},
        label="context editing_capabilities",
    )
    scope = _required_text(
        value.get("scope"),
        "context editing_capabilities scope",
        maximum=64,
    )
    if scope != "selected_object":
        raise ValueError(
            "context editing_capabilities scope must be 'selected_object'."
        )
    target_id = _optional_text(
        value.get("target_object_id"),
        "context editing_capabilities target_object_id",
        maximum=96,
    )
    if target_id is not None:
        target_id = _uuid_text(
            target_id,
            "context editing_capabilities target_object_id",
        )
    primary_id = selection.get("primary_object_id")
    if target_id != primary_id:
        raise ValueError(
            "context editing_capabilities target must match the primary selection."
        )

    raw_operations = require_json_list(
        value.get("allowed_operations"),
        label="context editing_capabilities allowed_operations",
    )
    if len(raw_operations) > _MAX_EDITING_CAPABILITIES:
        raise ValueError("context editing_capabilities contains too many operations.")
    if target_id is None and raw_operations:
        raise ValueError(
            "context editing_capabilities cannot expose operations without a target."
        )

    normalized: list[dict[str, Any]] = []
    field_ids: set[str] = set()
    setting_paths: set[str] = set()
    for index, item in enumerate(raw_operations):
        operation = require_json_object(
            item,
            label=f"context editing_capabilities allowed_operations[{index}]",
        )
        reject_unknown_keys(
            operation,
            {
                "operation_type",
                "target_id",
                "field_id",
                "section",
                "label",
                "setting_path",
                "editor",
                "current_value",
                "choices",
                "minimum",
                "maximum",
                "help_text",
            },
            label=f"context editing_capabilities allowed_operations[{index}]",
        )
        if operation.get("operation_type") != "set_setting":
            raise ValueError(
                "Assistant editing capabilities currently allow only set_setting."
            )
        operation_target = _uuid_text(
            operation.get("target_id"),
            "context editing capability target_id",
        )
        if operation_target != target_id:
            raise ValueError(
                "Assistant editing capability target must match the selected object."
            )
        field_id = _required_text(
            operation.get("field_id"),
            "context editing capability field_id",
            maximum=96,
        )
        if field_id in field_ids:
            raise ValueError("Assistant editing capability field IDs must be unique.")
        field_ids.add(field_id)
        setting_path = _required_text(
            operation.get("setting_path"),
            "context editing capability setting_path",
            maximum=1024,
        )
        if not setting_path.startswith("/"):
            raise ValueError(
                "Assistant editing capability setting_path must be absolute."
            )
        if setting_path in setting_paths:
            raise ValueError(
                "Assistant editing capability setting paths must be unique."
            )
        setting_paths.add(setting_path)
        editor = _required_text(
            operation.get("editor"),
            "context editing capability editor",
            maximum=32,
        )
        if editor not in ASSISTANT_EDITABLE_FIELD_EDITORS:
            raise ValueError(
                f"Unsupported Assistant editing capability editor: {editor!r}"
            )
        choices = _text_list(
            operation.get("choices"),
            label="context editing capability choices",
            maximum_item_length=256,
        )
        if len(choices) > _MAX_CAPABILITY_CHOICES:
            raise ValueError("Assistant editing capability contains too many choices.")
        if editor == "choice" and not choices:
            raise ValueError("Choice editing capabilities require bounded choices.")
        minimum = _optional_capability_number(
            operation.get("minimum"),
            label="context editing capability minimum",
        )
        maximum = _optional_capability_number(
            operation.get("maximum"),
            label="context editing capability maximum",
        )
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(
                "Assistant editing capability minimum cannot exceed maximum."
            )
        normalized.append(
            {
                "operation_type": "set_setting",
                "target_id": operation_target,
                "field_id": field_id,
                "section": _required_text(
                    operation.get("section"),
                    "context editing capability section",
                    maximum=128,
                ),
                "label": _required_text(
                    operation.get("label"),
                    "context editing capability label",
                    maximum=256,
                ),
                "setting_path": setting_path,
                "editor": editor,
                "current_value": _validate_capability_value(
                    operation.get("current_value"),
                    label="context editing capability current_value",
                ),
                "choices": list(choices),
                "minimum": minimum,
                "maximum": maximum,
                "help_text": _free_text(
                    operation.get("help_text", ""),
                    "context editing capability help_text",
                    maximum=1000,
                ),
            }
        )
    return {
        "scope": scope,
        "target_object_id": target_id,
        "allowed_operations": normalized,
    }


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


@dataclass(frozen=True)
class AssistantProviderDescriptor:
    provider_id: str
    display_name: str
    capabilities: tuple[str, ...]
    model_label: str | None = None
    data_policy: str = ASSISTANT_DATA_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(
            self,
            "display_name",
            _required_text(self.display_name, "display_name", maximum=120),
        )
        capabilities = tuple(self.capabilities)
        if not capabilities:
            raise ValueError("Assistant provider must declare at least one capability.")
        _text_list(
            list(capabilities),
            label="provider capabilities",
            allowed=ASSISTANT_PROVIDER_CAPABILITIES,
        )
        if not set(capabilities) & set(ASSISTANT_PROPOSAL_KINDS):
            raise ValueError(
                "Assistant provider must support at least one typed proposal kind."
            )
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(
            self,
            "model_label",
            _optional_text(self.model_label, "model_label", maximum=120),
        )
        if self.data_policy != ASSISTANT_DATA_POLICY:
            raise ValueError("Assistant provider has an unsupported data policy.")

    @property
    def supports_cancellation(self) -> bool:
        return "cancellation" in self.capabilities

    @property
    def proposal_kinds(self) -> tuple[str, ...]:
        return tuple(
            item for item in self.capabilities if item in ASSISTANT_PROPOSAL_KINDS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_PROVIDER_DESCRIPTOR_KIND,
            "version": ASSISTANT_PROVIDER_DESCRIPTOR_VERSION,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "model_label": self.model_label,
            "capabilities": list(self.capabilities),
            "data_policy": self.data_policy,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantProviderDescriptor:
        value = require_json_object(payload, label="AssistantProviderDescriptor")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "provider_id",
                "display_name",
                "model_label",
                "capabilities",
                "data_policy",
            },
            label="AssistantProviderDescriptor",
        )
        if value.get("kind") != ASSISTANT_PROVIDER_DESCRIPTOR_KIND:
            raise ValueError("Not a SciPlot AssistantProviderDescriptor payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_PROVIDER_DESCRIPTOR_VERSION
        ):
            raise ValueError("Unsupported AssistantProviderDescriptor version.")
        return cls(
            provider_id=_provider_id(value.get("provider_id")),
            display_name=_required_text(
                value.get("display_name"), "display_name", maximum=120
            ),
            model_label=_optional_text(
                value.get("model_label"), "model_label", maximum=120
            ),
            capabilities=_text_list(
                value.get("capabilities"),
                label="provider capabilities",
                allowed=ASSISTANT_PROVIDER_CAPABILITIES,
            ),
            data_policy=_required_text(value.get("data_policy"), "data_policy"),
        )


@dataclass(frozen=True)
class AssistantRequest:
    transaction_id: str
    provider_id: str
    intent: str
    base_revision: int
    context: dict[str, Any]
    allowed_proposal_kinds: tuple[str, ...]
    request_id: str = field(default_factory=lambda: str(uuid4()))
    context_sha256: str | None = None
    created_at: str = field(default_factory=_now)
    visual_preview: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _uuid_text(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "transaction_id",
            _uuid_text(self.transaction_id, "transaction_id"),
        )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(
            self,
            "intent",
            _required_text(
                self.intent,
                "assistant intent",
                maximum=ASSISTANT_MAX_INTENT_LENGTH,
            ),
        )
        if isinstance(self.base_revision, bool) or not isinstance(
            self.base_revision, int
        ):
            raise ValueError("Assistant request base_revision must be an integer.")
        if self.base_revision < 0:
            raise ValueError("Assistant request base_revision must be non-negative.")
        context = _validate_context(self.context)
        object.__setattr__(self, "context", context)
        allowed = _text_list(
            list(self.allowed_proposal_kinds),
            label="allowed_proposal_kinds",
            allowed=ASSISTANT_PROPOSAL_KINDS,
        )
        if not allowed:
            raise ValueError("Assistant request must allow a typed proposal kind.")
        object.__setattr__(self, "allowed_proposal_kinds", allowed)
        expected_sha = canonical_payload_sha256(context)
        if self.context_sha256 is not None:
            supplied = _sha256(self.context_sha256, "context_sha256")
            if supplied != expected_sha:
                raise ValueError(
                    "Assistant request context_sha256 does not match context."
                )
        object.__setattr__(self, "context_sha256", expected_sha)
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "request created_at")
        )
        if context["revision"] != self.base_revision:
            raise ValueError(
                "Assistant request context revision must match base_revision."
            )
        object.__setattr__(
            self,
            "visual_preview",
            _validate_visual_preview(
                self.visual_preview,
                base_revision=self.base_revision,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": ASSISTANT_REQUEST_KIND,
            "version": ASSISTANT_REQUEST_VERSION,
            "request_id": self.request_id,
            "transaction_id": self.transaction_id,
            "provider_id": self.provider_id,
            "intent": self.intent,
            "base_revision": self.base_revision,
            "context": copy.deepcopy(self.context),
            "context_sha256": self.context_sha256,
            "allowed_proposal_kinds": list(self.allowed_proposal_kinds),
            "created_at": self.created_at,
        }
        if self.visual_preview is not None:
            payload["visual_preview"] = copy.deepcopy(self.visual_preview)
        return payload

    @property
    def payload_sha256(self) -> str:
        return canonical_payload_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantRequest:
        value = require_json_object(payload, label="AssistantRequest")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "request_id",
                "transaction_id",
                "provider_id",
                "intent",
                "base_revision",
                "context",
                "context_sha256",
                "allowed_proposal_kinds",
                "created_at",
                "visual_preview",
            },
            label="AssistantRequest",
        )
        if value.get("kind") != ASSISTANT_REQUEST_KIND:
            raise ValueError("Not a SciPlot AssistantRequest payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_REQUEST_VERSION
        ):
            raise ValueError("Unsupported AssistantRequest version.")
        return cls(
            request_id=_uuid_text(value.get("request_id"), "request_id"),
            transaction_id=_uuid_text(value.get("transaction_id"), "transaction_id"),
            provider_id=_provider_id(value.get("provider_id")),
            intent=_required_text(
                value.get("intent"),
                "assistant intent",
                maximum=ASSISTANT_MAX_INTENT_LENGTH,
            ),
            base_revision=require_json_int(
                value.get("base_revision"), label="base_revision"
            ),
            context=dict(require_json_object(value.get("context"), label="context")),
            context_sha256=_sha256(value.get("context_sha256"), "context_sha256"),
            allowed_proposal_kinds=_text_list(
                value.get("allowed_proposal_kinds"),
                label="allowed_proposal_kinds",
                allowed=ASSISTANT_PROPOSAL_KINDS,
            ),
            created_at=_timestamp(value.get("created_at"), "request created_at"),
            visual_preview=(
                dict(
                    require_json_object(
                        value["visual_preview"],
                        label="visual_preview",
                    )
                )
                if "visual_preview" in value
                else None
            ),
        )


@dataclass(frozen=True)
class AssistantProgressEvent:
    request_id: str
    provider_id: str
    sequence: int
    stage: str
    message: str
    cancellable: bool
    progress: float | None = None
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _uuid_text(self.request_id, "request_id")
        )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("Assistant progress sequence must be an integer.")
        if self.sequence < 1:
            raise ValueError("Assistant progress sequence must be positive.")
        if self.stage not in ASSISTANT_PROGRESS_STAGES:
            raise ValueError(f"Unsupported Assistant progress stage: {self.stage!r}")
        object.__setattr__(
            self,
            "message",
            _required_text(
                self.message,
                "progress message",
                maximum=_MAX_PROGRESS_MESSAGE_LENGTH,
            ),
        )
        if type(self.cancellable) is not bool:
            raise ValueError("Assistant progress cancellable must be a boolean.")
        if self.progress is not None:
            progress = require_json_number(self.progress, label="progress")
            if not 0.0 <= progress <= 1.0:
                raise ValueError("Assistant progress must be between zero and one.")
            object.__setattr__(self, "progress", progress)
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "progress created_at")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_PROGRESS_KIND,
            "version": ASSISTANT_PROGRESS_VERSION,
            "request_id": self.request_id,
            "provider_id": self.provider_id,
            "sequence": self.sequence,
            "stage": self.stage,
            "message": self.message,
            "cancellable": self.cancellable,
            "progress": self.progress,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantProgressEvent:
        value = require_json_object(payload, label="AssistantProgressEvent")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "request_id",
                "provider_id",
                "sequence",
                "stage",
                "message",
                "cancellable",
                "progress",
                "created_at",
            },
            label="AssistantProgressEvent",
        )
        if value.get("kind") != ASSISTANT_PROGRESS_KIND:
            raise ValueError("Not a SciPlot AssistantProgressEvent payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_PROGRESS_VERSION
        ):
            raise ValueError("Unsupported AssistantProgressEvent version.")
        return cls(
            request_id=_uuid_text(value.get("request_id"), "request_id"),
            provider_id=_provider_id(value.get("provider_id")),
            sequence=require_json_int(value.get("sequence"), label="sequence"),
            stage=_required_text(value.get("stage"), "stage"),
            message=_required_text(
                value.get("message"),
                "progress message",
                maximum=_MAX_PROGRESS_MESSAGE_LENGTH,
            ),
            cancellable=require_json_bool(
                value.get("cancellable"), label="cancellable"
            ),
            progress=(
                require_json_number(value["progress"], label="progress")
                if value.get("progress") is not None
                else None
            ),
            created_at=_timestamp(value.get("created_at"), "progress created_at"),
        )


@dataclass(frozen=True)
class AssistantResponse:
    request_id: str
    transaction_id: str
    provider_id: str
    request_sha256: str
    status: str
    understanding: str
    proposal_kind: str | None = None
    proposal: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    response_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "response_id", _uuid_text(self.response_id, "response_id")
        )
        object.__setattr__(
            self, "request_id", _uuid_text(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "transaction_id",
            _uuid_text(self.transaction_id, "transaction_id"),
        )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(
            self,
            "request_sha256",
            _sha256(self.request_sha256, "request_sha256"),
        )
        if self.status not in ASSISTANT_RESPONSE_STATUSES:
            raise ValueError(f"Unsupported Assistant response status: {self.status!r}")
        object.__setattr__(
            self,
            "understanding",
            _required_text(
                self.understanding,
                "assistant understanding",
                maximum=_MAX_UNDERSTANDING_LENGTH,
            ),
        )
        warnings = _text_list(
            list(self.warnings),
            label="assistant warnings",
            maximum_item_length=_MAX_WARNING_LENGTH,
        )
        object.__setattr__(self, "warnings", warnings)
        if self.status == "proposal":
            if self.proposal_kind not in ASSISTANT_PROPOSAL_KINDS:
                raise ValueError(
                    "Proposal response requires a supported proposal_kind."
                )
            if not isinstance(self.proposal, dict):
                raise ValueError("Proposal response requires a proposal object.")
            if self.proposal_kind == "veusz_setting_operation_batch":
                parsed = VeuszSettingOperationBatch.from_dict(self.proposal)
            else:
                parsed = DataMappingProposal.from_dict(self.proposal)
            if parsed.provider != self.provider_id:
                raise ValueError(
                    "Assistant response proposal provider must match provider_id."
                )
            object.__setattr__(self, "proposal", parsed.to_dict())
        elif self.proposal_kind is not None or self.proposal is not None:
            raise ValueError(
                "Non-proposal Assistant responses must not contain a proposal."
            )
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "response created_at")
        )

    def validate_for_request(self, request: AssistantRequest) -> None:
        if self.request_id != request.request_id:
            raise ValueError("Assistant response request_id does not match request.")
        if self.transaction_id != request.transaction_id:
            raise ValueError(
                "Assistant response transaction_id does not match request."
            )
        if self.provider_id != request.provider_id:
            raise ValueError("Assistant response provider_id does not match request.")
        if self.request_sha256 != request.payload_sha256:
            raise ValueError(
                "Assistant response request_sha256 does not match the exact request."
            )
        if self.proposal_kind is not None and (
            self.proposal_kind not in request.allowed_proposal_kinds
        ):
            raise ValueError(
                "Assistant response uses a proposal kind not allowed by request."
            )
        if self.proposal_kind == "veusz_setting_operation_batch":
            batch = VeuszSettingOperationBatch.from_dict(dict(self.proposal or {}))
            if batch.base_revision != request.base_revision:
                raise ValueError(
                    "Assistant VeuszSettingOperationBatch base_revision does not "
                    "match request."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_RESPONSE_KIND,
            "version": ASSISTANT_RESPONSE_VERSION,
            "response_id": self.response_id,
            "request_id": self.request_id,
            "transaction_id": self.transaction_id,
            "provider_id": self.provider_id,
            "request_sha256": self.request_sha256,
            "status": self.status,
            "understanding": self.understanding,
            "proposal_kind": self.proposal_kind,
            "proposal": (
                copy.deepcopy(self.proposal) if self.proposal is not None else None
            ),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantResponse:
        value = require_json_object(payload, label="AssistantResponse")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "response_id",
                "request_id",
                "transaction_id",
                "provider_id",
                "request_sha256",
                "status",
                "understanding",
                "proposal_kind",
                "proposal",
                "warnings",
                "created_at",
            },
            label="AssistantResponse",
        )
        if value.get("kind") != ASSISTANT_RESPONSE_KIND:
            raise ValueError("Not a SciPlot AssistantResponse payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_RESPONSE_VERSION
        ):
            raise ValueError("Unsupported AssistantResponse version.")
        proposal = value.get("proposal")
        if proposal is not None:
            proposal = dict(
                require_json_object(proposal, label="Assistant response proposal")
            )
        return cls(
            response_id=_uuid_text(value.get("response_id"), "response_id"),
            request_id=_uuid_text(value.get("request_id"), "request_id"),
            transaction_id=_uuid_text(value.get("transaction_id"), "transaction_id"),
            provider_id=_provider_id(value.get("provider_id")),
            request_sha256=_sha256(
                value.get("request_sha256"),
                "request_sha256",
            ),
            status=_required_text(value.get("status"), "status"),
            understanding=_required_text(
                value.get("understanding"),
                "assistant understanding",
                maximum=_MAX_UNDERSTANDING_LENGTH,
            ),
            proposal_kind=_optional_text(
                value.get("proposal_kind"), "proposal_kind", maximum=64
            ),
            proposal=proposal,
            warnings=_text_list(
                value.get("warnings", []),
                label="assistant warnings",
                maximum_item_length=_MAX_WARNING_LENGTH,
            ),
            created_at=_timestamp(value.get("created_at"), "response created_at"),
        )


@dataclass
class AssistantDataMappingState:
    """Persisted human-confirmation state for one mapping proposal."""

    status: str = "proposed"
    source_root: str | None = None
    output_root: str | None = None
    preview: dict[str, Any] | None = None
    confirmation: dict[str, Any] | None = None
    execution_manifest: str | None = None
    execution_manifest_sha256: str | None = None
    mapped_document: str | None = None
    mapped_document_sha256: str | None = None
    last_error: str | None = None
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.status not in ASSISTANT_DATA_MAPPING_STATES:
            raise ValueError(
                f"Unsupported Assistant data-mapping state: {self.status!r}"
            )
        for field_name in (
            "source_root",
            "output_root",
            "execution_manifest",
            "mapped_document",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            text = _required_text(value, f"mapping {field_name}", maximum=4096)
            if not Path(text).is_absolute():
                raise ValueError(f"mapping {field_name} must be an absolute path.")
            setattr(self, field_name, text)
        if self.execution_manifest_sha256 is not None:
            self.execution_manifest_sha256 = _sha256(
                self.execution_manifest_sha256,
                "mapping execution_manifest_sha256",
            )
        if self.mapped_document_sha256 is not None:
            self.mapped_document_sha256 = _sha256(
                self.mapped_document_sha256,
                "mapping mapped_document_sha256",
            )
        if self.preview is not None:
            self.preview = dict(
                require_json_object(self.preview, label="mapping preview")
            )
            _validate_json_value(self.preview, path="mapping.preview")
            if self.preview.get("kind") != "sciplot_data_mapping_preview":
                raise ValueError("Mapping preview has an unsupported kind.")
            if (
                require_json_int(
                    self.preview.get("version", 0), label="mapping preview version"
                )
                != 1
            ):
                raise ValueError("Mapping preview has an unsupported version.")
            if self.preview.get("status") != "ready_for_confirmation":
                raise ValueError("Mapping preview is not ready for confirmation.")
            if self.preview.get("writes_performed") is not False:
                raise ValueError("Mapping preview must prove that no writes occurred.")
            if self.preview.get("raw_values_in_preview") is not False:
                raise ValueError("Mapping preview must not contain raw values.")
            if self.preview.get("requires_confirmation_receipt") is not True:
                raise ValueError("Mapping preview must require a confirmation receipt.")
        if self.confirmation is not None:
            from sciplot_core.mapping_contract import (
                DataMappingConfirmation,
            )

            self.confirmation = DataMappingConfirmation.from_dict(
                dict(
                    require_json_object(
                        self.confirmation,
                        label="mapping confirmation",
                    )
                )
            ).to_dict()
        if self.last_error is not None:
            self.last_error = _required_text(
                self.last_error,
                "mapping last_error",
                maximum=2000,
            )
        self.updated_at = _timestamp(self.updated_at, "mapping updated_at")

        preview_required = self.status in {
            "preview_ready",
            "confirmed",
            "executing",
            "executed",
        }
        confirmation_required = self.status in {
            "confirmed",
            "executing",
            "executed",
        }
        if self.status in {
            "previewing",
            "confirmed",
            "executing",
            "executed",
        } and (self.source_root is None):
            raise ValueError(f"Mapping state {self.status!r} requires source_root.")
        if preview_required and self.preview is None:
            raise ValueError(f"Mapping state {self.status!r} requires a preview.")
        if preview_required and self.output_root is None:
            raise ValueError(f"Mapping state {self.status!r} requires output_root.")
        if confirmation_required and self.confirmation is None:
            raise ValueError(
                f"Mapping state {self.status!r} requires a confirmation receipt."
            )
        if confirmation_required and self.output_root is None:
            raise ValueError(f"Mapping state {self.status!r} requires output_root.")
        if self.status == "executed":
            if self.execution_manifest is None or (
                self.execution_manifest_sha256 is None
            ) or self.mapped_document is None or (
                self.mapped_document_sha256 is None
            ):
                raise ValueError(
                    "Executed mapping state requires hashed execution and mapped-document artifacts."
                )
        elif any(
            value is not None
            for value in (
                self.execution_manifest,
                self.execution_manifest_sha256,
                self.mapped_document,
                self.mapped_document_sha256,
            )
        ):
            raise ValueError(
                "Only an executed mapping state may reference handoff artifacts."
            )

    def validate_for_proposal(self, proposal: DataMappingProposal) -> None:
        proposal_hash = canonical_payload_sha256(proposal.to_dict())
        if self.preview is not None:
            if self.preview.get("proposal_id") != proposal.proposal_id:
                raise ValueError("Mapping preview targets another proposal.")
            if self.preview.get("proposal_sha256") != proposal_hash:
                raise ValueError("Mapping preview proposal hash is stale.")
            if self.preview.get("base_request_sha256") != (
                proposal.base_request_sha256
            ):
                raise ValueError("Mapping preview request hash is stale.")
            if self.preview.get("provider") != proposal.provider:
                raise ValueError("Mapping preview provider does not match proposal.")
            preview_sources = self.preview.get("sources")
            if not isinstance(preview_sources, list):
                raise ValueError("Mapping preview requires a source inventory.")
            source_proofs = {
                str(item.get("relative_path") or ""): str(item.get("sha256") or "")
                for item in preview_sources
                if isinstance(item, dict)
            }
            if source_proofs != proposal.source_hashes:
                raise ValueError("Mapping preview source hashes are stale.")
            if self.preview.get("request_patch") != proposal.request_patch:
                raise ValueError("Mapping preview request patch changed.")
            if self.source_root is None or Path(
                str(self.preview.get("source_root") or "")
            ).expanduser().resolve() != Path(self.source_root):
                raise ValueError("Mapping preview source-root binding is stale.")
        if self.confirmation is not None:
            from sciplot_core.mapping_contract import (
                DataMappingConfirmation,
            )

            receipt = DataMappingConfirmation.from_dict(self.confirmation)
            if receipt.proposal_id != proposal.proposal_id:
                raise ValueError("Mapping confirmation targets another proposal.")
            if receipt.proposal_sha256 != proposal_hash:
                raise ValueError("Mapping confirmation proposal hash is stale.")
            if receipt.base_request_sha256 != proposal.base_request_sha256:
                raise ValueError("Mapping confirmation request hash is stale.")
            if receipt.source_hashes != proposal.source_hashes:
                raise ValueError("Mapping confirmation source hashes are stale.")
            if self.source_root is None or receipt.source_root != self.source_root:
                raise ValueError("Mapping confirmation source-root binding is stale.")
            if self.output_root is None or receipt.output_root != self.output_root:
                raise ValueError("Mapping confirmation output-root binding is stale.")
            preview_request = Path(
                str((self.preview or {}).get("base_request") or "")
            ).expanduser().resolve()
            if Path(receipt.request_path) != preview_request:
                raise ValueError("Mapping confirmation request-path binding is stale.")
        if self.status == "executed":
            expected_root = (Path(self.output_root or "") / proposal.proposal_id).resolve()
            if Path(self.execution_manifest or "") != (
                expected_root / "execution.json"
            ):
                raise ValueError("Mapping execution manifest path is not confirmed.")
            if Path(self.mapped_document or "") != (
                expected_root / "studio" / "document.vsz"
            ):
                raise ValueError("Mapped Veusz document path is not confirmed.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_DATA_MAPPING_STATE_KIND,
            "version": ASSISTANT_DATA_MAPPING_STATE_VERSION,
            "status": self.status,
            "source_root": self.source_root,
            "output_root": self.output_root,
            "preview": copy.deepcopy(self.preview),
            "confirmation": copy.deepcopy(self.confirmation),
            "execution_manifest": self.execution_manifest,
            "execution_manifest_sha256": self.execution_manifest_sha256,
            "mapped_document": self.mapped_document,
            "mapped_document_sha256": self.mapped_document_sha256,
            "last_error": self.last_error,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantDataMappingState:
        value = require_json_object(payload, label="AssistantDataMappingState")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "status",
                "source_root",
                "output_root",
                "preview",
                "confirmation",
                "execution_manifest",
                "execution_manifest_sha256",
                "mapped_document",
                "mapped_document_sha256",
                "last_error",
                "updated_at",
            },
            label="AssistantDataMappingState",
        )
        if value.get("kind") != ASSISTANT_DATA_MAPPING_STATE_KIND:
            raise ValueError("Not a SciPlot AssistantDataMappingState payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_DATA_MAPPING_STATE_VERSION
        ):
            raise ValueError("Unsupported AssistantDataMappingState version.")
        return cls(
            status=_required_text(value.get("status"), "mapping status"),
            source_root=_optional_text(
                value.get("source_root"), "mapping source_root", maximum=4096
            ),
            output_root=_optional_text(
                value.get("output_root"), "mapping output_root", maximum=4096
            ),
            preview=(
                dict(require_json_object(value["preview"], label="mapping preview"))
                if value.get("preview") is not None
                else None
            ),
            confirmation=(
                dict(
                    require_json_object(
                        value["confirmation"], label="mapping confirmation"
                    )
                )
                if value.get("confirmation") is not None
                else None
            ),
            execution_manifest=_optional_text(
                value.get("execution_manifest"),
                "mapping execution_manifest",
                maximum=4096,
            ),
            execution_manifest_sha256=(
                _sha256(
                    value["execution_manifest_sha256"],
                    "mapping execution_manifest_sha256",
                )
                if value.get("execution_manifest_sha256") is not None
                else None
            ),
            mapped_document=_optional_text(
                value.get("mapped_document"),
                "mapping mapped_document",
                maximum=4096,
            ),
            mapped_document_sha256=(
                _sha256(
                    value["mapped_document_sha256"],
                    "mapping mapped_document_sha256",
                )
                if value.get("mapped_document_sha256") is not None
                else None
            ),
            last_error=_optional_text(
                value.get("last_error"), "mapping last_error", maximum=2000
            ),
            updated_at=_timestamp(value.get("updated_at"), "mapping updated_at"),
        )


@dataclass
class AssistantRequestRecord:
    request: dict[str, Any]
    status: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    response: dict[str, Any] | None = None
    mapping_state: dict[str, Any] | None = None
    error: str | None = None
    request_sha256: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        parsed_request = AssistantRequest.from_dict(self.request)
        self.request = parsed_request.to_dict()
        expected_sha = parsed_request.payload_sha256
        if self.request_sha256 is not None:
            supplied = _sha256(self.request_sha256, "request_sha256")
            if supplied != expected_sha:
                raise ValueError(
                    "Assistant request record hash does not match request."
                )
        self.request_sha256 = expected_sha
        if self.status not in ASSISTANT_REQUEST_RECORD_STATUSES:
            raise ValueError(
                f"Unsupported Assistant request record status: {self.status!r}"
            )
        normalized_events: list[dict[str, Any]] = []
        if len(self.events) > _MAX_EVENTS:
            raise ValueError("Assistant request record contains too many events.")
        for index, payload in enumerate(self.events, start=1):
            event = AssistantProgressEvent.from_dict(payload)
            if event.request_id != parsed_request.request_id:
                raise ValueError(
                    "Assistant progress request_id does not match request."
                )
            if event.provider_id != parsed_request.provider_id:
                raise ValueError(
                    "Assistant progress provider_id does not match request."
                )
            if event.sequence != index:
                raise ValueError(
                    "Assistant progress events must be contiguous and ordered."
                )
            normalized_events.append(event.to_dict())
        self.events = normalized_events
        if self.status == "queued" and self.events:
            raise ValueError(
                "Queued Assistant requests cannot contain progress events."
            )
        parsed_response = None
        if self.response is not None:
            response = AssistantResponse.from_dict(self.response)
            parsed_response = response
            response.validate_for_request(parsed_request)
            self.response = response.to_dict()
            expected_status = {
                "proposal": "proposal_ready",
                "needs_human_confirmation": "needs_human_confirmation",
                "needs_rule_repair": "needs_rule_repair",
                "cancelled": "cancelled",
            }[response.status]
            if self.status not in {expected_status, "applied", "rejected"}:
                raise ValueError(
                    "Assistant request record status does not match its response."
                )
            if self.status in {"applied", "rejected"} and response.status != "proposal":
                raise ValueError(
                    "Only a proposal response can become applied or rejected."
                )
        elif self.status in {
            "proposal_ready",
            "needs_human_confirmation",
            "needs_rule_repair",
            "cancelled",
            "applied",
            "rejected",
        }:
            raise ValueError(
                "Assistant request record status requires a matching response."
            )
        restored_mapping = None
        if self.mapping_state is not None:
            restored_mapping = AssistantDataMappingState.from_dict(self.mapping_state)
        mapping_response = bool(
            parsed_response is not None
            and parsed_response.proposal_kind == "data_mapping_proposal"
        )
        if mapping_response:
            proposal = DataMappingProposal.from_dict(
                dict(parsed_response.proposal or {})
            )
            if restored_mapping is None:
                restored_mapping = AssistantDataMappingState(
                    status=("rejected" if self.status == "rejected" else "proposed")
                )
            restored_mapping.validate_for_proposal(proposal)
            if self.status == "applied" and restored_mapping.status != "executed":
                raise ValueError(
                    "Applied data mapping requests require executed mapping state."
                )
            if self.status == "rejected" and restored_mapping.status != "rejected":
                raise ValueError(
                    "Rejected data mapping requests require rejected mapping state."
                )
            self.mapping_state = restored_mapping.to_dict()
        elif restored_mapping is not None:
            raise ValueError(
                "Only a DataMappingProposal response may persist mapping state."
            )
        if self.error is not None:
            self.error = _required_text(self.error, "request error", maximum=2000)
        if self.status in {"failed", "interrupted"} and self.error is None:
            raise ValueError(
                "Failed or interrupted Assistant request records require an error."
            )
        if self.status not in {"failed", "interrupted"} and self.error is not None:
            raise ValueError(
                "Only failed or interrupted Assistant request records may contain an error."
            )
        self.created_at = _timestamp(self.created_at, "request record created_at")
        self.updated_at = _timestamp(self.updated_at, "request record updated_at")
        created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        updated = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
        if updated < created:
            raise ValueError(
                "Assistant request record updated_at cannot precede created_at."
            )

    @property
    def parsed_request(self) -> AssistantRequest:
        return AssistantRequest.from_dict(self.request)

    @property
    def parsed_response(self) -> AssistantResponse | None:
        return (
            AssistantResponse.from_dict(self.response)
            if self.response is not None
            else None
        )

    @property
    def parsed_mapping_state(self) -> AssistantDataMappingState | None:
        return (
            AssistantDataMappingState.from_dict(self.mapping_state)
            if self.mapping_state is not None
            else None
        )

    @property
    def latest_event(self) -> AssistantProgressEvent | None:
        return (
            AssistantProgressEvent.from_dict(self.events[-1]) if self.events else None
        )

    @property
    def provider_running(self) -> bool:
        return self.status in {"queued", "running", "cancel_requested"}

    def append_event(self, event: AssistantProgressEvent) -> None:
        if self.status not in {"queued", "running"}:
            raise ValueError(
                "Assistant request cannot accept progress in its current state."
            )
        request = self.parsed_request
        if event.request_id != request.request_id:
            raise ValueError("Assistant progress request_id does not match request.")
        if event.provider_id != request.provider_id:
            raise ValueError("Assistant progress provider_id does not match request.")
        if event.sequence != len(self.events) + 1:
            raise ValueError(
                "Assistant progress sequence is not the next expected value."
            )
        if len(self.events) >= _MAX_EVENTS:
            raise ValueError("Assistant request has reached its progress-event limit.")
        self.events.append(event.to_dict())
        self.status = "running"
        self.updated_at = _now()

    def request_cancel(self) -> None:
        if self.status not in {"queued", "running"}:
            raise ValueError("Assistant request is not running.")
        self.status = "cancel_requested"
        self.updated_at = _now()

    def complete(self, response: AssistantResponse) -> None:
        if self.status not in {"queued", "running", "cancel_requested"}:
            raise ValueError("Assistant request cannot complete in its current state.")
        request = self.parsed_request
        response.validate_for_request(request)
        if self.status == "cancel_requested" and response.status != "cancelled":
            raise ValueError(
                "A cancelled Assistant request cannot accept a late proposal."
            )
        self.response = response.to_dict()
        self.status = {
            "proposal": "proposal_ready",
            "needs_human_confirmation": "needs_human_confirmation",
            "needs_rule_repair": "needs_rule_repair",
            "cancelled": "cancelled",
        }[response.status]
        self.mapping_state = (
            AssistantDataMappingState().to_dict()
            if response.proposal_kind == "data_mapping_proposal"
            else None
        )
        self.error = None
        self.updated_at = _now()

    def fail(self, error: str) -> None:
        if self.status not in {"queued", "running", "cancel_requested"}:
            raise ValueError("Assistant request cannot fail in its current state.")
        self.status = "failed"
        self.error = _required_text(error, "request error", maximum=2000)
        self.updated_at = _now()

    def interrupt(self, error: str) -> None:
        if self.status not in {"queued", "running", "cancel_requested"}:
            raise ValueError("Assistant request is not in progress.")
        self.status = "interrupted"
        self.error = _required_text(error, "request interruption", maximum=2000)
        self.updated_at = _now()

    def mark_proposal_outcome(self, *, accepted: bool) -> None:
        if self.status != "proposal_ready":
            raise ValueError("Assistant request has no pending proposal outcome.")
        response = self.parsed_response
        if response is not None and response.proposal_kind == "data_mapping_proposal":
            state = self.parsed_mapping_state
            if state is None:
                raise ValueError("Data mapping proposal has no persisted state.")
            if accepted and state.status != "executed":
                raise ValueError(
                    "Data mapping proposal cannot be accepted before execution."
                )
            if not accepted:
                if state.status == "executed":
                    raise ValueError(
                        "An executed mapping candidate retains evidence and cannot be relabeled as rejected."
                    )
                state.status = "rejected"
                state.last_error = None
                state.updated_at = _now()
                self.mapping_state = AssistantDataMappingState.from_dict(
                    state.to_dict()
                ).to_dict()
        self.status = "applied" if accepted else "rejected"
        self.updated_at = _now()

    def set_mapping_state(self, state: AssistantDataMappingState) -> None:
        if self.status != "proposal_ready":
            raise ValueError("Assistant request has no active mapping proposal.")
        response = self.parsed_response
        if response is None or response.proposal_kind != "data_mapping_proposal":
            raise ValueError("Assistant response is not a DataMappingProposal.")
        restored = AssistantDataMappingState.from_dict(state.to_dict())
        proposal = DataMappingProposal.from_dict(dict(response.proposal or {}))
        restored.validate_for_proposal(proposal)
        self.mapping_state = restored.to_dict()
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_REQUEST_RECORD_KIND,
            "version": ASSISTANT_REQUEST_RECORD_VERSION,
            "request": copy.deepcopy(self.request),
            "request_sha256": self.request_sha256,
            "status": self.status,
            "events": copy.deepcopy(self.events),
            "response": (
                copy.deepcopy(self.response) if self.response is not None else None
            ),
            "mapping_state": (
                copy.deepcopy(self.mapping_state)
                if self.mapping_state is not None
                else None
            ),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantRequestRecord:
        value = require_json_object(payload, label="AssistantRequestRecord")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "request",
                "request_sha256",
                "status",
                "events",
                "response",
                "mapping_state",
                "error",
                "created_at",
                "updated_at",
            },
            label="AssistantRequestRecord",
        )
        if value.get("kind") != ASSISTANT_REQUEST_RECORD_KIND:
            raise ValueError("Not a SciPlot AssistantRequestRecord payload.")
        version = require_json_int(value.get("version", 0), label="version")
        if version not in ASSISTANT_REQUEST_RECORD_COMPATIBLE_VERSIONS:
            raise ValueError("Unsupported AssistantRequestRecord version.")
        events = require_json_list(value.get("events", []), label="request events")
        if not all(isinstance(event, dict) for event in events):
            raise ValueError("Every Assistant request event must be an object.")
        response = value.get("response")
        if response is not None:
            response = dict(require_json_object(response, label="request response"))
        return cls(
            request=dict(require_json_object(value.get("request"), label="request")),
            request_sha256=_sha256(value.get("request_sha256"), "request_sha256"),
            status=_required_text(value.get("status"), "request status"),
            events=[dict(event) for event in events],
            response=response,
            mapping_state=(
                dict(require_json_object(value["mapping_state"], label="mapping_state"))
                if value.get("mapping_state") is not None
                else None
            ),
            error=_optional_text(value.get("error"), "request error", maximum=2000),
            created_at=_timestamp(value.get("created_at"), "request record created_at"),
            updated_at=_timestamp(value.get("updated_at"), "request record updated_at"),
        )


class AssistantCancelled(RuntimeError):
    """Raised by a provider when cooperative cancellation is observed."""


class AssistantCancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AssistantCancelled("Assistant request cancelled by the user.")


AssistantProgressCallback = Callable[[AssistantProgressEvent], None]


class AssistantProvider(Protocol):
    @property
    def descriptor(self) -> AssistantProviderDescriptor: ...

    def generate(
        self,
        request: AssistantRequest,
        *,
        emit_progress: AssistantProgressCallback,
        cancellation: AssistantCancellationToken,
    ) -> AssistantResponse: ...


__all__ = [
    "ASSISTANT_CONTEXT_KIND",
    "ASSISTANT_CONTEXT_VERSION",
    "ASSISTANT_DATA_POLICY",
    "ASSISTANT_DATA_MAPPING_STATES",
    "ASSISTANT_MAX_INTENT_LENGTH",
    "ASSISTANT_PROGRESS_STAGES",
    "ASSISTANT_PROPOSAL_KINDS",
    "ASSISTANT_PROVIDER_CAPABILITIES",
    "ASSISTANT_REQUEST_RECORD_STATUSES",
    "ASSISTANT_REQUEST_TERMINAL_STATUSES",
    "ASSISTANT_RESPONSE_STATUSES",
    "ASSISTANT_VISUAL_PREVIEW_MAX_BYTES",
    "AssistantCancellationToken",
    "AssistantCancelled",
    "AssistantDataMappingState",
    "AssistantProgressCallback",
    "AssistantProgressEvent",
    "AssistantProvider",
    "AssistantProviderDescriptor",
    "AssistantRequest",
    "AssistantRequestRecord",
    "AssistantResponse",
    "canonical_payload_sha256",
]
