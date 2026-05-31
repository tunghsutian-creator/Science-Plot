from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import plot_style
from src.plot_contract import style_contract
from src.rendering.custom_themes import (
    CustomThemePackage,
    custom_theme_summary_payload,
    custom_theme_to_payload,
    normalize_custom_theme_package,
)

USER_THEME_DIR = Path.home() / "Library" / "Application Support" / "SciPlot" / "plot_themes"


def _theme_filename(theme_id: str) -> str:
    return f"{theme_id.replace('/', '__')}.json"


def theme_member_filename(theme_id: str) -> str:
    return _theme_filename(theme_id)


def ensure_user_theme_dir() -> None:
    USER_THEME_DIR.mkdir(parents=True, exist_ok=True)


def theme_path(theme_id: str) -> Path:
    ensure_user_theme_dir()
    return USER_THEME_DIR / _theme_filename(theme_id)


def builtin_theme_summaries() -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for style_id in plot_style.list_public_style_presets():
        style = style_contract(style_id)
        palette = plot_style.get_palette_swatches(style.recommended_palette_preset)
        summaries.append(
            {
                "id": style_id,
                "label": style.label,
                "builtin": True,
                "base_style_id": style_id,
                "palette_preset": style.recommended_palette_preset,
                "visual_theme_id": style.recommended_visual_theme_id,
                "swatches": list(palette),
            }
        )
    return summaries


def load_custom_theme(theme_id: str) -> CustomThemePackage:
    path = theme_path(theme_id)
    if not path.exists():
        raise FileNotFoundError(f"Custom plot theme not found: {theme_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_custom_theme_package(payload).package


def list_custom_themes() -> list[CustomThemePackage]:
    ensure_user_theme_dir()
    themes: list[CustomThemePackage] = []
    for path in sorted(USER_THEME_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        themes.append(normalize_custom_theme_package(payload).package)
    return sorted(themes, key=lambda item: (item.label.lower(), item.id))


def save_custom_theme(value: object, *, overwrite: bool = False) -> CustomThemePackage:
    normalized = normalize_custom_theme_package(value)
    theme = normalized.package
    path = theme_path(theme.id)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Custom plot theme already exists: {theme.id}")
    path.write_text(
        json.dumps(custom_theme_to_payload(theme), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return theme


def delete_custom_theme(theme_id: str) -> None:
    path = theme_path(theme_id)
    if not path.exists():
        raise FileNotFoundError(f"Custom plot theme not found: {theme_id}")
    path.unlink()


def list_theme_summaries() -> list[dict[str, Any]]:
    return [
        *builtin_theme_summaries(),
        *[custom_theme_summary_payload(theme) for theme in list_custom_themes()],
    ]


def resolve_custom_theme(theme_id: str | None, draft: object | None = None) -> CustomThemePackage | None:
    if draft is not None:
        return normalize_custom_theme_package(draft).package
    if not theme_id:
        return None
    return load_custom_theme(theme_id)


__all__ = [
    "USER_THEME_DIR",
    "builtin_theme_summaries",
    "delete_custom_theme",
    "ensure_user_theme_dir",
    "list_custom_themes",
    "list_theme_summaries",
    "load_custom_theme",
    "resolve_custom_theme",
    "save_custom_theme",
    "theme_member_filename",
    "theme_path",
]
