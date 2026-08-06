"""Immutable resolved-figure plan and strict JSON round-trip."""

from __future__ import annotations

from dataclasses import dataclass
import re

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_object,
)

from sciplot_core.figure_plan.constants import (
    RESOLVED_FIGURE_PLAN_KIND,
    RESOLVED_FIGURE_PLAN_VERSION,
)
from sciplot_core.figure_plan.outcome import FigureOutcome
from sciplot_core.figure_plan.payload_types import (
    ResolvedFigurePlanPayload,
    ResolvedFigurePlanStatus,
)
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.figure_plan.values import required_text, text_tuple


@dataclass(frozen=True, slots=True)
class ResolvedFigurePlan:
    """The authoritative selected task set and its one-to-one outcomes."""

    rule_id: str
    selection_policy: str
    primary_figure_id: str
    tasks: tuple[FigureTask, ...]
    outcomes: tuple[FigureOutcome, ...]
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        rule_id = required_text(self.rule_id, label="plan.rule_id")
        selection_policy = required_text(
            self.selection_policy,
            label="plan.selection_policy",
        )
        if not isinstance(self.tasks, tuple | list) or not self.tasks:
            raise ValueError("ResolvedFigurePlan requires at least one FigureTask.")
        tasks = tuple(self.tasks)
        if not all(isinstance(task, FigureTask) for task in tasks):
            raise ValueError("ResolvedFigurePlan tasks must be FigureTask objects.")
        if [task.order for task in tasks] != list(range(1, len(tasks) + 1)):
            raise ValueError("FigureTask order must be contiguous and list ordered.")
        task_ids = [task.figure_id for task in tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("ResolvedFigurePlan figure IDs must be unique.")
        artifact_stems = [task.artifact_stem for task in tasks]
        if len(set(artifact_stems)) != len(artifact_stems):
            raise ValueError("ResolvedFigurePlan artifact stems must be unique.")
        document_stems = [task.document_stem for task in tasks]
        if len(set(document_stems)) != len(document_stems):
            raise ValueError("ResolvedFigurePlan document stems must be unique.")
        primary = required_text(
            self.primary_figure_id,
            label="plan.primary_figure_id",
        )
        if primary not in task_ids:
            raise ValueError("primary_figure_id must reference a selected FigureTask.")
        if not isinstance(self.outcomes, tuple | list):
            raise ValueError("ResolvedFigurePlan outcomes must be a sequence.")
        outcomes = tuple(self.outcomes)
        if not all(isinstance(outcome, FigureOutcome) for outcome in outcomes):
            raise ValueError(
                "ResolvedFigurePlan outcomes must be FigureOutcome objects."
            )
        if [outcome.figure_id for outcome in outcomes] != task_ids:
            raise ValueError(
                "ResolvedFigurePlan requires one ordered outcome per FigureTask."
            )
        source_sha256 = self.source_sha256
        if source_sha256 is not None and (
            not isinstance(source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        ):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest.")
        object.__setattr__(self, "rule_id", rule_id)
        object.__setattr__(self, "selection_policy", selection_policy)
        object.__setattr__(self, "primary_figure_id", primary)
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "source_sha256", source_sha256)

    @classmethod
    def planned(
        cls,
        *,
        rule_id: str,
        selection_policy: str,
        primary_figure_id: str,
        tasks: tuple[FigureTask, ...],
        source_sha256: str | None = None,
    ) -> ResolvedFigurePlan:
        return cls(
            rule_id=rule_id,
            selection_policy=selection_policy,
            primary_figure_id=primary_figure_id,
            tasks=tasks,
            outcomes=tuple(
                FigureOutcome(figure_id=task.figure_id, status="pending")
                for task in tasks
            ),
            source_sha256=source_sha256,
        )

    @property
    def selected_figure_ids(self) -> tuple[str, ...]:
        return tuple(task.figure_id for task in self.tasks)

    @property
    def complete(self) -> bool:
        return all(
            outcome.status == "ready" and outcome.delivery_artifacts_complete
            for outcome in self.outcomes
        )

    @property
    def status(self) -> ResolvedFigurePlanStatus:
        if self.complete:
            return "ready"
        statuses = {outcome.status for outcome in self.outcomes}
        if statuses == {"pending"}:
            return "planned"
        if statuses <= {"pending", "editable"} and "editable" in statuses:
            return "editable"
        return "incomplete"

    @property
    def plan_sha256(self) -> str:
        return canonical_json_sha256(
            {
                "kind": RESOLVED_FIGURE_PLAN_KIND,
                "version": RESOLVED_FIGURE_PLAN_VERSION,
                "rule_id": self.rule_id,
                "selection_policy": self.selection_policy,
                "primary_figure_id": self.primary_figure_id,
                "source_sha256": self.source_sha256,
                "tasks": [task.to_payload() for task in self.tasks],
            },
            allow_nan=False,
        )

    @property
    def plan_id(self) -> str:
        return f"rfp_{self.plan_sha256[:16]}"

    def to_payload(self) -> ResolvedFigurePlanPayload:
        return {
            "kind": RESOLVED_FIGURE_PLAN_KIND,
            "version": RESOLVED_FIGURE_PLAN_VERSION,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "rule_id": self.rule_id,
            "selection_policy": self.selection_policy,
            "primary_figure_id": self.primary_figure_id,
            "source_sha256": self.source_sha256,
            "selected_figure_ids": list(self.selected_figure_ids),
            "tasks": [task.to_payload() for task in self.tasks],
            "outcomes": [outcome.to_payload() for outcome in self.outcomes],
            "status": self.status,
            "complete": self.complete,
        }

    @classmethod
    def from_payload(cls, value: object) -> ResolvedFigurePlan:
        payload = require_json_object(value, label="ResolvedFigurePlan")
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "plan_id",
                "plan_sha256",
                "rule_id",
                "selection_policy",
                "primary_figure_id",
                "source_sha256",
                "selected_figure_ids",
                "tasks",
                "outcomes",
                "status",
                "complete",
            },
            label="ResolvedFigurePlan",
        )
        if payload.get("kind") != RESOLVED_FIGURE_PLAN_KIND:
            raise ValueError("Not a SciPlot ResolvedFigurePlan payload.")
        if (
            require_json_int(
                payload.get("version"),
                label="ResolvedFigurePlan.version",
            )
            != RESOLVED_FIGURE_PLAN_VERSION
        ):
            raise ValueError("Unsupported ResolvedFigurePlan version.")
        plan = cls(
            rule_id=required_text(
                payload.get("rule_id"),
                label="ResolvedFigurePlan.rule_id",
            ),
            selection_policy=required_text(
                payload.get("selection_policy"),
                label="ResolvedFigurePlan.selection_policy",
            ),
            primary_figure_id=required_text(
                payload.get("primary_figure_id"),
                label="ResolvedFigurePlan.primary_figure_id",
            ),
            tasks=tuple(
                FigureTask.from_payload(item)
                for item in require_json_list(
                    payload.get("tasks"),
                    label="ResolvedFigurePlan.tasks",
                )
            ),
            outcomes=tuple(
                FigureOutcome.from_payload(item)
                for item in require_json_list(
                    payload.get("outcomes"),
                    label="ResolvedFigurePlan.outcomes",
                )
            ),
            source_sha256=(
                required_text(
                    payload.get("source_sha256"),
                    label="ResolvedFigurePlan.source_sha256",
                )
                if payload.get("source_sha256") is not None
                else None
            ),
        )
        selected_ids = text_tuple(
            require_json_list(
                payload.get("selected_figure_ids"),
                label="ResolvedFigurePlan.selected_figure_ids",
            ),
            label="ResolvedFigurePlan.selected_figure_ids",
        )
        if selected_ids != plan.selected_figure_ids:
            raise ValueError(
                "ResolvedFigurePlan selected_figure_ids do not match tasks."
            )
        if payload.get("plan_id") != plan.plan_id:
            raise ValueError("ResolvedFigurePlan plan_id does not match its tasks.")
        if payload.get("plan_sha256") != plan.plan_sha256:
            raise ValueError("ResolvedFigurePlan plan_sha256 does not match its tasks.")
        if payload.get("status") != plan.status:
            raise ValueError("ResolvedFigurePlan status does not match its outcomes.")
        if (
            require_json_bool(
                payload.get("complete"),
                label="ResolvedFigurePlan.complete",
            )
            is not plan.complete
        ):
            raise ValueError("ResolvedFigurePlan complete does not match its outcomes.")
        return plan


def resolved_figure_plan_from_payload(
    value: object,
) -> ResolvedFigurePlan | None:
    """Accept missing legacy state, but fail closed on a present invalid plan."""

    if value is None:
        return None
    return ResolvedFigurePlan.from_payload(value)


__all__ = ["ResolvedFigurePlan", "resolved_figure_plan_from_payload"]
