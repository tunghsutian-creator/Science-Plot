"""Model one declared source-column role mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
)

from sciplot_core.mapping_contract.constants import (
    DATA_COLUMN_ROLES,
)

from sciplot_core.mapping_contract.values import (
    _required_text,
    _safe_id,
    _optional_text,
)


@dataclass(frozen=True)
class DataColumnMapping:
    source_id: str
    source_column_index: int
    output_column: str
    role: str
    expected_header: str | None = None
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        index = require_json_int(self.source_column_index, label="source_column_index")
        if index < 0:
            raise ValueError("source_column_index must be non-negative.")
        output = _required_text(self.output_column, "output_column")
        if output.startswith("__sciplot_"):
            raise ValueError("output_column uses a reserved SciPlot prefix.")
        object.__setattr__(self, "output_column", output)
        role = _required_text(self.role, "column mapping role")
        if role not in DATA_COLUMN_ROLES:
            raise ValueError(f"Unsupported data column role: {role!r}")
        object.__setattr__(self, "role", role)
        object.__setattr__(
            self,
            "expected_header",
            _optional_text(self.expected_header, "expected_header"),
        )
        if type(self.required) is not bool:
            raise ValueError("column mapping required must be a boolean.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_column_index": self.source_column_index,
            "output_column": self.output_column,
            "role": self.role,
            "expected_header": self.expected_header,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DataColumnMapping:
        reject_unknown_keys(
            payload,
            {
                "source_id",
                "source_column_index",
                "output_column",
                "role",
                "expected_header",
                "required",
            },
            label="DataColumnMapping",
        )
        return cls(
            source_id=_required_text(payload.get("source_id"), "source_id"),
            source_column_index=require_json_int(
                payload.get("source_column_index"),
                label="source_column_index",
            ),
            output_column=_required_text(
                payload.get("output_column"),
                "output_column",
            ),
            role=_required_text(payload.get("role"), "column mapping role"),
            expected_header=(
                _required_text(payload["expected_header"], "expected_header")
                if payload.get("expected_header") is not None
                else None
            ),
            required=require_json_bool(
                payload.get("required", True), label="column mapping required"
            ),
        )
