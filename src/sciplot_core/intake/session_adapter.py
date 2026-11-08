"""Local AI confirmation adapter; the existing intake and project owners execute."""

import json
from pathlib import Path
from typing import Any
from sciplot_core.source_coverage.file_snapshots import _assert_snapshot_current
from . import application
from .project.session_project import read_confirmed_source_file
from .run import publish_prepared_intake_project
from .session import prepare_local_session
from .session_contract import (
    IntakeSessionError as IntakeSessionError,
    checked_session_request as _checked_request,
    admit_session_payload,
)
from .table_preview import preview_table_payload

def prepare_session(source: Path, *, output_root: Path, rule_id: str | None = None) -> dict[str, Any]:
    return prepare_local_session(source, output_root=output_root, requested_rule_id=rule_id)

def create_session(session: Path) -> dict[str, Any]:
    path = session.expanduser().resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = admit_session_payload(value)
    prepared = application.create_intake_project_from_session(payload)
    result = publish_prepared_intake_project(prepared)
    failed = bool(result.get("run_failed") or (result.get("last_run") or {}).get("ready_to_use") is False)
    return {**result, "status": "failed" if failed else "complete", "ready_to_use": not failed,
            "confirmed_session": str(path),
            "selection": {"rule_id": payload["rule_id"], "authority": "explicit_request", "recognition_confidence": None},
            "context_is_non_authoritative": True}


def preview_session_table(session: Path, *, group_index: int, file_index: int,
                          sheet: str | None = None) -> dict[str, Any]:
    value = json.loads(session.expanduser().read_text(encoding="utf-8"))
    request = _checked_request(value)
    if (type(group_index) is not int or type(file_index) is not int or group_index < 0 or file_index < 0
            or group_index >= len(request["groups"]) or file_index >= len(request["groups"][group_index]["files"])):
        raise IntakeSessionError("Select an exact existing group/file index; no other table is substituted.")
    group = request["groups"][group_index]
    reference = group["files"][file_index]
    original, captured = read_confirmed_source_file(reference)
    preview = preview_table_payload(name=original.name, content=original.content, selected_sheet=sheet)
    _assert_snapshot_current(captured, label="Intake table preview", expected_sha256=reference["sha256"])
    confirmation = {"sample": group["sample"], "file_name": reference["name"],
                    "source_path": reference["source_path"], "source_sha256": reference["sha256"],
                    "sheet": preview["sheet"], "sheet_selected": preview["sheet"] is not None,
                    "columns": [{"index": column["index"], "name": column["name"],
                                 "inferred_type": column["inferred_type"], "confirmed_type": "auto", "role": "auto"}
                                for column in preview["columns"]]}
    return {**preview, "group_index": group_index, "file_index": file_index,
            "sample": group["sample"], "source_path": reference["source_path"],
            "confirmation_request": confirmation,
            "creates_project": False, "changes_sources": False}
