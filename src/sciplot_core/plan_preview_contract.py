"""Wire types and pure output construction for source-bound plan previews."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Literal, NotRequired, TypedDict

from sciplot_core.figure_plan.payload_types import ResolvedFigurePlanPayload


PLAN_PREVIEW_KIND: Final = "sciplot_figure_plan_preview"
PLAN_PREVIEW_VERSION: Final = 1


PlanPreviewStatus = Literal["planned", "not_applicable", "blocked"]


class PlanPreviewBlocker(TypedDict):
    reason_code: str
    message: str


class PlanPreviewBase(TypedDict):
    kind: Literal["sciplot_figure_plan_preview"]
    version: Literal[1]
    source: str
    rule_id: str | None
    template: str
    preview_identity: dict[str, Any] | None
    data_mapping: NotRequired[dict[str, Any]]


class PlanPreviewPayload(PlanPreviewBase):
    status: PlanPreviewStatus
    resolved_figure_plan: ResolvedFigurePlanPayload | None
    scientific_transform: dict[str, Any] | None
    blocker: PlanPreviewBlocker | None


def _blocked_preview(
    *,
    source: Path,
    rule_id: str | None,
    template: str,
    reason_code: str,
    message: str,
    scientific_transform: dict[str, Any] | None = None,
) -> PlanPreviewPayload:
    return {
        **_preview_base(source=source, rule_id=rule_id, template=template),
        "status": "blocked",
        "resolved_figure_plan": None,
        "scientific_transform": scientific_transform,
        "blocker": {
            "reason_code": reason_code,
            "message": message,
        },
    }


def _preview_base(
    *,
    source: Path,
    rule_id: str | None,
    template: str,
) -> PlanPreviewBase:
    return {
        "kind": PLAN_PREVIEW_KIND,
        "version": PLAN_PREVIEW_VERSION,
        "source": str(source),
        "rule_id": rule_id,
        "template": template,
        "preview_identity": None,
    }


__all__ = [
    "PLAN_PREVIEW_KIND",
    "PLAN_PREVIEW_VERSION",
    "PlanPreviewBase",
    "PlanPreviewBlocker",
    "PlanPreviewPayload",
    "PlanPreviewStatus",
]
