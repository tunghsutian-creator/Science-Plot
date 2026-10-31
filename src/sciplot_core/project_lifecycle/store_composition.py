"""Select the existing host composition for an exact already versioned project."""
from pathlib import Path

from sciplot_core.project_store.adapters import store_for_project
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.errors import ProjectStoreError
from .errors import EngineError


def existing_store(project: Path) -> FileProjectStore:
    if (project / "plot_request.json").is_symlink():
        raise EngineError("semantic_project_invalid", "A selected native project request cannot follow a symbolic alias.")
    if (project / "plot_request.json").is_file():
        # Native request fields select host publication capabilities. Only its
        # already admitted generation bytes may contribute those capabilities.
        observation = store_for_project(project).observe_members(("plot_request.json",), projection=False,
                                                                 physical=("plot_request.json",))
        recorded = observation.members["plot_request.json"].data
        if recorded is None:
            raise ProjectStoreError("The logical resource is not a member of this generation.")
        physical = observation.physical["plot_request.json"]
        if physical is None:
            raise FileNotFoundError(project / "plot_request.json")
        actual, _mode = physical
        if actual != recorded:
            raise EngineError("semantic_project_changed", "The physical native project request differs from its admitted generation; reconcile it before selecting host resources.")
        from sciplot_core.studio_core.project_command_scope import project_store

        return project_store(project)
    return FileProjectStore(project)


def tracked_namespace_store(path: Path) -> tuple[FileProjectStore, Path] | None:
    """Recognize only an exact old-format namespace already tracked by a project."""
    from sciplot_core.project_store.io import STORE
    from .legacy_namespace import known_head

    namespace = namespace_root(path)
    if namespace is None:
        return None
    for project in namespace.parent.parents:
        if (project / STORE / "head.json").is_file():
            store = existing_store(project)
            return (store, namespace) if known_head(store, namespace) else None
    return None


def project_identity(store: FileProjectStore) -> str:
    with store._locked(allow_pending=True) as (_io, current):
        return str(current["project_id"])


def namespace_root(path: Path) -> Path | None:
    """The closed existing semantic namespace shape, including descendant reads."""
    return next((item for item in (path, *path.parents)
                      if (item.parent.name == ".sciplot_documents" and item.name not in {"managed", "creations"})
                      or item.parent.name == "managed" and item.parent.parent.name == ".sciplot_documents"), None)
