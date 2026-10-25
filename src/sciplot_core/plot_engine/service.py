"""Public compatibility facade; semantic orchestration belongs to ProjectApplication.

Native prepared suites have their own complete-native authority and transaction
owner. The composition adapter routes those objects before entering the semantic
aggregate application; no native draft is silently promoted to Managed authority.
"""
from pathlib import Path
from typing import Any

from sciplot_core.project_lifecycle.application import ProjectApplication
from sciplot_core.project_lifecycle.composition import components
from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_lifecycle.ports import ProjectRepository, ProjectTargets
from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets

from .backend import PlotBackend
from .description_scope import require_selector
from .prepared_routing import native_dispatch


class PlotService(ProjectApplication):
    def __init__(self, backend: PlotBackend | None = None, *, repository: ProjectRepository | None = None,
                 capabilities: dict[str, Any] | None = None, resolve_figure: Any = None, targets: ProjectTargets | None = None) -> None:
        backend, repository, capabilities, resolve_figure = components(backend, repository, capabilities, resolve_figure)
        super().__init__(backend, repository, capabilities=capabilities,
                         targets=targets if targets is not None else FilesystemProjectTargets(repository, resolve_figure=resolve_figure))

    def create(self, request: dict[str, Any], *, project: Path | None = None) -> dict[str, Any]:
        from .selected_project import selected_project_creation

        with selected_project_creation(project, request):
            return super().create(request)

    def open(self, target: Path, figure_id: str | None = None, *,
             description: dict[str, Any] | None = None) -> dict[str, Any]:
        description = require_selector(description)
        native = native_dispatch("describe", canonical_path(target), figure_id=figure_id, description=description)
        return native if native is not None else super().open(target, figure_id, description=description)

    def describe(self, plot: Path, *, description: dict[str, Any] | None = None) -> dict[str, Any]:
        description = require_selector(description)
        native = native_dispatch("describe", canonical_path(plot), description=description)
        return native if native is not None else super().describe(plot, description=description)

    def patch(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        from sciplot_core.plot_document import validate_patch

        request = validate_patch(request)
        native = native_dispatch("patch", canonical_path(plot), request=request)
        return native if native is not None else super().patch(plot, request)

    def decide(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        from .contracts import validate_decide

        request = validate_decide(request)
        native = native_dispatch("decide", canonical_path(plot), request=request)
        return native if native is not None else super().decide(plot, request)

    def resume(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        native = native_dispatch("resume", canonical_path(plot), request=request)
        return native if native is not None else super().resume(plot, request)

    def export(self, plot: Path) -> dict[str, Any]:
        native = native_dispatch("export", canonical_path(plot))
        return native if native is not None else super().export(plot)
