"""Create a project from a confirmed intake session."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from ..config import _DEFAULT_OUTPUT_ROOT
from ..models import IncomingFile, IntakeGroupInput

from sciplot_core.intake.project.project_builder import (
    create_intake_project,
)


def create_intake_project_from_session(
    session: str | Path | dict[str, Any],
    *,
    studio_preparer: Callable[[Path], dict[str, Any]],
    project_factory: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if isinstance(session, str | Path):
        payload = json.loads(Path(session).expanduser().read_text(encoding="utf-8"))
    else:
        payload = dict(session)
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
            source_text = str(item.get("source_path") or "").strip()
            if not source_text:
                raise ValueError(
                    "Intake session file "
                    f"{group_index + 1}.{file_index + 1} has no source_path."
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
            content = source_path.read_bytes()
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if len(content) != expected_size or actual_sha256 != expected_sha256:
                raise ValueError(
                    "Intake session source changed after the session was "
                    f"prepared: {source_path}"
                )
            files.append(
                IncomingFile(
                    name=str(item.get("name") or source_path.name),
                    content=content,
                )
            )
        groups.append(
            IntakeGroupInput(sample=str(group.get("sample") or ""), files=tuple(files))
        )
    factory = project_factory or create_intake_project
    arguments = {
        "project_name": str(payload.get("project_name") or ""),
        "data_type_id": str(payload.get("data_type_id") or "unknown"),
        "experiment_type_id": str(payload.get("experiment_type_id") or "unknown"),
        "groups": groups,
        "output_root": Path(str(payload.get("output_root") or _DEFAULT_OUTPUT_ROOT)),
        "plot_output": payload.get("plot_output"),
        "exports": payload.get("exports"),
        "render_options": payload.get("render_options"),
        "column_confirmations": payload.get("column_confirmations"),
        "replicate_mode": payload.get("replicate_mode"),
        "recognition": (
            payload.get("semantic")
            if isinstance(payload.get("semantic"), dict)
            else {
                "semantic_family": payload.get("experiment_type_id"),
                "rule_id": payload.get("rule_id"),
                "confidence": payload.get("confidence"),
                "reason": payload.get("reason"),
            }
        ),
    }
    if project_factory is None:
        arguments["studio_preparer"] = studio_preparer
    return factory(**arguments)
