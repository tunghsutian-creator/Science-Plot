"""Save independent ordinary XY figures through the standalone archive owner."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.writer_lease import WriterLeaseBusy, WriterLeaseChanged
from sciplot_core.plot_engine.contracts import validate_create
from sciplot_core.project_store.errors import ProjectConflict
from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.source_tables.read_session import table_read_session

from .attached_repository import AttachedProjectRepository
from .attachment_import import entry_for
from .attachment_index import Attachment, attachment_id, read_index
from .context import digest, repository_scope
from .errors import EngineError
from .managed_creation import committed_managed_creation
from .project_file import ProjectFileSaveUnconfirmed, create_project_file, open_project_file
from .targets import ManagedCreationLocation


def _admit_xy(request: dict[str, Any]) -> dict[str, Any]:
    request = validate_create(request)
    if request.get("rule_id") != "ordinary_xy" or request.get("storage") != "project_store_v2":
        raise EngineError("project_file_append_unsupported", "Supply a resolved ordinary XY Managed creation request.")
    return request


def _saved(store: FileProjectStore, entry: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    owner = AttachedProjectRepository(Attachment(store, entry))
    root = owner.attachment.root
    with owner.query_scope(root):
        state = owner.read(root / "managed-creation.json")
        if state["request_hash"] != digest(request):
            raise EngineError("document_idempotency_conflict", "This key belongs to a different request.",
                              action="use_original_request")
        document: dict[str, Any] = owner.load_revision(root, 0)["document"]
        if state["phase"] != "committed" or document["plot_id"] != entry["plot_id"]:
            raise EngineError("project_file_append_unconfirmed", "The saved entry does not identify a completed figure.",
                              action="inspect_project_file")
    return document


def _seal(store: FileProjectStore, snapshot: dict[str, Any], key: str, request: dict[str, Any],
          capabilities: dict[str, Any] | None) -> dict[str, Any]:
    identity = attachment_id(snapshot["project_id"], key)
    namespace = Path(".sciplot_semantic") / identity
    origin = Path(snapshot["locators"][""])
    plot_id = "plot:" + digest([snapshot["project_id"], key])[:24]
    entry = entry_for(store, key=key, figure_id=plot_id, plot_id=plot_id, origin=origin / namespace,
                      managed_output=str(origin / STORE / "semantic-derived" / identity / "output"))
    entry["output_owner"] = "derived"
    attachment = Attachment(store, entry)
    owner = AttachedProjectRepository(attachment, new_sources=tuple(request["data_binding"]["data_sources"]))
    location = ManagedCreationLocation(attachment.root, attachment.cache / "output", plot_id)
    # One held source scope records the exact bytes and revision in the same
    # ProjectCommands batch that registers this figure.
    with (
        table_read_session(),
        repository_scope(owner, capabilities=capabilities),
        owner.backend_scope(),
        owner.storage_batch(location.root),
        committed_managed_creation(request, location=location) as head,
    ):
        document: dict[str, Any] = head["document"]
        return document


def _result(kind: str, status: str, path: Path, project_id: str, generation: str,
            document: dict[str, Any]) -> dict[str, Any]:
    target = str(path)
    return {"kind": kind, "version": 1, "status": status, "project_file": target,
            "project_id": project_id, "generation": generation,
            **{name: document[name] for name in ("plot_id", "revision", "scientific_hash", "presentation_hash")},
            "next_step": {"action": "project.open", "arguments": {"target": target, "figure_id": document["plot_id"],
                                                                  "description": {"scope": "summary"}}}}


def project_file_create_xy(path: Path, request: dict[str, Any], *,
                           capabilities: dict[str, Any] | None) -> dict[str, Any]:
    """Build the first figure in private storage and publish one new file."""
    request = _admit_xy(request)
    key = "project-file-create:" + request["idempotency_key"]
    kind = "sciplot_project_file_create"
    if path.exists():
        # Retry from the saved archive before touching sources (which may now
        # be offline). Never adopt or replace a competing save.
        try:
            with open_project_file(path) as session:
                index = read_index(session.store)
                entry = index["attachments"].get(attachment_id(session.project_id, key))
                if entry is not None:
                    return _result(kind, "already_saved", session.path, session.project_id, session.opened_generation,
                                   _saved(session.store, entry, request))
        except EngineError:
            raise
        except (OSError, ValueError):
            pass  # Not readable as this operation's saved archive; never replace it.
        raise EngineError("project_file_destination_exists", "Choose a new .sciplot filename. The existing destination was not changed.",
                          action="choose_project_file")
    with TemporaryDirectory(prefix="sciplot-create-") as temporary:
        store = FileProjectStore(Path(temporary).resolve())
        initial = store.snapshot(import_legacy=True)
        document = _seal(store, initial, key, request, capabilities)
        generation = store.snapshot()["generation"]
        try:
            receipt = create_project_file(path, store, expected_generation=generation)
        except FileExistsError as exc:
            raise EngineError("project_file_destination_exists", "The .sciplot destination was taken before save. It was not changed.",
                              action="choose_project_file") from exc
        except ProjectFileSaveUnconfirmed as exc:
            raise EngineError("project_file_save_unconfirmed",
                              "The file may contain this figure. Retry the same request to check its saved key.",
                              action="retry_same_request", plot_id=document["plot_id"]) from exc
        return _result(kind, "saved", path, receipt.project_id, receipt.generation, document)


def project_file_append_xy(path: Path, request: dict[str, Any], *, expected_generation: str,
                           capabilities: dict[str, Any] | None) -> dict[str, Any]:
    """Seal one new figure in a private Store batch and publish the accepted generation."""
    request = _admit_xy(request)

    with open_project_file(path) as session:
        store = session.store
        snapshot = store.snapshot()
        generation = snapshot["generation"]
        key = "project-file-append:" + request["idempotency_key"]
        index = read_index(store, snapshot)
        entry = index["attachments"].get(attachment_id(session.project_id, key))
        status = "already_saved"
        if entry is not None:
            document = _saved(store, entry, request)
        else:
            if generation != expected_generation:
                raise EngineError("project_file_generation_conflict", "Read the current project generation before appending.",
                                  action="inspect_project_file", current_generation=generation)
            document = _seal(store, snapshot, key, request, capabilities)
            generation = store.snapshot()["generation"]
            try:
                session.save(expected_generation=generation)
            except ProjectFileSaveUnconfirmed as exc:
                raise EngineError("project_file_save_unconfirmed",
                                  "The file may contain this figure. Retry the same request to check its saved key.",
                                  action="retry_same_request", plot_id=document["plot_id"]) from exc
            except (ProjectConflict, WriterLeaseBusy, WriterLeaseChanged) as exc:
                raise EngineError("project_file_save_conflict", "The project file changed or another writer holds its save lease.",
                                  action="inspect_project_file") from exc
            except (OSError, ValueError) as exc:
                raise EngineError("project_file_save_failed", "The append could not be saved.",
                                  action="retry_same_request") from exc
            status = "saved"
        return _result("sciplot_project_file_append", status, session.path, session.project_id, generation, document)
