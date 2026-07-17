from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sciplot_core.canvas._validation import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_number,
    require_json_object,
)

CANVAS_OPERATION_KIND = "sciplot_canvas_operation"
CANVAS_OPERATION_BATCH_KIND = "sciplot_canvas_operation_batch"
CANVAS_OPERATION_VERSION = 1
SUPPORTED_COMPOSITION_OPERATIONS = {
    "composition_place_module",
    "composition_reorder_modules",
    "composition_set_canvas_height",
    "composition_set_layout",
    "composition_set_legend_policy",
}
SUPPORTED_CANVAS_OPERATIONS = {
    "set_setting",
    "add_widget",
    "composition_place_module",
    "composition_reorder_modules",
    "composition_set_canvas_height",
    "composition_set_layout",
    "composition_set_legend_policy",
}
SUPPORTED_NATIVE_ANNOTATION_WIDGETS = {"label", "line", "rect", "ellipse"}
NATIVE_ANNOTATION_WIDGET_SETTINGS = {
    "label": {
        "xPos",
        "yPos",
        "positioning",
        "xAxis",
        "yAxis",
        "label",
        "alignHorz",
        "alignVert",
        "clip",
        "Text__color",
        "Text__size",
    },
    "line": {
        "xPos",
        "yPos",
        "xPos2",
        "yPos2",
        "positioning",
        "xAxis",
        "yAxis",
        "mode",
        "clip",
        "arrowright",
        "arrowleft",
        "arrowSize",
        "Line__color",
        "Line__width",
        "Fill__color",
    },
    "rect": {
        "xPos",
        "yPos",
        "positioning",
        "xAxis",
        "yAxis",
        "width",
        "height",
        "clip",
        "Border__color",
        "Border__width",
        "Fill__color",
        "Fill__transparency",
        "Fill__hide",
    },
    "ellipse": {
        "xPos",
        "yPos",
        "positioning",
        "xAxis",
        "yAxis",
        "width",
        "height",
        "clip",
        "Border__color",
        "Border__width",
        "Fill__color",
        "Fill__transparency",
        "Fill__hide",
    },
}
_SAFE_WIDGET_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


def _optional_safe_reference(value: object, label: str) -> str | None:
    if value is None:
        return None
    text = _required_text(value, label)
    if _SAFE_WIDGET_NAME.fullmatch(text) is None:
        raise ValueError(f"{label} must be a safe SciPlot identifier.")
    return text


