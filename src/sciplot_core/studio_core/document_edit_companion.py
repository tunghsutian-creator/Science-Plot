"""Archive and recover the specification participating in an annotation edit."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.delivery_recovery import _write_durable
from sciplot_core.studio_core.delivery_recovery_state import canonical_path
from sciplot_core.studio_core.document_edit_state import edit_state


def companion_path(project: Path, record: dict[str, Any]) -> Path:
    relative = Path(record["relative"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("studio",):
        raise ValueError("The edit specification must be a managed studio file.")
    return canonical_path(project / relative)


def archive_companion(project: Path, spec: Path, candidate: Path, root: Path) -> dict[str, Any]:
    relative = str(spec.relative_to(project))
    descriptor = {"relative": relative, "base_sha256": file_sha256(spec),
                  "result_sha256": file_sha256(candidate), "mode": spec.stat().st_mode & 0o777}
    companion_path(project, descriptor)
    for name, path in (("before.spec.json", spec), ("after.spec.json", candidate)):
        target = root / name
        if target.exists() and file_sha256(target) != file_sha256(path):
            raise ValueError("Archived annotation specification conflicts with the reviewed edit.")
        if not target.exists():
            _write_durable(target, path.read_bytes())
    return descriptor


def replace_companion(path: Path, contents: bytes, mode: int) -> None:
    fd, name = tempfile.mkstemp(prefix=".annotation-spec-", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        staged.chmod(mode)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def recover_companion(project: Path, root: Path, record: dict[str, Any], review: dict[str, Any]) -> None:
    """Complete an interrupted two-file install only from unchanged archived evidence."""
    companion = record.get("companion")
    if not isinstance(companion, dict):
        return
    path = companion_path(project, companion)
    for name, key in (("before.spec.json", "base_sha256"), ("after.spec.json", "result_sha256")):
        if file_sha256(root / name) != companion[key]:
            raise ValueError("Annotation specification recovery evidence changed.")
    if record["status"] != "pending":
        return
    state = edit_state(project)
    allowed = {record["document_relative"]: (record["base_sha256"], record["result_sha256"]),
               companion["relative"]: (companion["base_sha256"], companion["result_sha256"])}
    expected = {**review["base_state"], "project_files": {**review["base_state"]["project_files"]}}
    for relative, digests in allowed.items():
        current = state["project_files"].get(relative)
        if current not in digests:
            raise ValueError("Interrupted annotation edit has a conflicting current file.")
        expected["project_files"][relative] = current
    if state != expected:
        raise ValueError("Project changed during interrupted annotation edit; preserve the archive.")
    doc_new = state["project_files"][record["document_relative"]] == record["result_sha256"]
    spec_new = state["project_files"][companion["relative"]] == companion["result_sha256"]
    # Restore the old specification when the document was not yet installed.
    # Ordinary apply can then replay the unchanged preview from its baseline.
    if doc_new != spec_new:
        name = "after.spec.json" if doc_new else "before.spec.json"
        replace_companion(path, (root / name).read_bytes(), companion["mode"])
