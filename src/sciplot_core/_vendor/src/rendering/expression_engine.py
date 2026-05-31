from __future__ import annotations

import ast
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

import numpy as np
import pandas as pd


class ExpressionError(ValueError):
    """Raised for user-facing safe expression evaluation errors."""


_ALLOWED_FUNCTIONS = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "asin": np.arcsin,
    "acos": np.arccos,
    "atan": np.arctan,
    "atan2": np.arctan2,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "exp": np.exp,
    "log": np.log,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "pow": np.power,
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
    "floor": np.floor,
    "ceil": np.ceil,
    "round": np.round,
    "mod": np.mod,
}
_ALLOWED_CONSTANTS = {"pi": math.pi, "e": math.e}
_MAX_EXPRESSION_LENGTH = 500
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _coerce_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    return frame if frame is not None else pd.DataFrame()


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _broadcast_scalar(value: object, row_count: int) -> pd.Series:
    length = row_count if row_count > 0 else 1
    return pd.Series([value] * length).reset_index(drop=True)


def _normalize_column_series(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        return numeric.reset_index(drop=True)
    return series.reset_index(drop=True)


def _columns_for_frame(frame: pd.DataFrame) -> dict[str, pd.Series]:
    columns: dict[str, pd.Series] = {}
    for column in frame.columns:
        columns[str(column)] = _normalize_column_series(frame[column])
    return columns


def _series_from_result(result: object, *, row_count: int, expect: str, label: str) -> pd.Series:
    if isinstance(result, pd.Series):
        series = result.reset_index(drop=True)
    elif isinstance(result, np.ndarray):
        if result.shape == ():
            series = _broadcast_scalar(result.item(), row_count)
        elif result.size == row_count:
            series = pd.Series(result.reshape(-1)).reset_index(drop=True)
        else:
            raise ExpressionError(f"{label}: expression result length does not match the table.")
    elif isinstance(result, (bool, np.bool_, int, float, np.number, str)):
        series = _broadcast_scalar(result, row_count)
    else:
        raise ExpressionError(f"{label}: expression produced an unsupported result.")
    expected_length = row_count if row_count > 0 else len(series)
    if len(series) != expected_length:
        raise ExpressionError(f"{label}: expression result length does not match the table.")
    if expect == "numeric":
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.isna().any():
            raise ExpressionError(f"{label}: expression produced a nonnumeric result.")
        return numeric.reset_index(drop=True)
    if expect == "boolean":
        if series.dtype == bool:
            return series.astype(bool).reset_index(drop=True)
        if not all(isinstance(value, (bool, np.bool_)) for value in series.tolist()):
            raise ExpressionError(f"{label}: expression produced a non-boolean result.")
        return series.astype(bool).reset_index(drop=True)
    return series.reset_index(drop=True)


def _compare(left: object, right: object, op: ast.cmpop) -> object:
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    left_numeric = cast(Any, pd.to_numeric(left, errors="coerce") if isinstance(left, pd.Series) else left)
    right_numeric = cast(Any, pd.to_numeric(right, errors="coerce") if isinstance(right, pd.Series) else right)
    if isinstance(op, ast.Lt):
        return left_numeric < right_numeric
    if isinstance(op, ast.LtE):
        return left_numeric <= right_numeric
    if isinstance(op, ast.Gt):
        return left_numeric > right_numeric
    if isinstance(op, ast.GtE):
        return left_numeric >= right_numeric
    raise ExpressionError("unsafe expression uses an unsupported comparison.")


def _name_column_lookup(name: str, columns: Mapping[str, pd.Series]) -> pd.Series | None:
    if name in columns:
        return columns[name]
    lowered = name.lower()
    for column_name, series in columns.items():
        if _SAFE_IDENTIFIER_RE.match(column_name) and column_name.lower() == lowered:
            return series
    return None


def evaluate_expression(
    expression: str,
    *,
    frame: pd.DataFrame | None = None,
    variables: Mapping[str, float] | None = None,
    expect: str = "numeric",
    names: Mapping[str, object] | None = None,
    label: str = "expression",
) -> pd.Series:
    cleaned = _cell_text(expression)
    if not cleaned:
        raise ExpressionError(f"{label}: expression must not be empty.")
    if len(cleaned) > _MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"{label}: unsafe expression is too long.")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"{label}: unsafe expression `{cleaned}`.") from exc
    data = _coerce_frame(frame)
    row_count = int(data.shape[0])
    columns = _columns_for_frame(data)
    variables_map = dict(variables or {})
    names_map = dict(names or {})

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str, bool)):
                return node.value
            raise ExpressionError(f"{label}: unsafe expression `{cleaned}`.")
        if isinstance(node, ast.Name):
            if node.id in names_map:
                return names_map[node.id]
            if node.id in _ALLOWED_CONSTANTS:
                return _ALLOWED_CONSTANTS[node.id]
            if node.id in _ALLOWED_FUNCTIONS:
                return _ALLOWED_FUNCTIONS[node.id]
            if node.id in variables_map:
                return variables_map[node.id]
            column = _name_column_lookup(node.id, columns)
            if column is not None:
                return column
            raise ExpressionError(f"{label}: unknown column or variable `{node.id}`.")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            value = evaluate(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value
            return ~value if isinstance(value, pd.Series) else not bool(value)
        if isinstance(node, ast.BinOp) and isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.BitAnd, ast.BitOr),
        ):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return np.power(left, right)
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.BitAnd):
                return left & right
            return left | right
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [evaluate(value) for value in node.values]
            result = values[0]
            for value in values[1:]:
                result = result & value if isinstance(node.op, ast.And) else result | value
            return result
        if isinstance(node, ast.Compare):
            left = evaluate(node.left)
            masks: list[object] = []
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = evaluate(comparator)
                masks.append(_compare(left, right, op))
                left = right
            result = masks[0]
            for mask in masks[1:]:
                result = cast(Any, result) & cast(Any, mask)
            return result
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function_name = node.func.id
            if node.keywords:
                raise ExpressionError(f"{label}: unsafe expression uses keyword arguments.")
            if function_name == "col":
                if len(node.args) != 1:
                    raise ExpressionError(f"{label}: col() requires exactly one column name.")
                column_name = evaluate(node.args[0])
                if not isinstance(column_name, str):
                    raise ExpressionError(f"{label}: col() requires a string column name.")
                if column_name not in columns:
                    raise ExpressionError(f"{label}: unknown column `{column_name}`.")
                return columns[column_name]
            if function_name == "var":
                if len(node.args) != 1:
                    raise ExpressionError(f"{label}: var() requires exactly one variable name.")
                variable_name = evaluate(node.args[0])
                if not isinstance(variable_name, str):
                    raise ExpressionError(f"{label}: var() requires a string variable name.")
                if variable_name not in variables_map:
                    raise ExpressionError(f"{label}: unknown variable `{variable_name}`.")
                return variables_map[variable_name]
            function = _ALLOWED_FUNCTIONS.get(function_name)
            if function is None:
                raise ExpressionError(f"{label}: unsafe expression uses `{function_name}`.")
            return function(*[evaluate(arg) for arg in node.args])
        raise ExpressionError(f"{label}: unsafe expression `{cleaned}`.")

    try:
        result = evaluate(tree)
    except ExpressionError:
        raise
    except Exception as exc:
        raise ExpressionError(f"{label}: unsafe expression `{cleaned}`.") from exc
    return _series_from_result(result, row_count=row_count, expect=expect, label=label)


