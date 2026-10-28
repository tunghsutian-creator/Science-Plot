"""The semantic logical repository on the existing complete-generation byte owner."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from fnmatch import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.writer_lease import exclusive_directory_lease
from sciplot_core.foundation.source_locations import source_location_scope
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation, SourceAdoption
from .attachment_index import Attachment, INDEX, OWNER, encode, read_index
from .attachment_projection import derived_relative, metadata_view
from .attachment_sources import AttachmentSourceResolver, prepared_sources, record_sources
from .errors import EngineError
from .journal_identity import saved_command
from .repository import FileProjectRepository
from .prepared_admission import PreparedReads, prepared_batch


@dataclass
class _Batch:
    snapshot: dict[str, Any]
    writes: dict[str, bytes | None] = field(default_factory=dict)
    reads: dict[str, str | None] = field(default_factory=dict)
    prepared: PreparedReads | None = None


class AttachedProjectRepository(FileProjectRepository):
    """Reuse every semantic validation; replace bytes and coherent publication only."""
    def __init__(self, attachment: Attachment, *, new_sources: tuple[dict[str, Any], ...] = ()) -> None:
        super().__init__()
        self.attachment, self._new_sources = attachment, new_sources
        self._batch: ContextVar[_Batch | None] = ContextVar("sciplot_attached_semantic_batch", default=None)
        self._source: ContextVar[AttachmentSourceResolver | None] = ContextVar("sciplot_attached_source_scope", default=None)

    def _cache_path(self, path: Path) -> Path | None:
        if path == self.attachment.cache or path.is_relative_to(self.attachment.cache):
            return path
        output = self.attachment.output
        if output is not None:
            original = Path(self.attachment.entry["managed_output"])
            for root in (original, output):
                if path == root or path.is_relative_to(root):
                    return output / path.relative_to(root)
        relative = self.attachment.relative(path)
        return self.attachment.cache / "state" / relative if relative is not None and derived_relative(relative) else None

    def runtime_path(self, path: Path) -> Path:
        return self._cache_path(path) or path

    @contextmanager
    def backend_scope(self, generation: str | None = None) -> Iterator[None]:
        current = self._source.get()
        if current is not None and (generation is None or generation == current.generation):
            yield
            return
        resolver = AttachmentSourceResolver(self.attachment.store, self._new_sources, generation=generation)
        token = self._source.set(resolver)
        try:
            with source_location_scope(resolver):
                yield
        finally:
            self._source.reset(token)

    @contextmanager
    def lease(self, root: Path) -> Iterator[None]:
        if self.attachment.relative(root) != Path("."):
            raise EngineError("semantic_attachment_path_invalid", "The aggregate lease requires its exact attached namespace.")
        lock = self.attachment.store.root / ".sciplot_store" / "semantic-locks" / self.attachment.entry["id"]
        lock.mkdir(parents=True, exist_ok=True, mode=0o700)
        with exclusive_directory_lease(lock) as held:
            with self.backend_scope():
                yield
            held.verify()

    def validation_root(self, root: Path) -> Path:
        return self.attachment.origin

    def runtime_envelope(self, root: Path, envelope: dict[str, Any]) -> dict[str, Any]:
        self._materialize_history()
        result: dict[str, Any] = metadata_view(envelope, self.attachment)
        return result

    def load_revision(self, root: Path, revision: int) -> dict[str, Any]:
        envelope = self._load_revision_envelope(root, revision)
        result = self.runtime_envelope(root, envelope)
        if self.has_head(root) and self._head_envelope(root)["document"]["revision"] != revision:
            from .attachment_versions import introduced_generation

            logical = self.attachment.logical(root / "revisions" / f"{revision:08d}.json")
            result["binding"]["_semantic_project_generation"] = introduced_generation(self.attachment.store, logical)
        return result

    def _materialize_history(self) -> None:
        from sciplot_core.project_store.io import install
        import os

        for relative, logical in self.attachment.entry.get("archived_derivatives", {}).items():
            target = self.attachment.cache / "state" / relative
            if target.exists():
                continue
            data = self.attachment.store.read_bytes(logical)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                install(descriptor, target.name, data, exclusive=True)
            except FileExistsError:
                pass
            finally:
                os.close(descriptor)

    def storage_binding(self, root: Path, binding: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = metadata_view(binding, self.attachment, storing=True, binding=True)
        return result

    @contextmanager
    def storage_batch(self, root: Path) -> Iterator[None]:
        if self._batch.get() is not None:
            yield
            return
        prepared = prepared_batch(self.attachment.store)
        batch = (_Batch(prepared[0], prepared=prepared[1]) if prepared is not None
                 else _Batch(self.attachment.store.snapshot()))
        token = self._batch.set(batch)
        try:
            yield
            self._flush(batch)
        finally:
            self._batch.reset(token)

    def _flush(self, batch: _Batch) -> None:
        if not batch.writes:
            return
        index = read_index(self.attachment.store, batch.snapshot)
        identity = self.attachment.entry["id"]
        existing = index["attachments"].get(identity)
        if existing is not None and existing != self.attachment.entry:
            raise EngineError("semantic_attachment_identity_conflict", "A stable semantic attachment cannot be redirected.")
        if existing is None:
            index["attachments"][identity] = self.attachment.entry
            batch.writes[INDEX] = encode(index)
            batch.reads[INDEX] = batch.snapshot["files"].get(INDEX, {}).get("sha256")
        marker = self.attachment.entry["namespace"] + "/" + OWNER
        if marker not in batch.snapshot["files"]:
            batch.writes[marker] = encode({"kind": "sciplot_semantic_owner", "version": 1,
                "origin_root": str(self.attachment.root), "project": str(self.attachment.store.root),
                "project_id": batch.snapshot["project_id"], "attachment_id": identity})
            batch.reads[marker] = None
        writes = {name: data for name, data in batch.writes.items()
                  if data is None or hashlib.sha256(data).hexdigest() != batch.snapshot["files"].get(name, {}).get("sha256")}
        if not writes:
            return
        for name in writes:
            batch.reads.setdefault(name, batch.snapshot["files"].get(name, {}).get("sha256"))
        sources = []
        for logical, payload in writes.items():
            if payload is not None:
                try:
                    sources.extend(record_sources(logical, json.loads(payload)))
                except (UnicodeError, ValueError):
                    pass  # Immutable binary/native resources are not source declarations.
        resolver = self._source.get()
        bound = {(source["path"], source["sha256"]) for source in sources}
        incoming = [item for item in resolver.pending if item.get("logical") in batch.snapshot["files"]
                    and (item["path"], item["sha256"]) in bound
                    and batch.snapshot["files"][item["logical"]]["sha256"] != item["sha256"]] if resolver else []
        captured = prepared_sources(self.attachment.store, sources,
                                   force=frozenset((item["path"], item["sha256"]) for item in incoming))
        observations = {}
        for item in incoming:
            logical = item["logical"]
            source = next(source for source in captured if source.locator == item["path"] and source.version == item["sha256"])
            before = batch.snapshot["files"][logical]["sha256"]
            batch.reads[logical] = before
            observations[logical] = SourceAdoption(logical, source.source_id, before, item["sha256"])
        if batch.prepared is not None:
            for name, expected in batch.prepared.files:
                if name in batch.reads and batch.reads[name] != expected:
                    raise EngineError("prepared_project_changed", "Semantic adoption differs from its prepared publication reads.")
                batch.reads[name] = expected
        mutation = ProjectMutation(writes, {"attachment_id": identity, "resources": sorted(writes)}, prepared_sources=captured)
        publication = canonical_json_sha256({"prepared": mutation.prepared_digest,
            "generation": batch.snapshot["generation"], "reads": batch.reads}, allow_nan=False)
        key = "semantic:" + identity + ":" + publication[:32]
        command = ProjectCommand.create("semantic_record", key, project_id=batch.snapshot["project_id"],
            expected_generation=batch.snapshot["generation"], read_set=batch.reads,
            write_set=sorted(writes), request={"prepared_digest": mutation.prepared_digest, "attachment_id": identity},
            source_adoptions=tuple(observations.values()),
            read_memberships=batch.prepared.memberships if batch.prepared is not None else (),
            source_trees=(batch.prepared.source,) if batch.prepared is not None else ())
        if batch.prepared is not None:
            admitted = self.attachment.store.reserve(command.key, command.command_digest,
                expected_generation=command.expected_generation, read_set=dict(command.read_set),
                write_set=command.write_set, metadata=command.to_payload())
            if admitted.get('source_tree_origins', {}).get(batch.prepared.source.locator) != batch.prepared.source_origin:
                raise EngineError('source_changed', 'The prepared source changed before its exact Core admission.')
        ProjectCommands(self.attachment.store).publish_prepared(command, mutation)
        if resolver is not None:
            resolver.refresh()

    def _bytes(self, path: Path) -> bytes:
        logical = self.attachment.logical(path)
        batch = self._batch.get()
        if batch is not None:
            if logical in batch.writes:
                data = batch.writes[logical]
                if data is None:
                    raise FileNotFoundError(path)
                return data
            snapshot = batch.snapshot
            batch.reads.setdefault(logical, snapshot["files"].get(logical, {}).get("sha256"))
        else:
            snapshot = self.attachment.store.snapshot()
        if logical not in snapshot["files"]:
            raise FileNotFoundError(path)
        return self.attachment.store.read_bytes(logical, generation=snapshot["generation"])

    def content_snapshot(self, path: Path) -> dict[str, Any]:
        data = self._bytes(path)
        return {"bytes": data, "sha256": hashlib.sha256(data).hexdigest(), "identity": {"size": len(data)}}

    def publish_content(self, path: Path, payload: bytes, verify_existing: Callable[[], None]) -> None:
        if self.exists(path):
            verify_existing()
            if self._bytes(path) != payload:
                raise EngineError("document_content_corrupt", "An immutable scientific content blob already has different bytes.")
            return
        with self.storage_batch(self.attachment.root):
            batch = self._batch.get()
            assert batch is not None
            logical = self.attachment.logical(path)
            batch.reads.setdefault(logical, None)
            batch.writes[logical] = payload

    def exists(self, path: Path) -> bool:
        cache = self._cache_path(path)
        if cache is not None:
            return cache.exists()
        relative = self.attachment.relative(path)
        if relative is None:
            raise EngineError("semantic_attachment_path_invalid", "Attached semantic IO cannot escape its registered namespace.")
        if not relative.parts:
            return bool(self.attachment.store.snapshot()["files"].get(INDEX))
        try:
            self._bytes(path)
            return True
        except FileNotFoundError:
            logical = self.attachment.logical(path) + "/"
            return any(name.startswith(logical) for name in self.attachment.store.snapshot()["files"])

    def read(self, path: Path) -> dict[str, Any]:
        cache = self._cache_path(path)
        if cache is not None:
            payload = read_json_object(cache)
            if payload is None:
                raise EngineError("document_state_missing", "The disposable semantic cache is absent.", evidence=str(cache))
            result: dict[str, Any] = metadata_view(payload, self.attachment)
            return result
        try:
            value = json.loads(self._bytes(path))
        except (OSError, ValueError) as exc:
            raise EngineError("document_state_missing", "Required attached semantic state is absent or invalid.", evidence=str(path)) from exc
        if not isinstance(value, dict):
            raise EngineError("document_state_invalid", "Attached semantic JSON must be an object.")
        if path.name == "transaction.json":
            saved_command(value)
            self._materialize_history()
        relative = self.attachment.relative(path)
        if relative is not None and (relative.parts[0] == "revisions" or relative.as_posix() == "head.json"):
            return value  # Original envelope digest is checked before runtime projection.
        projected: dict[str, Any] = metadata_view(value, self.attachment)
        return projected

    def write(self, path: Path, payload: dict[str, Any]) -> None:
        cache = self._cache_path(path)
        if cache is not None:
            atomic_write_json(cache, metadata_view(payload, self.attachment, storing=True))
            return
        value = metadata_view(payload, self.attachment, storing=True)
        with self.storage_batch(self.attachment.root):
            batch = self._batch.get()
            assert batch is not None
            logical = self.attachment.logical(path)
            batch.reads.setdefault(logical, batch.snapshot["files"].get(logical, {}).get("sha256"))
            batch.writes[logical] = encode(value)

    def json_members(self, directory: Path, pattern: str) -> list[Path]:
        cache = self._cache_path(directory)
        if cache is not None:
            return sorted(cache.glob(pattern))
        relative = self.attachment.relative(directory)
        if relative is None:
            raise EngineError("semantic_attachment_path_invalid", "Only registered semantic members may be listed.")
        prefix = self.attachment.entry["namespace"] + "/" + relative.as_posix().rstrip(".").rstrip("/")
        prefix = prefix.rstrip("/") + "/"
        names = set(self.attachment.store.snapshot()["files"])
        batch = self._batch.get()
        if batch is not None:
            names.update(batch.writes)
        return sorted(self.attachment.root / Path(name).relative_to(self.attachment.entry["namespace"])
                      for name in names if name.startswith(prefix) and "/" not in name[len(prefix):]
                      and fnmatch(name[len(prefix):], pattern))

    def prepare_namespace(self, root: Path) -> None:
        if self.attachment.relative(root) is None:
            raise EngineError("semantic_attachment_path_invalid", "A namespace must belong to this attachment.")

    def create_namespace(self, root: Path) -> None:
        self.prepare_namespace(root)

    def require_empty_output(self, output: Path) -> None:
        if not (output.is_relative_to(self.attachment.store.root) or output.is_relative_to(self.attachment.cache)):
            raise EngineError("managed_output_conflict", "Attached derived output requires an explicit project-owned location.")
        if output.exists() and any(output.iterdir()):
            raise EngineError("managed_output_conflict", "The selected derived output already contains files.")
