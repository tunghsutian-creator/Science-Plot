"""Authoritative resolved-figure planning API."""

from __future__ import annotations

from sciplot_core.figure_plan.constants import (
    FIGURE_OUTCOME_KIND,
    FIGURE_OUTCOME_VERSION,
    FIGURE_TASK_KIND,
    FIGURE_TASK_V1_VERSION,
    FIGURE_TASK_V2_VERSION,
    FIGURE_TASK_VERSION,
    RESOLVED_FIGURE_PLAN_KIND,
    RESOLVED_FIGURE_PLAN_VERSION,
    REQUIRED_FIGURE_PLAN_RULE_IDS,
    SUPPORTED_FIGURE_PLAN_RULE_IDS,
)
from sciplot_core.figure_plan.execution import (
    editable_figure_plan,
    figure_plan_gate,
    finalize_figure_plan_result,
    merge_figure_outcomes,
    outcomes_for_artifact_map,
    outcomes_from_payload,
    request_for_figure_task,
    sync_figure_plan_projection,
)
from sciplot_core.figure_plan.manifest_gate import figure_plan_manifest_gate
from sciplot_core.figure_plan.metric_binding import (
    CartesianMetricBinding,
    FigureMetricBinding,
    OrderedMetricsBinding,
)
from sciplot_core.figure_plan.mechanical_resolution import resolve_mechanical_plan
from sciplot_core.figure_plan.outcome import FigureOutcome, FigureOutcomeStatus
from sciplot_core.figure_plan.payload_types import (
    CartesianMetricBindingPayload,
    FigureOutcomePayload,
    FigurePlanGateInvalidPayload,
    FigurePlanGatePayload,
    FigurePlanGateValidPayload,
    FigurePlanManifestGatePayload,
    FigurePlanManifestGateValidPayload,
    FigurePlanProjectionConsistencyPayload,
    FigureMetricBindingPayload,
    FigureTaskPayload,
    FigureTaskReplicateCountPayload,
    FigureTaskV1Payload,
    FigureTaskV2Payload,
    OrderedMetricsBindingPayload,
    ResolvedFigurePlanPayload,
    ResolvedFigurePlanStatus,
)
from sciplot_core.figure_plan.plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.preparation_validation import (
    validate_preparation_figure_plan,
)
from sciplot_core.figure_plan.resolution import (
    FigurePlanResolutionError,
    resolve_current_figure_plan,
    resolve_figure_plan,
    resolve_preparation_figure_plan,
    stable_impact_figure_id,
)
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.figure_plan.source_binding import (
    source_tree_sha256,
    source_trees_match_sha256,
)

__all__ = [
    "FIGURE_OUTCOME_KIND",
    "FIGURE_OUTCOME_VERSION",
    "FIGURE_TASK_KIND",
    "FIGURE_TASK_V1_VERSION",
    "FIGURE_TASK_V2_VERSION",
    "FIGURE_TASK_VERSION",
    "RESOLVED_FIGURE_PLAN_KIND",
    "RESOLVED_FIGURE_PLAN_VERSION",
    "REQUIRED_FIGURE_PLAN_RULE_IDS",
    "SUPPORTED_FIGURE_PLAN_RULE_IDS",
    "CartesianMetricBinding",
    "CartesianMetricBindingPayload",
    "FigureOutcome",
    "FigureOutcomePayload",
    "FigureOutcomeStatus",
    "FigurePlanGateInvalidPayload",
    "FigurePlanGatePayload",
    "FigurePlanGateValidPayload",
    "FigurePlanManifestGatePayload",
    "FigurePlanManifestGateValidPayload",
    "FigurePlanProjectionConsistencyPayload",
    "FigurePlanResolutionError",
    "FigureMetricBinding",
    "FigureMetricBindingPayload",
    "FigureTask",
    "FigureTaskPayload",
    "FigureTaskReplicateCountPayload",
    "FigureTaskV1Payload",
    "FigureTaskV2Payload",
    "OrderedMetricsBinding",
    "OrderedMetricsBindingPayload",
    "ResolvedFigurePlan",
    "ResolvedFigurePlanPayload",
    "ResolvedFigurePlanStatus",
    "editable_figure_plan",
    "figure_plan_gate",
    "figure_plan_manifest_gate",
    "finalize_figure_plan_result",
    "merge_figure_outcomes",
    "outcomes_for_artifact_map",
    "outcomes_from_payload",
    "request_for_figure_task",
    "resolve_current_figure_plan",
    "resolve_figure_plan",
    "resolve_mechanical_plan",
    "resolve_preparation_figure_plan",
    "validate_preparation_figure_plan",
    "resolved_figure_plan_from_payload",
    "stable_impact_figure_id",
    "source_tree_sha256",
    "source_trees_match_sha256",
    "sync_figure_plan_projection",
]
