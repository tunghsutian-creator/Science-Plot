"""Model legacy and current user confirmations for a mapping proposal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_int,
    require_json_object,
)

from sciplot_core.mapping_contract.constants import (
    DATA_MAPPING_CONFIRMATION_KIND,
    DATA_MAPPING_CONFIRMATION_LEGACY_VERSION,
    DATA_MAPPING_CONFIRMATION_VERSION,
)

from sciplot_core.mapping_contract.values import (
    _now,
    _absolute_path,
    _timestamp,
    _required_text,
    _safe_id,
    _sha256,
    _relative_source_path,
)


@dataclass(frozen=True)
class LegacyDataMappingConfirmation:
    """Read-only compatibility shape for path-unbound v1 receipts."""

    proposal_id: str
    proposal_sha256: str
    base_request_sha256: str
    source_hashes: dict[str, str]
    confirmed_by: str
    confirmed_at: str
    confirmation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "confirmation_id",
            _safe_id(self.confirmation_id, "confirmation_id"),
        )
        object.__setattr__(
            self, "proposal_id", _safe_id(self.proposal_id, "proposal_id")
        )
        object.__setattr__(
            self,
            "proposal_sha256",
            _sha256(self.proposal_sha256, "proposal_sha256"),
        )
        object.__setattr__(
            self,
            "base_request_sha256",
            _sha256(self.base_request_sha256, "base_request_sha256"),
        )
        object.__setattr__(
            self, "confirmed_by", _required_text(self.confirmed_by, "confirmed_by")
        )
        object.__setattr__(
            self,
            "confirmed_at",
            _timestamp(self.confirmed_at, "confirmed_at"),
        )
        if not isinstance(self.source_hashes, dict) or not self.source_hashes:
            raise ValueError("LegacyDataMappingConfirmation requires source hashes.")
        normalized = {
            _relative_source_path(path): _sha256(digest, f"source_hashes[{path!r}]")
            for path, digest in self.source_hashes.items()
        }
        object.__setattr__(self, "source_hashes", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": DATA_MAPPING_CONFIRMATION_KIND,
            "version": DATA_MAPPING_CONFIRMATION_LEGACY_VERSION,
            "confirmation_id": self.confirmation_id,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "base_request_sha256": self.base_request_sha256,
            "source_hashes": dict(self.source_hashes),
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LegacyDataMappingConfirmation:
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "confirmation_id",
                "proposal_id",
                "proposal_sha256",
                "base_request_sha256",
                "source_hashes",
                "confirmed_by",
                "confirmed_at",
            },
            label="LegacyDataMappingConfirmation",
        )
        if payload.get("kind") != DATA_MAPPING_CONFIRMATION_KIND:
            raise ValueError("Not a SciPlot DataMappingConfirmation payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != DATA_MAPPING_CONFIRMATION_LEGACY_VERSION:
            raise ValueError(
                f"Unsupported legacy DataMappingConfirmation version: {version!r}"
            )
        if "confirmed_at" not in payload:
            raise ValueError(
                "LegacyDataMappingConfirmation confirmed_at is required for inspection."
            )
        return cls(
            confirmation_id=_required_text(
                payload.get("confirmation_id"), "confirmation_id"
            ),
            proposal_id=_required_text(payload.get("proposal_id"), "proposal_id"),
            proposal_sha256=_required_text(
                payload.get("proposal_sha256"), "proposal_sha256"
            ),
            base_request_sha256=_required_text(
                payload.get("base_request_sha256"), "base_request_sha256"
            ),
            source_hashes={
                _required_text(key, "source_hash path"): _required_text(
                    value, f"source_hashes[{key!r}]"
                )
                for key, value in require_json_object(
                    payload.get("source_hashes"), label="source_hashes"
                ).items()
            },
            confirmed_by=_required_text(payload.get("confirmed_by"), "confirmed_by"),
            confirmed_at=_required_text(payload.get("confirmed_at"), "confirmed_at"),
        )


@dataclass(frozen=True)
class DataMappingConfirmation:
    proposal_id: str
    proposal_sha256: str
    base_request_sha256: str
    source_hashes: dict[str, str]
    source_root: str
    request_path: str
    output_root: str
    confirmed_by: str
    confirmed_at: str = field(default_factory=_now)
    confirmation_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "confirmation_id",
            _safe_id(self.confirmation_id, "confirmation_id"),
        )
        object.__setattr__(
            self, "proposal_id", _safe_id(self.proposal_id, "proposal_id")
        )
        object.__setattr__(
            self,
            "proposal_sha256",
            _sha256(self.proposal_sha256, "proposal_sha256"),
        )
        object.__setattr__(
            self,
            "base_request_sha256",
            _sha256(self.base_request_sha256, "base_request_sha256"),
        )
        object.__setattr__(
            self,
            "source_root",
            _absolute_path(self.source_root, "source_root"),
        )
        object.__setattr__(
            self,
            "request_path",
            _absolute_path(self.request_path, "request_path"),
        )
        object.__setattr__(
            self,
            "output_root",
            _absolute_path(self.output_root, "output_root"),
        )
        object.__setattr__(
            self, "confirmed_by", _required_text(self.confirmed_by, "confirmed_by")
        )
        object.__setattr__(
            self,
            "confirmed_at",
            _timestamp(self.confirmed_at, "confirmed_at"),
        )
        if not isinstance(self.source_hashes, dict) or not self.source_hashes:
            raise ValueError("DataMappingConfirmation requires source hashes.")
        normalized = {
            _relative_source_path(path): _sha256(digest, f"source_hashes[{path!r}]")
            for path, digest in self.source_hashes.items()
        }
        object.__setattr__(self, "source_hashes", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": DATA_MAPPING_CONFIRMATION_KIND,
            "version": DATA_MAPPING_CONFIRMATION_VERSION,
            "confirmation_id": self.confirmation_id,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "base_request_sha256": self.base_request_sha256,
            "source_hashes": dict(self.source_hashes),
            "source_root": self.source_root,
            "request_path": self.request_path,
            "output_root": self.output_root,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DataMappingConfirmation:
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "confirmation_id",
                "proposal_id",
                "proposal_sha256",
                "base_request_sha256",
                "source_hashes",
                "source_root",
                "request_path",
                "output_root",
                "confirmed_by",
                "confirmed_at",
            },
            label="DataMappingConfirmation",
        )
        if payload.get("kind") != DATA_MAPPING_CONFIRMATION_KIND:
            raise ValueError("Not a SciPlot DataMappingConfirmation payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != DATA_MAPPING_CONFIRMATION_VERSION:
            raise ValueError(
                f"Unsupported DataMappingConfirmation version: {version!r}"
            )
        if "confirmed_at" not in payload:
            raise ValueError(
                "DataMappingConfirmation confirmed_at is required for an immutable receipt."
            )
        return cls(
            confirmation_id=_required_text(
                payload.get("confirmation_id"),
                "confirmation_id",
            ),
            proposal_id=_required_text(
                payload.get("proposal_id"),
                "proposal_id",
            ),
            proposal_sha256=_required_text(
                payload.get("proposal_sha256"),
                "proposal_sha256",
            ),
            base_request_sha256=_required_text(
                payload.get("base_request_sha256"),
                "base_request_sha256",
            ),
            source_hashes={
                _required_text(key, "source_hash path"): _required_text(
                    value,
                    f"source_hashes[{key!r}]",
                )
                for key, value in require_json_object(
                    payload.get("source_hashes"),
                    label="source_hashes",
                ).items()
            },
            source_root=_required_text(
                payload.get("source_root"),
                "source_root",
            ),
            request_path=_required_text(
                payload.get("request_path"),
                "request_path",
            ),
            output_root=_required_text(
                payload.get("output_root"),
                "output_root",
            ),
            confirmed_by=_required_text(
                payload.get("confirmed_by"),
                "confirmed_by",
            ),
            confirmed_at=_required_text(
                payload.get("confirmed_at"),
                "confirmed_at",
            ),
        )
