"""Validate declarative transformation and request-patch parameters."""

from __future__ import annotations

import math
from typing import Any
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
    DATA_MAPPING_REQUEST_PATCH_KEYS,
    _REPLICATE_MODES,
)

from sciplot_core.mapping_contract.values import (
    _required_text,
    _text_parameter,
    _text_list,
    _int_list,
    _reject_executable_keys,
    _string_mapping,
)


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
            conditions = require_json_list(parameters["where"], label="exclude where")
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
            _required_text(parameters["output_column"], "unit_convert output_column")
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
            raise ValueError("derive_ratio zero_policy must be `error` or `missing`.")
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
            raise ValueError(f"normalize_baseline has unsupported method: {method!r}")
        if method == "mean_first_n":
            n = require_json_int(parameters.get("n"), label="normalize_baseline n")
            if n <= 0:
                raise ValueError("normalize_baseline n must be positive.")
        elif "n" in parameters:
            raise ValueError("normalize_baseline n is only valid for mean_first_n.")
        if method == "explicit":
            value = require_json_number(
                parameters.get("value"), label="normalize_baseline value"
            )
            if value == 0.0:
                raise ValueError("normalize_baseline explicit value cannot be zero.")
        elif "value" in parameters:
            raise ValueError("normalize_baseline value is only valid for explicit.")
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
            raise ValueError("aggregate count_column requires include_count=true.")
        return
    raise ValueError(f"Unsupported declarative transformation: {transformation_type!r}")


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
