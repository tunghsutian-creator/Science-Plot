"""Select the existing host composition for an exact already versioned project."""
from pathlib import Path

from sciplot_core.project_store.repository import FileProjectStore
from .errors import EngineError


def existing_store(project: Path) -> FileProjectStore:
    if (project / "plot_request.json").is_symlink():
        raise EngineError("semantic_project_invalid", "A selected native project request cannot follow a symbolic alias.")
    if (project / "plot_request.json").is_file():
        from sciplot_core.studio_core.project_command_scope import project_store

        return project_store(project)
    return FileProjectStore(project)
