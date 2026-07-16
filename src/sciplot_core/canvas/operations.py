from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sciplot_core.canvas._validation import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_object,
)

CANVAS_OPERATION_KIND = "sciplot_canvas_operation"
CANVAS_OPERATION_BATCH_KIND = "sciplot_canvas_operation_batch"
CANVAS_OPERATION_VERSION = 1
SUPPORTED_CANVAS_OPERATIONS = {"set_setting"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


def _validate_json_value(value: Any, *, path: str = "value") -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings.")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} must be JSON-serializable, not {type(value).__name__}.")


@dataclass(frozen=True)
class CanvasOperation:
    operation_type: str
    target_id: str
    arguments: dict[str, Any]
    operation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _required_text(self.operation_id, "operation_id")
        if self.operation_type not in SUPPORTED_CANVAS_OPERATIONS:
            raise ValueError(f"Unsupported CanvasOperation: {self.operation_type!r}")
        _required_text(self.target_id, "target_id")
        if not isinstance(self.arguments, dict):
            raise ValueError("arguments must be an object.")
        _validate_json_value(self.arguments, path="arguments")
        if self.operation_type == "set_setting":
            unexpected = set(self.arguments) - {
                "setting_path",
                "value",
                "expected_value",
            }
            if unexpected:
                raise ValueError(
                    f"set_setting contains unsupported arguments: {sorted(unexpected)!r}"
                )
            setting_path = _required_text(
                self.arguments.get("setting_path"), "setting_path"
            )
            if not setting_path.startswith("/"):
                raise ValueError("set_setting requires an absolute Veusz setting_path.")
            if "value" not in self.arguments:
                raise ValueError("set_setting requires a value.")

    @classmethod
    def set_setting(
        cls,
        *,
        target_id: str,
        setting_path: str,
        value: Any,
        expected_value: Any = None,
        require_expected_value: bool = False,
    ) -> CanvasOperation:
        arguments = {
            "setting_path": setting_path,
            "value": value,
        }
        if require_expected_value or expected_value is not None:
            arguments["expected_value"] = expected_value
        return cls(
            operation_type="set_setting",
            target_id=target_id,
            arguments=arguments,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": CANVAS_OPERATION_KIND,
            "version": CANVAS_OPERATION_VERSION,
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "target_id": self.target_id,
            "arguments": dict(self.arguments),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CanvasOperation:
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "operation_id",
                "operation_type",
                "target_id",
                "arguments",
                "created_at",
            },
            label="CanvasOperation",
        )
        if payload.get("kind") != CANVAS_OPERATION_KIND:
            raise ValueError("Not a SciPlot CanvasOperation payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != CANVAS_OPERATION_VERSION:
            raise ValueError(
                f"Unsupported CanvasOperation version: {payload.get('version')!r}"
            )
        arguments = require_json_object(
            payload.get("arguments"), label="CanvasOperation arguments"
        )
        return cls(
            operation_id=_required_text(payload.get("operation_id"), "operation_id"),
            operation_type=_required_text(
                payload.get("operation_type"), "operation_type"
            ),
            target_id=_required_text(payload.get("target_id"), "target_id"),
            arguments=dict(arguments),
            created_at=str(payload.get("created_at") or _now()),
        )


@dataclass(frozen=True)
class CanvasOperationBatch:
    base_revision: int
    operations: tuple[CanvasOperation, ...]
    provider: str
    rationale: str = ""
    atomic: bool = True
    batch_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _required_text(self.batch_id, "batch_id")
        if isinstance(self.base_revision, bool) or not isinstance(
            self.base_revision, int
        ):
            raise ValueError("base_revision must be an integer.")
        if self.base_revision < 0:
            raise ValueError("base_revision must be non-negative.")
        if not self.operations:
            raise ValueError("CanvasOperationBatch requires at least one operation.")
        if not all(
            isinstance(operation, CanvasOperation) for operation in self.operations
        ):
            raise ValueError(
                "CanvasOperationBatch entries must be CanvasOperation objects."
            )
        if type(self.atomic) is not bool:
            raise ValueError("CanvasOperationBatch atomic must be a boolean.")
        if not self.atomic:
            raise ValueError("CanvasOperationBatch version 1 requires atomic=true.")
        _required_text(self.provider, "provider")
        if len({operation.operation_id for operation in self.operations}) != len(
            self.operations
        ):
            raise ValueError("CanvasOperationBatch operation IDs must be unique.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": CANVAS_OPERATION_BATCH_KIND,
            "version": CANVAS_OPERATION_VERSION,
            "batch_id": self.batch_id,
            "base_revision": self.base_revision,
            "provider": self.provider,
            "rationale": self.rationale,
            "atomic": self.atomic,
            "operations": [operation.to_dict() for operation in self.operations],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CanvasOperationBatch:
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "batch_id",
                "base_revision",
                "provider",
                "rationale",
                "atomic",
                "operations",
                "created_at",
            },
            label="CanvasOperationBatch",
        )
        if payload.get("kind") != CANVAS_OPERATION_BATCH_KIND:
            raise ValueError("Not a SciPlot CanvasOperationBatch payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != CANVAS_OPERATION_VERSION:
            raise ValueError(
                f"Unsupported CanvasOperationBatch version: {payload.get('version')!r}"
            )
        raw_operations = require_json_list(
            payload.get("operations"), label="CanvasOperationBatch operations"
        )
        if not all(isinstance(item, dict) for item in raw_operations):
            raise ValueError("Every CanvasOperationBatch operation must be an object.")
        return cls(
            batch_id=_required_text(payload.get("batch_id"), "batch_id"),
            base_revision=require_json_int(
                payload.get("base_revision", 0), label="base_revision"
            ),
            provider=_required_text(payload.get("provider"), "provider"),
            rationale=str(payload.get("rationale") or ""),
            atomic=require_json_bool(payload.get("atomic", True), label="atomic"),
            operations=tuple(
                CanvasOperation.from_dict(item) for item in raw_operations
            ),
            created_at=str(payload.get("created_at") or _now()),
        )


__all__ = [
    "CANVAS_OPERATION_BATCH_KIND",
    "CANVAS_OPERATION_KIND",
    "CANVAS_OPERATION_VERSION",
    "CanvasOperation",
    "CanvasOperationBatch",
    "SUPPORTED_CANVAS_OPERATIONS",
]
