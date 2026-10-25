"""Concrete application composition and explicitly separate native authorities."""
from typing import Any

from .repository_router import ComposedProjectRepository
from .ports import ProjectRepository


from .capabilities import COMPATIBILITY_CAPABILITIES


def components(backend: Any, repository: ProjectRepository | None, capabilities: dict[str, Any] | None,
               resolve_figure: Any) -> tuple[Any, ProjectRepository, dict[str, Any], Any]:
    if backend is None:
        from sciplot_core.plot_backends.veusz import VeuszBackend
        from sciplot_core.plot_backends.figure_plan import capability_profile
        from sciplot_core.plot_engine.backend_router import BackendRouter

        backend = BackendRouter(VeuszBackend())
        capabilities = capability_profile() if capabilities is None else capabilities
    if repository is None:
        from sciplot_core.studio_core.project_session import external_project_session

        repository = ComposedProjectRepository(lease=external_project_session)
        from .backend_paths import RepositoryBackendPaths

        backend = RepositoryBackendPaths(backend, repository)
    return backend, repository, COMPATIBILITY_CAPABILITIES if capabilities is None else capabilities, resolve_figure
