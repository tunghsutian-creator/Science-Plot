from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, cast

if TYPE_CHECKING:
    from sciplot_core.canvas.provider import AssistantProvider


_AUTO_ASSISTANT_PROVIDER = object()


def resolve_composition_application_workspace(
    targets: list[Path] | tuple[Path, ...],
    *,
    output_root: Path | None = None,
    name: str | None = None,
    layout_id: str | None = None,
    canvas_height_mm: float = 55.0,
):
    from sciplot_core._utils import slug, unique_path
    from sciplot_core.composition_workspace import (
        create_composition_workspace,
        resolve_composition_workspace,
    )

    resolved = [target.expanduser().resolve() for target in targets]
    if len(resolved) == 1:
        target = resolved[0]
        if target.is_file() and target.name == "composition.json":
            return resolve_composition_workspace(target)
        if target.is_dir() and (target / "composition.json").is_file():
            return resolve_composition_workspace(target)
    if not resolved:
        raise ValueError(
            "Composition requires an existing project or source VSZ files."
        )
    project_name = str(name or " + ".join(path.stem for path in resolved)).strip()
    root_parent = (output_root or Path("outputs") / "composition_projects").resolve()
    root_parent.mkdir(parents=True, exist_ok=True)
    project_root = unique_path(root_parent, slug(project_name))
    workspace, _project = create_composition_workspace(
        resolved,
        root=project_root,
        name=project_name,
        layout_id=layout_id,
        canvas_height_mm=canvas_height_mm,
    )
    return workspace


def resolve_canvas_assistant_provider(
    assistant_provider: AssistantProvider | None | object = _AUTO_ASSISTANT_PROVIDER,
    *,
    environ: Mapping[str, str] | None = None,
) -> AssistantProvider | None:
    if assistant_provider is not _AUTO_ASSISTANT_PROVIDER:
        return cast("AssistantProvider | None", assistant_provider)
    from sciplot_core.openai_provider import load_openai_provider_from_environment

    try:
        return load_openai_provider_from_environment(environ)
    except ValueError as exc:
        warnings.warn(
            "SciPlot Canvas is continuing without OpenAI Assistant because its "
            f"configuration is invalid: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


def launch_canvas_application(
    target: Path,
    *,
    output_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    assistant_provider: AssistantProvider | None | object = _AUTO_ASSISTANT_PROVIDER,
) -> int:
    from PyQt6 import QtCore, QtWidgets

    from sciplot_gui.main_window import SciPlotCanvasWindow
    from sciplot_gui.workspace import resolve_canvas_workspace

    resolved_provider = resolve_canvas_assistant_provider(assistant_provider)

    workspace = resolve_canvas_workspace(
        target,
        output_root=output_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication(sys.argv[:1])
    application.setApplicationName("SciPlot Canvas")
    application.setOrganizationName("SciPlot")
    application.setQuitOnLastWindowClosed(True)
    QtCore.QCoreApplication.setApplicationVersion("0.1.0-m3-dev")
    window = SciPlotCanvasWindow(
        workspace,
        assistant_provider=resolved_provider,
    )
    window.show()
    if not owns_application:
        return 0
    return int(application.exec())


def launch_composition_application(
    targets: list[Path] | tuple[Path, ...],
    *,
    output_root: Path | None = None,
    name: str | None = None,
    layout_id: str | None = None,
    canvas_height_mm: float = 55.0,
) -> int:
    from PyQt6 import QtCore, QtWidgets

    from sciplot_gui.composition_window import SciPlotCompositionWindow

    workspace = resolve_composition_application_workspace(
        targets,
        output_root=output_root,
        name=name,
        layout_id=layout_id,
        canvas_height_mm=canvas_height_mm,
    )
    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication(sys.argv[:1])
    application.setApplicationName("SciPlot Composition")
    application.setOrganizationName("SciPlot")
    application.setQuitOnLastWindowClosed(True)
    QtCore.QCoreApplication.setApplicationVersion("0.1.0-m4-dev")
    window = SciPlotCompositionWindow(workspace)
    window.show()
    if not owns_application:
        return 0
    return int(application.exec())


__all__ = [
    "launch_canvas_application",
    "launch_composition_application",
    "resolve_canvas_assistant_provider",
    "resolve_composition_application_workspace",
]
