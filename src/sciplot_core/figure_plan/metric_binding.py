"""Closed metric bindings for selected figure tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_list,
    require_json_object,
)

from sciplot_core.figure_plan.payload_types import (
    CartesianMetricBindingPayload,
    OrderedMetricsBindingPayload,
)
from sciplot_core.figure_plan.values import required_text, text_tuple


@dataclass(frozen=True, slots=True)
class CartesianMetricBinding:
    """One real x/y metric pair."""

    x_metric: str
    y_metric: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "x_metric",
            required_text(self.x_metric, label="metric_binding.x_metric"),
        )
        object.__setattr__(
            self,
            "y_metric",
            required_text(self.y_metric, label="metric_binding.y_metric"),
        )

    def to_payload(self) -> CartesianMetricBindingPayload:
        return {
            "kind": "cartesian_xy",
            "x_metric": self.x_metric,
            "y_metric": self.y_metric,
        }


@dataclass(frozen=True, slots=True)
class OrderedMetricsBinding:
    """One ordered, unique set of real metric identities."""

    metric_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        metric_ids = text_tuple(
            self.metric_ids,
            label="metric_binding.metric_ids",
        )
        if not metric_ids:
            raise ValueError("metric_binding.metric_ids must not be empty.")
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("metric_binding.metric_ids must be unique.")
        object.__setattr__(self, "metric_ids", metric_ids)

    def to_payload(self) -> OrderedMetricsBindingPayload:
        return {
            "kind": "ordered_metrics",
            "metric_ids": list(self.metric_ids),
        }


FigureMetricBinding: TypeAlias = CartesianMetricBinding | OrderedMetricsBinding


def metric_binding_from_payload(value: object) -> FigureMetricBinding:
    """Parse one closed v2 metric binding."""

    payload = require_json_object(value, label="FigureTask.metric_binding")
    kind = payload.get("kind")
    if kind == "cartesian_xy":
        reject_unknown_keys(
            payload,
            {"kind", "x_metric", "y_metric"},
            label="FigureTask.metric_binding",
        )
        return CartesianMetricBinding(
            x_metric=required_text(
                payload.get("x_metric"),
                label="FigureTask.metric_binding.x_metric",
            ),
            y_metric=required_text(
                payload.get("y_metric"),
                label="FigureTask.metric_binding.y_metric",
            ),
        )
    if kind == "ordered_metrics":
        reject_unknown_keys(
            payload,
            {"kind", "metric_ids"},
            label="FigureTask.metric_binding",
        )
        return OrderedMetricsBinding(
            metric_ids=text_tuple(
                require_json_list(
                    payload.get("metric_ids"),
                    label="FigureTask.metric_binding.metric_ids",
                ),
                label="FigureTask.metric_binding.metric_ids",
            )
        )
    raise ValueError("FigureTask.metric_binding has an unsupported kind.")


__all__ = [
    "CartesianMetricBinding",
    "FigureMetricBinding",
    "OrderedMetricsBinding",
    "metric_binding_from_payload",
]
