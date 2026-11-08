"""Create a project from a confirmed intake session."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from ..config import _DEFAULT_OUTPUT_ROOT
from ..models import IncomingFile, IntakeGroupInput
from ..catalog import _catalog_item
from ..session_contract import IntakeSessionError, admit_session_payload
from ..table_preview import preview_table_payload
from sciplot_core.semantic_sources.confirmation_contract import has_column_intent
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot

from sciplot_core.intake.project.project_builder import (
    create_intake_project,
)


def read_confirmed_source_file(item: dict[str, Any], *, label: str = "selected") -> tuple[IncomingFile, dict[str, Any]]:
    """Read declared bytes and an operation-local witness; never persist host identity."""
    source_text = str(item.get("source_path") or "").strip()
    if not source_text:
        raise ValueError(
            "Intake session file "
            f"{label} has no source_path."
        )
    source_path = Path(source_text).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(
            f"Intake session source is missing or not a file: {source_path}"
        )
    expected_size = item.get("size_bytes")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
    ):
        raise ValueError(
            f"Intake session source has no valid size record: {source_path}"
        )
    expected_sha256 = str(item.get("sha256") or "").strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError(
            f"Intake session source has no valid SHA-256 record: {source_path}"
        )
    captured = stable_file_snapshot(source_path, label="Confirmed intake source")
    content = captured["bytes"]
    if len(content) != expected_size or captured["sha256"] != expected_sha256:
        raise ValueError(
            "Intake session source changed after the session was "
            f"prepared: {source_path}"
        )
    return IncomingFile(name=str(item.get("name") or source_path.name), content=content,
                        source_path=str(captured["path"])), captured


def _validate_columns(request: dict[str, Any], groups: list[IntakeGroupInput], *, rule_id: str) -> None:
    files = [(group.sample.strip(), item.name, reference, item.content)
             for group, declared in zip(groups, request["groups"], strict=True)
             for item, reference in zip(group.files, declared["files"], strict=True)]
    seen = set()
    for confirmation in request.get("column_confirmations", []):
        matches = [(reference, content) for sample, name, reference, content in files
                   if sample == confirmation["sample"].strip() and name == confirmation["file_name"]
                   and (not confirmation.get("source_path")
                        or Path(reference["source_path"]).expanduser().resolve() == Path(confirmation["source_path"]).expanduser().resolve())]
        if len(matches) != 1:
            raise IntakeSessionError("Every column confirmation must identify exactly one selected sample/file.")
        reference, content = matches[0]
        if confirmation["source_sha256"] != reference["sha256"]:
            raise IntakeSessionError("A column/worksheet confirmation belongs to changed source bytes.")
        key = (confirmation["sample"].strip(), confirmation["file_name"], reference["source_path"])
        if key in seen:
            raise IntakeSessionError("A file must have one complete column/worksheet confirmation.")
        seen.add(key)
        preview = preview_table_payload(name=confirmation["file_name"], content=content,
                                        selected_sheet=confirmation.get("sheet"))
        columns = {column["index"]: column for column in preview["columns"]}
        indices = set()
        for column in confirmation["columns"]:
            actual = columns.get(column["index"])
            if (actual is None or column["index"] in indices or column["name"] != actual["name"]
                    or ("inferred_type" in column and column["inferred_type"] != actual["inferred_type"])):
                raise IntakeSessionError("Column identities must match the original preview; indices must be unique.")
            indices.add(column["index"])
        if has_column_intent(confirmation):
            from sciplot_core.semantic_sources.rheology_confirmation import check_confirmed_rheology_bytes

            check_confirmed_rheology_bytes(confirmation["file_name"], content, confirmation, rule_id=rule_id)


def create_intake_project_from_session(
    session: str | Path | dict[str, Any],
    *,
    studio_preparer: Callable[[Path], dict[str, Any]],
    project_factory: Callable[..., dict[str, Any]] | None = None,
    template: str | None = None,
    delivery_root: Path | None = None,
) -> dict[str, Any]:
    if isinstance(session, str | Path):
        payload = json.loads(Path(session).expanduser().read_text(encoding="utf-8"))
    else:
        payload = dict(session)
    if payload.get("kind") == "sciplot_local_intake_session":
        payload = admit_session_payload(payload, template=template)
    groups: list[IntakeGroupInput] = []
    for group_index, group in enumerate(payload.get("groups", [])):
        if not isinstance(group, dict):
            raise ValueError(
                f"Intake session group {group_index + 1} must be an object."
            )
        files: list[IncomingFile] = []
        for file_index, item in enumerate(group.get("files", [])):
            if not isinstance(item, dict):
                raise ValueError(
                    "Intake session file "
                    f"{group_index + 1}.{file_index + 1} must be an object."
                )
            incoming, _snapshot = read_confirmed_source_file(item, label=f"{group_index + 1}.{file_index + 1}")
            files.append(incoming)
        groups.append(
            IntakeGroupInput(sample=str(group.get("sample") or ""), files=tuple(files))
        )
    if payload.get("column_confirmations"):
        _, experiment = _catalog_item(payload["data_type_id"], payload["experiment_type_id"])
        _validate_columns(payload, groups, rule_id=str(experiment.get("rule_id") or ""))
    factory = project_factory or create_intake_project
    semantic = (
        dict(payload["semantic"])
        if isinstance(payload.get("semantic"), dict)
        else {
            "semantic_family": payload.get("experiment_type_id"),
            "rule_id": payload.get("rule_id"),
            "confidence": payload.get("confidence"),
            "reason": payload.get("reason"),
        }
    )
    if payload.get("pending_rule_review") is True:
        semantic["pending_rule_review"] = True
    arguments = {
        "project_name": str(payload.get("project_name") or ""),
        "data_type_id": str(payload.get("data_type_id") or "unknown"),
        "experiment_type_id": str(payload.get("experiment_type_id") or "unknown"),
        "groups": groups,
        "group_order_is_explicit": payload.get("group_order_is_explicit", True)
        is not False,
        "output_root": Path(str(payload.get("output_root") or _DEFAULT_OUTPUT_ROOT)),
        "plot_output": payload.get("plot_output"),
        "exports": payload.get("exports"),
        "render_options": payload.get("render_options"),
        "column_confirmations": payload.get("column_confirmations"),
        "replicate_mode": payload.get("replicate_mode"),
        "recognition": semantic,
    }
    if template is not None:
        arguments["template"] = template
    if delivery_root is not None:
        arguments["delivery_root"] = delivery_root
    if project_factory is None:
        arguments["studio_preparer"] = studio_preparer
    return factory(**arguments)
