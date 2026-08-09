"""Stage the legacy primary document when it is not task-source rendered."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.studio_core.registry_state import _veusz_spec_path


def append_staged_primary_replacements(
    *,
    primary_document: Path,
    primary_staged_document: Path | None,
    primary_staged_spec: Path | None,
    primary_prior_generated_hash: str | None,
    task_source_rendered: bool,
    replacements: list[dict[str, Any]],
    manual_archive_requests: list[dict[str, Any]],
) -> None:
    """Add an externally staged primary pair unless this transaction renders it."""

    if primary_staged_document is None and primary_staged_spec is None:
        return
    if primary_staged_document is None or primary_staged_spec is None:
        raise ValueError(
            "A staged primary Studio document and spec must be supplied together."
        )
    if task_source_rendered:
        return
    document_hash = existing_file_sha256(primary_staged_document)
    spec_hash = existing_file_sha256(primary_staged_spec)
    if not document_hash or not spec_hash:
        raise RuntimeError("The staged primary Studio document is incomplete.")
    replacements.extend(
        [
            {
                "staged": primary_staged_document,
                "target": primary_document,
                "expected_hash": document_hash,
                "kind": "document",
            },
            {
                "staged": primary_staged_spec,
                "target": _veusz_spec_path(primary_document),
                "expected_hash": spec_hash,
                "kind": "spec",
            },
        ]
    )
    manual_archive_requests.append(
        {
            "document": primary_document,
            "spec": _veusz_spec_path(primary_document),
            "generated_hash": primary_prior_generated_hash,
        }
    )


__all__ = ["append_staged_primary_replacements"]
