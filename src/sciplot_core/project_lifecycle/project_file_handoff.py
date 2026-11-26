"""Install a selected publication from one committed, read-only project file."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.plot_document.schema import figure_handoff_schema
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.project_store.runtime import project_runtime

from .errors import EngineError
from .project_file_summary import project_file_figure

if TYPE_CHECKING:
    from sciplot_core.plot_engine.service import PlotService


def project_file_handoff(service: "PlotService", path: Path, request: dict[str, Any]) -> dict[str, Any]:
    validate_wire(request, figure_handoff_schema(), code="figure_handoff_invalid_request")
    if type(request["revision"]) is not int:
        raise EngineError("figure_handoff_invalid_request", "Use the integer revision from project.open.")
    if "pdf" not in request["formats"]:
        raise EngineError("project_file_handoff_unsupported", "Select PDF or PDF and 300 dpi TIFF for a .sciplot file.")
    with project_file_figure(path, request["plot_id"], exact_plot_id=True) as (session, owner, document):
        locator = {"project_file": str(session.path), "project_id": session.project_id}
        if (document["plot_id"], document["revision"]) != (request["plot_id"], request["revision"]):
            raise EngineError("figure_handoff_revision_conflict", "Choose the exact current plot ID and revision from project.open.",
                              action="project.open", **locator)
        root = owner.attachment.root

        def rebuild_missing() -> None:
            try:
                receipt = service.export(root)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                # The native owner may put private binding paths in its error text.
                raise EngineError("figure_handoff_publication_unready", "The saved figure did not pass native export checks.") from exc
            if receipt.get("ready_to_use") is not True:
                raise EngineError("figure_handoff_publication_unready", "The saved figure did not pass native export checks.")

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
