"""Open and redraw the saved native artifact, not its editable project state."""
from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.file_hashing import file_sha256


def _native_owner_root(target: Path) -> Path | None:
    from sciplot_core.delivery_identity import DELIVERY_IDENTITY

    return next((parent for parent in target.parents
                 if (parent / "plot_request.json").is_file() or (parent / DELIVERY_IDENTITY).is_file()),
                None)


def _native_file_root(target: Path) -> Path:
    return _native_owner_root(target) or target.parent


def is_standalone_export_target(document: Path, output: Path) -> bool:
    """Allow exact export only from an unowned VSZ into a separate artifact tree."""
    from sciplot_core.policy import DELIVERY_LAUNCHER, DELIVERY_PROJECT_DIR

    document = canonical_path(document)
    if not document.is_file() or _native_owner_root(document) is not None:
        return False
    if any(parent.name == DELIVERY_PROJECT_DIR and (parent.parent / DELIVERY_LAUNCHER).is_file()
           for parent in document.parents):
        return False
    destination = canonical_path(output)
    source = document.parent
    return not (destination.is_relative_to(source) or source.is_relative_to(destination))


def _saved_plot(target: Path, figure_id: str | None) -> tuple[Path, Path]:
    target = canonical_path(target)
    if target.is_file() and target.suffix.lower() == ".vsz":
        root = _native_file_root(target)
        if figure_id is not None:
            from sciplot_core.project_lifecycle.figure_observation import observe_legacy_project

            if not (root / "plot_request.json").is_file():
                raise ValueError("Select a project directory to use a figure ID.")
            observation = observe_legacy_project(root)
            selected = observation.select(figure_id)
            observation.require_current(selected=selected)
            if selected["document"] != str(target):
                raise ValueError("The figure ID does not match this saved VSZ.")
        return root, target
    if not ((target.is_dir() and (target / "plot_request.json").is_file())
            or (target.is_file() and target.name == "plot_request.json")):
        raise ValueError("Select a saved project directory, plot_request.json or exact .vsz file.")
    from sciplot_core.project_lifecycle.figure_observation import resolve_project_figure

    selected = resolve_project_figure(target, figure_id)
    return Path(selected["project"]), Path(selected["document"])


def open_legacy_document(root: Path, document: Path) -> dict[str, Any]:
    from sciplot_core.studio_core.project_query import _inspect_document

    observed = _inspect_document(document)
    return {"kind": "sciplot_legacy_plot", "version": 1, "status": "opened",
            "project": str(root), "document": observed["document"],
            "pages": observed["pages"], "linked_files": observed["linked_files"],
            "read_only": True, "new_features_require_conversion": True,
            "next_step": {"action": "redraw_legacy", "target": str(document),
                          "cli_argv": ["sciplot", "project", "legacy-redraw", str(document), "--out"],
                          "requires": ["new_output_directory"]},
            "conversion": conversion_guidance(document)}


def conversion_guidance(document: Path) -> dict[str, Any]:
    return {"action": "legacy_convert", "target": str(document),
            "cli_argv": ["sciplot", "project", "legacy-convert", str(document), "--out"],
            "requires": ["new_output_directory"],
            "message": "To edit a supported saved XY plot, convert a separate copy."}


def redraw_legacy_plot(target: Path, *, output: Path, formats: list[str],
                       figure_id: str | None = None) -> dict[str, Any]:
    from sciplot_core.foundation.research_destination import require_data_destination
    from sciplot_core.policy import normalize_export_formats
    from sciplot_core.veusz_worker.operations import export_document

    root, document = _saved_plot(target, figure_id)
    destination = canonical_path(output)
    if destination.is_relative_to(root):
        raise ValueError("Legacy redraw output must be outside the original project directory.")
    require_data_destination(destination)
    selected_formats = list(normalize_export_formats(formats, default=("pdf",)))
    expected = file_sha256(document)
    destination.mkdir()
    # The native adapter puts diagnostics alongside the output directory, so
    # contain both diagnostics and artifacts below the newly allocated root.
    result = export_document(document, formats=selected_formats, output_dir=destination / "figures")
    if result["document_sha256"] != expected:
        raise ValueError("The saved native document changed before redraw completed.")
    return {**result, "kind": "sciplot_legacy_plot_redraw", "version": 1, "status": "redrawn",
            "project": str(root), "read_only": True}

def conversion_required(document: Path) -> Exception:
    from sciplot_core.project_lifecycle.errors import EngineError

    guidance = conversion_guidance(document)
    guidance.pop("message")
    return EngineError("legacy_conversion_required", "This saved legacy figure is read-only. Convert a separate copy to edit it.",
                       **guidance)
