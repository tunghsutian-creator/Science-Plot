"""Keep new research namespaces outside SciPlot software; never move old data."""
from pathlib import Path
import tomllib
from platformdirs import user_cache_path

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def software_root(path: Path) -> Path | None:
    destination = path.expanduser().resolve()
    for package in (_PACKAGE_ROOT, _PACKAGE_ROOT.parent / "sciplot_recipes"):
        if destination == package or destination.is_relative_to(package):
            return package
    for parent in (destination, *destination.parents):
        project = parent / "pyproject.toml"
        if not (parent / "src" / "sciplot_core").is_dir() or not project.is_file():
            continue
        with project.open("rb") as stream:
            identity = tomllib.load(stream)
        project_identity = identity.get("project", {})
        if not isinstance(project_identity, dict):
            raise ValueError(f"Invalid source checkout project identity: {project}")
        if project_identity.get("name") == "sciplot-core":
            return parent
    return None


def require_data_destination(path: Path, *, existing_namespace: Path | None = None) -> Path:
    """Admit a new independent destination; never relocate existing user data.

    An application's already-loaded namespace may contain derived children.
    That internal parameter is not a wire option, permission grant or deletion
    authority. File/source/transaction validation remains with the actual owner.
    """
    destination = path.expanduser().resolve()
    if existing_namespace is not None:
        owner = existing_namespace.expanduser().resolve()
        if not owner.is_dir() or not (destination == owner or destination.is_relative_to(owner)):
            raise ValueError("Derived output must stay in its existing application namespace.")
        return destination
    protected = software_root(destination)
    if protected is not None:
        raise ValueError(
            f"New research output cannot be created inside SciPlot software: {destination}. "
            "Choose a dedicated research directory outside the source checkout. "
            "Existing inputs and saved projects were not moved or modified."
        )
    cache = (user_cache_path("SciPlot") / "development").resolve()
    if destination == cache or destination.is_relative_to(cache):
        raise ValueError(
            f"New research output cannot use the evictable SciPlot cache: {destination}. "
            "Choose a dedicated research directory outside application caches."
        )
    return destination
