"""Open and redraw the saved native artifact, not its editable project state."""
from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.file_hashing import file_sha256


def resolve_legacy_plot(target: Path, figure_id: str | None) -> tuple[Path, Path]:
    """Use the same saved authority as public open, without attaching or importing it."""
    from sciplot_core.project_lifecycle.errors import EngineError
    from sciplot_core.project_lifecycle.target_adapter import observe_saved_legacy_target

    saved = observe_saved_legacy_target(target, figure_id)
    if saved is None:
        raise EngineError("legacy_plot_not_found", "Select a saved legacy project, delivery, or exact .vsz file.",
                          action="select_legacy_plot")
    return saved


def open_legacy_document(root: Path, document: Path) -> dict[str, Any]:
    from sciplot_core.studio_core.project_query import _inspect_document

    observed = _inspect_document(document)
    return {"kind": "sciplot_legacy_plot", "version": 1, "status": "opened",
            "project": str(root), "document": observed["document"],
            "pages": observed["pages"], "linked_files": observed["linked_files"],
            "read_only": True, "new_features_require_conversion": True,
            "next_step": {"action": "redraw_legacy", "target": str(document),
                          "mcp_tool": "sciplot_project_legacy_redraw",
                          "cli_argv": ["sciplot", "project", "legacy-redraw", str(document), "--out"],
                          "requires": ["new_output_directory"]},
            "conversion": conversion_guidance(document)}


def conversion_guidance(document: Path) -> dict[str, Any]:
    return {"action": "legacy_convert", "target": str(document),
            "mcp_tool": "sciplot_project_legacy_convert",
            "cli_argv": ["sciplot", "project", "legacy-convert", str(document), "--out"],
            "requires": ["new_output_directory"],
            "message": "To edit a supported saved XY plot, convert a separate copy."}


def redraw_legacy_plot(target: Path, *, output: Path, formats: list[str],
                       figure_id: str | None = None) -> dict[str, Any]:
    from sciplot_core.foundation.research_destination import require_data_destination
    from sciplot_core.policy import normalize_export_formats
    from sciplot_core.veusz_worker.operations import export_document

    root, document = resolve_legacy_plot(target, figure_id)
    destination = canonical_path(output)
    if destination.is_relative_to(root) or destination.is_relative_to(canonical_path(target)):
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
