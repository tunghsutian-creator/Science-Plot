"""Hold the configured core services used by native Studio project docks."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any
from sciplot_gui.studio_project_services import StudioProjectServices

_project_services: StudioProjectServices | None = None


def configure_studio_project_services(services: StudioProjectServices) -> None:
    """Install the core operations used by subsequently attached Project docks."""

    global _project_services
    _project_services = services


def _require_project_services() -> StudioProjectServices:
    if _project_services is None:
        raise RuntimeError(
            "SciPlot Project services were not configured by the Studio entrypoint."
        )
    return _project_services


def project_change_service(
    operation: str, *, apply: bool = False
) -> Callable[..., dict[str, Any]] | None:
    """Resolve an optional injected operation, preserving older integrations."""
    if _project_services is None:
        return None
    if operation == "delivery_recovery":
        return (
            _project_services.apply_delivery_recovery
            if apply
            else _project_services.preview_delivery_recovery
        )
    if operation == "source_update":
        return (
            _project_services.apply_source_update
            if apply
            else _project_services.preview_source_update
        )
    raise ValueError(f"Unknown project operation: {operation}")


def atomic_save_veusz_document(document: Any, target: Path) -> dict[str, Any]:
    return _require_project_services().atomic_save_document(document, target)


def export_studio_document(
    document_path: Path,
    *,
    formats: list[str],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    return _require_project_services().export_document(
        document_path,
        formats=formats,
        output_dir=output_dir,
    )


def publish_standalone_export_receipt(**kwargs: Any) -> dict[str, Any]:
    return _require_project_services().publish_standalone_export(**kwargs)


def publish_studio_export_run(**kwargs: Any) -> dict[str, Any]:
    return _require_project_services().publish_project_export(**kwargs)


def _studio_figure_set_export_scope(
    project_dir: Path,
    *,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    return _require_project_services().build_figure_set_scope(
        project_dir,
        request=request,
    )


def _is_primary_figure_set_export_scope(value: object) -> bool:
    return _require_project_services().is_complete_figure_set_scope(value)
