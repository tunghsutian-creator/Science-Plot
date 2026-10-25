"""Select the existing host composition for an exact already versioned project."""
from pathlib import Path
import os

from sciplot_core.project_store.adapters import store_for_project
from sciplot_core.project_store.io import read_file
from sciplot_core.project_store.repository import FileProjectStore
from .errors import EngineError


def existing_store(project: Path) -> FileProjectStore:
    if (project / "plot_request.json").is_symlink():
        raise EngineError("semantic_project_invalid", "A selected native project request cannot follow a symbolic alias.")
    if (project / "plot_request.json").is_file():
        # Native request fields select host publication capabilities. Only its
        # already admitted generation bytes may contribute those capabilities.
        recorded = store_for_project(project).read_bytes("plot_request.json")
        descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            actual, _mode = read_file(descriptor, "plot_request.json", owned=True)
        finally:
            os.close(descriptor)
        if actual != recorded:
            raise EngineError("semantic_project_changed", "The physical native project request differs from its admitted generation; reconcile it before selecting host resources.")
        from sciplot_core.studio_core.project_command_scope import project_store

        return project_store(project)
    return FileProjectStore(project)


def tracked_namespace_store(path: Path) -> tuple[FileProjectStore, Path] | None:
    """Recognize only an exact old-format namespace already tracked by a project."""
    from sciplot_core.project_store.io import STORE
    from .legacy_namespace import known_head

    namespace = next((item for item in (path, *path.parents)
                      if (item.parent.name == ".sciplot_documents" and item.name not in {"managed", "creations"})
                      or item.parent.name == "managed" and item.parent.parent.name == ".sciplot_documents"), None)
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
