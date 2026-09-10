"""Model one source file and its immutable content binding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_int,
)

from sciplot_core.mapping_contract.values import (
    _required_text,
    _safe_id,
    _sha256,
    _relative_source_path,
)


@dataclass(frozen=True)
class DataSourceReference:
    source_id: str
    relative_path: str
    sha256: str
    sheet: str | int | None = None
    header_row: int | None = 0
    delimiter: str = "auto"
    decimal: str = "."
    data_start_row: int | None = None
    data_end_row: int | None = None
    cell_evidence: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        object.__setattr__(
            self, "relative_path", _relative_source_path(self.relative_path)
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "source sha256"))
        if isinstance(self.sheet, bool) or not isinstance(self.sheet, str | int | None):
            raise ValueError("source sheet must be a string, integer, or null.")
        if isinstance(self.sheet, str) and not self.sheet.strip():
            raise ValueError("source sheet string must not be empty.")
        if self.header_row is not None:
            header_row = require_json_int(self.header_row, label="source header_row")
            if header_row < 0:
                raise ValueError("source header_row must be non-negative or null.")
        delimiter = _required_text(self.delimiter, "source delimiter")
        if delimiter not in {"auto", ",", "\t", ";", "|"}:
            raise ValueError(
                "source delimiter must be auto, comma, tab, semicolon, or pipe."
            )
        object.__setattr__(self, "delimiter", delimiter)
        decimal = _required_text(self.decimal, "source decimal")
        if decimal not in {".", ","}:
            raise ValueError("source decimal must be `.` or `,`.")
        object.__setattr__(self, "decimal", decimal)
        for key in ("data_start_row", "data_end_row"):
            value = getattr(self, key)
            if value is not None and (require_json_int(value, label=key) < 0):
                raise ValueError(f"{key} must be non-negative.")
        if self.data_end_row is not None and (
            self.data_start_row is None or self.data_end_row <= self.data_start_row
        ):
            raise ValueError("data_end_row requires an earlier data_start_row (end exclusive).")
        if not isinstance(self.cell_evidence, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            and len(key.split(",")) == 2
            and all(part.isdigit() for part in key.split(","))
            for key, value in self.cell_evidence.items()
        ):
            raise ValueError("cell_evidence needs zero-based row,column keys and original text values.")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "source_id": self.source_id,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "sheet": self.sheet,
            "header_row": self.header_row,
            "delimiter": self.delimiter,
            "decimal": self.decimal,
        }
        # Omit new optional fields for byte-compatible historical proposal hashes.
        if self.data_start_row is not None:
            result["data_start_row"] = self.data_start_row
        if self.data_end_row is not None:
            result["data_end_row"] = self.data_end_row
        if self.cell_evidence:
            result["cell_evidence"] = dict(self.cell_evidence)
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DataSourceReference:
        reject_unknown_keys(
            payload,
            {
                "source_id",
                "relative_path",
                "sha256",
                "sheet",
                "header_row",
                "delimiter",
                "decimal",
                "data_start_row", "data_end_row", "cell_evidence",
            },
            label="DataSourceReference",
        )
        header_row = payload.get("header_row", 0)
        if header_row is not None:
            header_row = require_json_int(header_row, label="source header_row")
        return cls(
            source_id=_required_text(payload.get("source_id"), "source_id"),
            relative_path=_required_text(
                payload.get("relative_path"),
                "relative_path",
            ),
            sha256=_required_text(payload.get("sha256"), "source sha256"),
            sheet=payload.get("sheet"),
            header_row=header_row,
            data_start_row=payload.get("data_start_row"),
            data_end_row=payload.get("data_end_row"),
            cell_evidence=payload.get("cell_evidence", {}),
            delimiter=(
                _required_text(payload["delimiter"], "source delimiter")
                if "delimiter" in payload
                else "auto"
            ),
            decimal=(
                _required_text(payload["decimal"], "source decimal")
                if "decimal" in payload
                else "."
            ),
        )
