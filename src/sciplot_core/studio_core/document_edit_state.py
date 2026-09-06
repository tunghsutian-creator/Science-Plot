"""Version and artifact boundaries for external native document edits."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.source_coverage.managed_documents import _source_records
from sciplot_core.studio_core.delivery_recovery import _audit_candidate
from sciplot_core.studio_core.delivery_recovery_state import canonical_path
from sciplot_core.studio_core.source_update_commit import (
    file_inventory,
    project_inventory,
)
from sciplot_core.veusz_runtime import veusz_worker_environment


def value_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def edit_state(project: Path) -> dict[str, Any]:
    inventory = project_inventory(project)
    request = json.loads((project / "plot_request.json").read_text())
    delivery = canonical_path(
        requested_delivery_root({"request": request}, run_output=project)
    )
    return {
        "project_files": inventory,
        "delivery": str(delivery),
        "delivery_files": file_inventory(delivery) if delivery.exists() else None,
    }


def new_preview_directory(project: Path, target: Path) -> Path:
    output = canonical_path(target)
    state = edit_state(project)
    request = json.loads((project / "plot_request.json").read_text())
    forbidden = [project, Path(state["delivery"])]
    for key in ("input", "input_path", "data_dir"):
        if isinstance(request.get(key), str):
            forbidden.append(canonical_path(Path(request[key])))
    if output.exists() or any(
        output == p or output.is_relative_to(p) for p in forbidden
    ):
        raise ValueError(
            "Choose a new preview directory outside the project, source and delivery."
        )
    output.mkdir(parents=True, mode=0o700)
    return output


def run_document_worker(*arguments: object) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "sciplot_core.veusz_worker", *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=120,
        env=veusz_worker_environment(),
    )
    if completed.returncode:
        detail = completed.stderr.strip().splitlines()
        raise ValueError(
            "Native document operation failed: "
            + (detail[-1] if detail else str(completed.returncode))
        )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise ValueError("Native document operation returned invalid state.")
    return result


def audit_edited_document(document: Path, spec: Path) -> dict[str, Any]:
    specification = spec.read_bytes()
    records = _source_records(json.loads(specification))

    def verify_sources() -> None:
        if spec.read_bytes() != specification or any(
            not path.is_file() or file_sha256(path) != digest
            for path, digest in records.items()
        ):
            raise ValueError(
                "Prepared scientific sources or their specification changed."
            )

    verify_sources()
    audit = _audit_candidate(document, spec)
    verify_sources()
    return audit


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
