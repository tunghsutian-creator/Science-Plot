"""Freeze old presentation before entering the replacement science namespace."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.document_edit import _audited_setting_candidate
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.studio_core.source_update_review import project_figures
from sciplot_core.studio_core.preparation_candidate import require_preparation_candidate
from sciplot_core.veusz_worker.style_projection import project_transferred_styles
from sciplot_core.veusz_worker.style_transfer import _style_plan


def capture_project_styles(project: Path) -> dict[str, dict[str, Any]]:
    """Inspect only the audited old generation, before any new source reads."""
    result = {}
    for identity, (document, spec) in project_figures(project).items():
        before = file_sha256(document), file_sha256(spec)
        state = run_document_worker("inspect-document-state", document)
        if (state.get("document", {}).get("sha256") != before[0]
                or before != (file_sha256(document), file_sha256(spec))):
            raise ValueError("The native style baseline changed while it was inspected")
        result[identity] = {"spec": json.loads(spec.read_text()), "widgets": state["widgets"],
                            "document_sha256": before[0], "spec_sha256": before[1]}
    return result


def transfer_project_styles(candidate: Path, baseline: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the existing finite presentation plan to new private native bytes."""
    require_preparation_candidate(candidate)
    changes: list[dict[str, Any]] = []
    for identity, (document, spec) in project_figures(candidate).items():
        if identity not in baseline:
            changes.append({"figure_id": identity, "status": "new_figure", "applied": []})
            continue
        previous = baseline[identity]
        current = json.loads(spec.read_text())
        inspected = run_document_worker("inspect-document-state", document)
        if inspected.get("document", {}).get("sha256") != file_sha256(document):
            raise ValueError("The new native style candidate changed during inspection")
        applied, skipped = _style_plan(previous["spec"], current, previous["widgets"], inspected["widgets"])
        # Existing native setting admission bounds each batch to 100 changes.
        # All batches remain inside this disposable candidate and receive the
        # ordinary exact scientific audit; the project is published only once.
        for start in range(0, len(applied), 100):
            batch = [{"object_path": item["current_widget"],
                      "setting_path": item["current_widget"] + "/" + item["setting"],
                      "expected_value": item["before"], "value": item["after"]}
                     for item in applied[start:start + 100]]
            with TemporaryDirectory(prefix=".sciplot-source-style-", dir=candidate / "studio") as directory:
                result = _audited_setting_candidate(document, spec, batch, Path(directory))
                document.write_bytes(Path(result["candidate"]["path"]).read_bytes())
        if applied:
            spec.write_text(json.dumps(project_transferred_styles(current, applied), ensure_ascii=False, indent=2, allow_nan=False))
        changes.append({"figure_id": identity, "status": "passed", "applied": applied, "skipped": skipped,
                        "reasons": []})
    return changes
