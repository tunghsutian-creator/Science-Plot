"""Invocation-local attachment selection; standalone and attached never dual-write."""
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import selected_project_store
from .attached_repository import AttachedProjectRepository
from .attachment_index import Attachment, owned_marker, read_index
from .errors import EngineError
from .repository import FileProjectRepository
from .store_composition import existing_store, project_identity, tracked_namespace_store


@dataclass
class _Invocation:
    owner: Any
    stack: ExitStack
    repositories: dict[tuple[str, str], AttachedProjectRepository] = field(default_factory=dict)


_ACTIVE: ContextVar[_Invocation | None] = ContextVar("sciplot_semantic_attachments", default=None)


class ComposedProjectRepository(FileProjectRepository):
    def __init__(self, *, lease: Any = None, attachment_admission: Any = None) -> None:
        super().__init__(lease=lease)
        self._attachment_admission = attachment_admission

    def validate_attachment(self, namespace: Any, envelope: dict[str, Any], attachment: Attachment) -> Any:
        if self._attachment_admission is None:
            raise EngineError("semantic_attachment_admission_required", "Composition must provide the original native currentness validator before ownership transfer.")
        return self._attachment_admission(namespace, envelope, attachment)

    @contextmanager
    def invocation_scope(self) -> Iterator[None]:
        existing = _ACTIVE.get()
        if existing is not None and existing.owner is self:
            yield
            return
        with ExitStack() as stack:
            token = _ACTIVE.set(_Invocation(self, stack))
            try:
                yield
            finally:
                _ACTIVE.reset(token)

    def select(self, attachment: Attachment, *, new_sources: tuple[dict[str, Any], ...] = ()) -> AttachedProjectRepository:
        active = _ACTIVE.get()
        if active is None or active.owner is not self:
            raise RuntimeError("An attached semantic repository requires an application invocation scope.")
        key = (str(attachment.store.root), attachment.entry["id"])
        existing = active.repositories.get(key)
        if existing is not None:
            return existing
        selected = AttachedProjectRepository(attachment, new_sources=new_sources)
        active.repositories[key] = selected
        return selected

    @contextmanager
    def binding_scope(self, binding: dict[str, Any]) -> Iterator[None]:
        root = binding.get("root")
        selected = self._discover(Path(root)) if root else None
        identity = binding.get("_semantic_attachment_id")
        active = _ACTIVE.get()
        if selected is None and identity is not None and active is not None and active.owner is self:
            exact = [repo for repo in active.repositories.values() if repo.attachment.entry["id"] == identity]
            selected = exact[0] if len(exact) == 1 else None
        if identity is not None and (selected is None or selected.attachment.entry["id"] != identity):
            raise EngineError("semantic_attachment_owner_conflict", "The runtime binding does not name its selected semantic attachment.")
        if selected is None:
            matches = [repo for repo in active.repositories.values() if binding.get("project") == str(repo.attachment.store.root)] if active and active.owner is self else []
            leased = [repo for repo in matches if repo._source.get() is not None]
            selected = matches[0] if len(matches) == 1 else leased[0] if len(leased) == 1 else None
            if matches and selected is None:
                raise EngineError("semantic_attachment_ambiguous", "The native binding requires its exact selected semantic attachment.")
        if selected is None:
            yield
        else:
            with selected.backend_scope(binding.get("_semantic_project_generation")):
                yield

    def selected_store(self) -> FileProjectStore | None:
        return selected_project_store()

    @contextmanager
    def scientific_request_scope(self, root: Path, request: dict[str, Any]) -> Iterator[None]:
        selected = self._discover(root)
        if selected is None:
            yield
            return
        from .attachment_admission import scientific_sources
        from .repository import transaction_path

        if selected.exists(transaction_path(root, request["idempotency_key"])):
            yield  # A saved command already owns its frozen source versions.
        else:
            with scientific_sources(selected, request):
                yield

    def _discover(self, path: Path) -> AttachedProjectRepository | None:
        active = _ACTIVE.get()
        if active is not None and active.owner is self:
            for selected in active.repositories.values():
                if selected.attachment.contains(path):
                    return selected
        candidates = []
        explicit = self.selected_store()
        if explicit is not None:
            candidates.append(explicit)
        # This is an exact versioned namespace format, never source-parent or
        # sibling-project discovery. Its index must confirm the stable identity.
        for parent in (path, *path.parents):
            if parent.name == ".sciplot_semantic":
                project = parent.parent
                if (project / STORE / "head.json").is_file():
                    candidates.append(existing_store(project))
                break
        tracked = tracked_namespace_store(path)
        if tracked is not None:
            candidates.append(tracked[0])
        marker = owned_marker(path)
        if marker is not None:
            owner = marker[1]
            if explicit is None or project_identity(explicit) != owner["project_id"]:
                project = Path(owner["project"])
                if not (project / STORE / "head.json").is_file() and not candidates:
                    raise EngineError("semantic_attachment_project_moved", "Open the moved project explicitly; the old namespace remains read-only history.")
                if (project / STORE / "head.json").is_file():
                    candidates.append(existing_store(project))
        for store in candidates:
            index = read_index(store)
            for entry in index["attachments"].values():
                attachment = Attachment(store, entry)
                if attachment.contains(path):
                    if marker is not None:
                        owner = marker[1]
                        accepted_origins = {entry["origin_root"], str(attachment.namespace_origin), entry.get("transfer_root")}
                        if (index["project_id"] != owner["project_id"] or owner["attachment_id"] != entry["id"]
                                or owner["origin_root"] not in accepted_origins):
                            raise EngineError("semantic_attachment_owner_conflict", "The semantic ownership fence does not identify this exact project attachment.")
                    return self.select(attachment)
        if marker is not None:
            raise EngineError("semantic_attachment_import_pending", "The namespace transfer is fenced but its complete generation is not yet published.",
                              action="open_attached_project")
        if tracked is not None:
            from .attachment_import import attach_existing

            store, namespace = tracked
            if explicit is not None and project_identity(explicit) != project_identity(store):
                raise EngineError("semantic_attachment_project_conflict", "The explicit semantic path belongs to another project generation.")
            return self.select(attach_existing(store, namespace, figure_id=None, validate=self.validate_attachment))
        return None

    def runtime_path(self, path: Path) -> Path:
        selected = self._discover(path)
        return selected.runtime_path(path) if selected is not None else path

    def _owner(self, path: Path) -> FileProjectRepository:
        return self._discover(path) or self

    def lease(self, root: Path) -> Any:
        owner = self._owner(root)
        return super().lease(root) if owner is self else owner.lease(root)

    def exists(self, path: Path) -> bool:
        owner = self._owner(path)
        return super().exists(path) if owner is self else owner.exists(path)

    def read(self, path: Path) -> dict[str, Any]:
        owner = self._owner(path)
        return super().read(path) if owner is self else owner.read(path)

    def write(self, path: Path, payload: dict[str, Any]) -> None:
        owner = self._owner(path)
        if owner is self:
            super().write(path, payload)
        else:
            owner.write(path, payload)

    def load_head(self, root: Path) -> dict[str, Any]:
        owner = self._owner(root)
        return super().load_head(root) if owner is self else owner.load_head(root)

    def load_revision(self, root: Path, revision: int) -> dict[str, Any]:
        owner = self._owner(root)
        return super().load_revision(root, revision) if owner is self else owner.load_revision(root, revision)

    def commit(self, root: Path, document: dict[str, Any], binding: dict[str, Any], transaction: str) -> None:
        owner = self._owner(root)
        if owner is self:
            super().commit(root, document, binding, transaction)
        else:
            owner.commit(root, document, binding, transaction)

    def persist(self, root: Path, transaction: dict[str, Any]) -> None:
        owner = self._owner(root)
        if owner is self:
            super().persist(root, transaction)
        else:
            owner.persist(root, transaction)

    def reserve(self, root: Path, transaction: dict[str, Any]) -> None:
        owner = self._owner(root)
        if owner is self:
            super().reserve(root, transaction)
        else:
            owner.reserve(root, transaction)

    def content_snapshot(self, path: Path) -> dict[str, Any]:
        owner = self._owner(path)
        return super().content_snapshot(path) if owner is self else owner.content_snapshot(path)

    def publish_content(self, path: Path, payload: bytes, verify_existing: Callable[[], None]) -> None:
        owner = self._owner(path)
        if owner is self:
            super().publish_content(path, payload, verify_existing)
        else:
            owner.publish_content(path, payload, verify_existing)

    def json_members(self, directory: Path, pattern: str) -> list[Path]:
        owner = self._owner(directory)
        return super().json_members(directory, pattern) if owner is self else owner.json_members(directory, pattern)

    def prepare_namespace(self, root: Path) -> None:
        owner = self._owner(root)
        if owner is self:
            super().prepare_namespace(root)
        else:
            owner.prepare_namespace(root)

    def create_namespace(self, root: Path) -> None:
        owner = self._owner(root)
        if owner is self:
            super().create_namespace(root)
        else:
            owner.create_namespace(root)

    def require_empty_output(self, output: Path) -> None:
        active = _ACTIVE.get()
        owners = [repo for repo in active.repositories.values() if output.is_relative_to(repo.attachment.store.root)] if active and active.owner is self else []
        if len(owners) == 1:
            owners[0].require_empty_output(output)
        else:
            super().require_empty_output(output)
