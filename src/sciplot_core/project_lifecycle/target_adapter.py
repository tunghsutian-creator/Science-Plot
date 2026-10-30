"""Resolve the existing filesystem formats at the composition boundary."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_io import read_json_object
from .errors import EngineError
from .paths import canonical_path
from .ports import ProjectRepository
from .repository import digest, document_root, transaction_path
from .targets import (DecisionKind, DecisionTarget, ImportTarget, ManagedCreationLocation,
                      ManagedDeliveryTarget, OpenTarget, StoredTarget)


class FilesystemProjectTargets:
    def __init__(self, repository: ProjectRepository, *,
                 resolve_figure: Callable[..., dict[str, Any]] | None = None) -> None:
        self.repository, self.resolve_figure = repository, resolve_figure

    def resolve_open(self, target: Path, figure_id: str | None = None) -> OpenTarget:
        target = canonical_path(target)
        from .repository_router import ComposedProjectRepository
        if isinstance(self.repository, ComposedProjectRepository):
            from .attachment_targets import resolve_attached_open

            attached = resolve_attached_open(self.repository, target, figure_id, self.resolve_figure)
            if attached is not None:
                return attached
        delivery_index = target / "index.json"
        package = read_json_object(delivery_index) if delivery_index.is_file() and not delivery_index.is_symlink() else None
        if package is not None and package.get("kind") == "sciplot_managed_delivery":
            from sciplot_core.plot_engine.managed_delivery_continuation import local_managed_target

            selected = local_managed_target(target, figure_id)
            return ManagedDeliveryTarget(selected["plot"], selected["item_id"], selected["native_snapshot"])
        if self.repository.has_head(target):
            return StoredTarget(target)
        resolve = self.resolve_figure
        if resolve is None:
            from sciplot_core.studio_core.project_query import resolve_project_figure

            resolve = resolve_project_figure
        selection = resolve(target, figure_id)
        project, selected_id = Path(selection["project"]), selection["figure_id"]
        return ImportTarget(document_root(project, selected_id), project, selected_id)

    def resolve_decision(self, target: Path) -> DecisionTarget:
        from .store_composition import namespace_root

        root = canonical_path(target)
        # These existing namespace formats are semantic aggregates. Classify
        # their command target without opening a query before its writer lease;
        # creation receipts have their own separate /creations/ namespace.
        if namespace_root(root) == root or root.parent.name == ".sciplot_semantic":
            return DecisionTarget(root, DecisionKind.SEMANTIC)
        return DecisionTarget(root, DecisionKind.CREATION if self.repository.exists(root / "creation.json") else DecisionKind.SEMANTIC)

    def creation_root(self, source: Path, key: str) -> Path:
        from .repository_router import ComposedProjectRepository

        if isinstance(self.repository, ComposedProjectRepository) and self.repository.selected_store() is not None:
            raise EngineError("semantic_project_creation_unsupported", "An attached existing project accepts Managed Template/Binding creation; source tasks create their own separate native project.")
        source = canonical_path(source)
        return transaction_path(source.parent / ".sciplot_documents" / "creations", key).parent

    def managed_creation(self, request: dict[str, Any]) -> ManagedCreationLocation:
        from .repository_router import ComposedProjectRepository
        if isinstance(self.repository, ComposedProjectRepository):
            from .attachment_targets import attached_managed_creation

            attached = attached_managed_creation(self.repository, request)
            if attached is not None:
                return attached
        sources = request["data_binding"]["data_sources"]
        if not sources:
            raise EngineError("managed_source_required", "Managed creation requires explicit original data sources.")
        source = canonical_path(Path(sources[0]["path"]))
        identifier = "plot:" + digest([str(source.parent), request["idempotency_key"]])[:24]
        root = source.parent / ".sciplot_documents" / "managed" / digest(request["idempotency_key"])
        output = canonical_path(Path(request["out"])) if "out" in request else source.parent / (source.stem + "_SciPlot") / identifier.replace(":", "_")
        if output == source or output == source.parent or output in source.parents or output == root:
            raise EngineError("managed_output_conflict", "Select a distinct managed output directory beside the source.")
        return ManagedCreationLocation(root, output, identifier)
