"""Resolve Studio targets and dispatch document preparation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY

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
    _apply_studio_request_overrides,
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
) -> dict[str, Any]:
    resolved = Path(target).expanduser().resolve()
    target_info = _resolve_studio_target(
        resolved,
        output_root=output_root,
        delivery_root=delivery_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    if target_info["mode"] == "vsz":
        if _normalize_optional_string(rule_id):
            raise ValueError(
                "--rule applies to raw data, a SciPlot project, or plot_request.json; not an existing VSZ."
            )
        return _existing_document_payload(target_info["document"])

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
    return generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
        figure_set_path_replacer=figure_set_path_replacer,
    )


def _resolve_studio_target(
    path: Path,
    *,
    output_root: Path | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
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
    project = create_intake_project_from_session(
        session,
        studio_preparer=prepare_studio_document,
    )
    project_dir = Path(str(project["project_dir"])).expanduser().resolve()
    request = project_dir / "plot_request.json"
    if delivery_root is not None:
        request_payload = _read_json(request)
        request_payload[REQUEST_DELIVERY_ROOT_KEY] = str(
            delivery_root.expanduser().resolve()
        )
        request.write_text(
            json.dumps(json_safe(request_payload), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    _apply_studio_request_overrides(
        project_dir,
        request_path=request,
        rule_id=rule_id,
        template=template,
        project_name=normalized_name,
    )
    return {
        "mode": "source",
        "source": path,
        "session": session.get("session_path"),
        "project_dir": project_dir,
        "request": request,
    }
