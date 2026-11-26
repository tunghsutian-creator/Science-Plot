"""Locate an exact native file without reading or writing its project."""
from pathlib import Path

from sciplot_core.foundation.canonical_paths import canonical_path


def _native_owner_root(target: Path) -> Path | None:
    from sciplot_core.delivery_identity import DELIVERY_IDENTITY
    from sciplot_core.policy import DELIVERY_LAUNCHER, DELIVERY_PROJECT_DIR

    return next((parent for parent in target.parents
                 if (parent / "plot_request.json").is_file() or (parent / DELIVERY_IDENTITY).is_file()
                 or (target.is_relative_to(parent / DELIVERY_PROJECT_DIR)
                     and (parent / DELIVERY_LAUNCHER).is_file())), None)


def native_file_root(target: Path) -> Path:
    return _native_owner_root(target) or target.parent


def is_standalone_export_target(document: Path, output: Path) -> bool:
    """Allow exact export only from an unowned VSZ into a separate artifact tree."""
    document = canonical_path(document)
    if not document.is_file() or _native_owner_root(document) is not None:
        return False
    destination = canonical_path(output)
    source = document.parent
    return not (destination.is_relative_to(source) or source.is_relative_to(destination))


def saved_native_target(target: Path, figure_id: str | None) -> tuple[Path, Path]:
    target = canonical_path(target)
    if target.is_file() and target.suffix.lower() == ".vsz":
        root = native_file_root(target)
        if figure_id is not None:
            from sciplot_core.project_lifecycle.figure_observation import observe_legacy_project

            if not (root / "plot_request.json").is_file():
                raise ValueError("Select a project directory to use a figure ID.")
            observation = observe_legacy_project(root)
            selected = observation.select(figure_id)
            observation.require_current(selected=selected)
            if selected["document"] != str(target):
                raise ValueError("The figure ID does not match this saved VSZ.")
        return root, target
    if not ((target.is_dir() and (target / "plot_request.json").is_file())
            or (target.is_file() and target.name == "plot_request.json")):
        raise ValueError("Select a saved project directory, plot_request.json or exact .vsz file.")
    from sciplot_core.project_lifecycle.figure_observation import resolve_project_figure

    selected = resolve_project_figure(target, figure_id)
    return Path(selected["project"]), Path(selected["document"])
