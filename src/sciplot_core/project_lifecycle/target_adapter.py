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
                 resolve_figure: Callable[..., dict[str, Any]] | None = None,
                 publish_fresh_managed_output: bool = False) -> None:
        self.repository, self.resolve_figure = repository, resolve_figure
        self.publish_fresh_managed_output = publish_fresh_managed_output

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

    def read_legacy_saved(self, target: Path, figure_id: str | None) -> tuple[Path, Path] | None:
        """Resolve read-only authority by selection, before any attach or import."""
        from .attachment_index import read_index
        from .store_composition import existing_store
        from sciplot_core.project_store.io import STORE
        from sciplot_core.studio_core.legacy_saved_plot import _saved_plot

        def stored(root: Path) -> tuple[Path, Path] | None:
            envelope = self.repository.load_head(root)
            document, binding = envelope["document"], envelope["binding"]
            authority = document.get("plot_type")
            if authority == "LegacyPlot" or (authority is None and
                    document.get("coverage", {}).get("mode") in {"legacy_shadow", "opaque"}):
                if binding.get("kind") != "sciplot_veusz_binding":
                    raise EngineError("legacy_native_binding_missing", "The saved legacy figure has no exact native document.")
                return canonical_path(Path(binding["project"])), canonical_path(Path(binding["document"]))
            return None

        from sciplot_core.delivery_identity import DELIVERY_IDENTITY
        from sciplot_core.policy import DELIVERY_LAUNCHER, DELIVERY_PROJECT_DIR

        delivery = target if target.is_dir() else target.parent
        if (target.is_dir() or target.name in {DELIVERY_IDENTITY, DELIVERY_LAUNCHER}) and (
                not (delivery / "plot_request.json").is_file() and
                (delivery / DELIVERY_PROJECT_DIR).is_dir() and any(
                    (delivery / name).is_file() for name in (DELIVERY_IDENTITY, DELIVERY_LAUNCHER))):
            from sciplot_core.studio_core.delivery_target import resolve_delivery_target

            resolved = resolve_delivery_target(target)
            if resolved is not None:
                if resolved["mode"] == "vsz":
                    if figure_id is not None:
                        raise EngineError("legacy_delivery_figure_required", "Pass the exact saved VSZ for a portable secondary figure.")
                    return canonical_path(delivery), canonical_path(Path(resolved["document"]))
                return self.read_legacy_saved(canonical_path(Path(resolved["project_dir"])), figure_id)

        explicit_vsz = target.is_file() and target.suffix.lower() == ".vsz"
        if explicit_vsz:
            from sciplot_core.studio_core.legacy_saved_plot import _native_file_root

            root = _native_file_root(target)
        else:
            root = target.parent if target.name == "plot_request.json" else target
        with self.repository.query_scope(root):
            if not explicit_vsz and self.repository.has_head(root):
                return stored(root)
            store = existing_store(root) if (root / STORE / "head.json").is_file() else None
            if store is not None and not explicit_vsz:
                entries = list(read_index(store)["attachments"].values())
                matches = [entry for entry in entries
                           if figure_id in {entry["figure_id"], entry["plot_id"]}] if figure_id is not None else entries
                if len(matches) == 1:
                    attached = root / matches[0]["namespace"]
                    if self.repository.has_head(attached):
                        return stored(attached)
                    if matches[0].get("managed_output") is not None:
                        return None
                if len(matches) > 1:
                    return None
            if not explicit_vsz and not ((root / "plot_request.json").is_file()
                    and (root / "studio" / "document.vsz").is_file()):
                return None
            saved = _saved_plot(target, figure_id)
            if store is not None and _prepared_native_figure(store, saved[1]):
                return None
            return saved

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
        legacy = transaction_path(source.parent / ".sciplot_documents" / "creations", key).parent
        if self.repository.exists(legacy / "creation.json"):
            return legacy
        return transaction_path(_source_control_parent(source) / ".sciplot_documents" / "creations", key).parent

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
        legacy = source.parent / ".sciplot_documents" / "managed" / digest(request["idempotency_key"])
        control = _source_control_parent(source) / ".sciplot_documents"
        root = legacy if self.repository.exists(legacy / "managed-creation.json") else control / "managed" / digest(request["idempotency_key"])
        old_attempt = self.repository.exists(root / "managed-creation.json")
        # Public expert output is a publication destination, not a backend
        # workspace. Leave registered external-executor creation on its
        # original route until it has equivalent Store host grants.
        public_output = (self.publish_fresh_managed_output and "out" in request
                         and not request.get("scientific_executors")
                         and not any(node.get("kind") == "external"
                                     for node in request["data_binding"].get("transforms", [])))
        if not old_attempt and (request.get("storage") == "project_store_v2" or public_output):
            if not isinstance(self.repository, ComposedProjectRepository):
                raise EngineError("managed_store_required", "The versioned Managed task requires the Project Store repository.")
            from .attachment_targets import attached_managed_creation
            from .managed_store_target import managed_publication_target, open_managed_store

            publication = managed_publication_target(root, request) if public_output else None
            store = open_managed_store(canonical_path(root), request)
            attached = attached_managed_creation(self.repository, request, store=store, publication=publication)
            assert attached is not None
            return attached
        output = canonical_path(Path(request["out"])) if "out" in request else source.parent / (source.stem + "_SciPlot") / identifier.replace(":", "_")
        if output == source or output == source.parent or output in source.parents or output == root:
            raise EngineError("managed_output_conflict", "Select a distinct managed output directory beside the source.")
        if not old_attempt:
            from sciplot_core.foundation.research_destination import require_data_destination
            require_data_destination(root)
            require_data_destination(output)
        return ManagedCreationLocation(root, output, identifier)


def _prepared_native_figure(store: Any, document: Path) -> bool:
    """A real generation-owned native figure is not an imported legacy shadow."""
    from sciplot_core.project_commands import ProjectCommands

    relative = document.relative_to(store.root).as_posix()
    for record in ProjectCommands(store).commands():
        metadata = record.get("metadata", {})
        request = metadata.get("request", {})
        if (record["phase"] == "complete" and metadata.get("kind") == "figure_set"
                and request.get("family") == "studio_preparation"
                and request.get("prepared_files", {}).get(relative)):
            return True
    return False


def _source_control_parent(source: Path) -> Path:
    from platformdirs import user_state_path
    from sciplot_core.foundation.research_destination import software_root
    return (user_state_path("SciPlot") / "source-projects" / digest(str(source.parent))
            if software_root(source.parent) is not None else source.parent)
