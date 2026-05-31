from __future__ import annotations

import ast
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd

from src.rendering.advanced_plot_axes import primary_axis, secondary_y_axis
from src.rendering.artist_tags import tag_interaction_artist
from src.rendering.expression_engine import ExpressionError, evaluate_expression, evaluate_variables
from src.rendering.models import QAReport, RenderedPlot, RenderOptions
from src.text_normalization import _clean_text

_ALLOWED_FUNCTIONS: dict[str, Callable[..., object]] = {
    "abs": abs,
    "cos": np.cos,
    "exp": np.exp,
    "log": np.log,
    "max": np.maximum,
    "min": np.minimum,
    "pow": np.power,
    "sin": np.sin,
    "sqrt": np.sqrt,
    "tan": np.tan,
}
_ALLOWED_CONSTANTS = {"e": math.e, "pi": math.pi}
_VALID_Y_AXIS_TARGETS = frozenset({"y_primary", "primary", "y_secondary", "secondary"})
_MAX_EXPRESSION_LENGTH = 180
_MAX_SAMPLE_COUNT = 2000


class AnalyticalLayerPayloadDict(TypedDict):
    id: str
    enabled: bool
    kind: str
    expression: str
    x_start: float
    x_end: float
    sample_count: int
    y_axis_target: str
    label: str | None


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = _clean_text(str(value))
    return cleaned or None


def _coerce_finite_float(value: object, *, field_name: str) -> float:
    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`{field_name}` must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"`{field_name}` must be a finite number.")
    return number


def _coerce_sample_count(value: object, *, field_name: str) -> int:
    try:
        count = int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`{field_name}` must be an integer.") from exc
    if count < 2:
        raise ValueError(f"`{field_name}` must be at least 2.")
    return min(count, _MAX_SAMPLE_COUNT)


def _normalize_y_axis_target(value: object, *, field_name: str) -> str:
    cleaned = _clean_text(str(value or "y_primary")).lower()
    if cleaned not in _VALID_Y_AXIS_TARGETS:
        raise ValueError(f"`{field_name}` must be one of: y_primary, y_secondary.")
    return "y_secondary" if cleaned in {"y_secondary", "secondary"} else "y_primary"


def _assert_safe_expression_node(node: ast.AST, *, expression: str) -> None:
    if isinstance(node, ast.Expression):
        _assert_safe_expression_node(node.body, expression=expression)
        return
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ValueError("Function expressions may only contain numeric constants.")
        return
    if isinstance(node, ast.Name):
        if node.id != "x" and node.id not in _ALLOWED_CONSTANTS:
            raise ValueError(f"Function expression uses unsupported name `{node.id}`.")
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)):
            raise ValueError("Function expression uses an unsupported binary operator.")
        _assert_safe_expression_node(node.left, expression=expression)
        _assert_safe_expression_node(node.right, expression=expression)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise ValueError("Function expression uses an unsupported unary operator.")
        _assert_safe_expression_node(node.operand, expression=expression)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
            raise ValueError("Function expression calls an unsupported function.")
        for arg in node.args:
            _assert_safe_expression_node(arg, expression=expression)
        if node.keywords:
            raise ValueError("Function expression calls cannot use keyword arguments.")
        return
    raise ValueError(f"Function expression contains unsupported syntax: {expression!r}.")


def compile_safe_function_expression(expression: str) -> Callable[[np.ndarray], np.ndarray]:
    cleaned = _clean_text(expression)
    if not cleaned:
        raise ValueError("Function expression must not be empty.")
    if len(cleaned) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("Function expression is too long.")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Function expression is not valid Python math syntax.") from exc
    _assert_safe_expression_node(tree, expression=cleaned)

    def _evaluate(x_values: np.ndarray) -> np.ndarray:
        frame = np.asarray(x_values, dtype=float)
        try:
            values = evaluate_expression(
                cleaned,
                frame=pd.DataFrame({"x": frame}),
                expect="numeric",
                label="Function expression",
            ).to_numpy(dtype=float)
        except ExpressionError as exc:
            raise ValueError(str(exc)) from exc
        if not np.isfinite(values).any():
            raise ValueError("Function expression produced no finite y values.")
        return values

    return _evaluate


