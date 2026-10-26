"""Admission and bind-once checkpoints for the two semantic edit adapters.

These files retain original requests, not transaction state. PlotService owns
execution, revisions, recovery and rollback; a replay must not recompile them.
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Literal, Protocol

from sciplot_core.studio_core.project_query_paths import canonical_path

from .errors import EngineError
from sciplot_core.project_lifecycle.checkpoint_storage import EditCheckpointStorage
from sciplot_core.project_lifecycle.context import repository_scope

EditEntryName = Literal["semantic-style.json", "semantic-edit.json"]
_BINDINGS = ("semantic-style.json", "semantic-edit.json", "task.json")


class _OwnedEditService(Protocol):
    def close(self) -> None: ...


@contextmanager
def edit_service_owner(owner: _OwnedEditService, *, owned: bool = True) -> Iterator[None]:
    """Close with this invocation's outcome, never a caller's handled failure."""
    failed = False
    selected = getattr(owner, "repository", None)
    scope = repository_scope(selected, capabilities=getattr(owner, "capabilities", None)) if selected is not None else nullcontext()
    try:
        with scope:
            yield
    except BaseException:
        failed = True
        raise
    finally:
        if owned:
            try:
                owner.close()
            except BaseException:
                if not failed:
                    raise


def edit_entry_owner(entry: Path) -> str | None:
    """A key belongs to one existing command authority, including legacy tasks."""
    entry = canonical_path(entry)
    storage = EditCheckpointStorage(entry)
    owners = [name for name in _BINDINGS if storage.exists(entry / name)]
    if len(owners) > 1:
        raise EngineError("document_idempotency_conflict", "The edit entry contains competing command bindings.")
    return owners[0] if owners else None


def read_edit_entry(entry: Path, name: EditEntryName) -> dict[str, Any] | None:
    """Read without allocating; an occupied key cannot change command owners."""
    entry = canonical_path(entry)
    owner = edit_entry_owner(entry)
    if owner is not None and owner != name:
        raise EngineError("document_idempotency_conflict",
                          "Use the original command for this occupied edit entry.")
    storage = EditCheckpointStorage(entry)
    if not storage.exists(entry / name):
        return None
    saved = storage.read(entry / name)
    intent = saved.get("intent")
    plot = intent.get("plot") if name == "semantic-style.json" and isinstance(intent, dict) else saved.get("plot")
    if (not isinstance(intent, dict) or not isinstance(saved.get("request"), dict)
            or not isinstance(plot, str) or not plot
            or "entry_intent" in saved and not isinstance(saved["entry_intent"], dict)):
        raise EngineError("document_state_invalid", "The original semantic edit binding is invalid.")
    return saved


def admit_edit_entry(entry: Path, root: Path, head: dict[str, Any]) -> None:
    """A new request checkpoint cannot overlap scientific or delivery state."""
    entry, root = canonical_path(entry), canonical_path(root)
    internal = entry.is_relative_to(root / "compatibility")
    protected = [canonical_path(Path(item["path"])) for item in head["document"]["scientific"]["data_sources"]]
    protected.extend(canonical_path(Path(head["binding"][field]))
                     for field in ("output", "document") if field in head["binding"])
    project = head["binding"].get("project")
    if project is not None:
        project = canonical_path(Path(project))
        if not (internal and root.is_relative_to(project)):
            protected.append(project)
    if not internal:
        protected.append(root)
    for path in protected:
        if entry == path or entry.is_relative_to(path) or path.is_relative_to(entry):
            raise EngineError("task_path_overlap",
                              "The edit entry must be separate from source, project, exports and revision storage.")
    storage = EditCheckpointStorage(entry)
    if storage.occupied() and not any(storage.exists(entry / name) for name in _BINDINGS):
        raise EngineError("document_idempotency_conflict",
                          "Use an empty edit entry or its original semantic edit binding.")


@contextmanager
def edit_entry_session(entry: Path) -> Iterator[None]:
    """Lease only the command checkpoint; PlotService leases its own plot."""
    entry = canonical_path(entry)
    with EditCheckpointStorage(entry).lease():
        yield


def bind_edit_entry(entry: Path, name: EditEntryName, payload: dict[str, Any]) -> dict[str, Any]:
    """Under the entry lease, retain a competing original or persist once."""
    saved = read_edit_entry(entry, name)
    if saved is not None:
        return saved
    storage = EditCheckpointStorage(entry)
    if storage.occupied():
        raise EngineError("document_idempotency_conflict",
                          "The edit entry became occupied before its request was bound.")
    storage.bind(name, payload)
    return payload
