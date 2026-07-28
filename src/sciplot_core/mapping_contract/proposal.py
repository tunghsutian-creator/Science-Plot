"""Model and validate a complete data-mapping proposal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_number,
    require_json_object,
)
from sciplot_core.assistant_operations import _validate_json_value

from sciplot_core.mapping_contract.constants import (
    DATA_MAPPING_PROPOSAL_KIND,
    DATA_MAPPING_PROPOSAL_VERSION,
)

from sciplot_core.mapping_contract.values import (
    _now,
    _timestamp,
    _required_text,
    _free_text,
    _safe_id,
    _sha256,
)

from sciplot_core.mapping_contract.transform_validation import (
    _validate_request_patch,
)

from sciplot_core.mapping_contract.source_reference import (
    DataSourceReference,
)

from sciplot_core.mapping_contract.column_mapping import (
    DataColumnMapping,
)

from sciplot_core.mapping_contract.transformation import (
    DeclarativeTransformation,
)


@dataclass(frozen=True)
class DataMappingProposal:
    base_request_sha256: str
    sources: tuple[DataSourceReference, ...]
    columns: tuple[DataColumnMapping, ...]
    provider: str
    sample_labels: dict[str, str] = field(default_factory=dict)
    unit_overrides: dict[str, str] = field(default_factory=dict)
    transformations: tuple[DeclarativeTransformation, ...] = ()
    request_patch: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    rationale: str = ""
    proposal_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proposal_id", _safe_id(self.proposal_id, "proposal_id")
        )
        object.__setattr__(
            self,
            "base_request_sha256",
            _sha256(self.base_request_sha256, "base_request_sha256"),
        )
        object.__setattr__(self, "provider", _required_text(self.provider, "provider"))
        object.__setattr__(
            self,
            "created_at",
            _timestamp(self.created_at, "created_at"),
        )
        object.__setattr__(
            self,
            "rationale",
            _free_text(self.rationale, "rationale"),
        )
        if not self.sources or not all(
            isinstance(source, DataSourceReference) for source in self.sources
        ):
            raise ValueError(
                "DataMappingProposal requires DataSourceReference entries."
            )
        source_ids = [source.source_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("DataMappingProposal source IDs must be unique.")
        source_paths = [source.relative_path for source in self.sources]
        if len(set(source_paths)) != len(source_paths):
            raise ValueError("DataMappingProposal source paths must be unique.")
        if not self.columns or not all(
            isinstance(column, DataColumnMapping) for column in self.columns
        ):
            raise ValueError("DataMappingProposal requires DataColumnMapping entries.")
        unknown_column_sources = sorted(
            {column.source_id for column in self.columns} - set(source_ids)
        )
        if unknown_column_sources:
            raise ValueError(
                "Column mappings reference unknown source IDs: "
                + ", ".join(unknown_column_sources)
            )
        for source_id in source_ids:
            source_columns = [
                column for column in self.columns if column.source_id == source_id
            ]
            if not source_columns:
                raise ValueError(
                    f"Data source {source_id!r} has no explicit column mappings."
                )
            indexes = [column.source_column_index for column in source_columns]
            outputs = [column.output_column for column in source_columns]
            if len(set(indexes)) != len(indexes):
                raise ValueError(
                    f"Data source {source_id!r} maps one source column more than once."
                )
            if len(set(outputs)) != len(outputs):
                raise ValueError(
                    f"Data source {source_id!r} has duplicate output columns."
                )
        if not any(column.role in {"x", "y", "z", "value"} for column in self.columns):
            raise ValueError(
                "DataMappingProposal must map at least one numeric "
                "x, y, z, or value role."
            )
        if not isinstance(self.sample_labels, dict):
            raise ValueError("sample_labels must be an object.")
        labels = {
            _safe_id(key, "sample_labels source_id"): _required_text(
                value, f"sample_labels[{key!r}]"
            )
            for key, value in self.sample_labels.items()
        }
        unknown_label_sources = sorted(set(labels) - set(source_ids))
        if unknown_label_sources:
            raise ValueError(
                "sample_labels reference unknown source IDs: "
                + ", ".join(unknown_label_sources)
            )
        object.__setattr__(self, "sample_labels", labels)
        if not isinstance(self.unit_overrides, dict):
            raise ValueError("unit_overrides must be an object.")
        units = {
            _required_text(key, "unit_overrides column"): _required_text(
                value, f"unit_overrides[{key!r}]"
            )
            for key, value in self.unit_overrides.items()
        }
        mapped_outputs = {column.output_column for column in self.columns}
        unknown_units = sorted(set(units) - mapped_outputs)
        if unknown_units:
            raise ValueError(
                "unit_overrides reference unmapped output columns: "
                + ", ".join(unknown_units)
            )
        object.__setattr__(self, "unit_overrides", units)
        if not all(
            isinstance(transformation, DeclarativeTransformation)
            for transformation in self.transformations
        ):
            raise ValueError(
                "transformations must contain DeclarativeTransformation objects."
            )
        transformation_ids = [
            transformation.transformation_id for transformation in self.transformations
        ]
        if len(set(transformation_ids)) != len(transformation_ids):
            raise ValueError("Transformation IDs must be unique.")
        unknown_transform_sources = sorted(
            {
                source_id
                for transformation in self.transformations
                for source_id in transformation.source_ids
            }
            - set(source_ids)
        )
        if unknown_transform_sources:
            raise ValueError(
                "Transformations reference unknown source IDs: "
                + ", ".join(unknown_transform_sources)
            )
        object.__setattr__(
            self, "request_patch", _validate_request_patch(self.request_patch)
        )
        confidence = require_json_number(self.confidence, label="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")
        object.__setattr__(self, "confidence", confidence)
        _validate_json_value(self.to_dict(), path="proposal")

    @property
    def requires_confirmation(self) -> bool:
        return True

    @property
    def executable(self) -> bool:
        return False

    @property
    def source_hashes(self) -> dict[str, str]:
        return {source.relative_path: source.sha256 for source in self.sources}

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": DATA_MAPPING_PROPOSAL_KIND,
            "version": DATA_MAPPING_PROPOSAL_VERSION,
            "proposal_id": self.proposal_id,
            "base_request_sha256": self.base_request_sha256,
            "provider": self.provider,
            "sources": [source.to_dict() for source in self.sources],
            "columns": [column.to_dict() for column in self.columns],
            "sample_labels": dict(self.sample_labels),
            "unit_overrides": dict(self.unit_overrides),
            "transformations": [
                transformation.to_dict() for transformation in self.transformations
            ],
            "request_patch": dict(self.request_patch),
            "confidence": self.confidence,
            "requires_confirmation": True,
            "executable": False,
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
                "base_request_sha256",
                "provider",
                "sources",
                "columns",
                "sample_labels",
                "unit_overrides",
                "transformations",
                "request_patch",
                "confidence",
                "requires_confirmation",
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
            raise ValueError(f"Unsupported DataMappingProposal version: {version!r}")
        if "created_at" not in payload:
            raise ValueError(
                "DataMappingProposal created_at is required so its confirmation hash is stable."
            )
        raw_sources = require_json_list(
            payload.get("sources"), label="DataMappingProposal sources"
        )
        raw_columns = require_json_list(
            payload.get("columns"), label="DataMappingProposal columns"
        )
        raw_transformations = require_json_list(
            payload.get("transformations", []),
            label="DataMappingProposal transformations",
        )
        for label, values in (
            ("sources", raw_sources),
            ("columns", raw_columns),
            ("transformations", raw_transformations),
        ):
            if not all(isinstance(item, dict) for item in values):
                raise ValueError(
                    f"Every DataMappingProposal {label} entry must be an object."
                )
        proposal = cls(
            proposal_id=_required_text(
                payload.get("proposal_id"),
                "proposal_id",
            ),
            base_request_sha256=_required_text(
                payload.get("base_request_sha256"),
                "base_request_sha256",
            ),
            provider=_required_text(payload.get("provider"), "provider"),
            sources=tuple(DataSourceReference.from_dict(item) for item in raw_sources),
            columns=tuple(DataColumnMapping.from_dict(item) for item in raw_columns),
            sample_labels={
                _required_text(key, "sample_labels source_id"): _required_text(
                    value,
                    f"sample_labels[{key!r}]",
                )
                for key, value in require_json_object(
                    payload.get("sample_labels", {}),
                    label="sample_labels",
                ).items()
            },
            unit_overrides={
                _required_text(key, "unit_overrides column"): _required_text(
                    value,
                    f"unit_overrides[{key!r}]",
                )
                for key, value in require_json_object(
                    payload.get("unit_overrides", {}),
                    label="unit_overrides",
                ).items()
            },
            transformations=tuple(
                DeclarativeTransformation.from_dict(item)
                for item in raw_transformations
            ),
            request_patch=dict(
                require_json_object(
                    payload.get("request_patch", {}),
                    label="request_patch",
                )
            ),
            confidence=require_json_number(
                payload.get("confidence", 0.0), label="confidence"
            ),
            rationale=_free_text(
                payload.get("rationale", ""),
                "rationale",
            ),
            created_at=_required_text(
                payload.get("created_at"),
                "created_at",
            ),
        )
        if (
            "requires_confirmation" in payload
            and require_json_bool(
                payload["requires_confirmation"], label="requires_confirmation"
            )
            is not True
        ):
            raise ValueError(
                "DataMappingProposal version 2 always requires external confirmation."
            )
        if (
            "executable" in payload
            and require_json_bool(payload["executable"], label="executable")
            is not False
        ):
            raise ValueError("DataMappingProposal cannot self-authorize execution.")
        return proposal
