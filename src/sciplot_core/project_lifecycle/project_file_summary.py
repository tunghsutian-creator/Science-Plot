"""Read and select a sealed plot in a standalone project file."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.plot_engine.description_scope import edit_target_summary
from sciplot_core.plot_engine.figure_updates import figure_property_names
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure

from .attached_repository import AttachedProjectRepository
from .attachment_index import Attachment, read_index
from .errors import EngineError
from .head_observation import observe_plot_head
from .project_file import ProjectFileSession, open_project_file


PROJECT_FILE_EDIT_PROPERTY = "axis.label"


@contextmanager
def project_file_figure(path: Path, figure_id: str | None, *, exact_plot_id: bool = False) -> Iterator[
        tuple[ProjectFileSession, AttachedProjectRepository, dict[str, Any]]]:
    """Identify one sealed Managed v2 plot in a private file session."""
    with ExitStack() as stack:
        try:
            session = stack.enter_context(open_project_file(path))
            entries = list(read_index(session.store)["attachments"].values())
        except FileNotFoundError as exc:
            raise EngineError("path_not_found", "The specified .sciplot file or its saved state was not found.",
                              action="check_project_file") from exc
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise EngineError("project_file_invalid", "Open a valid, regular .sciplot project file, not a symbolic alias.",
                              action="check_project_file") from exc
        matches = [entry for entry in entries if figure_id in (None, entry["plot_id"])
                   or (not exact_plot_id and figure_id == entry["figure_id"])]
        if len(matches) > 1:
            raise EngineError("project_file_figure_ambiguous", "Choose one exact saved plot or figure ID.",
                              action="select_figure")
        if not matches:
            raise EngineError("project_file_figure_not_found", "This .sciplot file has no saved figure matching the selection.",
                              action="select_figure")

        attachment = Attachment(session.store, matches[0])
        owner = AttachedProjectRepository(attachment)
        try:
            head = observe_plot_head(attachment.root, owner=owner)
            assert head is not None
            document = head["document"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Inner owner diagnostics can refer to an extracted or old workspace.
            raise EngineError("project_file_figure_unreadable", "The selected figure has no valid committed revision in this .sciplot file.",
                              action="check_project_file") from exc
        if document.get("plot_type") != "ManagedPlot" or not is_figure(document):
            raise EngineError("project_file_figure_unsupported", "This .sciplot operation supports saved Managed FigureSpec v2 figures only.")
        if document["plot_id"] != attachment.entry["plot_id"]:
            raise EngineError("project_file_figure_unreadable", "The registered identity does not match the saved figure.",
                              action="check_project_file")

        yield session, owner, document


def project_file_summary(path: Path, figure_id: str | None) -> dict[str, Any]:
    """Report a sealed semantic record without rendering or exposing workspace paths."""
    with project_file_figure(path, figure_id) as (session, _, document):
        objects = document["presentation"]["objects"]
        axes = {target: [PROJECT_FILE_EDIT_PROPERTY]
                for target, properties in figure_property_names(figure_spec(document)).items()
                if PROJECT_FILE_EDIT_PROPERTY in properties and objects[target]["kind"] == "axis"}
        return {"kind": "sciplot_project_file_summary", "version": 1, "read_only": True,
                "project_file": str(session.path), "project_id": session.project_id,
                "edit_targets": edit_target_summary(objects, axes, {}),
                **{key: document[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")}}
