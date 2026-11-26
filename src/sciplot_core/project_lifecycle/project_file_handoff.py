"""Install a selected publication from one committed, read-only project file."""

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from sciplot_core.plot_document.schema import figure_handoff_schema
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.export_status import sealed_publication
from sciplot_core.project_store.runtime import project_runtime

from .attached_repository import AttachedProjectRepository
from .contracts import RevisionToken
from .errors import EngineError
from .project_file_summary import project_file_figure

if TYPE_CHECKING:
    from .application import ProjectApplication


def _has_deferred_export(owner: AttachedProjectRepository, root: Path) -> bool:
    # A local cache is evidence, even when invalid. Only a historical Store fallback
    # may mask the fact that the current deferred revision has no publication.
    path = root / "export-cache.json"
    local = owner.runtime_path(path)
    if local.exists() or local.is_symlink():
        return False
    with owner.query_scope(root):
        head = owner.load_head(root)
        tx_id = head["transaction"]
        if re.fullmatch("[0-9a-f]{64}", tx_id) is None:
            return False
        journal = root / "transactions" / tx_id / "transaction.json"
        if not owner.exists(journal):
            return False
        tx = owner.read(journal)
        fallback_ir = owner.read(path)["export"].get("ir_hash")
        if (tx.get("normalized_command", {}).get("kind") != "intent" or tx["id"] != tx_id
                or tx["phase"] != "complete" or tx.get("export_deferred") is not True
                or RevisionToken.of(tx["document"]) != RevisionToken.of(head["document"])
                or not isinstance(fallback_ir, str)):
            return False
        for revision in range(head["document"]["revision"] - 1, -1, -1):
            prior = owner.load_revision(root, revision)
            if prior["binding"].get("ir_hash") == fallback_ir:
                return (sealed_publication(root, prior) or {}).get("ready_to_use") is True
        return False


def project_file_handoff(service: "ProjectApplication", path: Path, request: dict[str, Any]) -> dict[str, Any]:
    validate_wire(request, figure_handoff_schema(), code="figure_handoff_invalid_request")
    if type(request["revision"]) is not int:
        raise EngineError("figure_handoff_invalid_request", "Use the integer revision from project.open.")
    with project_file_figure(path, request["plot_id"], exact_plot_id=True) as (session, owner, document):
        locator = {"project_file": str(session.path), "project_id": session.project_id}
        if (document["plot_id"], document["revision"]) != (request["plot_id"], request["revision"]):
            raise EngineError("figure_handoff_revision_conflict", "Choose the exact current plot ID and revision from project.open.",
                              action="project.open", **locator)
        root = owner.attachment.root

        def rebuild_missing(reason: str) -> bool:
            try:
                if reason != "figure_handoff_cache_missing" and not _has_deferred_export(owner, root):
                    return False
                receipt = service.export(root)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                # The native owner may put private binding paths in its error text.
                raise EngineError("figure_handoff_publication_unready", "The saved figure did not pass native export checks.") from exc
            if receipt.get("ready_to_use") is not True:
                raise EngineError("figure_handoff_publication_unready", "The saved figure did not pass native export checks.")
            return True

        try:
            with project_runtime(session.store):
                result = service.handoff_figure(root, request, rebuild_missing=rebuild_missing)
        except EngineError as exc:
            raise EngineError(exc.reason_code, str(exc), action="inspect_project_file_handoff", **locator) from exc
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            raise EngineError("figure_handoff_publication_unready", "The saved figure has no verifiable selected publication.",
                              action="inspect_project_file_handoff", **locator) from exc
        return {**result, **locator, "plot": str(session.path),
                **{key: document[key] for key in ("scientific_hash", "presentation_hash")}}
