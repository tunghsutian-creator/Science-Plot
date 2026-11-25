"""Resolve Managed creation's Store member and optional visible output."""
from pathlib import Path
from typing import Any

from .errors import EngineError
from .paths import canonical_path
from .ports import ProjectRepository
from .repository import digest
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
    legacy = source.parent / ".sciplot_documents" / "managed" / digest(request["idempotency_key"])
    control = source_control_parent(source) / ".sciplot_documents"
    root = legacy if repository.exists(legacy / "managed-creation.json") else control / "managed" / digest(request["idempotency_key"])
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


def source_control_parent(source: Path) -> Path:
    from platformdirs import user_state_path
    from sciplot_core.foundation.research_destination import software_root
    return (user_state_path("SciPlot") / "source-projects" / digest(str(source.parent))
            if software_root(source.parent) is not None else source.parent)