def evaluate_variables(
    variables: object,
    *,
    frame: pd.DataFrame | None = None,
) -> dict[str, float]:
    if variables is None:
        return {}
    if not isinstance(variables, Sequence) or isinstance(variables, (str, bytes, bytearray)):
        raise ExpressionError("`data_variables` must be a list of mappings.")
    resolved: dict[str, float] = {}
    pending: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(variables):
        if not isinstance(item, Mapping):
            raise ExpressionError(f"`data_variables[{index}]` must be a mapping.")
        variable_id = _cell_text(item.get("id"))
        if not variable_id:
            raise ExpressionError(f"`data_variables[{index}].id` must not be empty.")
        if variable_id in seen:
            raise ExpressionError("`data_variables` ids must be unique.")
        seen.add(variable_id)
        if not bool(item.get("enabled", True)):
            continue
        pending.append(item)
    while pending:
        progress = False
        remaining: list[Mapping[str, Any]] = []
        for item in pending:
            variable_id = _cell_text(item.get("id"))
            kind = _cell_text(item.get("kind") or "scalar").lower()
            label = f"data_variables.{variable_id}"
            try:
                if kind == "scalar":
                    value = float(item.get("value", 0.0))
                elif kind == "expression":
                    result = evaluate_expression(
                        str(item.get("expression") or ""),
                        frame=frame,
                        variables=resolved,
                        expect="numeric",
                        label=label,
                    )
                    if len(result) == 0:
                        raise ExpressionError(f"{label}: expression variable needs at least one row.")
                    if not np.allclose(result, result.iloc[0]):
                        raise ExpressionError(f"{label}: expression variable must produce a scalar result.")
                    value = float(result.iloc[0])
                else:
                    raise ExpressionError(f"{label}: data variable kind must be scalar or expression.")
            except ExpressionError as exc:
                if "unknown variable" in str(exc):
                    remaining.append(item)
                    continue
                raise
            if not math.isfinite(value):
                raise ExpressionError(f"{label}: variable value must be finite.")
            resolved[variable_id] = value
            progress = True
        if not progress:
            unresolved = ", ".join(_cell_text(item.get("id")) for item in remaining)
            raise ExpressionError(f"`data_variables` contain unknown variable references or cycles: {unresolved}.")
        pending = remaining
    return resolved


__all__ = ["ExpressionError", "evaluate_expression", "evaluate_variables"]
