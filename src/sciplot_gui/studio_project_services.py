from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StudioProjectServices:
    """Core lifecycle operations injected into the Qt Project dock."""

    atomic_save_document: Callable[..., dict[str, Any]]
    export_document: Callable[..., dict[str, Any]]
    publish_standalone_export: Callable[..., dict[str, Any]]
    publish_project_export: Callable[..., dict[str, Any]]
    build_figure_set_scope: Callable[..., dict[str, Any] | None]
    is_complete_figure_set_scope: Callable[[object], bool]


__all__ = ["StudioProjectServices"]
