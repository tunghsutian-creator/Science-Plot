"""Append one resolved ordinary XY figure through the standalone archive owner."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.writer_lease import WriterLeaseBusy, WriterLeaseChanged
from sciplot_core.plot_engine.contracts import validate_create
from sciplot_core.project_store.errors import ProjectConflict
from sciplot_core.project_store.io import STORE
from sciplot_core.source_tables.read_session import table_read_session

from .attached_repository import AttachedProjectRepository
from .attachment_import import entry_for
from .attachment_index import Attachment, attachment_id, read_index
from .context import digest, repository_scope
from .errors import EngineError
from .managed_creation import committed_managed_creation
from .project_file import ProjectFileSaveUnconfirmed, open_project_file
from .targets import ManagedCreationLocation


def project_file_append_xy(path: Path, request: dict[str, Any], *, expected_generation: str,
                           capabilities: dict[str, Any] | None) -> dict[str, Any]:
    """Seal the figure in one private Store batch and publish the exact generation."""
    request = validate_create(request)
    if request.get("rule_id") != "ordinary_xy" or request.get("storage") != "project_store_v2":
        raise EngineError("project_file_append_unsupported", "Supply a resolved ordinary XY Managed creation request.")

    with open_project_file(path) as session:
        store = session.store
        snapshot = store.snapshot()
        generation = snapshot["generation"]
        key = "project-file-append:" + request["idempotency_key"]
        identity = attachment_id(session.project_id, key)
        index = read_index(store, snapshot)
        entry = index["attachments"].get(identity)
        status = "already_saved"
        if entry is not None:
            # A completed append is witnessed by the archive. In particular a
            # retry does not need the original source paths to be present.
            owner = AttachedProjectRepository(Attachment(store, entry))
            root = owner.attachment.root
            with owner.query_scope(root):
                state = owner.read(root / "managed-creation.json")
                if state["request_hash"] != digest(request):
                    raise EngineError("document_idempotency_conflict", "This append key belongs to a different request.",
                                      action="use_original_request")
                document = owner.load_revision(root, 0)["document"]
                if state["phase"] != "committed" or document["plot_id"] != entry["plot_id"]:
                    raise EngineError("project_file_append_unconfirmed", "The saved entry does not identify a completed append.",
                                      action="inspect_project_file")
        else:
            if generation != expected_generation:
                raise EngineError("project_file_generation_conflict", "Read the current project generation before appending.",
                                  action="inspect_project_file", current_generation=generation)
            namespace = Path(".sciplot_semantic") / identity
            origin = Path(snapshot["locators"][""])
            plot_id = "plot:" + digest([session.project_id, key])[:24]
            entry = entry_for(store, key=key, figure_id=plot_id, plot_id=plot_id, origin=origin / namespace,
                              managed_output=str(origin / STORE / "semantic-derived" / identity / "output"))
            entry["output_owner"] = "derived"
            attachment = Attachment(store, entry)
            owner = AttachedProjectRepository(attachment, new_sources=tuple(request["data_binding"]["data_sources"]))
            location = ManagedCreationLocation(attachment.root, attachment.cache / "output", plot_id)
            # Keep the source scope alive through source capture and the same
            # ProjectCommands batch that registers the new semantic namespace.
            with (
                table_read_session(),
                repository_scope(owner, capabilities=capabilities),
                owner.backend_scope(),
                owner.storage_batch(location.root),
                committed_managed_creation(request, location=location) as head,
            ):
                document = head["document"]
            generation = store.snapshot()["generation"]
            try:
                session.save(expected_generation=generation)
            except ProjectFileSaveUnconfirmed as exc:
                raise EngineError("project_file_save_unconfirmed",
                                  "The file may contain this figure. Retry the same request to check its saved key.",
                                  action="retry_same_request", plot_id=plot_id) from exc
            except (ProjectConflict, WriterLeaseBusy, WriterLeaseChanged) as exc:
                raise EngineError("project_file_save_conflict", "The project file changed or another writer holds its save lease.",
                                  action="inspect_project_file") from exc
            except (OSError, ValueError) as exc:
                raise EngineError("project_file_save_failed", "The append could not be saved.",
                                  action="retry_same_request") from exc
            status = "saved"
        target = str(session.path)
        return {"kind": "sciplot_project_file_append", "version": 1,
                "status": status,
                "project_file": target, "project_id": session.project_id, "generation": generation,
                **{name: document[name] for name in ("plot_id", "revision", "scientific_hash", "presentation_hash")},
                "next_step": {"action": "project.open", "arguments": {"target": target, "figure_id": document["plot_id"],
                                                                      "description": {"scope": "summary"}}}}
