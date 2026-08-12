"""Preflight the one named recipe allowed to consume the DMA FigurePlan."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
    DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
    DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
    DMA_TEMPERATURE_RECIPE,
    DMA_TEMPERATURE_RULE_ID,
    DMA_TEMPERATURE_TEMPLATE,
    DMA_TEMPERATURE_X_LABEL,
    DMA_TEMPERATURE_X_METRIC,
    DMA_TEMPERATURE_Y_LABEL,
    DMA_TEMPERATURE_Y_METRIC,
)
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.figure_plan.dma_temperature_resolution import (
    DmaTemperatureSourceFacts,
)
from sciplot_core.request_contract import normalize_render_options
from sciplot_core.workflow.dma_temperature_plan import (
    require_dma_temperature_execution_plan,
)

if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source import (
        ResolvedScientificSource,
    )


_FORGED_TERMINAL_FIELDS = frozenset(
    {
        "axis_data_visibility",
        "palette_resolution",
        "resolved_figure_task",
        "series_encoding_contract",
    }
)
_UNIT_FIELDS = {
    "x_unit": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
    "canonical_x_unit": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
    "display_x_unit": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
    "y_unit": DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
    "canonical_y_unit": DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
    "display_y_unit": DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
}


@dataclass(frozen=True, slots=True)
class DmaNamedRecipePlanBinding:
    """Closed pre-render proof that the recipe owns no independent selection."""

    plan_id: str
    plan_sha256: str
    source_sha256: str
    sample_order: tuple[str, ...]
    point_counts: tuple[int, ...]
    explicit_render_option_keys: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": "sciplot_dma_named_recipe_plan_binding",
            "version": 1,
            "route": "recipe",
            "recipe": DMA_TEMPERATURE_RECIPE,
            "rule_id": DMA_TEMPERATURE_RULE_ID,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "source_sha256": self.source_sha256,
            "sample_order": list(self.sample_order),
            "point_counts": list(self.point_counts),
            "metric_binding": {
                "x_metric": DMA_TEMPERATURE_X_METRIC,
                "y_metric": DMA_TEMPERATURE_Y_METRIC,
            },
            "units": {
                "canonical_temperature": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
                "canonical_modulus": DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
                "display_modulus": DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
            },
            "template": DMA_TEMPERATURE_TEMPLATE,
            "explicit_render_option_keys": list(self.explicit_render_option_keys),
            "selection_authority": "resolved_figure_plan",
            "render_option_authority": (
                "semantic_rule_then_explicit_request_no_recipe_defaults"
            ),
            "terminal_evidence_authorities": [
                "spec.series_encoding_contract",
                "spec.axis_data_visibility",
            ],
        }


def bind_dma_named_recipe_request(
    *,
    requested_recipe: str,
    request: dict[str, Any],
    semantic: dict[str, Any],
    plan: ResolvedFigurePlan,
    input_path: Path,
    resolved_scientific_source: ResolvedScientificSource | None = None,
) -> DmaNamedRecipePlanBinding:
    """Reject every recipe/plan conflict before semantic preparation writes."""

    if requested_recipe != DMA_TEMPERATURE_RECIPE:
        _conflict("recipe", requested_recipe, DMA_TEMPERATURE_RECIPE)
    if request.get("recipe") != requested_recipe:
        _conflict("captured recipe", request.get("recipe"), requested_recipe)
    if request.get("rule_id") != DMA_TEMPERATURE_RULE_ID:
        _conflict("rule", request.get("rule_id"), DMA_TEMPERATURE_RULE_ID)
    if (
        semantic.get("rule_id") != DMA_TEMPERATURE_RULE_ID
        or semantic.get("semantic_family") != DMA_TEMPERATURE_RULE_ID
        or semantic.get("recommended_recipe") != DMA_TEMPERATURE_RECIPE
    ):
        raise ValueError(
            "dma_named_recipe_semantic_mismatch: rheology_dma requires the "
            "ready dma_temperature_sweep semantic contract."
        )
    if (
        semantic.get("needs_ai_intervention") is True
        or semantic.get("rule_readiness") != "ready"
    ):
        raise ValueError(
            "dma_named_recipe_semantic_not_ready: the named recipe cannot "
            "bypass DMA semantic readiness or intervention."
        )

    facts = require_dma_temperature_execution_plan(
        plan,
        source=input_path,
        resolved_scientific_source=resolved_scientific_source,
    )
    _validate_request_identity(request, sample_order=facts.sample_order)
    render_options = _validated_render_options(request)
    _validate_render_series_identity(
        render_options,
        sample_order=facts.sample_order,
    )
    _validate_axis_visibility_options(render_options, facts=facts)
    explicit_keys = _explicit_option_keys(request, render_options=render_options)
    return DmaNamedRecipePlanBinding(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        source_sha256=facts.source_sha256,
        sample_order=facts.sample_order,
        point_counts=facts.point_counts,
        explicit_render_option_keys=explicit_keys,
    )


def _validate_request_identity(
    request: dict[str, Any],
    *,
    sample_order: tuple[str, ...],
) -> None:
    forged = sorted(_FORGED_TERMINAL_FIELDS.intersection(request))
    if forged:
        raise ValueError(
            "dma_named_recipe_terminal_evidence_forged: terminal evidence is "
            "renderer-owned, not request-owned: " + ", ".join(forged)
        )
    _optional_exact(request, "template", DMA_TEMPERATURE_TEMPLATE)
    _optional_exact(request, "x_metric", DMA_TEMPERATURE_X_METRIC)
    _optional_exact(request, "y_metric", DMA_TEMPERATURE_Y_METRIC)
    _optional_exact(request, "x_label", DMA_TEMPERATURE_X_LABEL)
    _optional_exact(request, "y_label", DMA_TEMPERATURE_Y_LABEL)
    for field, expected in _UNIT_FIELDS.items():
        _optional_exact(request, field, expected)
    if "series_order" in request and request["series_order"] not in (
        None,
        [],
        list(sample_order),
        sample_order,
    ):
        _conflict("sample order", request["series_order"], list(sample_order))


def _validated_render_options(request: dict[str, Any]) -> dict[str, Any]:
    raw = request.get("render_options")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            "dma_named_recipe_render_options_invalid: render_options must be an object."
        )
    normalized = normalize_render_options(raw, template=DMA_TEMPERATURE_TEMPLATE)
    for field in ("series_order", "series_include"):
        value = normalized.get(field)
        request_order = request.get("series_order")
        if field == "series_order" and value and request_order not in (None, [], value):
            _conflict("sample order authorities", value, request_order)
    _optional_exact(normalized, "x_label_override", DMA_TEMPERATURE_X_LABEL)
    _optional_exact(normalized, "y_label_override", DMA_TEMPERATURE_Y_LABEL)
    _optional_exact(normalized, "xscale", "linear")
    _optional_exact(normalized, "yscale", "linear")
    _optional_exact(normalized, "reverse_x", False)
    if "data_variables" in normalized:
        raise ValueError(
            "dma_named_recipe_metric_conflict: the FigureTask owns the DMA "
            "temperature/storage-modulus metric binding."
        )
    return normalized


def _validate_render_series_identity(
    options: dict[str, Any],
    *,
    sample_order: tuple[str, ...],
) -> None:
    expected = list(sample_order)
    for field in ("series_order", "series_include"):
        value = options.get(field)
        if value not in (None, [], expected, sample_order):
            _conflict(field, value, expected)


def _validate_axis_visibility_options(
    options: dict[str, Any],
    *,
    facts: DmaTemperatureSourceFacts,
) -> None:
    _reject_clipping_bound(
        options,
        field="x_min",
        data_edge=facts.minimum_temperature_C,
        clips=lambda bound, edge: bound > edge,
    )
    _reject_clipping_bound(
        options,
        field="x_max",
        data_edge=facts.maximum_temperature_C,
        clips=lambda bound, edge: bound < edge,
    )
    y_min = options.get("y_min")
    if y_min is not None:
        bound = _finite_bound(y_min, field="y_min")
        if not math.isclose(bound, 0.0, abs_tol=1e-12) and (
            bound > facts.minimum_display_value_MPa
        ):
            _axis_conflict("y_min", bound, facts.minimum_display_value_MPa)
    _reject_clipping_bound(
        options,
        field="y_max",
        data_edge=facts.maximum_display_value_MPa,
        clips=lambda bound, edge: bound < edge,
    )


def _reject_clipping_bound(
    options: dict[str, Any],
    *,
    field: str,
    data_edge: float,
    clips: Callable[[float, float], bool],
) -> None:
    if options.get(field) is None:
        return
    bound = _finite_bound(options[field], field=field)
    if clips(bound, data_edge):
        _axis_conflict(field, bound, data_edge)


def _finite_bound(value: object, *, field: str) -> float:
    try:
        bound = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"dma_named_recipe_axis_conflict: {field} must be finite."
        ) from exc
    if not math.isfinite(bound):
        raise ValueError(f"dma_named_recipe_axis_conflict: {field} must be finite.")
    return bound


def _explicit_option_keys(
    request: dict[str, Any],
    *,
    render_options: dict[str, Any],
) -> tuple[str, ...]:
    raw = request.get("explicit_render_option_keys", [])
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item for item in raw
    ):
        raise ValueError(
            "dma_named_recipe_encoding_conflict: explicit render-option keys "
            "must be a list of non-empty strings."
        )
    keys = tuple(raw)
    if len(keys) != len(set(keys)) or not set(keys).issubset(render_options):
        raise ValueError(
            "dma_named_recipe_encoding_conflict: explicit render-option keys "
            "must uniquely reference the shared render_options object."
        )
    return keys


def _optional_exact(values: dict[str, Any], field: str, expected: object) -> None:
    if field in values and values[field] is not None and values[field] != expected:
        _conflict(field, values[field], expected)


def _axis_conflict(field: str, value: float, data_edge: float) -> None:
    raise ValueError(
        "dma_named_recipe_axis_visibility_conflict: explicit "
        f"{field}={value} would exclude the source edge {data_edge}."
    )


def _conflict(field: str, actual: object, expected: object) -> None:
    raise ValueError(
        "dma_named_recipe_plan_conflict: "
        f"{field}={actual!r} does not match {expected!r}."
    )


__all__ = ["DmaNamedRecipePlanBinding", "bind_dma_named_recipe_request"]
