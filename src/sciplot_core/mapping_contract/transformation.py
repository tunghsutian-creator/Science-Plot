"""Model one validated declarative data transformation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_list,
    require_json_object,
)
from sciplot_core.assistant_operations import _validate_json_value

from sciplot_core.mapping_contract.constants import (
    DECLARATIVE_TRANSFORMATIONS,
)

from sciplot_core.mapping_contract.values import (
    _required_text,
    _safe_id,
    _reject_executable_keys,
)

from sciplot_core.mapping_contract.transform_validation import (
    _validate_transform_parameters,
)


@dataclass(frozen=True)
class DeclarativeTransformation:
    transformation_type: str
    parameters: dict[str, Any]
    source_ids: tuple[str, ...] = ()
    transformation_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transformation_id",
            _safe_id(self.transformation_id, "transformation_id"),
        )
        transformation_type = _required_text(
            self.transformation_type, "transformation_type"
        )
        if transformation_type not in DECLARATIVE_TRANSFORMATIONS:
            raise ValueError(
                f"Unsupported declarative transformation: {transformation_type!r}"
            )
        if not isinstance(self.parameters, dict):
            raise ValueError("transformation parameters must be an object.")
        source_ids = tuple(
            _safe_id(source_id, "transformation source_id")
            for source_id in self.source_ids
        )
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("transformation source_ids must be unique.")
        object.__setattr__(self, "source_ids", source_ids)
        _validate_json_value(self.parameters, path="parameters")
        _reject_executable_keys(self.parameters)
        _validate_transform_parameters(transformation_type, self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transformation_id": self.transformation_id,
            "transformation_type": self.transformation_type,
            "source_ids": list(self.source_ids),
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeclarativeTransformation:
        reject_unknown_keys(
            payload,
            {
                "transformation_id",
                "transformation_type",
                "source_ids",
                "parameters",
            },
            label="DeclarativeTransformation",
        )
        if "transformation_id" not in payload:
            raise ValueError(
                "DeclarativeTransformation transformation_id is required "
                "so proposal hashes remain stable."
            )
        return cls(
            transformation_id=_required_text(
                payload.get("transformation_id"),
                "transformation_id",
            ),
            transformation_type=_required_text(
                payload.get("transformation_type"),
                "transformation_type",
            ),
            source_ids=tuple(
                _required_text(
                    item,
                    "DeclarativeTransformation source_id",
                )
                for item in require_json_list(
                    payload.get("source_ids", []),
                    label="DeclarativeTransformation source_ids",
                )
            ),
            parameters=dict(
                require_json_object(
                    payload.get("parameters"),
                    label="DeclarativeTransformation parameters",
                )
            ),
        )
