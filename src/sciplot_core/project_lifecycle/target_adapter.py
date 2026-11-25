"""Resolve the existing filesystem formats at the composition boundary."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .contracts import RevisionToken
from .errors import EngineError
from .paths import canonical_path
from .ports import ProjectRepository
from .managed_creation_targets import managed_creation_target, source_control_parent
from .repository import document_root, transaction_path
from .targets import (DecisionKind, DecisionTarget, ImportTarget, ManagedCreationLocation,
                      ManagedDeliveryTarget, OpenTarget, StoredTarget)


class FilesystemProjectTargets:
    publish_fresh_managed_output = False

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
        from sciplot_core.plot_engine.managed_delivery_continuation import local_managed_target, managed_delivery_location

        delivery = managed_delivery_location(target)
        if delivery is not None:
            root, snapshot, manifest = delivery
            selected = local_managed_target(root, figure_id, native_snapshot=snapshot, manifest=manifest)
            return ManagedDeliveryTarget(selected["plot"], selected["item_id"], selected["native_snapshot"],
                                         RevisionToken.of(selected["head"]["document"]))
        if self.repository.has_head(target):
            return StoredTarget(target)
        resolve = self.resolve_figure
        if resolve is None:
            from sciplot_core.project_lifecycle.figure_observation import resolve_project_figure

            resolve = resolve_project_figure
        selection = resolve(target, figure_id)
        project, selected_id = Path(selection["project"]), selection["figure_id"]
        return ImportTarget(document_root(project, selected_id), project, selected_id)

    def read_legacy_saved(self, target: Path, figure_id: str | None) -> tuple[Path, Path] | None:
        """Resolve read-only authority by selection, before any attach or import."""
        from sciplot_core.plot_engine.managed_delivery_continuation import managed_delivery_location
        from .attachment_index import read_index
        from .head_observation import observe_plot_head
        from .store_composition import existing_store
        from sciplot_core.project_store.io import STORE
        from sciplot_core.studio_core.legacy_saved_plot import _saved_plot

        def stored(root: Path) -> tuple[Path, Path] | None:
            envelope = observe_plot_head(root, owner=self.repository)
            assert envelope is not None
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

        if managed_delivery_location(target) is not None:
            return None

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
        return transaction_path(source_control_parent(source) / ".sciplot_documents" / "creations", key).parent

    def managed_creation(self, request: dict[str, Any]) -> ManagedCreationLocation:
        return managed_creation_target(self.repository, request,
                                       publish_fresh_managed_output=self.publish_fresh_managed_output)


class PublicFilesystemProjectTargets(FilesystemProjectTargets):
    """New public expert plots publish to their admitted output."""

    publish_fresh_managed_output = True


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
