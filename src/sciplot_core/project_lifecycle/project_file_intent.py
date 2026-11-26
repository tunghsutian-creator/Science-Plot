"""Publish one supported typed edit back to its explicit standalone project file."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.foundation.writer_lease import WriterLeaseBusy, WriterLeaseChanged
from sciplot_core.plot_engine.typed_intent import compile_intent, validate_intent
from sciplot_core.project_store.errors import ProjectConflict
from sciplot_core.project_store.runtime import project_runtime

from .attached_repository import AttachedProjectRepository
from .context import repository_scope, transaction_path
from .contracts import RevisionToken
from .errors import EngineError
from .head_observation import observe_plot_head
from .journal_identity import saved_command
from .project_file import ProjectFileSaveUnconfirmed
from .project_file_summary import project_file_figure

if TYPE_CHECKING:
    from .application import ProjectApplication


def _published_intent(owner: AttachedProjectRepository, request: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the original command against the archive journal without re-running it."""
    root = owner.attachment.root
    journal = transaction_path(root, request["idempotency_key"])
    with repository_scope(owner), owner.query_scope(root):
        if not owner.exists(journal):
            return None
        tx = owner.read(journal)
        command = saved_command(tx)
        if command is None or command.kind != "intent" or command.original_payload != request:
            raise EngineError("document_idempotency_conflict", "This key identifies another original command.",
                              action="use_original_request")
        if tx["phase"] != "complete":
            raise EngineError("project_file_intent_unconfirmed",
                              "This key has no matching completed edit in the project file.",
                              action="inspect_project_file")
        document: dict[str, Any] = tx["document"]
        accepted = owner.load_revision(root, document["revision"])["document"]
        if RevisionToken.of(document) != RevisionToken.of(accepted):
            raise EngineError("project_file_intent_unconfirmed",
                              "The recorded edit is not a saved revision of this project file.",
                              action="inspect_project_file")
        return document


def _receipt(status: str, locator: dict[str, Any], document: dict[str, Any], *,
             current_revision: int, **details: Any) -> dict[str, Any]:
    return {"kind": "sciplot_project_file_intent", "version": 1, "status": status,
            **locator, "current_revision": current_revision,
            **{key: document[key] for key in ("revision", "scientific_hash", "presentation_hash")}, **details}


def project_file_axis_intent(service: "ProjectApplication", path: Path, request: dict[str, Any], *,
                             expected_project_id: str | None = None,
                             expected_revision: RevisionToken | None = None) -> dict[str, Any]:
    """Only the archive owner may acknowledge a saved edit, not its disposable Store."""
    request = validate_intent(request)
    if request["property"] != "axis.label":
        raise EngineError("project_file_intent_unsupported", "A .sciplot file currently supports only axis label edits.",
                          action="choose_axis_label")
    with project_file_figure(path, request["plot_id"]) as (session, owner, before):
        if expected_project_id is not None and session.project_id != expected_project_id:
            raise EngineError("project_file_identity_conflict", "This path no longer contains the original project file.",
                              action="inspect_project_file")
        locator = {"project_file": str(session.path), "project_id": session.project_id,
                   "plot_id": before["plot_id"], "idempotency_key": request["idempotency_key"]}
        if request["mode"] == "apply":
            # No export/recovery on retry: the archive is the publication witness.
            try:
                published = _published_intent(owner, request)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                if getattr(exc, "reason_code", None) == "document_idempotency_conflict":
                    raise EngineError("document_idempotency_conflict", "This key identifies another original command.",
                                      action="use_original_request") from exc
                raise EngineError("project_file_intent_unconfirmed",
                                  "The existing key cannot be confirmed as a saved edit.",
                                  action="inspect_project_file") from exc
            if published is not None:
                return _receipt("already_saved", locator, published, current_revision=before["revision"], saved=True)

        if expected_revision is not None and RevisionToken.of(before) != expected_revision:
            raise EngineError("document_revision_conflict", "Read the current revision before changing this plot.",
                              action="inspect_project_file", current_revision=before["revision"])

        # A sealed semantic head suffices for a plan; no renderer or files change.
        _, plan = compile_intent(before, request)
        if request["mode"] == "plan":
            return {**plan, **locator, "saved": False}

        try:
            with project_runtime(session.store):
                result = service.intent(owner.attachment.root, request)
            if result.get("status") != "complete":
                raise EngineError("project_file_edit_not_saved", "The axis edit could not complete; no file was replaced.")
            edited = observe_plot_head(owner.attachment.root, owner=owner)
            if (edited is None or edited["document"]["scientific_hash"] != before["scientific_hash"]
                    or edited["document"]["revision"] != before["revision"] + bool(result.get("changed"))):
                raise EngineError("project_file_edit_not_saved", "The private edit did not produce the expected revision.")
            generation = session.store.snapshot()["generation"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise EngineError("project_file_edit_not_saved", "The axis edit could not complete; no file was replaced.",
                              action="inspect_project_file", **locator) from exc

        document = edited["document"]
        try:
            session.save(expected_generation=generation)
        except ProjectFileSaveUnconfirmed as exc:
            raise EngineError("project_file_save_unconfirmed",
                              "The project file may contain this edit. Retry this exact request to check its saved key.",
                              action="retry_same_request", revision=document["revision"], **locator) from exc
        except (ProjectConflict, WriterLeaseBusy, WriterLeaseChanged) as exc:
            raise EngineError("project_file_save_conflict", "The current project file was not replaced by this edit.",
                              action="inspect_project_file", **locator) from exc
        except (OSError, ValueError) as exc:
            raise EngineError("project_file_save_failed", "The axis edit was not saved; no file was replaced.",
                              action="retry_same_request", **locator) from exc
        return _receipt("saved", locator, document, current_revision=document["revision"], saved=True)
