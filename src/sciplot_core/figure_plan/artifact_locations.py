"""Publish host artifact locators without changing scientific or audit facts."""

from dataclasses import replace
from pathlib import Path

from sciplot_core.foundation.source_locations import (
    literal_source_path,
    resolve_source_path,
    selected_source_resolver,
)

from sciplot_core.figure_plan.plan import ResolvedFigurePlan


def literal_artifact_path(path: str | Path) -> str:
    """Only a selected host scope translates newly produced artifact addresses."""
    return literal_source_path(Path(path)) if selected_source_resolver() is not None else str(path)


def artifact_is_file(path: str | Path) -> bool:
    """Check the actual selected IO view, rejecting missing or invalid bindings."""
    try:
        return resolve_source_path(Path(path).expanduser()).is_file()
    except (OSError, ValueError):
        return False


def literal_figure_plan_artifacts(plan: ResolvedFigurePlan) -> ResolvedFigurePlan:
    """Keep tasks, source digest, outcome status and plan identity unchanged."""
    if selected_source_resolver() is None:
        return plan
    return replace(plan, outcomes=tuple(
        replace(outcome, artifacts=tuple(literal_artifact_path(path) for path in outcome.artifacts))
        for outcome in plan.outcomes
    ))
