"""Literal edit-request checkpoints use the selected project's physical owner.

A checkpoint freezes intent before discovery/execution. It owns no revision,
transaction or recovery state. External entries retain their independent local
owner; entries inside an existing project are ordinary generation resources.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.foundation.writer_lease import exclusive_directory_lease
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime, selected_project_store

from .attachment_index import encode, require_local_owner
from .errors import EngineError
from .repository import FileProjectRepository, digest
from .store_composition import existing_store


class EditCheckpointStorage:
    def __init__(self, entry: Path) -> None:
        self.entry = entry
        selected = selected_project_store()
        self.store: FileProjectStore | None = selected if selected is not None and entry.is_relative_to(selected.root) else next(
            (existing_store(parent) for parent in entry.parents
             if (parent / STORE / "head.json").is_file()), None)
        self.local = FileProjectRepository()

    def _logical(self, path: Path) -> str:
        assert self.store is not None
        return path.relative_to(self.store.root).as_posix()

    def exists(self, path: Path) -> bool:
        if self.store is None:
            return self.local.exists(path)
        logical = self._logical(path)
        files = self.store.snapshot()["files"]
        return logical in files or any(name.startswith(logical + "/") for name in files)

    def occupied(self) -> bool:
        return self.exists(self.entry) or (self.entry.exists() and (
            not self.entry.is_dir() or any(self.entry.iterdir())))

    def read(self, path: Path) -> dict[str, Any]:
        if self.store is None:
            return self.local.read(path)
        import json

        result = json.loads(self.store.read_bytes(self._logical(path)))
        if not isinstance(result, dict):
            raise EngineError("document_state_invalid", "An edit checkpoint must contain an object.")
        return result

    def bind(self, name: str, payload: dict[str, Any]) -> None:
        if self.store is None:
            self.local.write(self.entry / name, payload)
            return
        snapshot = self.store.snapshot()
        logical = self._logical(self.entry / name)
        mutation = ProjectMutation({logical: encode(payload)}, {"checkpoint": logical})
        command = ProjectCommand.create("semantic_record", "edit-checkpoint:" + digest(logical),
            project_id=snapshot["project_id"], expected_generation=snapshot["generation"],
            read_set={logical: None}, write_set=[logical],
            request={"prepared_digest": mutation.prepared_digest, "checkpoint": logical})
        ProjectCommands(self.store).publish_prepared(command, mutation)

    @contextmanager
    def lease(self) -> Iterator[None]:
        if self.store is None:
            require_local_owner(self.entry)
            self.entry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with external_project_session(self.entry):
                yield
        else:
            # A separate checkpoint lease is held through execution; the project
            # writer lease remains short and is acquired by ProjectCommands.
            lock = self.store.root / STORE / "edit-checkpoint-locks" / digest(self._logical(self.entry))
            lock.mkdir(parents=True, exist_ok=True, mode=0o700)
            with exclusive_directory_lease(lock) as held, project_runtime(self.store):
                yield
                held.verify()
