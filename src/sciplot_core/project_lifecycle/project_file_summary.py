"""Read and select a sealed plot in a standalone project file."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.plot_engine.description_scope import edit_target_summary
from sciplot_core.plot_engine.figure_updates import figure_property_names
from sciplot_core.plot_engine.typed_intent import DISPLAY_LABEL, LINE_COLOR, display_label_targets, line_color_targets
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure
from sciplot_core.project_store.errors import ProjectConflict

from .attached_repository import AttachedProjectRepository
from .attachment_index import Attachment, read_index
from .errors import EngineError
from .head_observation import observe_plot_head
from .project_file import ProjectFileSession, open_project_file


PROJECT_FILE_AXIS_PROPERTIES = {"axis.label", "axis.ticks"}
PROJECT_FILE_EDIT_PROPERTIES = PROJECT_FILE_AXIS_PROPERTIES | {LINE_COLOR, DISPLAY_LABEL}


@contextmanager
def project_file_read_session(path: Path) -> Iterator[ProjectFileSession]:
    """Open a verified project file using the public read diagnostics."""
    public_path = str(path.expanduser().absolute())
    with ExitStack() as stack:
        try:
            session = stack.enter_context(open_project_file(path))
        except FileNotFoundError as exc:
            raise EngineError("path_not_found", "The .sciplot file or its saved state was not found. If it was moved, open its new location.",
                              action="check_project_file", project_file=public_path) from exc
        except PermissionError as exc:
            raise EngineError("project_file_access_denied",
                              "Check that the file can be read and SciPlot can use its temporary workspace.",
                              action="check_project_file_access", project_file=public_path) from exc
        except ProjectConflict as exc:
            raise EngineError("project_file_open_conflict", "The file changed while opening. Open the latest saved file again.",
                              action="project.open", target=public_path) from exc
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise EngineError("project_file_invalid", "Open a valid, regular .sciplot project file, not a symbolic alias.",
                              action="check_project_file", project_file=public_path) from exc
        yield session


def saved_project_file_figure(
    session: ProjectFileSession, figure_id: str | None, *, exact_plot_id: bool = False
) -> tuple[AttachedProjectRepository, dict[str, Any]]:
    """Select one committed figure from an already verified file session."""
    try:
        entries = list(read_index(session.store)["attachments"].values())
    except FileNotFoundError as exc:
        raise EngineError("path_not_found", "The specified .sciplot file or its saved state was not found.",
                          action="check_project_file") from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EngineError("project_file_invalid", "Open a valid, regular .sciplot project file, not a symbolic alias.",
                          action="check_project_file") from exc
    matches = [entry for entry in entries if figure_id in (None, entry["plot_id"])
               or (not exact_plot_id and figure_id == entry["figure_id"])]
    if len(matches) != 1:
        if not matches:
            code = "project_file_figure_not_found"
            message = "This .sciplot file has no saved figure matching the selection."
        else:
            code = "project_file_figure_ambiguous"
            message = "Choose one exact saved plot or figure ID."
        choices = [{key: entry[key] for key in ("figure_id", "plot_id")} for entry in matches or entries]
        raise EngineError(code, message, action="select_figure", project_id=session.project_id,
                          project_file=str(session.path), generation=session.opened_generation, figures=choices)

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

    return owner, document


@contextmanager
def project_file_figure(path: Path, figure_id: str | None, *, exact_plot_id: bool = False) -> Iterator[
        tuple[ProjectFileSession, AttachedProjectRepository, dict[str, Any]]]:
    """Identify one sealed Managed v2 plot in a private file session."""
    with project_file_read_session(path) as session:
        owner, document = saved_project_file_figure(session, figure_id, exact_plot_id=exact_plot_id)
        yield session, owner, document


def project_file_summary(path: Path, figure_id: str | None) -> dict[str, Any]:
    """Report a sealed semantic record without rendering or exposing workspace paths."""
    try:
        with project_file_figure(path, figure_id) as (session, _, document):
            return _summarize(session, document)
    except EngineError as exc:
        if exc.repair["action"] == "select_figure":
            target = exc.repair["project_file"]
            for choice in exc.repair["figures"]:
                choice["open_arguments"] = {"target": target, "figure_id": choice["plot_id"],
                                            "description": {"scope": "summary"}}
        raise


def _summarize(session: ProjectFileSession, document: dict[str, Any]) -> dict[str, Any]:
    objects = document["presentation"]["objects"]
    spec = figure_spec(document)
    targets = {target: [prop for prop in properties if prop in PROJECT_FILE_AXIS_PROPERTIES]
               for target, properties in figure_property_names(spec).items()
               if "axis.label" in properties and objects[target]["kind"] == "axis"}
    line_targets = line_color_targets(document, spec)
    targets.update({target: [DISPLAY_LABEL, *([LINE_COLOR] if target in line_targets else [])]
                    for target in display_label_targets(spec)})
    return {"kind": "sciplot_project_file_summary", "version": 1, "read_only": True,
            "project_file": str(session.path), "project_id": session.project_id, "generation": session.opened_generation,
            "edit_targets": edit_target_summary(objects, targets, {}),
            **{key: document[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")}}
