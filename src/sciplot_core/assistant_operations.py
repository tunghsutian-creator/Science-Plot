from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_object,
)

VEUSZ_SETTING_OPERATION_KIND = "sciplot_veusz_setting_operation"
VEUSZ_SETTING_OPERATION_BATCH_KIND = "sciplot_veusz_setting_operation_batch"
VEUSZ_SETTING_OPERATION_VERSION = 1
SUPPORTED_VEUSZ_SETTING_OPERATIONS = frozenset({"set_setting"})


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
class VeuszSettingOperation:
    operation_type: str
    target_id: str
    arguments: dict[str, Any]
    operation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _required_text(self.operation_id, "operation_id")
        if self.operation_type not in SUPPORTED_VEUSZ_SETTING_OPERATIONS:
            raise ValueError(
                f"Unsupported VeuszSettingOperation: {self.operation_type!r}"
            )
        _required_text(self.target_id, "target_id")
        if not isinstance(self.arguments, dict):
            raise ValueError("arguments must be an object.")
        _validate_json_value(self.arguments, path="arguments")
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
    ) -> VeuszSettingOperation:
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
            "kind": VEUSZ_SETTING_OPERATION_KIND,
            "version": VEUSZ_SETTING_OPERATION_VERSION,
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "target_id": self.target_id,
            "arguments": dict(self.arguments),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VeuszSettingOperation:
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
            label="VeuszSettingOperation",
        )
        if payload.get("kind") != VEUSZ_SETTING_OPERATION_KIND:
            raise ValueError("Not a SciPlot VeuszSettingOperation payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != VEUSZ_SETTING_OPERATION_VERSION:
            raise ValueError(
                "Unsupported VeuszSettingOperation version: "
                f"{payload.get('version')!r}"
            )
        arguments = require_json_object(
            payload.get("arguments"), label="VeuszSettingOperation arguments"
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
class VeuszSettingOperationBatch:
    base_revision: int
    operations: tuple[VeuszSettingOperation, ...]
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
            raise ValueError(
                "VeuszSettingOperationBatch requires at least one operation."
            )
        if not all(
            isinstance(operation, VeuszSettingOperation)
            for operation in self.operations
        ):
            raise ValueError(
                "VeuszSettingOperationBatch entries must be "
                "VeuszSettingOperation objects."
            )
        if type(self.atomic) is not bool:
            raise ValueError("VeuszSettingOperationBatch atomic must be a boolean.")
        if not self.atomic:
            raise ValueError(
                "VeuszSettingOperationBatch version 1 requires atomic=true."
            )
        _required_text(self.provider, "provider")
        if len({operation.operation_id for operation in self.operations}) != len(
            self.operations
        ):
            raise ValueError(
                "VeuszSettingOperationBatch operation IDs must be unique."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": VEUSZ_SETTING_OPERATION_BATCH_KIND,
            "version": VEUSZ_SETTING_OPERATION_VERSION,
            "batch_id": self.batch_id,
            "base_revision": self.base_revision,
            "provider": self.provider,
            "rationale": self.rationale,
            "atomic": self.atomic,
            "operations": [operation.to_dict() for operation in self.operations],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VeuszSettingOperationBatch:
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
            label="VeuszSettingOperationBatch",
        )
        if payload.get("kind") != VEUSZ_SETTING_OPERATION_BATCH_KIND:
            raise ValueError("Not a SciPlot VeuszSettingOperationBatch payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != VEUSZ_SETTING_OPERATION_VERSION:
            raise ValueError(
                "Unsupported VeuszSettingOperationBatch version: "
                f"{payload.get('version')!r}"
            )
        raw_operations = require_json_list(
            payload.get("operations"),
            label="VeuszSettingOperationBatch operations",
        )
        if not all(isinstance(item, dict) for item in raw_operations):
            raise ValueError(
                "Every VeuszSettingOperationBatch operation must be an object."
            )
        return cls(
            batch_id=_required_text(payload.get("batch_id"), "batch_id"),
            base_revision=require_json_int(
                payload.get("base_revision", 0), label="base_revision"
            ),
            provider=_required_text(payload.get("provider"), "provider"),
            rationale=str(payload.get("rationale") or ""),
            atomic=require_json_bool(payload.get("atomic", True), label="atomic"),
            operations=tuple(
                VeuszSettingOperation.from_dict(item) for item in raw_operations
            ),
            created_at=str(payload.get("created_at") or _now()),
        )


__all__ = [
    "SUPPORTED_VEUSZ_SETTING_OPERATIONS",
    "VEUSZ_SETTING_OPERATION_BATCH_KIND",
    "VEUSZ_SETTING_OPERATION_KIND",
    "VEUSZ_SETTING_OPERATION_VERSION",
    "VeuszSettingOperation",
    "VeuszSettingOperationBatch",
]
