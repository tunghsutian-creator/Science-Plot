"""Resolve Studio targets and dispatch document preparation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY
from sciplot_core.terminal_source_binding import (
    SealedTerminalSourceBinding,
    TerminalSourceBindingError,
)

from sciplot_core.studio_core.context import (
    _normalize_optional_string,
)
from sciplot_core.studio_core.export_execution import (
    _project_studio_document,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.prepare_existing import (
    reuse_existing_studio_document,
)
from sciplot_core.studio_core.prepare_generated import (
    generate_studio_document,
)
from sciplot_core.studio_core.request_overrides import (
    _existing_document_payload,
)


def prepare_studio_document(
    target: str | Path,
    *,
    output_root: Path | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    regenerate_generated: bool = False,
    figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
    _terminal_source_binding: SealedTerminalSourceBinding | None = None,
    _terminal_source_prepared: bool = False,
) -> dict[str, Any]:
    resolved = Path(target).expanduser().resolve()
    target_info = _resolve_studio_target(
        resolved,
        output_root=output_root,
        delivery_root=delivery_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
        figure_set_path_replacer=figure_set_path_replacer,
    )
    if target_info["mode"] == "vsz":
        if _terminal_source_binding is not None:
            raise TerminalSourceBindingError(
                "terminal_source_binding_request_mismatch",
                "A materialized terminal source requires an internal request target.",
            )
        if _normalize_optional_string(rule_id):
            raise ValueError(
                "--rule applies to raw data, a SciPlot project, or plot_request.json; not an existing VSZ."
            )
        return _existing_document_payload(target_info["document"])
    if target_info["mode"] == "source":
        if _terminal_source_binding is not None:
            raise TerminalSourceBindingError(
                "terminal_source_binding_request_mismatch",
                "A materialized terminal source cannot enter raw-source intake.",
            )
        return target_info["prepared"]

    request_path = target_info["request"]
    project_dir = target_info["project_dir"]
    if delivery_root is not None:
        request = _read_json(request_path)
        request[REQUEST_DELIVERY_ROOT_KEY] = str(delivery_root.expanduser().resolve())
        request_path.write_text(
            json.dumps(json_safe(request), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    existing_document = _project_studio_document(project_dir)
    if (
        target_info.get("mode") == "project"
        and existing_document is not None
        and rule_id is None
        and template is None
        and project_name is None
        and not regenerate_generated
    ):
        return reuse_existing_studio_document(
            project_dir=project_dir,
            request_path=request_path,
            document_path=existing_document,
        )
    binding_option = (
        {"_terminal_source_binding": _terminal_source_binding}
        if _terminal_source_binding is not None
        else {}
    )
    return generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
        figure_set_path_replacer=figure_set_path_replacer,
        _terminal_source_prepared=_terminal_source_prepared,
        **binding_option,
    )


def _resolve_studio_target(
    path: Path,
    *,
    output_root: Path | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    if path.suffix.lower() == ".vsz":
        if not path.exists():
            raise FileNotFoundError(f"Veusz document not found: {path}")
        return {"mode": "vsz", "document": path}
    if path.is_dir():
        request = path / "plot_request.json"
        if not request.exists():
            return _qt_first_project_from_source(
                path,
                output_root=output_root,
                delivery_root=delivery_root,
                rule_id=rule_id,
                template=template,
                project_name=project_name,
                figure_set_path_replacer=figure_set_path_replacer,
            )
        return {"mode": "project", "project_dir": path, "request": request}
    if path.is_file() and path.suffix.lower() == ".json":
        return {"mode": "request", "project_dir": path.parent, "request": path}
    if path.exists():
        return _qt_first_project_from_source(
            path,
            output_root=output_root,
            delivery_root=delivery_root,
            rule_id=rule_id,
            template=template,
            project_name=project_name,
            figure_set_path_replacer=figure_set_path_replacer,
        )
    raise ValueError(
        "studio accepts a SciPlot project directory, plot_request.json, or .vsz document."
    )


def _qt_first_project_from_source(
    path: Path,
    *,
    output_root: Path | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    from sciplot_core.intake.project import create_intake_project_from_session
    from sciplot_core.intake.session import prepare_intake_session

    project_root = output_root or Path("outputs") / "intake_projects"
    session = prepare_intake_session(
        path,
        output_root=project_root,
        requested_rule_id=rule_id,
        allow_pending_rule_review=bool(
            _normalize_optional_string(rule_id) and _normalize_optional_string(template)
        ),
    )
    normalized_name = _normalize_optional_string(project_name)
    if normalized_name:
        session["project_name"] = normalized_name
        session_path = session.get("session_path")
        if isinstance(session_path, str) and session_path.strip():
            Path(session_path).write_text(
                json.dumps(json_safe(session), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    prepared: dict[str, Any] | None = None
    preparation_error: Exception | None = None
    preparation_traceback: TracebackType | None = None

    def prepare_once(project_dir: Path) -> dict[str, Any]:
        nonlocal prepared, preparation_error, preparation_traceback
        try:
            payload = generate_studio_document(
                project_dir=project_dir,
                request_path=project_dir / "plot_request.json",
                rule_id=None,
                template=None,
                project_name=None,
                figure_set_path_replacer=figure_set_path_replacer,
            )
            prepared = payload
        except Exception as exc:
            preparation_error = exc
            preparation_traceback = exc.__traceback__
            raise
        return payload

    project = create_intake_project_from_session(
        session,
        studio_preparer=prepare_once,
        template=template,
        delivery_root=delivery_root,
    )
    project_dir = Path(str(project["project_dir"])).expanduser().resolve()
    request = project_dir / "plot_request.json"
    if preparation_error is not None:
        preparation_error.add_note(
            "SciPlot retained the blocked intake project at "
            f"{project_dir} and its diagnostic ZIP at {project['zip_path']}."
        )
        raise preparation_error.with_traceback(preparation_traceback)
    if prepared is None:
        raise RuntimeError(
            f"Studio preparation did not return a document for intake project: {project_dir}"
        )
    project_studio = (
        project.get("studio") if isinstance(project.get("studio"), dict) else {}
    )
    prepared_project = Path(str(prepared.get("project_dir") or "")).expanduser()
    prepared_request = Path(str(prepared.get("request") or "")).expanduser()
    prepared_document = Path(str(prepared.get("document") or "")).expanduser()
    registered_document = str(project_studio.get("document") or "").strip()
    registered_request = str(project_studio.get("generated_from") or "").strip()
    if (
        project_studio.get("status") != "ready"
        or prepared_project.resolve() != project_dir
        or prepared_request.resolve() != request
        or not prepared_document.is_file()
        or (
            registered_document
            and Path(registered_document).expanduser().resolve()
            != prepared_document.resolve()
        )
        or (
            registered_request
            and Path(registered_request).expanduser().resolve() != request
        )
    ):
        raise RuntimeError(
            "Studio preparation and the finalized intake project disagree; "
            f"inspect the retained project at {project_dir}."
        )
    return {
        "mode": "source",
        "source": path,
        "session": session.get("session_path"),
        "project_dir": project_dir,
        "request": request,
        "prepared": prepared,
    }
