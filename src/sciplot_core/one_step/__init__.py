"""One-step lifecycle contract API and compatibility facade."""

from __future__ import annotations

from sciplot_core.readiness import (
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
)

from sciplot_core.one_step.quality_catalog import (  # noqa: F401
    ONE_STEP_MODEL_KIND,
    ONE_STEP_MODEL_VERSION,
    READY_STATE,
    HUMAN_CONFIRMATION_STATE,
    RULE_REPAIR_STATE,
    _LEGEND_INLINE_STRATEGY,
    _LEGEND_AUTO_STRATEGY,
    _STACK_SPLIT_POLICY,
    _ISSUE_QUALITY_ACTIONS,
    _STACK_SPLIT_QUALITY_ACTION,
    _AUTOFIX_QUALITY_ACTIONS,
)
from sciplot_core.one_step.confidence import (  # noqa: F401
    _now,
    _source_counts,
    _semantic_confidence,
    confidence_band,
)
from sciplot_core.one_step.quality_actions import (  # noqa: F401
    _quality_action,
    _layout_summary_height_mm,
    _template_for_issue,
    build_quality_actions,
)
from sciplot_core.one_step.packages import (  # noqa: F401
    build_source_package,
    build_mapping_package,
    build_render_request_package,
    build_figure_qa_report,
)
from sciplot_core.one_step.readiness import (  # noqa: F401
    _readiness,
)
from sciplot_core.one_step.intervention import (  # noqa: F401
    build_intervention_package,
)
from sciplot_core.one_step.project import (  # noqa: F401
    build_one_step_project,
)

__all__ = [
    "HIGH_CONFIDENCE_THRESHOLD",
    "HUMAN_CONFIRMATION_STATE",
    "MEDIUM_CONFIDENCE_THRESHOLD",
    "ONE_STEP_MODEL_KIND",
    "ONE_STEP_MODEL_VERSION",
    "READY_STATE",
    "RULE_REPAIR_STATE",
    "build_figure_qa_report",
    "build_intervention_package",
    "build_mapping_package",
    "build_one_step_project",
    "build_quality_actions",
    "build_render_request_package",
    "build_source_package",
    "confidence_band",
]