def _composition_module_ids(value: object, label: str) -> list[str]:
    items = require_json_list(value, label=label)
    if not 1 <= len(items) <= 12:
        raise ValueError(f"{label} must contain one to twelve module ids.")
    normalized = [_required_text(item, f"{label} item") for item in items]
    if any(_SAFE_WIDGET_NAME.fullmatch(item) is None for item in normalized):
        raise ValueError(f"{label} entries must be safe SciPlot identifiers.")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} entries must be unique.")
    return normalized


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
        elif self.operation_type == "add_widget":
            unexpected = set(self.arguments) - {
                "widget_type",
                "name",
                "index",
                "settings",
            }
            if unexpected:
                raise ValueError(
                    f"add_widget contains unsupported arguments: {sorted(unexpected)!r}"
                )
            widget_type = _required_text(
                self.arguments.get("widget_type"),
                "widget_type",
            )
            if widget_type not in SUPPORTED_NATIVE_ANNOTATION_WIDGETS:
                raise ValueError(
                    f"Unsupported native annotation widget: {widget_type!r}"
                )
            name = _required_text(self.arguments.get("name"), "name")
            if _SAFE_WIDGET_NAME.fullmatch(name) is None:
                raise ValueError("add_widget name must be a safe renderer object name.")
            index = require_json_int(
                self.arguments.get("index", -1),
                label="add_widget index",
            )
            if index not in {-1, 0}:
                raise ValueError("add_widget index must be -1 (append) or 0 (front).")
            settings = require_json_object(
                self.arguments.get("settings"),
                label="add_widget settings",
            )
            unsupported_settings = (
                set(settings) - NATIVE_ANNOTATION_WIDGET_SETTINGS[widget_type]
            )
            if unsupported_settings:
                raise ValueError(
                    f"{widget_type} promotion contains unsupported settings: "
                    f"{sorted(unsupported_settings)!r}"
                )
            if not settings:
                raise ValueError("add_widget requires bounded initial settings.")
        elif self.operation_type == "composition_place_module":
            unexpected = set(self.arguments) - {
                "module_id",
                "slot_ref",
                "expected_slot_ref",
            }
            if unexpected:
                raise ValueError(
                    "composition_place_module contains unsupported arguments: "
                    f"{sorted(unexpected)!r}"
                )
            if (
                "slot_ref" not in self.arguments
                or "expected_slot_ref" not in self.arguments
            ):
                raise ValueError(
                    "composition_place_module requires slot_ref and expected_slot_ref."
                )
            module_id = _required_text(
                self.arguments.get("module_id"),
                "composition module_id",
            )
            if _SAFE_WIDGET_NAME.fullmatch(module_id) is None:
                raise ValueError("composition module_id must be a safe identifier.")
            _optional_safe_reference(
                self.arguments.get("slot_ref"),
                "composition slot_ref",
            )
            _optional_safe_reference(
                self.arguments.get("expected_slot_ref"),
                "composition expected_slot_ref",
            )
        elif self.operation_type == "composition_reorder_modules":
            unexpected = set(self.arguments) - {
                "ordered_module_ids",
                "expected_ordered_module_ids",
            }
            if unexpected:
                raise ValueError(
                    "composition_reorder_modules contains unsupported arguments: "
                    f"{sorted(unexpected)!r}"
                )
            ordered = _composition_module_ids(
                self.arguments.get("ordered_module_ids"),
                "ordered_module_ids",
            )
            expected = _composition_module_ids(
                self.arguments.get("expected_ordered_module_ids"),
                "expected_ordered_module_ids",
            )
            if set(ordered) != set(expected):
                raise ValueError(
                    "Composition reorder current and expected ids must match."
                )
        elif self.operation_type == "composition_set_layout":
            unexpected = set(self.arguments) - {
                "layout_id",
                "expected_layout_id",
            }
            if unexpected:
                raise ValueError(
                    "composition_set_layout contains unsupported arguments: "
                    f"{sorted(unexpected)!r}"
                )
            _required_text(self.arguments.get("layout_id"), "layout_id")
            _required_text(
                self.arguments.get("expected_layout_id"),
                "expected_layout_id",
            )
        elif self.operation_type == "composition_set_canvas_height":
            unexpected = set(self.arguments) - {
                "height_mm",
                "expected_height_mm",
            }
            if unexpected:
                raise ValueError(
                    "composition_set_canvas_height contains unsupported arguments: "
                    f"{sorted(unexpected)!r}"
                )
            height = require_json_number(
                self.arguments.get("height_mm"),
                label="height_mm",
            )
            expected_height = require_json_number(
                self.arguments.get("expected_height_mm"),
                label="expected_height_mm",
            )
            if not 20.0 <= height <= 170.0:
                raise ValueError("height_mm must be between 20 and 170 mm.")
            if not 20.0 <= expected_height <= 170.0:
                raise ValueError("expected_height_mm must be between 20 and 170 mm.")
        elif self.operation_type == "composition_set_legend_policy":
            unexpected = set(self.arguments) - {
                "legend_policy",
                "expected_legend_policy",
            }
            if unexpected:
                raise ValueError(
                    "composition_set_legend_policy contains unsupported arguments: "
                    f"{sorted(unexpected)!r}"
                )
            allowed = {"auto", "shared_when_equivalent", "per_panel"}
            policy = _required_text(
                self.arguments.get("legend_policy"),
                "legend_policy",
            )
            expected_policy = _required_text(
                self.arguments.get("expected_legend_policy"),
                "expected_legend_policy",
            )
            if policy not in allowed or expected_policy not in allowed:
                raise ValueError(f"Legend policy must be one of {sorted(allowed)!r}.")

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

    @classmethod
    def add_widget(
        cls,
        *,
        target_id: str,
        widget_type: str,
        name: str,
        settings: dict[str, Any],
        index: int = -1,
    ) -> CanvasOperation:
        return cls(
            operation_type="add_widget",
            target_id=target_id,
            arguments={
                "widget_type": widget_type,
                "name": name,
                "index": index,
                "settings": dict(settings),
            },
        )

    @classmethod
    def place_composition_module(
        cls,
        *,
        variant_id: str,
        module_id: str,
        slot_ref: str | None,
        expected_slot_ref: str | None,
    ) -> CanvasOperation:
        return cls(
            operation_type="composition_place_module",
            target_id=variant_id,
            arguments={
                "module_id": module_id,
                "slot_ref": slot_ref,
                "expected_slot_ref": expected_slot_ref,
            },
        )

    @classmethod
    def reorder_composition_modules(
        cls,
        *,
        variant_id: str,
        ordered_module_ids: list[str] | tuple[str, ...],
        expected_ordered_module_ids: list[str] | tuple[str, ...],
    ) -> CanvasOperation:
        return cls(
            operation_type="composition_reorder_modules",
            target_id=variant_id,
            arguments={
                "ordered_module_ids": list(ordered_module_ids),
                "expected_ordered_module_ids": list(expected_ordered_module_ids),
            },
        )

    @classmethod
    def set_composition_layout(
        cls,
        *,
        variant_id: str,
        layout_id: str,
        expected_layout_id: str,
    ) -> CanvasOperation:
        return cls(
            operation_type="composition_set_layout",
            target_id=variant_id,
            arguments={
                "layout_id": layout_id,
                "expected_layout_id": expected_layout_id,
            },
        )

    @classmethod
    def set_composition_canvas_height(
        cls,
        *,
        variant_id: str,
        height_mm: float,
        expected_height_mm: float,
    ) -> CanvasOperation:
        return cls(
            operation_type="composition_set_canvas_height",
            target_id=variant_id,
            arguments={
                "height_mm": height_mm,
                "expected_height_mm": expected_height_mm,
            },
        )

    @classmethod
    def set_composition_legend_policy(
        cls,
        *,
        variant_id: str,
        legend_policy: str,
        expected_legend_policy: str,
    ) -> CanvasOperation:
        return cls(
            operation_type="composition_set_legend_policy",
            target_id=variant_id,
            arguments={
                "legend_policy": legend_policy,
                "expected_legend_policy": expected_legend_policy,
            },
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
    "NATIVE_ANNOTATION_WIDGET_SETTINGS",
    "SUPPORTED_CANVAS_OPERATIONS",
    "SUPPORTED_COMPOSITION_OPERATIONS",
    "SUPPORTED_NATIVE_ANNOTATION_WIDGETS",
]
