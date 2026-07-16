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

CANVAS_SESSION_KIND = "sciplot_canvas_session"
CANVAS_SESSION_VERSION = 2
CANVAS_SESSION_COMPATIBLE_VERSIONS = {1, CANVAS_SESSION_VERSION}
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
CANVAS_TRANSACTION_STATES = {"active", "paused", "committed", "rejected", "rolled_back"}


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
class CanvasSelection:
    object_ids: list[str] = field(default_factory=list)
    primary_object_id: str | None = None

    def __post_init__(self) -> None:
        self.object_ids = [
            _required_text(object_id, "selection object_id")
            for object_id in self.object_ids
        ]
        if len(set(self.object_ids)) != len(self.object_ids):
            raise ValueError("CanvasSelection object_ids must be unique.")
        if self.primary_object_id and self.primary_object_id not in self.object_ids:
            raise ValueError("primary_object_id must be included in object_ids.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_ids": list(self.object_ids),
            "primary_object_id": self.primary_object_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> CanvasSelection:
        if payload is None:
            return cls()
        payload = require_json_object(payload, label="selection")
        reject_unknown_keys(
            payload,
            {"object_ids", "primary_object_id"},
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
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.transaction_id = _required_text(self.transaction_id, "transaction_id")
        self.provider = _required_text(self.provider, "provider")
        if self.base_revision < 0:
            raise ValueError("CanvasTransaction base_revision must be non-negative.")
        if self.status not in CANVAS_TRANSACTION_STATES:
            raise ValueError(f"Unsupported CanvasTransaction state: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "provider": self.provider,
            "base_revision": self.base_revision,
            "status": self.status,
            "snapshot_path": self.snapshot_path,
            "created_at": self.created_at,
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
                "created_at",
            },
            label="active_transaction",
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
            created_at=str(payload.get("created_at") or _now()),
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
    qa_summary: dict[str, Any] = field(default_factory=dict)
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
        if not isinstance(self.qa_summary, dict):
            raise ValueError("qa_summary must be an object.")
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
            "qa_summary": dict(self.qa_summary),
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
                "qa_summary",
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
            qa_summary=dict(qa_summary),
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
    "CanvasInterfaceState",
    "CanvasObjectRecord",
    "CanvasSelection",
    "CanvasSession",
    "CanvasTransaction",
    "CanvasViewport",
    "ObjectIdentityRegistry",
]
