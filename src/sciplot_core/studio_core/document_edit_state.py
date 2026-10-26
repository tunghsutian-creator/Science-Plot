"""Version and artifact boundaries for external native document edits."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core.delivery.filesystem_metadata import is_delivery_finder_metadata
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.studio_core.native_scientific_audit import audit_edited_document as audit_edited_document
from sciplot_core.studio_core.delivery_recovery_state import canonical_path
from sciplot_core.studio_core.source_update_files import (
    file_inventory,
    project_inventory,
)
from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.native_process import run_worker
from sciplot_core.studio_core.project_command_scope import project_read_runtime
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.foundation.source_locations import selected_source_resolver


def value_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def native_edit_request_key(project_id: str, request_id: str) -> str:
    """A host's explicit operation identity stays stable through preview retries."""
    if not isinstance(request_id, str) or re.fullmatch(r"[0-9a-f]{64}", request_id) is None:
        raise ValueError("A native edit request identity requires one exact SHA256 identifier.")
    return canonical_json_sha256({"kind": "document_edit", "project_id": project_id, "request_id": request_id})


@project_read_runtime
def edit_state(project: Path, selected: dict[str, Any] | None = None) -> dict[str, Any]:
    if selected is not None:
        from sciplot_core.studio_core.project_command_scope import figure_read_state

        request = json.loads((project / "plot_request.json").read_text())
        return {**figure_read_state(project, selected),
                "delivery": str(canonical_path(requested_delivery_root({"request": request}, run_output=project))),
                "delivery_files": None}
    inventory = project_inventory(project)
    request = json.loads((project / "plot_request.json").read_text())
    delivery = canonical_path(
        requested_delivery_root({"request": request}, run_output=project)
    )
    # Keep the generic source/project inventory strict. Only incidental Finder
    # files in this visible delivery are outside the reviewed artifact baseline.
    delivery_files = (
        {
            name: digest
            for name, digest in file_inventory(delivery).items()
            if not is_delivery_finder_metadata(delivery / name)
        }
        if delivery.exists()
        else None
    )
    return {
        "project_files": inventory,
        "delivery": str(delivery),
        "delivery_files": delivery_files,
    }


def new_preview_directory(project: Path, target: Path) -> Path:
    project = canonical_path(project)
    output = canonical_path(target)
    request = json.loads(canonical_path(project / "plot_request.json").read_text())
    delivery = canonical_path(requested_delivery_root({"request": request}, run_output=project))
    # This checks paths only. The edit owner captures and verifies byte identity
    # before and after preview generation; another inventory here is redundant.
    forbidden = [project, delivery]
    for key in ("input", "input_path", "data_dir"):
        if isinstance(request.get(key), str):
            source = Path(request[key]).expanduser()
            forbidden.append(canonical_path(source if source.is_absolute() else project / source))
    if output.exists() or any(
        output == p or output.is_relative_to(p) for p in forbidden
    ):
        raise ValueError(
            "Choose a new preview directory outside the project, source and delivery."
        )
    output.mkdir(parents=True, mode=0o700)
    return output


def run_document_worker(*arguments: object) -> dict[str, Any]:
    if selected_source_resolver() is None and len(arguments) >= 2:
        from sciplot_core.studio_core.context import resolve_studio_project_context
        from sciplot_core.studio_core.project_command_scope import project_store

        context = resolve_studio_project_context(Path(str(arguments[1])))
        if context is not None and (context["project_dir"] / ".sciplot_store").exists():
            with project_runtime(project_store(context["project_dir"])):
                return _run_document_worker(*arguments)
    return _run_document_worker(*arguments)


def _run_document_worker(*arguments: object) -> dict[str, Any]:
    completed = run_worker(
        [sys.executable, "-m", "sciplot_core.veusz_worker", *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=120,
        env=veusz_worker_environment(), cold_runner=subprocess.run,
    )
    if completed.returncode:
        from sciplot_core.studio_core.categorical_display_errors import raise_categorical_worker_rejection

        raise_categorical_worker_rejection(completed.returncode, completed.stderr)
        detail = completed.stderr.strip().splitlines()
        raise ValueError(
            "Native document operation failed: "
            + (detail[-1] if detail else str(completed.returncode))
        )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise ValueError("Native document operation returned invalid state.")
    return result




def preview_identity(preview: dict[str, Any]) -> str:
    return value_digest({k: v for k, v in preview.items() if k != "operation_id"})


def check_artifact(record: dict[str, Any]) -> Path:
    path = canonical_path(Path(record["path"]))
    if not path.is_file() or file_sha256(path) != record["sha256"]:
        raise ValueError("An edit preview artifact changed; create a fresh preview.")
    return path


def history_directory(project: Path, operation_id: str) -> Path:
    if len(operation_id) != 64 or any(
        c not in "0123456789abcdef" for c in operation_id
    ):
        raise ValueError("Invalid document edit operation identity.")
    return canonical_path(
        project.parent / ".document_edit_history" / project.name / operation_id
    )
