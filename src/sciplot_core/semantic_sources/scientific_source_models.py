"""Typed scientific-source envelope shared by orchestration owners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.rheology_sweep_domain import (
    ResolvedRheologySweepDomain,
)
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)

if TYPE_CHECKING:
    from sciplot_core.figure_plan.plan import ResolvedFigurePlan


ScientificSourceDomain = ResolvedScientificTransform | ResolvedRheologySweepDomain
DomainT = TypeVar("DomainT")


class ScientificSourceResolutionError(ValueError):
    """Stable adapter error consumed by preview, Studio, and Workflow."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ResolvedScientificSource:
    """One typed source snapshot shared by planning and materialization."""

    rule_id: str
    source: Path
    domain: ScientificSourceDomain
    figure_plan: ResolvedFigurePlan | None
    source_sha256: str | None

    def __post_init__(self) -> None:
        if self.source != self.source.expanduser().resolve():
            raise ValueError("Resolved scientific source path must be absolute.")
        if isinstance(self.domain, ResolvedRheologySweepDomain):
            if self.domain.rule_id != self.rule_id:
                raise ValueError(
                    "Resolved scientific domain does not match its rule identity."
                )
            if self.domain.source != self.source:
                raise ValueError(
                    "Resolved scientific domain does not match its source path."
                )
            if self.domain.source_sha256 != self.source_sha256:
                raise ValueError(
                    "Resolved scientific domain does not match its source hash."
                )
        elif self.domain.contract.semantic_family != self.rule_id:
            raise ValueError(
                "Resolved scientific domain does not match its rule identity."
            )
        if self.figure_plan is not None:
            if self.figure_plan.rule_id != self.rule_id:
                raise ValueError(
                    "Resolved scientific FigurePlan does not match its rule identity."
                )
            if self.source_sha256 != self.figure_plan.source_sha256:
                raise ValueError(
                    "Resolved scientific source hash does not match its FigurePlan."
                )

    @property
    def semantic_family(self) -> str:
        if isinstance(self.domain, ResolvedScientificTransform):
            return self.domain.contract.semantic_family
        return get_rule(self.rule_id).semantic_family

    @property
    def transform(self) -> ResolvedScientificTransform | None:
        return (
            self.domain
            if isinstance(self.domain, ResolvedScientificTransform)
            else None
        )

    def require_domain(self, domain_type: type[DomainT]) -> DomainT:
        if not isinstance(self.domain, domain_type):
            raise ValueError(
                "Resolved scientific source has an incompatible domain type."
            )
        return self.domain


__all__ = [
    "ResolvedScientificSource",
    "ScientificSourceDomain",
    "ScientificSourceResolutionError",
]
