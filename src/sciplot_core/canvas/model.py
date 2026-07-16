from __future__ import annotations

import copy
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

CANVAS_SESSION_KIND = "sciplot_canvas_session"
CANVAS_SESSION_VERSION = 5
CANVAS_SESSION_COMPATIBLE_VERSIONS = {1, 2, 3, 4, CANVAS_SESSION_VERSION}
CANVAS_SESSION_STATES = {
    "preparing",
    "canvas_ready",
    "editing",
    "validating",
    "ready",
    "ai_proposing",
    "ai_applying",
    "needs_human_confirmation",
    "needs_rule_repair",
    "conflict",
}
CANVAS_TRANSACTION_STATES = {
    "active",
    "paused",
    "committed",
    "rejected",
    "rolled_back",
    "conflict",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


def _optional_sha256(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    text = str(value)
    if re.fullmatch(r"[0-9a-fA-F]{64}", text) is None:
        raise ValueError(f"{label} must be a SHA-256 digest.")
    return text


def _validate_json_tree(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_tree(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings.")
            _validate_json_tree(item, path=f"{path}.{key}")
        return
    raise ValueError(
        f"{path} must contain JSON values, not {type(value).__name__}."
    )


@dataclass
class CanvasObjectRecord:
    object_id: str
    structural_key: str
    current_path: str
    object_type: str
    first_seen_revision: int
    last_seen_revision: int

    def __post_init__(self) -> None:
        self.object_id = _required_text(self.object_id, "object_id")
        self.structural_key = _required_text(self.structural_key, "structural_key")
        self.current_path = _required_text(self.current_path, "current_path")
        self.object_type = _required_text(self.object_type, "object_type")
        if self.first_seen_revision < 0:
            raise ValueError("first_seen_revision must be non-negative.")
        if self.last_seen_revision < self.first_seen_revision:
            raise ValueError("last_seen_revision cannot precede first_seen_revision.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "structural_key": self.structural_key,
            "current_path": self.current_path,
            "object_type": self.object_type,
            "first_seen_revision": self.first_seen_revision,
            "last_seen_revision": self.last_seen_revision,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CanvasObjectRecord:
        reject_unknown_keys(
            payload,
            {
                "object_id",
                "structural_key",
                "current_path",
                "object_type",
                "first_seen_revision",
                "last_seen_revision",
            },
            label="CanvasObjectRecord",
        )
        return cls(
            object_id=_required_text(payload.get("object_id"), "object_id"),
            structural_key=_required_text(
                payload.get("structural_key"), "structural_key"
            ),
            current_path=_required_text(payload.get("current_path"), "current_path"),
            object_type=_required_text(payload.get("object_type"), "object_type"),
            first_seen_revision=require_json_int(
                payload.get("first_seen_revision", 0),
                label="first_seen_revision",
            ),
            last_seen_revision=require_json_int(
                payload.get("last_seen_revision", 0),
                label="last_seen_revision",
            ),
        )


@dataclass
class ObjectIdentityRegistry:
    """Persist SciPlot IDs against structural positions, not display names."""

    records: dict[str, CanvasObjectRecord] = field(default_factory=dict)

    def bind(
        self,
        *,
        structural_key: str,
        current_path: str,
        object_type: str,
        revision: int,
    ) -> CanvasObjectRecord:
        key = _required_text(structural_key, "structural_key")
        path = _required_text(current_path, "current_path")
        kind = _required_text(object_type, "object_type")
        if revision < 0:
            raise ValueError("Object registry revision must be non-negative.")
        record = self.records.get(key)
        if record is None:
            record = CanvasObjectRecord(
                object_id=str(uuid4()),
                structural_key=key,
                current_path=path,
                object_type=kind,
                first_seen_revision=revision,
                last_seen_revision=revision,
            )
            self.records[key] = record
        else:
            if revision < record.first_seen_revision:
                raise ValueError(
                    "Object registry revision predates first_seen_revision."
                )
            record.current_path = path
            record.object_type = kind
            record.last_seen_revision = revision
        return record

    def by_id(self, object_id: str) -> CanvasObjectRecord | None:
        return next(
            (
                record
                for record in self.records.values()
                if record.object_id == object_id
            ),
            None,
        )

    def reconcile(
        self,
        objects: list[tuple[str, str, str]],
        *,
        revision: int,
    ) -> list[CanvasObjectRecord]:
        """Reconcile a complete object tree without losing IDs on insertion.

        Exact persisted paths win first so sibling insertion or reordering
        cannot transfer an existing object's ID to a newly inserted object.
        Structural keys remain the fallback for legitimate path renames.
        """

        if revision < 0:
            raise ValueError("Object registry revision must be non-negative.")
        structural_keys = [str(item[0]) for item in objects]
        current_paths = [str(item[1]) for item in objects]
        if len(set(structural_keys)) != len(structural_keys):
            raise ValueError("Object reconciliation structural keys must be unique.")
        if len(set(current_paths)) != len(current_paths):
            raise ValueError("Object reconciliation paths must be unique.")

        old_records = list(self.records.values())
        assigned: list[CanvasObjectRecord | None] = [None] * len(objects)
        used_ids: set[str] = set()
        by_path = {
            (record.current_path, record.object_type): record
            for record in old_records
        }

        for index, (_, current_path, object_type) in enumerate(objects):
            record = by_path.get((str(current_path), str(object_type)))
            if record is not None and record.object_id not in used_ids:
                assigned[index] = record
                used_ids.add(record.object_id)

        for index, (structural_key, _, object_type) in enumerate(objects):
            if assigned[index] is not None:
                continue
            record = self.records.get(str(structural_key))
            if (
                record is not None
                and record.object_type == str(object_type)
                and record.object_id not in used_ids
            ):
                assigned[index] = record
                used_ids.add(record.object_id)

        reconciled: dict[str, CanvasObjectRecord] = {}
        ordered: list[CanvasObjectRecord] = []
        for index, (structural_key, current_path, object_type) in enumerate(objects):
            key = _required_text(structural_key, "structural_key")
            path = _required_text(current_path, "current_path")
            kind = _required_text(object_type, "object_type")
            record = assigned[index]
            if record is None:
                record = CanvasObjectRecord(
                    object_id=str(uuid4()),
                    structural_key=key,
                    current_path=path,
                    object_type=kind,
                    first_seen_revision=revision,
                    last_seen_revision=revision,
                )
            else:
                if revision < record.first_seen_revision:
                    raise ValueError(
                        "Object registry revision predates first_seen_revision."
                    )
                record.structural_key = key
                record.current_path = path
                record.object_type = kind
                record.last_seen_revision = revision
            reconciled[key] = record
            ordered.append(record)
        self.records = reconciled
        return ordered

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": "typed_sibling_index_v1",
            "records": {
                key: record.to_dict() for key, record in sorted(self.records.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> ObjectIdentityRegistry:
        if payload is None:
            return cls()
        payload = require_json_object(payload, label="object_registry")
        reject_unknown_keys(
            payload,
            {"strategy", "records"},
            label="object_registry",
        )
        strategy = payload.get("strategy", "typed_sibling_index_v1")
        if strategy != "typed_sibling_index_v1":
            raise ValueError(f"Unsupported object identity strategy: {strategy!r}")
        raw_records = require_json_object(
            payload.get("records"), label="object_registry.records"
        )
        records: dict[str, CanvasObjectRecord] = {}
        for key, value in raw_records.items():
            if not isinstance(value, dict):
                raise ValueError("Every object registry record must be an object.")
            record = CanvasObjectRecord.from_dict(value)
            if str(key) != record.structural_key:
                raise ValueError("Object registry key does not match structural_key.")
            records[str(key)] = record
        object_ids = [record.object_id for record in records.values()]
        if len(set(object_ids)) != len(object_ids):
            raise ValueError("Object registry object IDs must be unique.")
        return cls(records=records)


@dataclass
class CanvasDataPointSelection:
    target_object_id: str
    x: float
    y: float
    graph_x: float
    graph_y: float
    x_label: str = "x"
    y_label: str = "y"
    index: str | None = None
    display_type: tuple[str, str] = ("numeric", "numeric")

    def __post_init__(self) -> None:
        self.target_object_id = _required_text(
            self.target_object_id, "data_point.target_object_id"
        )
        values = (self.x, self.y, self.graph_x, self.graph_y)
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("Canvas data-point coordinates must be finite numbers.")
        self.x = float(self.x)
        self.y = float(self.y)
        self.graph_x = float(self.graph_x)
        self.graph_y = float(self.graph_y)
        self.x_label = _required_text(self.x_label, "data_point.x_label")
        self.y_label = _required_text(self.y_label, "data_point.y_label")
        if self.index is not None:
            self.index = _required_text(self.index, "data_point.index")
        if (
            not isinstance(self.display_type, tuple)
            or len(self.display_type) != 2
            or not all(isinstance(item, str) and item for item in self.display_type)
        ):
            raise ValueError("data_point.display_type must contain two strings.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_object_id": self.target_object_id,
            "x": self.x,
            "y": self.y,
            "graph_x": self.graph_x,
            "graph_y": self.graph_y,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "index": self.index,
            "display_type": list(self.display_type),
        }

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any] | None
    ) -> CanvasDataPointSelection | None:
        if payload is None:
            return None
        value = require_json_object(payload, label="selection.data_point")
        reject_unknown_keys(
            value,
            {
                "target_object_id",
                "x",
                "y",
                "graph_x",
                "graph_y",
                "x_label",
                "y_label",
                "index",
                "display_type",
            },
            label="selection.data_point",
        )
        raw_display = require_json_list(
            value.get("display_type", ["numeric", "numeric"]),
            label="selection.data_point.display_type",
        )
        if len(raw_display) != 2 or not all(
            isinstance(item, str) and item for item in raw_display
        ):
            raise ValueError(
                "selection.data_point.display_type must contain two strings."
            )

        def number(key: str) -> float:
            raw = value.get(key)
            if (
                not isinstance(raw, (int, float))
                or isinstance(raw, bool)
                or not math.isfinite(float(raw))
            ):
                raise ValueError(f"selection.data_point.{key} must be finite.")
            return float(raw)

        raw_index = value.get("index")
        if raw_index is not None and not isinstance(raw_index, str):
            raise ValueError("selection.data_point.index must be a string or null.")
        return cls(
            target_object_id=_required_text(
                value.get("target_object_id"),
                "selection.data_point.target_object_id",
            ),
            x=number("x"),
            y=number("y"),
            graph_x=number("graph_x"),
            graph_y=number("graph_y"),
            x_label=_required_text(
                value.get("x_label", "x"), "selection.data_point.x_label"
            ),
            y_label=_required_text(
                value.get("y_label", "y"), "selection.data_point.y_label"
            ),
            index=raw_index or None,
            display_type=(str(raw_display[0]), str(raw_display[1])),
        )


@dataclass
class CanvasSelection:
    object_ids: list[str] = field(default_factory=list)
    primary_object_id: str | None = None
    data_point: CanvasDataPointSelection | None = None

    def __post_init__(self) -> None:
        self.object_ids = [
            _required_text(object_id, "selection object_id")
            for object_id in self.object_ids
        ]
        if len(set(self.object_ids)) != len(self.object_ids):
            raise ValueError("CanvasSelection object_ids must be unique.")
        if self.primary_object_id and self.primary_object_id not in self.object_ids:
            raise ValueError("primary_object_id must be included in object_ids.")
        if (
            self.data_point is not None
            and self.data_point.target_object_id not in self.object_ids
        ):
            raise ValueError(
                "data_point target_object_id must be included in object_ids."
            )
        if (
            self.data_point is not None
            and self.primary_object_id != self.data_point.target_object_id
        ):
            raise ValueError(
                "data_point target_object_id must be the primary_object_id."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_ids": list(self.object_ids),
            "primary_object_id": self.primary_object_id,
            "data_point": self.data_point.to_dict() if self.data_point else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> CanvasSelection:
        if payload is None:
            return cls()
        payload = require_json_object(payload, label="selection")
        reject_unknown_keys(
            payload,
            {"object_ids", "primary_object_id", "data_point"},
            label="selection",
        )
        raw_ids = require_json_list(
            payload.get("object_ids", []), label="selection.object_ids"
        )
        ids = [_required_text(item, "selection object_id") for item in raw_ids]
        primary = payload.get("primary_object_id")
        if primary is not None and not isinstance(primary, str):
            raise ValueError("selection.primary_object_id must be a string or null.")
        return cls(
            object_ids=ids,
            primary_object_id=primary or None,
            data_point=CanvasDataPointSelection.from_dict(
                payload.get("data_point")
            ),
        )


@dataclass
class CanvasViewport:
    zoom: float = 1.0
    center_x: float = 0.5
    center_y: float = 0.5

    def __post_init__(self) -> None:
        values = (self.zoom, self.center_x, self.center_y)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("CanvasViewport values must be finite.")
        if self.zoom <= 0:
            raise ValueError("CanvasViewport zoom must be positive.")
        if not 0.0 <= self.center_x <= 1.0 or not 0.0 <= self.center_y <= 1.0:
            raise ValueError("CanvasViewport center coordinates must be normalized.")

    def to_dict(self) -> dict[str, float]:
        return {
            "zoom": float(self.zoom),
            "center_x": float(self.center_x),
            "center_y": float(self.center_y),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> CanvasViewport:
        if payload is None:
            return cls()
        value = require_json_object(payload, label="viewport")
        reject_unknown_keys(
            value,
            {"zoom", "center_x", "center_y"},
            label="viewport",
        )
        return cls(
            zoom=require_json_number(value.get("zoom", 1.0), label="viewport.zoom"),
            center_x=require_json_number(
                value.get("center_x", 0.5), label="viewport.center_x"
            ),
            center_y=require_json_number(
                value.get("center_y", 0.5), label="viewport.center_y"
            ),
        )


@dataclass
class CanvasInterfaceState:
    """Document-local workbench preferences that do not alter visual authority."""

    inspector_visible: bool = True
    inspector_width: int = 340
    high_contrast: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.inspector_visible, bool):
            raise ValueError("inspector_visible must be a boolean.")
        if not isinstance(self.inspector_width, int) or isinstance(
            self.inspector_width, bool
        ):
            raise ValueError("inspector_width must be an integer.")
        if not 280 <= self.inspector_width <= 720:
            raise ValueError("inspector_width must be between 280 and 720 pixels.")
        if not isinstance(self.high_contrast, bool):
            raise ValueError("high_contrast must be a boolean.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspector_visible": self.inspector_visible,
            "inspector_width": self.inspector_width,
            "high_contrast": self.high_contrast,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> CanvasInterfaceState:
        if payload is None:
            return cls()
        value = require_json_object(payload, label="interface")
        reject_unknown_keys(
            value,
            {"inspector_visible", "inspector_width", "high_contrast"},
            label="interface",
        )
        return cls(
            inspector_visible=require_json_bool(
                value.get("inspector_visible", True),
                label="interface.inspector_visible",
            ),
            inspector_width=require_json_int(
                value.get("inspector_width", 340),
                label="interface.inspector_width",
            ),
            high_contrast=require_json_bool(
                value.get("high_contrast", False),
                label="interface.high_contrast",
            ),
        )


@dataclass
class CanvasTransaction:
    transaction_id: str
    provider: str
    base_revision: int
    status: str = "active"
    snapshot_path: str | None = None
    snapshot_sha256: str | None = None
    review_snapshot_path: str | None = None
    review_snapshot_sha256: str | None = None
    baseline_render_sha256: str | None = None
    baseline_saved_revision: int | None = None
    baseline_exported_revision: int | None = None
    baseline_state: str | None = None
    baseline_document_sha256: str | None = None
    baseline_qa_summary: dict[str, Any] = field(default_factory=dict)
    baseline_structural_qa_summary: dict[str, Any] = field(default_factory=dict)
    baseline_page: int = 0
    baseline_viewport: dict[str, Any] = field(
        default_factory=lambda: CanvasViewport().to_dict()
    )
    current_revision: int | None = None
    rationale: str = ""
    request_record: dict[str, Any] | None = None
    pending_batch: dict[str, Any] | None = None
    pending_preview: dict[str, Any] | None = None
    applying_batch_id: str | None = None
    accepted_batch_ids: list[str] = field(default_factory=list)
    accepted_revisions: list[int] = field(default_factory=list)
    undone_batch_ids: list[str] = field(default_factory=list)
    rejected_batch_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.transaction_id = _required_text(self.transaction_id, "transaction_id")
        self.provider = _required_text(self.provider, "provider")
        if isinstance(self.base_revision, bool) or not isinstance(
            self.base_revision, int
        ):
            raise ValueError("CanvasTransaction base_revision must be an integer.")
        if self.base_revision < 0:
            raise ValueError("CanvasTransaction base_revision must be non-negative.")
        if self.status not in CANVAS_TRANSACTION_STATES:
            raise ValueError(f"Unsupported CanvasTransaction state: {self.status!r}")
        if self.snapshot_path is not None:
            self.snapshot_path = _required_text(
                self.snapshot_path, "transaction snapshot_path"
            )
        self.snapshot_sha256 = _optional_sha256(
            self.snapshot_sha256, "transaction snapshot_sha256"
        )
        if self.review_snapshot_path is not None:
            self.review_snapshot_path = _required_text(
                self.review_snapshot_path, "transaction review_snapshot_path"
            )
        self.review_snapshot_sha256 = _optional_sha256(
            self.review_snapshot_sha256,
            "transaction review_snapshot_sha256",
        )
        self.baseline_render_sha256 = _optional_sha256(
            self.baseline_render_sha256,
            "transaction baseline_render_sha256",
        )
        self.baseline_document_sha256 = _optional_sha256(
            self.baseline_document_sha256,
            "transaction baseline_document_sha256",
        )
        if self.baseline_saved_revision is None:
            self.baseline_saved_revision = self.base_revision
        if (
            isinstance(self.baseline_saved_revision, bool)
            or not isinstance(self.baseline_saved_revision, int)
            or not 0 <= self.baseline_saved_revision <= self.base_revision
        ):
            raise ValueError(
                "transaction baseline_saved_revision must be between zero "
                "and base_revision."
            )
        if self.baseline_exported_revision is not None and (
            isinstance(self.baseline_exported_revision, bool)
            or not isinstance(self.baseline_exported_revision, int)
            or not 0 <= self.baseline_exported_revision <= self.base_revision
        ):
            raise ValueError(
                "transaction baseline_exported_revision must be between zero "
                "and base_revision."
            )
        if self.baseline_state is not None and self.baseline_state not in (
            CANVAS_SESSION_STATES
        ):
            raise ValueError(
                f"Unsupported transaction baseline state: {self.baseline_state!r}"
            )
        if not isinstance(self.baseline_qa_summary, dict):
            raise ValueError("transaction baseline_qa_summary must be an object.")
        if not isinstance(self.baseline_structural_qa_summary, dict):
            raise ValueError(
                "transaction baseline_structural_qa_summary must be an object."
            )
        _validate_json_tree(
            self.baseline_qa_summary,
            path="transaction.baseline_qa_summary",
        )
        _validate_json_tree(
            self.baseline_structural_qa_summary,
            path="transaction.baseline_structural_qa_summary",
        )
        if isinstance(self.baseline_page, bool) or not isinstance(
            self.baseline_page, int
        ):
            raise ValueError("transaction baseline_page must be an integer.")
        if self.baseline_page < 0:
            raise ValueError("transaction baseline_page must be non-negative.")
        if not isinstance(self.baseline_viewport, dict):
            raise ValueError("transaction baseline_viewport must be an object.")
        self.baseline_viewport = CanvasViewport.from_dict(
            self.baseline_viewport
        ).to_dict()
        if self.current_revision is None:
            self.current_revision = self.base_revision
        if (
            isinstance(self.current_revision, bool)
            or not isinstance(self.current_revision, int)
            or self.current_revision < self.base_revision
        ):
            raise ValueError(
                "transaction current_revision cannot precede base_revision."
            )
        self.rationale = str(self.rationale or "").strip()
        restored_request_record = None
        if self.request_record is not None:
            if not isinstance(self.request_record, dict):
                raise ValueError("transaction request_record must be an object.")
            from sciplot_core.canvas.provider import AssistantRequestRecord

            restored_request_record = AssistantRequestRecord.from_dict(
                self.request_record
            )
            request = restored_request_record.parsed_request
            if request.transaction_id != self.transaction_id:
                raise ValueError(
                    "transaction request_record transaction_id must match the "
                    "Canvas transaction."
                )
            if request.provider_id != self.provider:
                raise ValueError(
                    "transaction request_record provider must match the Canvas "
                    "transaction."
                )
            if not self.base_revision <= request.base_revision <= int(
                self.current_revision
            ):
                raise ValueError(
                    "transaction request_record revision must remain inside the "
                    "Canvas transaction revision range."
                )
            self.request_record = restored_request_record.to_dict()
        restored_batch = None
        if self.pending_batch is not None:
            if not isinstance(self.pending_batch, dict):
                raise ValueError("transaction pending_batch must be an object.")
            from sciplot_core.canvas.operations import CanvasOperationBatch

            restored_batch = CanvasOperationBatch.from_dict(self.pending_batch)
            self.pending_batch = restored_batch.to_dict()
            if restored_batch.provider != self.provider:
                raise ValueError(
                    "transaction pending batch provider must match the "
                    "transaction provider."
                )
            if restored_batch.base_revision != self.current_revision:
                raise ValueError(
                    "transaction pending batch must target current_revision."
                )
        if (self.pending_batch is None) != (self.pending_preview is None):
            raise ValueError(
                "transaction pending batch and preview must be stored together."
            )
        if restored_batch is not None and self.pending_preview is not None:
            self.pending_preview = self._normalize_pending_preview(
                restored_batch,
                self.pending_preview,
            )
        if restored_request_record is not None:
            response = restored_request_record.parsed_response
            if (
                response is not None
                and response.proposal_kind == "canvas_operation_batch"
            ):
                from sciplot_core.canvas.operations import CanvasOperationBatch

                response_batch = CanvasOperationBatch.from_dict(
                    dict(response.proposal or {})
                )
                if restored_request_record.status == "proposal_ready":
                    if restored_batch is None:
                        raise ValueError(
                            "A proposal-ready Assistant request must persist its "
                            "CanvasOperationBatch and preview."
                        )
                    if response_batch.batch_id != restored_batch.batch_id:
                        raise ValueError(
                            "Assistant request response does not match the pending "
                            "Canvas batch."
                        )
                elif restored_request_record.status == "applied":
                    if response_batch.batch_id not in self.accepted_batch_ids:
                        raise ValueError(
                            "Applied Assistant request response is absent from the "
                            "accepted batch ledger."
                        )
                elif restored_request_record.status == "rejected":
                    if response_batch.batch_id not in self.rejected_batch_ids:
                        raise ValueError(
                            "Rejected Assistant request response is absent from the "
                            "rejected batch ledger."
                        )
        if self.applying_batch_id is not None:
            self.applying_batch_id = _required_text(
                self.applying_batch_id,
                "transaction applying_batch_id",
            )
            if (
                self.pending_batch is None
                or self.pending_batch.get("batch_id") != self.applying_batch_id
            ):
                raise ValueError(
                    "transaction applying_batch_id must reference the pending batch."
                )
        for label, values in (
            ("accepted_batch_ids", self.accepted_batch_ids),
            ("undone_batch_ids", self.undone_batch_ids),
            ("rejected_batch_ids", self.rejected_batch_ids),
        ):
            if not isinstance(values, list):
                raise ValueError(f"transaction {label} must be a list.")
            normalized = [_required_text(value, f"transaction {label}") for value in values]
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"transaction {label} must be unique.")
            setattr(self, label, normalized)
        if not isinstance(self.accepted_revisions, list) or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in self.accepted_revisions
        ):
            raise ValueError("transaction accepted_revisions must contain integers.")
        if len(self.accepted_revisions) != len(self.accepted_batch_ids):
            raise ValueError(
                "transaction accepted batch IDs and revisions must align."
            )
        if any(
            revision <= self.base_revision
            for revision in self.accepted_revisions
        ) or any(
            later <= earlier
            for earlier, later in zip(
                self.accepted_revisions,
                self.accepted_revisions[1:],
            )
        ):
            raise ValueError(
                "transaction accepted revisions must increase after base_revision."
            )
        if not set(self.undone_batch_ids) <= set(self.accepted_batch_ids):
            raise ValueError(
                "transaction undone batches must have been accepted first."
            )
        if set(self.accepted_batch_ids) & set(self.rejected_batch_ids):
            raise ValueError(
                "transaction batch IDs cannot be both accepted and rejected."
            )
        if self.pending_batch_id in (
            set(self.accepted_batch_ids) | set(self.rejected_batch_ids)
        ):
            raise ValueError(
                "transaction pending batch cannot already be accepted or rejected."
            )
        if (
            self.accepted_revisions
            and int(self.current_revision) < self.accepted_revisions[-1]
        ):
            raise ValueError(
                "transaction current_revision cannot precede an accepted revision."
            )
        if self.status in {"committed", "rejected", "rolled_back"} and (
            self.pending_batch is not None or self.applying_batch_id is not None
        ):
            raise ValueError(
                "terminal transactions cannot retain a pending or applying batch."
            )
        self.created_at = _required_text(self.created_at, "transaction created_at")
        self.updated_at = _required_text(self.updated_at, "transaction updated_at")

    @property
    def pending_batch_id(self) -> str | None:
        if self.pending_batch is None:
            return None
        return str(self.pending_batch["batch_id"])

    @staticmethod
    def _normalize_pending_preview(
        batch: Any,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        value = require_json_object(
            preview,
            label="transaction.pending_preview",
        )
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "batch_id",
                "base_revision",
                "provider",
                "rationale",
                "operation_count",
                "affected_target_ids",
                "changes",
                "render_before",
                "publication_document_changed",
            },
            label="transaction.pending_preview",
        )
        if value.get("kind") != "sciplot_canvas_operation_preview":
            raise ValueError("transaction pending preview kind is invalid.")
        version = require_json_int(
            value.get("version", 0),
            label="transaction.pending_preview.version",
        )
        if version != 1:
            raise ValueError(
                f"Unsupported transaction pending preview version: {version!r}"
            )
        batch_id = _required_text(
            value.get("batch_id"),
            "transaction pending preview batch_id",
        )
        base_revision = require_json_int(
            value.get("base_revision"),
            label="transaction.pending_preview.base_revision",
        )
        provider = _required_text(
            value.get("provider"),
            "transaction pending preview provider",
        )
        rationale = _required_text(
            value.get("rationale"),
            "transaction pending preview rationale",
        )
        operation_count = require_json_int(
            value.get("operation_count"),
            label="transaction.pending_preview.operation_count",
        )
        target_ids = require_json_list(
            value.get("affected_target_ids"),
            label="transaction.pending_preview.affected_target_ids",
        )
        normalized_target_ids = [
            _required_text(
                target_id,
                "transaction pending preview affected_target_id",
            )
            for target_id in target_ids
        ]
        if len(set(normalized_target_ids)) != len(normalized_target_ids):
            raise ValueError(
                "transaction pending preview target IDs must be unique."
            )
        changes = require_json_list(
            value.get("changes"),
            label="transaction.pending_preview.changes",
        )
        if not all(isinstance(change, dict) for change in changes):
            raise ValueError(
                "transaction pending preview changes must contain objects."
            )
        _validate_json_tree(
            changes,
            path="transaction.pending_preview.changes",
        )
        render_before = _optional_sha256(
            str(value.get("render_before") or "") or None,
            "transaction pending preview render_before",
        )
        if render_before is None:
            raise ValueError(
                "transaction pending preview requires a render_before hash."
            )
        publication_changed = require_json_bool(
            value.get("publication_document_changed"),
            label=(
                "transaction.pending_preview.publication_document_changed"
            ),
        )
        if publication_changed:
            raise ValueError(
                "transaction pending preview cannot claim a document mutation."
            )
        if (
            batch_id != batch.batch_id
            or base_revision != batch.base_revision
            or provider != batch.provider
            or rationale != batch.rationale
            or operation_count != len(batch.operations)
            or len(changes) != len(batch.operations)
        ):
            raise ValueError(
                "transaction pending preview does not describe its pending batch."
            )
        expected_target_ids = list(
            dict.fromkeys(operation.target_id for operation in batch.operations)
        )
        if normalized_target_ids != expected_target_ids:
            raise ValueError(
                "transaction pending preview target list does not match its batch."
            )
        for operation, change in zip(batch.operations, changes):
            if (
                change.get("operation_type") != operation.operation_type
                or change.get("operation_id") != operation.operation_id
                or change.get("target_id") != operation.target_id
            ):
                raise ValueError(
                    "transaction pending preview change identity does not "
                    "match its operation."
                )
            if operation.operation_type == "set_setting":
                if (
                    change.get("setting_path")
                    != operation.arguments["setting_path"]
                    or change.get("value") != operation.arguments["value"]
                ):
                    raise ValueError(
                        "transaction pending preview setting change does not "
                        "match its operation."
                    )
                if (
                    "expected_value" in operation.arguments
                    and change.get("old_value")
                    != operation.arguments.get("expected_value")
                ):
                    raise ValueError(
                        "transaction pending preview before value does not "
                        "match its operation precondition."
                    )
                continue
            if operation.operation_type == "add_widget" and (
                change.get("widget_type")
                != operation.arguments["widget_type"]
                or change.get("name") != operation.arguments["name"]
                or change.get("index", -1)
                != operation.arguments.get("index", -1)
                or change.get("settings") != operation.arguments["settings"]
            ):
                raise ValueError(
                    "transaction pending preview widget change does not "
                    "match its operation."
                )
        return {
            **value,
            "version": version,
            "batch_id": batch_id,
            "base_revision": base_revision,
            "provider": provider,
            "rationale": rationale,
            "operation_count": operation_count,
            "affected_target_ids": normalized_target_ids,
            "changes": [dict(change) for change in changes],
            "render_before": render_before,
            "publication_document_changed": False,
        }

    @property
    def active_batch_ids(self) -> list[str]:
        undone = set(self.undone_batch_ids)
        return [
            batch_id
            for batch_id in self.accepted_batch_ids
            if batch_id not in undone
        ]

    @property
    def baseline_complete(self) -> bool:
        return bool(
            self.snapshot_path
            and self.snapshot_sha256
            and self.review_snapshot_path
            and self.review_snapshot_sha256
            and self.baseline_render_sha256
            and self.baseline_state
        )

    def set_pending_batch(
        self,
        batch: Any,
        preview: dict[str, Any],
    ) -> None:
        from sciplot_core.canvas.operations import CanvasOperationBatch

        if self.status != "active":
            raise ValueError("Only an active transaction can accept a proposal.")
        if self.pending_batch is not None or self.applying_batch_id is not None:
            raise ValueError(
                "Resolve the current transaction proposal before adding another."
            )
        restored = CanvasOperationBatch.from_dict(batch.to_dict())
        if restored.provider != self.provider:
            raise ValueError(
                "CanvasOperationBatch provider must match the transaction provider."
            )
        if restored.base_revision != self.current_revision:
            raise ValueError(
                "CanvasOperationBatch base_revision is stale for this transaction."
            )
        if not str(restored.rationale).strip():
            raise ValueError(
                "Assistant CanvasOperationBatch requires an auditable rationale."
            )
        normalized_preview = self._normalize_pending_preview(
            restored,
            preview,
        )
        self.pending_batch = restored.to_dict()
        self.pending_preview = normalized_preview
        self.updated_at = _now()

    def begin_applying(self) -> str:
        if self.status != "active":
            raise ValueError("Resume the transaction before accepting a proposal.")
        batch_id = self.pending_batch_id
        if batch_id is None:
            raise ValueError("The transaction has no pending proposal.")
        if self.applying_batch_id is not None:
            raise ValueError("The transaction is already applying a proposal.")
        self.applying_batch_id = batch_id
        self.updated_at = _now()
        return batch_id

    def record_applied(self, *, batch_id: str, revision: int) -> None:
        if self.applying_batch_id != batch_id or self.pending_batch_id != batch_id:
            raise ValueError("Applied batch does not match the transaction proposal.")
        if revision <= int(self.current_revision):
            raise ValueError("Applied transaction revision must increase.")
        if batch_id in self.accepted_batch_ids:
            raise ValueError("The transaction batch was already accepted.")
        self.accepted_batch_ids.append(batch_id)
        self.accepted_revisions.append(revision)
        self.current_revision = revision
        request_record = self.parsed_request_record
        if request_record is not None and request_record.status == "proposal_ready":
            response = request_record.parsed_response
            if (
                response is not None
                and response.proposal_kind == "canvas_operation_batch"
                and str((response.proposal or {}).get("batch_id")) == batch_id
            ):
                request_record.mark_proposal_outcome(accepted=True)
                self.set_request_record(request_record)
        self.pending_batch = None
        self.pending_preview = None
        self.applying_batch_id = None
        self.updated_at = _now()

    def reject_pending(self) -> str:
        if self.status not in {"active", "paused"}:
            raise ValueError("The transaction cannot reject a proposal now.")
        batch_id = self.pending_batch_id
        if batch_id is None:
            raise ValueError("The transaction has no pending proposal.")
        if self.applying_batch_id is not None:
            raise ValueError("An applying proposal cannot be rejected.")
        self.rejected_batch_ids.append(batch_id)
        request_record = self.parsed_request_record
        if request_record is not None and request_record.status == "proposal_ready":
            response = request_record.parsed_response
            if (
                response is not None
                and response.proposal_kind == "canvas_operation_batch"
                and str((response.proposal or {}).get("batch_id")) == batch_id
            ):
                request_record.mark_proposal_outcome(accepted=False)
                self.set_request_record(request_record)
        self.pending_batch = None
        self.pending_preview = None
        self.updated_at = _now()
        return batch_id

    def record_undo(self, *, batch_id: str, revision: int) -> None:
        active = self.active_batch_ids
        if not active or active[-1] != batch_id:
            raise ValueError(
                "Only the most recent active transaction batch can be undone."
            )
        if revision <= int(self.current_revision):
            raise ValueError("Transaction undo revision must increase.")
        self.undone_batch_ids.append(batch_id)
        self.current_revision = revision
        self.updated_at = _now()

    def set_paused(self, paused: bool) -> None:
        if self.status not in {"active", "paused"}:
            raise ValueError("The transaction can no longer be paused or resumed.")
        if self.applying_batch_id is not None:
            raise ValueError("An applying proposal cannot be paused.")
        self.status = "paused" if paused else "active"
        self.updated_at = _now()

    @property
    def parsed_request_record(self) -> Any | None:
        if self.request_record is None:
            return None
        from sciplot_core.canvas.provider import AssistantRequestRecord

        return AssistantRequestRecord.from_dict(self.request_record)

    def set_request_record(self, record: Any | None) -> None:
        if record is None:
            self.request_record = None
            self.updated_at = _now()
            return
        from sciplot_core.canvas.provider import AssistantRequestRecord

        restored = AssistantRequestRecord.from_dict(record.to_dict())
        request = restored.parsed_request
        if request.transaction_id != self.transaction_id:
            raise ValueError(
                "Assistant request transaction_id must match the Canvas transaction."
            )
        if request.provider_id != self.provider:
            raise ValueError(
                "Assistant request provider must match the Canvas transaction."
            )
        if not self.base_revision <= request.base_revision <= int(
            self.current_revision
        ):
            raise ValueError(
                "Assistant request revision must remain inside the Canvas "
                "transaction revision range."
            )
        self.request_record = restored.to_dict()
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "provider": self.provider,
            "base_revision": self.base_revision,
            "status": self.status,
            "snapshot_path": self.snapshot_path,
            "snapshot_sha256": self.snapshot_sha256,
            "review_snapshot_path": self.review_snapshot_path,
            "review_snapshot_sha256": self.review_snapshot_sha256,
            "baseline_render_sha256": self.baseline_render_sha256,
            "baseline_saved_revision": self.baseline_saved_revision,
            "baseline_exported_revision": self.baseline_exported_revision,
            "baseline_state": self.baseline_state,
            "baseline_document_sha256": self.baseline_document_sha256,
            "baseline_qa_summary": copy.deepcopy(self.baseline_qa_summary),
            "baseline_structural_qa_summary": copy.deepcopy(
                self.baseline_structural_qa_summary
            ),
            "baseline_page": self.baseline_page,
            "baseline_viewport": copy.deepcopy(self.baseline_viewport),
            "current_revision": self.current_revision,
            "rationale": self.rationale,
            "request_record": (
                copy.deepcopy(self.request_record)
                if self.request_record is not None
                else None
            ),
            "pending_batch": (
                copy.deepcopy(self.pending_batch)
                if self.pending_batch is not None
                else None
            ),
            "pending_preview": (
                copy.deepcopy(self.pending_preview)
                if self.pending_preview is not None
                else None
            ),
            "applying_batch_id": self.applying_batch_id,
            "accepted_batch_ids": list(self.accepted_batch_ids),
            "accepted_revisions": list(self.accepted_revisions),
            "undone_batch_ids": list(self.undone_batch_ids),
            "rejected_batch_ids": list(self.rejected_batch_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> CanvasTransaction | None:
        if payload is None:
            return None
        payload = require_json_object(payload, label="active_transaction")
        reject_unknown_keys(
            payload,
            {
                "transaction_id",
                "provider",
                "base_revision",
                "status",
                "snapshot_path",
                "snapshot_sha256",
                "review_snapshot_path",
                "review_snapshot_sha256",
                "baseline_render_sha256",
                "baseline_saved_revision",
                "baseline_exported_revision",
                "baseline_state",
                "baseline_document_sha256",
                "baseline_qa_summary",
                "baseline_structural_qa_summary",
                "baseline_page",
                "baseline_viewport",
                "current_revision",
                "rationale",
                "request_record",
                "pending_batch",
                "pending_preview",
                "applying_batch_id",
                "accepted_batch_ids",
                "accepted_revisions",
                "undone_batch_ids",
                "rejected_batch_ids",
                "created_at",
                "updated_at",
            },
            label="active_transaction",
        )
        pending_batch = payload.get("pending_batch")
        if pending_batch is not None and not isinstance(pending_batch, dict):
            raise ValueError("active_transaction.pending_batch must be an object.")
        pending_preview = payload.get("pending_preview")
        if pending_preview is not None and not isinstance(pending_preview, dict):
            raise ValueError("active_transaction.pending_preview must be an object.")
        request_record = payload.get("request_record")
        if request_record is not None and not isinstance(request_record, dict):
            raise ValueError("active_transaction.request_record must be an object.")
        baseline_qa_summary = require_json_object(
            payload.get("baseline_qa_summary", {}),
            label="active_transaction.baseline_qa_summary",
        )
        baseline_structural_qa_summary = require_json_object(
            payload.get("baseline_structural_qa_summary", {}),
            label="active_transaction.baseline_structural_qa_summary",
        )
        baseline_viewport = require_json_object(
            payload.get("baseline_viewport", {}),
            label="active_transaction.baseline_viewport",
        )
        return cls(
            transaction_id=_required_text(
                payload.get("transaction_id"), "transaction_id"
            ),
            provider=_required_text(payload.get("provider"), "provider"),
            base_revision=require_json_int(
                payload.get("base_revision", 0),
                label="active_transaction.base_revision",
            ),
            status=str(payload.get("status") or "active"),
            snapshot_path=str(payload["snapshot_path"])
            if payload.get("snapshot_path")
            else None,
            snapshot_sha256=(
                str(payload["snapshot_sha256"])
                if payload.get("snapshot_sha256")
                else None
            ),
            review_snapshot_path=(
                str(payload["review_snapshot_path"])
                if payload.get("review_snapshot_path")
                else None
            ),
            review_snapshot_sha256=(
                str(payload["review_snapshot_sha256"])
                if payload.get("review_snapshot_sha256")
                else None
            ),
            baseline_render_sha256=(
                str(payload["baseline_render_sha256"])
                if payload.get("baseline_render_sha256")
                else None
            ),
            baseline_saved_revision=require_json_int(
                payload.get(
                    "baseline_saved_revision",
                    payload.get("base_revision", 0),
                ),
                label="active_transaction.baseline_saved_revision",
            ),
            baseline_exported_revision=(
                require_json_int(
                    payload["baseline_exported_revision"],
                    label="active_transaction.baseline_exported_revision",
                )
                if payload.get("baseline_exported_revision") is not None
                else None
            ),
            baseline_state=(
                str(payload["baseline_state"])
                if payload.get("baseline_state")
                else None
            ),
            baseline_document_sha256=(
                str(payload["baseline_document_sha256"])
                if payload.get("baseline_document_sha256")
                else None
            ),
            baseline_qa_summary=dict(baseline_qa_summary),
            baseline_structural_qa_summary=dict(
                baseline_structural_qa_summary
            ),
            baseline_page=require_json_int(
                payload.get("baseline_page", 0),
                label="active_transaction.baseline_page",
            ),
            baseline_viewport=dict(baseline_viewport),
            current_revision=require_json_int(
                payload.get("current_revision", payload.get("base_revision", 0)),
                label="active_transaction.current_revision",
            ),
            rationale=str(payload.get("rationale") or ""),
            request_record=(
                dict(request_record) if request_record is not None else None
            ),
            pending_batch=dict(pending_batch) if pending_batch is not None else None,
            pending_preview=(
                dict(pending_preview) if pending_preview is not None else None
            ),
            applying_batch_id=(
                str(payload["applying_batch_id"])
                if payload.get("applying_batch_id")
                else None
            ),
            accepted_batch_ids=[
                _required_text(item, "active_transaction.accepted_batch_id")
                for item in require_json_list(
                    payload.get("accepted_batch_ids", []),
                    label="active_transaction.accepted_batch_ids",
                )
            ],
            accepted_revisions=[
                require_json_int(
                    item,
                    label="active_transaction.accepted_revision",
                )
                for item in require_json_list(
                    payload.get("accepted_revisions", []),
                    label="active_transaction.accepted_revisions",
                )
            ],
            undone_batch_ids=[
                _required_text(item, "active_transaction.undone_batch_id")
                for item in require_json_list(
                    payload.get("undone_batch_ids", []),
                    label="active_transaction.undone_batch_ids",
                )
            ],
            rejected_batch_ids=[
                _required_text(item, "active_transaction.rejected_batch_id")
                for item in require_json_list(
                    payload.get("rejected_batch_ids", []),
                    label="active_transaction.rejected_batch_ids",
                )
            ],
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or payload.get("created_at") or _now()),
        )


@dataclass
class CanvasSession:
    project_id: str
    document_id: str
    document_path: str
    session_id: str = field(default_factory=lambda: str(uuid4()))
    state: str = "preparing"
    revision: int = 0
    current_page: int = 0
    selection: CanvasSelection = field(default_factory=CanvasSelection)
    viewport: CanvasViewport = field(default_factory=CanvasViewport)
    interface: CanvasInterfaceState = field(default_factory=CanvasInterfaceState)
    active_inspector: str | None = None
    active_transaction: CanvasTransaction | None = None
    saved_revision: int = 0
    exported_revision: int | None = None
    document_sha256: str | None = None
    last_render_sha256: str | None = None
    review_annotation_ids: list[str] = field(default_factory=list)
    structural_qa_summary: dict[str, Any] = field(default_factory=dict)
    qa_summary: dict[str, Any] = field(default_factory=dict)
    journal_outbox: list[dict[str, Any]] = field(default_factory=list)
    recovery_snapshots: list[str] = field(default_factory=list)
    recovery_snapshot_hashes: dict[str, str] = field(default_factory=dict)
    object_registry: ObjectIdentityRegistry = field(
        default_factory=ObjectIdentityRegistry
    )
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.session_id = _required_text(self.session_id, "session_id")
        self.project_id = _required_text(self.project_id, "project_id")
        self.document_id = _required_text(self.document_id, "document_id")
        self.document_path = _required_text(self.document_path, "document_path")
        self.document_sha256 = _optional_sha256(self.document_sha256, "document_sha256")
        self.last_render_sha256 = _optional_sha256(
            self.last_render_sha256, "last_render_sha256"
        )
        if self.state not in CANVAS_SESSION_STATES:
            raise ValueError(f"Unsupported CanvasSession state: {self.state!r}")
        if self.revision < 0:
            raise ValueError("revision must be non-negative.")
        if self.current_page < 0:
            raise ValueError("current_page must be non-negative.")
        if self.saved_revision < 0 or self.saved_revision > self.revision:
            raise ValueError("saved_revision must be between zero and revision.")
        if (
            self.exported_revision is not None
            and not 0 <= self.exported_revision <= self.revision
        ):
            raise ValueError("exported_revision must be between zero and revision.")
        if len(set(self.review_annotation_ids)) != len(self.review_annotation_ids):
            raise ValueError("review_annotation_ids must be unique.")
        if not isinstance(self.structural_qa_summary, dict):
            raise ValueError("structural_qa_summary must be an object.")
        if not isinstance(self.qa_summary, dict):
            raise ValueError("qa_summary must be an object.")
        if not isinstance(self.journal_outbox, list) or not all(
            isinstance(entry, dict) for entry in self.journal_outbox
        ):
            raise ValueError("journal_outbox must contain JSON objects.")
        event_ids: list[str] = []
        for index, entry in enumerate(self.journal_outbox):
            _validate_json_tree(entry, path=f"journal_outbox[{index}]")
            event_ids.append(
                _required_text(
                    entry.get("event_id"),
                    f"journal_outbox[{index}].event_id",
                )
            )
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("journal_outbox event IDs must be unique.")
        if not isinstance(self.recovery_snapshot_hashes, dict):
            raise ValueError("recovery_snapshot_hashes must be an object.")
        for reference, digest in self.recovery_snapshot_hashes.items():
            if reference not in self.recovery_snapshots:
                raise ValueError(
                    "Recovery snapshot hash refers to an unknown snapshot."
                )
            _optional_sha256(digest, f"recovery_snapshot_hashes[{reference!r}]")

    @property
    def dirty(self) -> bool:
        return self.revision != self.saved_revision

    def set_state(self, state: str) -> None:
        if state not in CANVAS_SESSION_STATES:
            raise ValueError(f"Unsupported CanvasSession state: {state!r}")
        self.state = state
        self.updated_at = _now()

    def advance_revision(self, *, state: str = "editing") -> int:
        self.revision += 1
        self.set_state(state)
        return self.revision

    def mark_saved(self, *, document_sha256: str) -> None:
        self.saved_revision = self.revision
        self.document_sha256 = _optional_sha256(document_sha256, "document_sha256")
        self.updated_at = _now()

    def mark_exported(self) -> None:
        if self.dirty:
            raise ValueError("Cannot mark an unsaved CanvasSession as exported.")
        self.exported_revision = self.revision
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": CANVAS_SESSION_KIND,
            "version": CANVAS_SESSION_VERSION,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "document_id": self.document_id,
            "document_path": self.document_path,
            "state": self.state,
            "revision": self.revision,
            "current_page": self.current_page,
            "selection": self.selection.to_dict(),
            "viewport": self.viewport.to_dict(),
            "interface": self.interface.to_dict(),
            "active_inspector": self.active_inspector,
            "active_transaction": (
                self.active_transaction.to_dict() if self.active_transaction else None
            ),
            "saved_revision": self.saved_revision,
            "exported_revision": self.exported_revision,
            "dirty": self.dirty,
            "document_sha256": self.document_sha256,
            "last_render_sha256": self.last_render_sha256,
            "review_annotation_ids": list(self.review_annotation_ids),
            "structural_qa_summary": copy.deepcopy(
                self.structural_qa_summary
            ),
            "qa_summary": copy.deepcopy(self.qa_summary),
            "journal_outbox": copy.deepcopy(self.journal_outbox),
            "recovery_snapshots": list(self.recovery_snapshots),
            "recovery_snapshot_hashes": dict(self.recovery_snapshot_hashes),
            "object_registry": self.object_registry.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CanvasSession:
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "session_id",
                "project_id",
                "document_id",
                "document_path",
                "state",
                "revision",
                "current_page",
                "selection",
                "viewport",
                "interface",
                "active_inspector",
                "active_transaction",
                "saved_revision",
                "exported_revision",
                "dirty",
                "document_sha256",
                "last_render_sha256",
                "review_annotation_ids",
                "structural_qa_summary",
                "qa_summary",
                "journal_outbox",
                "recovery_snapshots",
                "recovery_snapshot_hashes",
                "object_registry",
                "created_at",
                "updated_at",
            },
            label="CanvasSession",
        )
        if payload.get("kind") != CANVAS_SESSION_KIND:
            raise ValueError("Not a SciPlot CanvasSession payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version not in CANVAS_SESSION_COMPATIBLE_VERSIONS:
            raise ValueError(
                f"Unsupported CanvasSession version: {payload.get('version')!r}"
            )
        review_annotation_ids = require_json_list(
            payload.get("review_annotation_ids", []),
            label="review_annotation_ids",
        )
        recovery_snapshots = require_json_list(
            payload.get("recovery_snapshots", []),
            label="recovery_snapshots",
        )
        recovery_snapshot_hashes = require_json_object(
            payload.get("recovery_snapshot_hashes", {}),
            label="recovery_snapshot_hashes",
        )
        qa_summary = require_json_object(
            payload.get("qa_summary", {}), label="qa_summary"
        )
        journal_outbox = require_json_list(
            payload.get("journal_outbox", []),
            label="journal_outbox",
        )
        if not all(isinstance(entry, dict) for entry in journal_outbox):
            raise ValueError("Every journal_outbox entry must be an object.")
        structural_qa_summary = require_json_object(
            payload.get("structural_qa_summary", {}),
            label="structural_qa_summary",
        )
        active_inspector = payload.get("active_inspector")
        if active_inspector is not None and not isinstance(active_inspector, str):
            raise ValueError("active_inspector must be a string or null.")
        session = cls(
            session_id=_required_text(payload.get("session_id"), "session_id"),
            project_id=_required_text(payload.get("project_id"), "project_id"),
            document_id=_required_text(payload.get("document_id"), "document_id"),
            document_path=_required_text(payload.get("document_path"), "document_path"),
            state=str(payload.get("state") or "preparing"),
            revision=require_json_int(payload.get("revision", 0), label="revision"),
            current_page=require_json_int(
                payload.get("current_page", 0), label="current_page"
            ),
            selection=CanvasSelection.from_dict(payload.get("selection")),
            viewport=CanvasViewport.from_dict(payload.get("viewport")),
            interface=CanvasInterfaceState.from_dict(payload.get("interface")),
            active_inspector=active_inspector or None,
            active_transaction=CanvasTransaction.from_dict(
                payload.get("active_transaction")
            ),
            saved_revision=require_json_int(
                payload.get("saved_revision", 0), label="saved_revision"
            ),
            exported_revision=(
                require_json_int(
                    payload["exported_revision"], label="exported_revision"
                )
                if payload.get("exported_revision") is not None
                else None
            ),
            document_sha256=(
                str(payload["document_sha256"])
                if payload.get("document_sha256")
                else None
            ),
            last_render_sha256=(
                str(payload["last_render_sha256"])
                if payload.get("last_render_sha256")
                else None
            ),
            review_annotation_ids=[
                _required_text(item, "review_annotation_id")
                for item in review_annotation_ids
            ],
            structural_qa_summary=dict(structural_qa_summary),
            qa_summary=dict(qa_summary),
            journal_outbox=[dict(entry) for entry in journal_outbox],
            recovery_snapshots=[
                _required_text(item, "recovery snapshot") for item in recovery_snapshots
            ],
            recovery_snapshot_hashes={
                str(key): str(value) for key, value in recovery_snapshot_hashes.items()
            },
            object_registry=ObjectIdentityRegistry.from_dict(
                payload.get("object_registry")
            ),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
        )
        if "dirty" in payload:
            recorded_dirty = require_json_bool(payload["dirty"], label="dirty")
            if recorded_dirty is not session.dirty:
                raise ValueError(
                    "CanvasSession dirty does not match revision/saved_revision."
                )
        return session


__all__ = [
    "CANVAS_SESSION_KIND",
    "CANVAS_SESSION_COMPATIBLE_VERSIONS",
    "CANVAS_SESSION_STATES",
    "CANVAS_SESSION_VERSION",
    "CANVAS_TRANSACTION_STATES",
    "CanvasDataPointSelection",
    "CanvasInterfaceState",
    "CanvasObjectRecord",
    "CanvasSelection",
    "CanvasSession",
    "CanvasTransaction",
    "CanvasViewport",
    "ObjectIdentityRegistry",
]