def normalize_analytical_layers_payload(value: object) -> tuple[AnalyticalLayerPayloadDict, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
        raise ValueError("`analytical_layers` must be a list of mappings.")
    layers: list[AnalyticalLayerPayloadDict] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(value):
        if not isinstance(raw_item, Mapping):
            raise ValueError("`analytical_layers` items must be mappings.")
        item = cast(Mapping[str, object], raw_item)
        layer_id = _clean_text(str(item.get("id", f"function-{index + 1}")))
        if not layer_id:
            raise ValueError(f"`analytical_layers[{index}].id` must not be empty.")
        if layer_id in seen_ids:
            raise ValueError("`analytical_layers` ids must be unique.")
        seen_ids.add(layer_id)

        kind = _clean_text(str(item.get("kind", "function"))).lower()
        if kind != "function":
            raise ValueError("`analytical_layers` currently supports only kind `function`.")
        expression = _clean_text(str(item.get("expression", "")))
        compile_safe_function_expression(expression)
        x_start = _coerce_finite_float(item.get("x_start", 0.0), field_name=f"analytical_layers[{index}].x_start")
        x_end = _coerce_finite_float(item.get("x_end", 1.0), field_name=f"analytical_layers[{index}].x_end")
        if math.isclose(x_start, x_end):
            raise ValueError(f"`analytical_layers[{index}].x_start` and `x_end` must differ.")
        if x_end < x_start:
            x_start, x_end = x_end, x_start
        layers.append(
            AnalyticalLayerPayloadDict(
                id=layer_id,
                enabled=bool(item.get("enabled", True)),
                kind="function",
                expression=expression,
                x_start=x_start,
                x_end=x_end,
                sample_count=_coerce_sample_count(
                    item.get("sample_count", 200),
                    field_name=f"analytical_layers[{index}].sample_count",
                ),
                y_axis_target=_normalize_y_axis_target(
                    item.get("y_axis_target", "y_primary"),
                    field_name=f"analytical_layers[{index}].y_axis_target",
                ),
                label=_clean_optional_text(item.get("label")),
            )
        )
    return tuple(layers) if layers else None


def analytical_layers_from_payload(value: object) -> tuple[AnalyticalLayerPayloadDict, ...]:
    return normalize_analytical_layers_payload(value) or ()


def _append_autofix(report: QAReport | None, *, autofix_id: str) -> QAReport | None:
    if report is None:
        return None
    if autofix_id in report.autofixes_applied:
        return report
    return replace(report, autofixes_applied=report.autofixes_applied + (autofix_id,))


def apply_analytical_layers(rendered: RenderedPlot, *, options: RenderOptions) -> RenderedPlot:
    layers = [layer for layer in analytical_layers_from_payload(options.analytical_layers) if layer["enabled"]]
    if not layers:
        return rendered
    primary = primary_axis(rendered)
    if primary is None:
        return rendered
    secondary = secondary_y_axis(rendered)

    applied = False
    for layer in layers:
        x_values = np.linspace(layer["x_start"], layer["x_end"], layer["sample_count"])
        try:
            variables = evaluate_variables(options.data_variables, frame=pd.DataFrame({"x": x_values}))
            y_values = evaluate_expression(
                layer["expression"],
                frame=pd.DataFrame({"x": x_values}),
                variables=variables,
                expect="numeric",
                label="Function expression",
            ).to_numpy(dtype=float)
        except ExpressionError as exc:
            raise ValueError(str(exc)) from exc
        mask = np.isfinite(x_values) & np.isfinite(y_values)
        if not mask.any():
            continue
        target_axis = (
            secondary
            if layer["y_axis_target"] == "y_secondary"
            and secondary is not None
            and hasattr(secondary, "plot")
            else primary
        )
        (line,) = target_axis.plot(
            x_values[mask],
            y_values[mask],
            label=layer["label"] or layer["expression"],
            linestyle="--",
            linewidth=1.0,
            alpha=0.92,
            zorder=4.6,
        )
        tag_interaction_artist(
            line,
            payload_type="analytical_layer",
            payload_id=layer["id"],
            kind="analytical_layer",
            label=layer["label"] or layer["expression"],
            operations=("select", "quick_edit", "more"),
        )
        applied = True

    if not applied:
        return rendered
    if primary.get_legend() is None:
        primary.legend(loc="upper right")
    return replace(rendered, qa_report=_append_autofix(rendered.qa_report, autofix_id="analytical_function_layer"))


__all__ = [
    "apply_analytical_layers",
    "analytical_layers_from_payload",
    "compile_safe_function_expression",
    "normalize_analytical_layers_payload",
]
