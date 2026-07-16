from __future__ import annotations

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
from sciplot_core.canvas.operations import _validate_json_value

DATA_MAPPING_PROPOSAL_KIND = "sciplot_data_mapping_proposal"
DATA_MAPPING_PROPOSAL_VERSION = 1
DECLARATIVE_TRANSFORMATIONS = {
    "rename",
    "select",
    "exclude",
    "drop_missing",
    "sort",
    "unit_convert",
    "derive_ratio",
    "normalize_baseline",
    "aggregate_replicates",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


def _reject_executable_keys(value: Any, *, path: str = "parameters") -> None:
    forbidden = {"python", "code", "script", "command", "shell", "executable"}
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in forbidden:
                raise ValueError(
                    f"{path}.{key} is executable content and is not allowed."
                )
            _reject_executable_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_executable_keys(item, path=f"{path}[{index}]")


@dataclass(frozen=True)
class DeclarativeTransformation:
    transformation_type: str
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.transformation_type, "transformation_type")
        if self.transformation_type not in DECLARATIVE_TRANSFORMATIONS:
            raise ValueError(
                f"Unsupported declarative transformation: {self.transformation_type!r}"
            )
        if not isinstance(self.parameters, dict):
            raise ValueError("transformation parameters must be an object.")
        _validate_json_value(self.parameters, path="parameters")
        _reject_executable_keys(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transformation_type": self.transformation_type,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeclarativeTransformation:
        reject_unknown_keys(
            payload,
            {"transformation_type", "parameters"},
            label="DeclarativeTransformation",
        )
        return cls(
            transformation_type=str(payload.get("transformation_type") or ""),
            parameters=dict(
                require_json_object(
                    payload.get("parameters"),
                    label="DeclarativeTransformation parameters",
                )
            ),
        )


@dataclass(frozen=True)
class DataMappingProposal:
    source_hashes: dict[str, str]
    column_roles: dict[str, str]
    sample_labels: dict[str, str] = field(default_factory=dict)
    unit_overrides: dict[str, str] = field(default_factory=dict)
    excluded_columns: tuple[str, ...] = ()
    transformations: tuple[DeclarativeTransformation, ...] = ()
    confidence: float = 0.0
    requires_confirmation: bool = True
    human_confirmed: bool = False
    rationale: str = ""
    proposal_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _required_text(self.proposal_id, "proposal_id")
        if not isinstance(self.source_hashes, dict):
            raise ValueError("source_hashes must be an object.")
        if not self.source_hashes:
            raise ValueError("DataMappingProposal requires immutable source hashes.")
        for path, digest in self.source_hashes.items():
            if (
                not str(path).strip()
                or re.fullmatch(r"[0-9a-fA-F]{64}", str(digest)) is None
            ):
                raise ValueError(
                    "Each source hash must map a path to a SHA-256 digest."
                )
        for label, mapping in (
            ("column_roles", self.column_roles),
            ("sample_labels", self.sample_labels),
            ("unit_overrides", self.unit_overrides),
        ):
            if not isinstance(mapping, dict):
                raise ValueError(f"{label} must be an object.")
            for key, value in mapping.items():
                _required_text(key, f"{label} key")
                _required_text(value, f"{label}[{key!r}]")
        if not self.column_roles:
            raise ValueError("DataMappingProposal requires at least one column role.")
        if len(set(self.excluded_columns)) != len(self.excluded_columns):
            raise ValueError("excluded_columns must be unique.")
        for column in self.excluded_columns:
            _required_text(column, "excluded column")
        if not all(
            isinstance(transformation, DeclarativeTransformation)
            for transformation in self.transformations
        ):
            raise ValueError(
                "transformations must contain DeclarativeTransformation objects."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")
        if not isinstance(self.requires_confirmation, bool) or not isinstance(
            self.human_confirmed, bool
        ):
            raise ValueError("confirmation flags must be booleans.")
        _validate_json_value(self.to_dict(), path="proposal")

    @property
    def executable(self) -> bool:
        return not self.requires_confirmation or self.human_confirmed

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": DATA_MAPPING_PROPOSAL_KIND,
            "version": DATA_MAPPING_PROPOSAL_VERSION,
            "proposal_id": self.proposal_id,
            "source_hashes": dict(self.source_hashes),
            "column_roles": dict(self.column_roles),
            "sample_labels": dict(self.sample_labels),
            "unit_overrides": dict(self.unit_overrides),
            "excluded_columns": list(self.excluded_columns),
            "transformations": [
                transformation.to_dict() for transformation in self.transformations
            ],
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation,
            "human_confirmed": self.human_confirmed,
            "executable": self.executable,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DataMappingProposal:
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "proposal_id",
                "source_hashes",
                "column_roles",
                "sample_labels",
                "unit_overrides",
                "excluded_columns",
                "transformations",
                "confidence",
                "requires_confirmation",
                "human_confirmed",
                "executable",
                "rationale",
                "created_at",
            },
            label="DataMappingProposal",
        )
        if payload.get("kind") != DATA_MAPPING_PROPOSAL_KIND:
            raise ValueError("Not a SciPlot DataMappingProposal payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != DATA_MAPPING_PROPOSAL_VERSION:
            raise ValueError(
                f"Unsupported DataMappingProposal version: {payload.get('version')!r}"
            )
        raw_transformations = require_json_list(
            payload.get("transformations"),
            label="DataMappingProposal transformations",
        )
        if not all(isinstance(item, dict) for item in raw_transformations):
            raise ValueError(
                "Every DataMappingProposal transformation must be an object."
            )
        source_hashes = require_json_object(
            payload.get("source_hashes"), label="source_hashes"
        )
        column_roles = require_json_object(
            payload.get("column_roles"), label="column_roles"
        )
        sample_labels = require_json_object(
            payload.get("sample_labels", {}), label="sample_labels"
        )
        unit_overrides = require_json_object(
            payload.get("unit_overrides", {}), label="unit_overrides"
        )
        excluded_columns = require_json_list(
            payload.get("excluded_columns", []), label="excluded_columns"
        )
        proposal = cls(
            proposal_id=_required_text(payload.get("proposal_id"), "proposal_id"),
            source_hashes={
                str(key): str(value) for key, value in source_hashes.items()
            },
            column_roles={str(key): str(value) for key, value in column_roles.items()},
            sample_labels={
                str(key): str(value) for key, value in sample_labels.items()
            },
            unit_overrides={
                str(key): str(value) for key, value in unit_overrides.items()
            },
            excluded_columns=tuple(str(item) for item in excluded_columns),
            transformations=tuple(
                DeclarativeTransformation.from_dict(item)
                for item in raw_transformations
            ),
            confidence=require_json_number(
                payload.get("confidence", 0.0), label="confidence"
            ),
            requires_confirmation=require_json_bool(
                payload.get("requires_confirmation", True),
                label="requires_confirmation",
            ),
            human_confirmed=require_json_bool(
                payload.get("human_confirmed", False), label="human_confirmed"
            ),
            rationale=str(payload.get("rationale") or ""),
            created_at=str(payload.get("created_at") or _now()),
        )
        if "executable" in payload:
            recorded_executable = require_json_bool(
                payload["executable"], label="executable"
            )
            if recorded_executable is not proposal.executable:
                raise ValueError(
                    "DataMappingProposal executable does not match confirmation state."
                )
        return proposal


__all__ = [
    "DATA_MAPPING_PROPOSAL_KIND",
    "DATA_MAPPING_PROPOSAL_VERSION",
    "DECLARATIVE_TRANSFORMATIONS",
    "DataMappingProposal",
    "DeclarativeTransformation",
]
