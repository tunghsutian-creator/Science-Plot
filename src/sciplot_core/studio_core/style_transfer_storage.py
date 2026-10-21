"""Named Studio port for an exact-audited native/spec style rollback set."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.figure_set_storage import _commit_studio_figure_set_transaction
from sciplot_core.studio_core.persistence import stage_veusz_document
from sciplot_core.veusz_worker.spec_audit import audit_spec_data


def save_transferred_style_pair(document: Any, target: Path, spec_path: Path,
                                spec: dict[str, Any], *, input_hashes: dict[str, str]) -> dict[str, Any]:
    staged_spec = spec_path.with_name(f".sciplot-style-transfer-{uuid4().hex}.json")
    staged_document: Path | None = None
    try:
        atomic_write_json(staged_spec, spec)

        def validate(path: Path, **_kwargs: Any) -> bool:
            return str(audit_spec_data(path, staged_spec, check_presentation=True)["status"]) == "passed"

        stage = stage_veusz_document(document, target, staged_validator=validate)
        staged_document = Path(stage["staged"])
        if not stage["reopen_validated"]:
            raise ValueError("Transferred native/spec pair did not pass its staged exact audit.")
        if any(file_sha256(Path(path)) != digest for path, digest in input_hashes.items()):
            raise ValueError("Style-transfer input changed before pair installation.")
        replacements = [
            {"staged": staged_document, "target": target, "expected_hash": stage["sha256"], "kind": "document"},
            {"staged": staged_spec, "target": spec_path, "expected_hash": file_sha256(staged_spec), "kind": "spec"},
        ]
        _commit_studio_figure_set_transaction(project_dir=target.parent, replacements=replacements,
                                             manual_archive_requests=[], registry=None)
        return {"kind": "sciplot_native_spec_style_pair", "status": "passed", "reopen_validated": True,
                "document_sha256": file_sha256(target), "spec_sha256": file_sha256(spec_path)}
    finally:
        staged_spec.unlink(missing_ok=True)
        if staged_document is not None:
            staged_document.unlink(missing_ok=True)
