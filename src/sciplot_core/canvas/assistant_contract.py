from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
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
DATA_MAPPING_PROPOSAL_VERSION = 2
DATA_MAPPING_CONFIRMATION_KIND = "sciplot_data_mapping_confirmation"
DATA_MAPPING_CONFIRMATION_VERSION = 1

DECLARATIVE_TRANSFORMATIONS = frozenset(
    {
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
)
DATA_COLUMN_ROLES = frozenset(
    {
        "x",
        "y",
        "z",
        "value",
        "sample",
        "replicate",
        "category",
        "x_error",
        "y_error",
        "metadata",
    }
)
DATA_MAPPING_REQUEST_PATCH_KEYS = frozenset(
    {
        "recipe",
        "rule_id",
        "template",
        "x_metric",
        "y_metric",
        "z_metric",
        "series_order",
        "replicate_mode",
    }
)
_REPLICATE_MODES = frozenset({"mean", "representative", "individual"})
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_EXECUTABLE_KEYS = {
    "python",
    "code",
    "script",
    "command",
    "shell",
    "executable",
    "expression",
    "eval",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: object, label: str) -> str:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset.")
    return text


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


def _free_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    return value.strip()


def _text_parameter(
    parameters: dict[str, Any],
    key: str,
    *,
    default: str,
    label: str,
) -> str:
    if key not in parameters:
        return default
    return _required_text(parameters[key], label)


def _safe_id(value: object, label: str) -> str:
    text = _required_text(value, label)
    if _SAFE_ID.fullmatch(text) is None:
        raise ValueError(
            f"{label} must use 1-96 ASCII letters, digits, dot, underscore, or dash."
        )
    return text


def _sha256(value: object, label: str) -> str:
    digest = _required_text(value, label).casefold()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _relative_source_path(value: object) -> str:
    text = _required_text(value, "relative_path")
    if "\\" in text:
        raise ValueError("Data source relative_path must use POSIX separators.")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(
            "Data source relative_path must remain inside the declared source root."
        )
    return path.as_posix()


def _text_list(
    value: object,
    *,
    label: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = require_json_list(value, label=label)
    result = tuple(_required_text(item, f"{label} item") for item in items)
    if not allow_empty and not result:
        raise ValueError(f"{label} must not be empty.")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain unique values.")
    return result


def _int_list(value: object, *, label: str) -> tuple[int, ...]:
    items = require_json_list(value, label=label)
    result = tuple(require_json_int(item, label=f"{label} item") for item in items)
    if any(item < 0 for item in result):
        raise ValueError(f"{label} values must be non-negative.")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain unique values.")
    return result


def _reject_executable_keys(value: Any, *, path: str = "parameters") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in _FORBIDDEN_EXECUTABLE_KEYS:
                raise ValueError(
                    f"{path}.{key} is executable content and is not allowed."
                )
            _reject_executable_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_executable_keys(item, path=f"{path}[{index}]")


def _string_mapping(value: object, *, label: str) -> dict[str, str]:
    payload = require_json_object(value, label=label)
    result = {
        _required_text(key, f"{label} key"): _required_text(
            item, f"{label}[{key!r}]"
        )
        for key, item in payload.items()
    }
    if not result:
        raise ValueError(f"{label} must not be empty.")
    return result


def _validate_condition(payload: dict[str, Any], *, label: str) -> None:
    reject_unknown_keys(
        payload,
        {"column", "operator", "value"},
        label=label,
    )
    _required_text(payload.get("column"), f"{label} column")
    operator = _required_text(payload.get("operator"), f"{label} operator")
    supported = {
        "eq",
        "ne",
        "in",
        "not_in",
        "lt",
        "lte",
        "gt",
        "gte",
        "is_missing",
        "not_missing",
    }
    if operator not in supported:
        raise ValueError(f"{label} has unsupported operator: {operator!r}")
    if operator in {"is_missing", "not_missing"}:
        if "value" in payload:
            raise ValueError(f"{label} {operator} must not define value.")
        return
    if "value" not in payload:
        raise ValueError(f"{label} {operator} requires value.")
    if operator in {"in", "not_in"}:
        values = require_json_list(payload["value"], label=f"{label} value")
        if not values:
            raise ValueError(f"{label} {operator} value must not be empty.")
    elif operator in {"lt", "lte", "gt", "gte"}:
        require_json_number(payload["value"], label=f"{label} value")
    _validate_json_value(payload["value"], path=f"{label}.value")


def _validate_transform_parameters(
    transformation_type: str,
    parameters: dict[str, Any],
) -> None:
    label = f"{transformation_type} parameters"
    if transformation_type == "rename":
        reject_unknown_keys(parameters, {"columns"}, label=label)
        _string_mapping(parameters.get("columns"), label="rename columns")
        return
    if transformation_type == "select":
        reject_unknown_keys(parameters, {"columns"}, label=label)
        _text_list(parameters.get("columns"), label="select columns")
        return
    if transformation_type == "exclude":
        reject_unknown_keys(
            parameters,
            {"columns", "row_indices", "where", "match"},
            label=label,
        )
        has_selector = False
        if "columns" in parameters:
            _text_list(parameters["columns"], label="exclude columns")
            has_selector = True
        if "row_indices" in parameters:
            _int_list(parameters["row_indices"], label="exclude row_indices")
            has_selector = True
        if "where" in parameters:
            conditions = require_json_list(
                parameters["where"], label="exclude where"
            )
            if not conditions or not all(isinstance(item, dict) for item in conditions):
                raise ValueError("exclude where must contain condition objects.")
            for index, condition in enumerate(conditions):
                _validate_condition(condition, label=f"exclude where[{index}]")
            match = _text_parameter(
                parameters,
                "match",
                default="all",
                label="exclude match",
            )
            if match not in {"all", "any"}:
                raise ValueError("exclude match must be `all` or `any`.")
            has_selector = True
        elif "match" in parameters:
            raise ValueError("exclude match is only valid with where.")
        if not has_selector:
            raise ValueError("exclude requires columns, row_indices, or where.")
        return
    if transformation_type == "drop_missing":
        reject_unknown_keys(parameters, {"columns", "how"}, label=label)
        if "columns" in parameters:
            _text_list(parameters["columns"], label="drop_missing columns")
        how = _text_parameter(
            parameters,
            "how",
            default="any",
            label="drop_missing how",
        )
        if how not in {"any", "all"}:
            raise ValueError("drop_missing how must be `any` or `all`.")
        return
    if transformation_type == "sort":
        reject_unknown_keys(
            parameters,
            {"by", "ascending", "na_position"},
            label=label,
        )
        by = _text_list(parameters.get("by"), label="sort by")
        ascending = parameters.get("ascending", True)
        if isinstance(ascending, list):
            values = [
                require_json_bool(item, label="sort ascending item")
                for item in ascending
            ]
            if len(values) != len(by):
                raise ValueError("sort ascending list must match sort by length.")
        else:
            require_json_bool(ascending, label="sort ascending")
        na_position = _text_parameter(
            parameters,
            "na_position",
            default="last",
            label="sort na_position",
        )
        if na_position not in {"first", "last"}:
            raise ValueError("sort na_position must be `first` or `last`.")
        return
    if transformation_type == "unit_convert":
        reject_unknown_keys(
            parameters,
            {"column", "from_unit", "to_unit", "output_column"},
            label=label,
        )
        _required_text(parameters.get("column"), "unit_convert column")
        source = _required_text(parameters.get("from_unit"), "unit_convert from_unit")
        target = _required_text(parameters.get("to_unit"), "unit_convert to_unit")
        if source == target:
            raise ValueError("unit_convert source and target units must differ.")
        if "output_column" in parameters:
            _required_text(
                parameters["output_column"], "unit_convert output_column"
            )
        return
    if transformation_type == "derive_ratio":
        reject_unknown_keys(
            parameters,
            {"numerator", "denominator", "output", "scale", "zero_policy"},
            label=label,
        )
        _required_text(parameters.get("numerator"), "derive_ratio numerator")
        _required_text(parameters.get("denominator"), "derive_ratio denominator")
        _required_text(parameters.get("output"), "derive_ratio output")
        scale = require_json_number(parameters.get("scale", 1.0), label="scale")
        if not math.isfinite(scale):
            raise ValueError("derive_ratio scale must be finite.")
        zero_policy = _text_parameter(
            parameters,
            "zero_policy",
            default="error",
            label="derive_ratio zero_policy",
        )
        if zero_policy not in {
            "error",
            "missing",
        }:
            raise ValueError(
                "derive_ratio zero_policy must be `error` or `missing`."
            )
        return
    if transformation_type == "normalize_baseline":
        reject_unknown_keys(
            parameters,
            {"column", "output", "method", "n", "value"},
            label=label,
        )
        _required_text(parameters.get("column"), "normalize_baseline column")
        _required_text(parameters.get("output"), "normalize_baseline output")
        method = _text_parameter(
            parameters,
            "method",
            default="first_finite",
            label="normalize_baseline method",
        )
        supported = {
            "first_finite",
            "last_finite",
            "max_abs",
            "mean_first_n",
            "explicit",
        }
        if method not in supported:
            raise ValueError(
                f"normalize_baseline has unsupported method: {method!r}"
            )
        if method == "mean_first_n":
            n = require_json_int(parameters.get("n"), label="normalize_baseline n")
            if n <= 0:
                raise ValueError("normalize_baseline n must be positive.")
        elif "n" in parameters:
            raise ValueError(
                "normalize_baseline n is only valid for mean_first_n."
            )
        if method == "explicit":
            value = require_json_number(
                parameters.get("value"), label="normalize_baseline value"
            )
            if value == 0.0:
                raise ValueError("normalize_baseline explicit value cannot be zero.")
        elif "value" in parameters:
            raise ValueError(
                "normalize_baseline value is only valid for explicit."
            )
        return
    if transformation_type == "aggregate_replicates":
        reject_unknown_keys(
            parameters,
            {
                "group_by",
                "value_columns",
                "method",
                "include_count",
                "count_column",
            },
            label=label,
        )
        _text_list(parameters.get("group_by"), label="aggregate group_by")
        _text_list(
            parameters.get("value_columns"),
            label="aggregate value_columns",
        )
        method = _text_parameter(
            parameters,
            "method",
            default="mean",
            label="aggregate method",
        )
        if method not in {"mean", "median"}:
            raise ValueError("aggregate method must be `mean` or `median`.")
        include_count = require_json_bool(
            parameters.get("include_count", True),
            label="aggregate include_count",
        )
        if include_count:
            _required_text(
                parameters.get("count_column", "replicate_count"),
                "aggregate count_column",
            )
        elif "count_column" in parameters:
            raise ValueError(
                "aggregate count_column requires include_count=true."
            )
        return
    raise ValueError(
        f"Unsupported declarative transformation: {transformation_type!r}"
    )


def _validate_request_patch(value: object) -> dict[str, Any]:
    patch = dict(require_json_object(value, label="request_patch"))
    reject_unknown_keys(
        patch,
        set(DATA_MAPPING_REQUEST_PATCH_KEYS),
        label="DataMappingProposal request_patch",
    )
    for key in ("recipe", "rule_id", "template", "x_metric", "y_metric", "z_metric"):
        if key in patch:
            patch[key] = _required_text(patch[key], f"request_patch {key}")
    if "series_order" in patch:
        patch["series_order"] = list(
            _text_list(patch["series_order"], label="request_patch series_order")
        )
    if "replicate_mode" in patch:
        mode = _required_text(
            patch["replicate_mode"], "request_patch replicate_mode"
        ).casefold()
        if mode not in _REPLICATE_MODES:
            raise ValueError(
                "request_patch replicate_mode must be mean, representative, or individual."
            )
        patch["replicate_mode"] = mode
    _validate_json_value(patch, path="request_patch")
    _reject_executable_keys(patch, path="request_patch")
    return patch


@dataclass(frozen=True)
class DataSourceReference:
    source_id: str
    relative_path: str
    sha256: str
    sheet: str | int | None = None
    header_row: int | None = 0
    delimiter: str = "auto"
    decimal: str = "."

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        object.__setattr__(
            self, "relative_path", _relative_source_path(self.relative_path)
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "source sha256"))
        if isinstance(self.sheet, bool) or not isinstance(
            self.sheet, str | int | None
        ):
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "sheet": self.sheet,
            "header_row": self.header_row,
            "delimiter": self.delimiter,
            "decimal": self.decimal,
        }

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
        index = require_json_int(
            self.source_column_index, label="source_column_index"
        )
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
            raise ValueError(
                "DataMappingProposal requires DataColumnMapping entries."
            )
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
        if not any(
            column.role in {"x", "y", "z", "value"}
            for column in self.columns
        ):
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
            transformation.transformation_id
            for transformation in self.transformations
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
        return {
            source.relative_path: source.sha256 for source in self.sources
        }

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
                transformation.to_dict()
                for transformation in self.transformations
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
            raise ValueError(
                f"Unsupported DataMappingProposal version: {version!r}"
            )
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
            sources=tuple(
                DataSourceReference.from_dict(item) for item in raw_sources
            ),
            columns=tuple(
                DataColumnMapping.from_dict(item) for item in raw_columns
            ),
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
        if "requires_confirmation" in payload and require_json_bool(
            payload["requires_confirmation"], label="requires_confirmation"
        ) is not True:
            raise ValueError(
                "DataMappingProposal version 2 always requires external confirmation."
            )
        if "executable" in payload and require_json_bool(
            payload["executable"], label="executable"
        ) is not False:
            raise ValueError(
                "DataMappingProposal cannot self-authorize execution."
            )
        return proposal


@dataclass(frozen=True)
class DataMappingConfirmation:
    proposal_id: str
    proposal_sha256: str
    base_request_sha256: str
    source_hashes: dict[str, str]
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
            _relative_source_path(path): _sha256(
                digest, f"source_hashes[{path!r}]"
            )
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
            confirmed_by=_required_text(
                payload.get("confirmed_by"),
                "confirmed_by",
            ),
            confirmed_at=_required_text(
                payload.get("confirmed_at"),
                "confirmed_at",
            ),
        )


__all__ = [
    "DATA_COLUMN_ROLES",
    "DATA_MAPPING_CONFIRMATION_KIND",
    "DATA_MAPPING_CONFIRMATION_VERSION",
    "DATA_MAPPING_PROPOSAL_KIND",
    "DATA_MAPPING_PROPOSAL_VERSION",
    "DATA_MAPPING_REQUEST_PATCH_KEYS",
    "DECLARATIVE_TRANSFORMATIONS",
    "DataColumnMapping",
    "DataMappingConfirmation",
    "DataMappingProposal",
    "DataSourceReference",
    "DeclarativeTransformation",
]
