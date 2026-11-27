"""Install a selected publication from one committed, read-only project file."""

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from sciplot_core.plot_document.schema import figure_handoff_schema
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.cache_identity import build_key
from sciplot_core.plot_engine.export_status import export_cache_record, sealed_publication
from sciplot_core.project_store.runtime import project_runtime

from .attached_repository import AttachedProjectRepository
from .context import repository_scope, transaction_path
from .contracts import RevisionToken
from .errors import EngineError
from .journal_identity import saved_command
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
        if (tx["id"] != tx_id or tx["phase"] != "complete" or tx.get("export_deferred") is not True
                or RevisionToken.of(tx["document"]) != RevisionToken.of(head["document"])):
            return False
        command = saved_command(tx)
        if command is None or transaction_path(root, command.idempotency_key) != journal:
            return False
        if command.kind != "intent":
            changes = command.business_payload.get("changes", [])
            if (command.kind != "patch" or re.fullmatch(r"archive-series:[a-f0-9]{64}", command.idempotency_key) is None
                    or len(changes) != 1):
                return False
            change = changes[0]
            replacement = change.get("value")
            if change.get("property") != "source.append" and not (
                    change.get("property") == "source.sha256" and isinstance(replacement, dict)
                    and isinstance(replacement.get("replacement_path"), str)
                    and Path(replacement["replacement_path"]).is_absolute()):
                return False
        fallback_ir = owner.read(path)["export"].get("ir_hash")
        if not isinstance(fallback_ir, str):
            return False
        for revision in range(head["document"]["revision"] - 1, -1, -1):
            prior = owner.load_revision(root, revision)
            if prior["binding"].get("ir_hash") == fallback_ir:
                return (sealed_publication(root, prior) or {}).get("ready_to_use") is True
        return False


def _export_formats(service: "ProjectApplication", owner: AttachedProjectRepository, root: Path,
                    formats: list[str], *, extend: bool) -> None:
    # The whole Store session is disposable here. No generic export
    # transaction, paired export, or modification of the .sciplot is needed.
    with repository_scope(owner, capabilities=service.capabilities), owner.lease(root):
        head = owner.load_head(root)
        binding = head["binding"]
        prior = sealed_publication(root, head) if extend else None
        if extend and (prior is None or prior.get("ready_to_use") is not True):
            raise EngineError("figure_handoff_publication_changed", "The saved publication changed before its missing format could be rendered.")
        existing = prior["exports"] if prior is not None else []
        missing = tuple(fmt for fmt in ("pdf", "tiff_300")
                        if fmt in formats and not any(record["format"] == fmt for record in existing))
        ir_binding = {**binding, "ir_path": str(owner.runtime_path(Path(binding["ir_path"])))}
        destination = owner.attachment.cache / "selected-exports"
        export_selected = getattr(service.backend, "export_selected", None)
        if export_selected is None:
            raise EngineError("figure_handoff_publication_unready", "The native backend cannot render selected formats.")
        exported = export_selected(ir_binding, destination, missing)
        if (exported.get("ready_to_use") is not True
                or {record["format"] for record in exported["exports"]} != set(missing)):
            raise EngineError("figure_handoff_publication_unready", "The native export did not produce just the missing formats.")
        exported["exports"] = [*existing, *exported["exports"]]
        files = {**exported["evidence_files"], **{record["path"]: record["sha256"] for record in existing}}
        owner.write(root / "export-cache.json", export_cache_record(build_key(head["document"], binding), exported, files, {}))


def project_file_handoff(service: "ProjectApplication", path: Path, request: dict[str, Any], *,
                         expected_project_id: str | None = None,
                         expected_revision: RevisionToken | None = None) -> dict[str, Any]:
    validate_wire(request, figure_handoff_schema(), code="figure_handoff_invalid_request")
    if type(request["revision"]) is not int:
        raise EngineError("figure_handoff_invalid_request", "Use the integer revision from project.open.")
    with project_file_figure(path, request["plot_id"], exact_plot_id=True) as (session, owner, document):
        locator = {"project_file": str(session.path), "project_id": session.project_id}
        if expected_project_id is not None and session.project_id != expected_project_id:
            raise EngineError("project_file_identity_conflict", "This path no longer contains the original project file.",
                              action="inspect_project_file", **locator)
        if ((document["plot_id"], document["revision"]) != (request["plot_id"], request["revision"])
                or (expected_revision is not None and RevisionToken.of(document) != expected_revision)):
            raise EngineError("figure_handoff_revision_conflict", "Choose the exact current plot ID and revision from project.open.",
                              action="project.open", **locator)
        root = owner.attachment.root

        def rebuild_missing(reason: str) -> bool:
            try:
                if reason not in {"figure_handoff_cache_missing", "figure_handoff_format_missing"} and not _has_deferred_export(owner, root):
                    return False
                if set(request["formats"]) <= {"pdf", "tiff_300"}:
                    _export_formats(service, owner, root, request["formats"], extend=reason == "figure_handoff_format_missing")
                    return True
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
