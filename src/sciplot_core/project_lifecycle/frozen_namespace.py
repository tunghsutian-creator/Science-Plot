"""Validate one captured old format with its original root and no fallback IO."""
from fnmatch import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any
from collections.abc import Callable

from sciplot_core.project_store.repository import FileProjectStore
from .attachment_projection import path_metadata_view
from .legacy_namespace import capture_registered

from .errors import EngineError
from .repository import FileProjectRepository


class FrozenNamespaceRepository(FileProjectRepository):
    """A read adapter; the existing repository owns all seal/aggregate validation."""
    def __init__(self, origin: Path, physical: Path, members: dict[str, bytes], *,
                 artifacts: dict[Path, bytes] | None = None, artifact_roots: tuple[Path, ...] = ()) -> None:
        super().__init__()
        self.origin, self.physical, self.members = origin, physical, members
        self.artifacts, self.artifact_roots = artifacts or {}, artifact_roots

    def _relative(self, path: Path) -> str:
        for root in (self.origin, self.physical):
            if path != root and path.is_relative_to(root):
                return path.relative_to(root).as_posix()
        raise EngineError("semantic_attachment_path_invalid", "The old format read escaped its exact captured namespace.")

    def _bytes(self, path: Path) -> bytes:
        if path in self.artifacts:
            return self.artifacts[path]
        try:
            return self.members[self._relative(path)]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    def exists(self, path: Path) -> bool:
        if any(path == root or path.is_relative_to(root) for root in self.artifact_roots):
            return path in self.artifacts
        if path in {self.origin, self.physical}:
            return bool(self.members)
        return self._relative(path) in self.members

    def read(self, path: Path) -> dict[str, Any]:
        value = json.loads(self._bytes(path))
        if not isinstance(value, dict):
            raise EngineError("document_state_invalid", "The captured old semantic JSON must be an object.")
        result: dict[str, Any] = value
        return result

    def content_snapshot(self, path: Path) -> dict[str, Any]:
        data = self._bytes(path)
        return {"bytes": data, "sha256": hashlib.sha256(data).hexdigest(), "identity": {"size": len(data)}}

    def json_members(self, directory: Path, pattern: str) -> list[Path]:
        prefix = self._relative(directory) + "/"
        return [directory / name.removeprefix(prefix) for name in sorted(self.members)
                if name.startswith(prefix) and fnmatch(name.removeprefix(prefix), pattern)]

    def write(self, path: Path, payload: dict[str, Any]) -> None:
        raise EngineError("semantic_attachment_history_read_only", "Captured original history cannot acquire a second writer.")

    def publish_content(self, path: Path, payload: bytes, verify_existing: Callable[[], None]) -> None:
        raise EngineError("semantic_attachment_history_read_only", "Captured original history cannot acquire a second writer.")

    def prepare_namespace(self, root: Path) -> None:
        raise EngineError("semantic_attachment_history_read_only", "Captured original history cannot acquire a second writer.")

    def create_namespace(self, root: Path) -> None:
        self.prepare_namespace(root)

    def require_empty_output(self, output: Path) -> None:
        self.prepare_namespace(output)


class NamespaceQueryRepository(FrozenNamespaceRepository):
    """A captured read witness, never a second head or attachment identity."""
    def __init__(self, store: FileProjectStore, namespace: Path) -> None:
        self.store, self.namespace = store, namespace
        self.witness = capture_registered(store, namespace)
        super().__init__(self.witness.origin, self.witness.physical, self.witness.members)
        with store._locked() as (_io, current):
            self.pairs = [(Path(origin), store.root if not key else store.locations[key])
                          for key, origin in current["locators"].items() if not key or key in store.locations]
        self.pairs.insert(0, (self.origin, self.physical))

    def contains(self, path: Path) -> bool:
        return any(path == root or path.is_relative_to(root) for root in (self.origin, self.physical))

    def _path(self, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            for origin, actual in sorted(self.pairs, key=lambda pair: len(str(pair[0])), reverse=True):
                if path == origin or path.is_relative_to(origin):
                    return str(actual / path.relative_to(origin))
        return value

    def validation_root(self, root: Path) -> Path:
        return self.origin

    def runtime_envelope(self, root: Path, envelope: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = path_metadata_view(envelope, self._path)
        return result

    def read(self, path: Path) -> dict[str, Any]:
        value = super().read(path)
        return value if path.name == "head.json" or path.parent.name == "revisions" else self.runtime_envelope(path, value)

    def verify(self) -> None:
        if capture_registered(self.store, self.namespace) != self.witness:
            raise EngineError("document_revision_conflict", "The registered semantic namespace changed during this query.")
