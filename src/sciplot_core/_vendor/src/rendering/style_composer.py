from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src import plot_style
from src.rendering.custom_themes import CustomThemePackage
from src.rendering.themes import (
    publication_profile_hard_constraints,
    publication_profile_protected_keys,
    sanitized_visual_theme_soft_overrides,
)


@dataclass(frozen=True)
class StyleBundle:
    publication_profile_id: str
    visual_theme_id: str | None
    resolved_hard: dict[str, object]
    resolved_soft: dict[str, object]
    protected_keys: tuple[str, ...]
    blocked_soft_keys: tuple[str, ...] = ()
    custom_theme_id: str | None = None
    hard_overrides: dict[str, dict[str, Any]] | None = None
    palette_colors: tuple[str, ...] | None = None


class StyleComposer(Protocol):
    def compose(
        self,
        publication_profile_id: str,
        visual_theme_id: str | None,
        *,
        custom_theme: CustomThemePackage | None = None,
    ) -> StyleBundle: ...


class ContractStyleComposer:
    def compose(
        self,
        publication_profile_id: str,
        visual_theme_id: str | None,
        *,
        custom_theme: CustomThemePackage | None = None,
    ) -> StyleBundle:
        normalized_profile_id = plot_style.normalize_style_preset(
            custom_theme.base_style_id if custom_theme is not None else publication_profile_id
        )
        resolved_theme_id = custom_theme.visual_theme_id if custom_theme is not None else visual_theme_id
        resolved_soft, blocked_soft_keys = sanitized_visual_theme_soft_overrides(
            normalized_profile_id,
            resolved_theme_id,
        )
        hard_overrides = custom_theme.hard_overrides if custom_theme is not None else None
        if custom_theme is not None:
            resolved_soft.update(custom_theme.soft_overrides or {})
            resolved_soft.update(custom_theme.expert_rcparams or {})
        resolved_hard = publication_profile_hard_constraints(normalized_profile_id)
        if hard_overrides:
            for group, values in hard_overrides.items():
                group_map = resolved_hard.get(group)
                if isinstance(group_map, dict):
                    group_map.update(values)
        return StyleBundle(
            publication_profile_id=normalized_profile_id,
            visual_theme_id=resolved_theme_id,
            resolved_hard=resolved_hard,
            resolved_soft=resolved_soft,
            protected_keys=publication_profile_protected_keys(normalized_profile_id),
            blocked_soft_keys=blocked_soft_keys,
            custom_theme_id=custom_theme.id if custom_theme is not None else None,
            hard_overrides=hard_overrides,
            palette_colors=(
                tuple(custom_theme.palette.get("categorical", ()))
                if custom_theme is not None and custom_theme.palette
                else None
            ),
        )


DEFAULT_STYLE_COMPOSER = ContractStyleComposer()


__all__ = ["ContractStyleComposer", "DEFAULT_STYLE_COMPOSER", "StyleBundle", "StyleComposer"]
