"""Exact public JSON payload types for resolved figure planning."""

from __future__ import annotations

from typing import Literal, TypeAlias, TypedDict


class FigureTaskReplicateCountPayload(TypedDict):
    sample: str
    count: int


class _FigureTaskCommonPayload(TypedDict):
    kind: Literal["sciplot_figure_task"]
    figure_id: str
    order: int
    selected: Literal[True]
    title: str
    template: str
    artifact_stem: str
    document_stem: str
    conditions: list[str]
    condition_labels: list[str]
    sample_order: list[str]
    replicate_counts: list[FigureTaskReplicateCountPayload]


class CartesianMetricBindingPayload(TypedDict):
    kind: Literal["cartesian_xy"]
    x_metric: str
    y_metric: str


class OrderedMetricsBindingPayload(TypedDict):
    kind: Literal["ordered_metrics"]
    metric_ids: list[str]


FigureMetricBindingPayload: TypeAlias = (
    CartesianMetricBindingPayload | OrderedMetricsBindingPayload
)


class FigureTaskV1Payload(_FigureTaskCommonPayload):
    version: Literal[1]
    x_metric: str
    y_metric: str


class FigureTaskV2Payload(_FigureTaskCommonPayload):
    version: Literal[2]
    metric_binding: FigureMetricBindingPayload


FigureTaskPayload: TypeAlias = FigureTaskV1Payload | FigureTaskV2Payload


FigureOutcomeStatus = Literal[
    "pending",
    "editable",
    "ready",
    "unavailable",
    "failed",
]


class FigureOutcomePayload(TypedDict):
    kind: Literal["sciplot_figure_outcome"]
    version: Literal[1]
    figure_id: str
    status: FigureOutcomeStatus
    artifacts: list[str]
    reason_code: str | None
    message: str | None


ResolvedFigurePlanStatus = Literal[
    "planned",
    "editable",
    "ready",
    "incomplete",
]


class ResolvedFigurePlanPayload(TypedDict):
    kind: Literal["sciplot_resolved_figure_plan"]
    version: Literal[1]
    plan_id: str
    plan_sha256: str
    rule_id: str
    selection_policy: str
    primary_figure_id: str
    source_sha256: str | None
    selected_figure_ids: list[str]
    tasks: list[FigureTaskPayload]
    outcomes: list[FigureOutcomePayload]
    status: ResolvedFigurePlanStatus
    complete: bool


class _FigurePlanGateCollectionsPayload(TypedDict):
    selected_figure_ids: list[str]
    ready_figure_ids: list[str]
    incomplete_figure_ids: list[str]


class FigurePlanGateInvalidPayload(_FigurePlanGateCollectionsPayload):
    valid: Literal[False]
    complete: Literal[False]
    plan_id: None
    plan_sha256: None
    reason: str


class FigurePlanGateValidPayload(_FigurePlanGateCollectionsPayload):
    valid: Literal[True]
    complete: bool
    plan_id: str
    plan_sha256: str
    source_sha256: str | None
    reason: str | None


FigurePlanGatePayload = FigurePlanGateInvalidPayload | FigurePlanGateValidPayload


class FigurePlanProjectionConsistencyPayload(TypedDict):
    manifest_rule_matches: bool
    result_plan_matches: bool
    study_plan_matches: bool
    outcome_artifacts_exist: bool


class FigurePlanManifestGateValidPayload(FigurePlanGateValidPayload):
    projection_consistency: FigurePlanProjectionConsistencyPayload


FigurePlanManifestGatePayload = (
    FigurePlanGateInvalidPayload | FigurePlanManifestGateValidPayload
)


__all__ = [
    "CartesianMetricBindingPayload",
    "FigureOutcomePayload",
    "FigureOutcomeStatus",
    "FigurePlanGateInvalidPayload",
    "FigurePlanGatePayload",
    "FigurePlanGateValidPayload",
    "FigurePlanManifestGatePayload",
    "FigurePlanManifestGateValidPayload",
    "FigurePlanProjectionConsistencyPayload",
    "FigureMetricBindingPayload",
    "FigureTaskPayload",
    "FigureTaskReplicateCountPayload",
    "FigureTaskV1Payload",
    "FigureTaskV2Payload",
    "OrderedMetricsBindingPayload",
    "ResolvedFigurePlanPayload",
    "ResolvedFigurePlanStatus",
]
