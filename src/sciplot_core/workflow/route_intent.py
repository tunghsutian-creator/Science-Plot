"""Resolve the immutable auto, recipe, or direct-render workflow route."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


WorkflowRoute = Literal["auto", "recipe", "render"]


@dataclass(frozen=True, slots=True)
class WorkflowRouteIntent:
    """One request-shape decision captured before later request enrichment."""

    route: WorkflowRoute
    requested_recipe: str | None
    requested_template: str | None

    def __post_init__(self) -> None:
        if self.route == "auto":
            if self.requested_recipe not in {None, "auto"}:
                raise ValueError(
                    "workflow_route_invalid: auto route cannot name a recipe."
                )
            if self.requested_recipe is None and self.requested_template is not None:
                raise ValueError(
                    "workflow_route_invalid: template-only request is direct render."
                )
            return
        if self.route == "recipe":
            if self.requested_recipe in {None, "auto"}:
                raise ValueError(
                    "workflow_route_invalid: recipe route requires a named recipe."
                )
            return
        if self.route == "render":
            if self.requested_recipe is not None or self.requested_template is None:
                raise ValueError(
                    "workflow_route_invalid: direct render requires only a template."
                )
            return
        raise ValueError(f"workflow_route_invalid: unknown route `{self.route}`.")

    @property
    def uses_semantic_preparation(self) -> bool:
        """Whether the request follows semantic auto preparation."""

        return self.route == "auto"


def resolve_workflow_route_intent(
    request: Mapping[str, Any],
) -> WorkflowRouteIntent:
    """Resolve route identity once from strict optional request fields."""

    requested_recipe = _optional_route_text(request, field="recipe")
    requested_template = _optional_route_text(request, field="template")
    if requested_recipe == "auto" or (
        requested_recipe is None and requested_template is None
    ):
        route: WorkflowRoute = "auto"
    elif requested_recipe is not None:
        route = "recipe"
    else:
        route = "render"
    return WorkflowRouteIntent(
        route=route,
        requested_recipe=requested_recipe,
        requested_template=requested_template,
    )


def _optional_route_text(
    request: Mapping[str, Any],
    *,
    field: str,
) -> str | None:
    if field not in request or request[field] is None:
        return None
    value = request[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"workflow_route_invalid: `{field}` must be non-empty text when present."
        )
    if value != value.strip():
        raise ValueError(
            f"workflow_route_invalid: `{field}` cannot contain surrounding whitespace."
        )
    return value


__all__ = [
    "WorkflowRoute",
    "WorkflowRouteIntent",
    "resolve_workflow_route_intent",
]
