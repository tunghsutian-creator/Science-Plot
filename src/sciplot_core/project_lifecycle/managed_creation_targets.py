"""Resolve Managed creation's Store member and optional visible output."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import EngineError
from .paths import canonical_path
from .ports import ProjectRepository
from .repository import FileProjectRepository, digest
from .targets import ManagedCreationLocation


def managed_creation_target(repository: ProjectRepository, request: dict[str, Any], *,
                            publish_fresh_managed_output: bool) -> ManagedCreationLocation:
    from .repository_router import ComposedProjectRepository
    if isinstance(repository, ComposedProjectRepository):
        from .attachment_targets import attached_managed_creation

        attached = attached_managed_creation(repository, request)
        if attached is not None:
            return attached
    sources = request["data_binding"]["data_sources"]
    if not sources:
        raise EngineError("managed_source_required", "Managed creation requires explicit original data sources.")
    source = canonical_path(Path(sources[0]["path"]))
    identifier = "plot:" + digest([str(source.parent), request["idempotency_key"]])[:24]
    _, root = _source_creation_roots(source, request["idempotency_key"], repository.exists)
    old_attempt = repository.exists(root / "managed-creation.json")
    versioned_task = request.get("storage") == "project_store_v2"
    # Keep the historical expert output locator without adding it to the
    # request. A versioned task publishes through its own delivery owner.
    output = (Path(request["out"]) if "out" in request else
              source.parent / (source.stem + "_SciPlot") / identifier.replace(":", "_"))
    public_output = publish_fresh_managed_output and not versioned_task
    if not old_attempt and (versioned_task or public_output):
        if not isinstance(repository, ComposedProjectRepository):
            raise EngineError("managed_store_required", "The versioned Managed task requires the Project Store repository.")
        from .attachment_targets import attached_managed_creation
        from .managed_store_target import managed_publication_target, open_managed_store

        publication = managed_publication_target(root, output, sources) if public_output else None
        declares_host_execution = bool(request.get("scientific_executors")) or any(
            node.get("kind") == "external" for node in request["data_binding"].get("transforms", []))

        def admit_host_execution() -> None:
            # Prove the exact current host registration before creating a
            # Store claim. The actual member is admitted by the same owner
            # under the writer lease, with its allocated stable plot ID.
            from .managed_creation import new_managed_member

            new_managed_member(request, identifier)

        store = open_managed_store(canonical_path(root), request,
                                   authorize_new=admit_host_execution if declares_host_execution else None)
        attached = attached_managed_creation(repository, request, store=store, publication=publication)
        assert attached is not None
        return attached
    if "out" in request:
        output = canonical_path(output)
    if output == source or output == source.parent or output in source.parents or output == root:
        raise EngineError("managed_output_conflict", "Select a distinct managed output directory beside the source.")
    if not old_attempt:
        from sciplot_core.foundation.research_destination import require_data_destination
        require_data_destination(root)
        require_data_destination(output)
    return ManagedCreationLocation(root, output, identifier)


def _source_creation_roots(source: Path, key: str, exists: Callable[[Path], bool]) -> tuple[Path, Path]:
    relative = Path(".sciplot_documents") / "managed" / digest(key)
    legacy = source.parent / relative
    root = legacy if exists(legacy / "managed-creation.json") else source_control_parent(source) / relative
    return legacy, root


def has_committed_managed_creation(request: dict[str, Any]) -> bool:
    """Check a frozen task's source-local attempt without admitting creation or recovery."""
    from .managed_store_target import has_committed_managed_store

    source = canonical_path(Path(request["data_binding"]["data_sources"][0]["path"]))
    reader = FileProjectRepository()
    legacy, root = _source_creation_roots(source, request["idempotency_key"], reader.exists)
    if reader.exists(root / "managed-creation.json"):
        return reader.has_head(root)
    # Retain the old task's direct-head check even for journals from before the
    # current creation record existed. A new Store wire requires its own proof.
    if request.get("storage") != "project_store_v2" and reader.has_head(legacy):
        return True
    return has_committed_managed_store(root, request)


def source_control_parent(source: Path) -> Path:
    from platformdirs import user_state_path
    from sciplot_core.foundation.research_destination import software_root
    return (user_state_path("SciPlot") / "source-projects" / digest(str(source.parent))
            if software_root(source.parent) is not None else source.parent)
