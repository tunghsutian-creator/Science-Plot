"""Concrete application composition and explicitly separate native authorities."""
from typing import Any

from .backend_paths import compose_project_repository
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
    profile = COMPATIBILITY_CAPABILITIES if capabilities is None else capabilities
    backend, repository = compose_project_repository(backend, repository, profile)
    return backend, repository, profile, resolve_figure
