"""Apply reviewed annotation meanings only inside an isolated source candidate."""

import json
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.annotation_rebinding import annotation_revision
from sciplot_core.studio_core.source_update_review import project_figures
from sciplot_core.studio_core.document_edit import _candidate


def transfer_annotations(previous: Path, candidate: Path, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before, after = project_figures(previous), project_figures(candidate)
    records = []
    for figure_id, (_, old_spec) in before.items():
        target = after.get(figure_id)
        new_spec = json.loads(target[1].read_text()) if target else None
        report, operations = annotation_revision(json.loads(old_spec.read_text()), new_spec,
            figure_id=figure_id, document_sha256=file_sha256(target[0]) if target else "",
            decisions=decisions)
        records.extend(report)
        if operations and target:
            with tempfile.TemporaryDirectory(prefix=".annotation-revision-", dir=candidate.parent) as temporary:
                result = _candidate(target[0], target[1], [], Path(temporary), operations=operations, figure_id=figure_id)
                target[0].write_bytes(Path(result["candidate"]["path"]).read_bytes())
                target[1].write_bytes(Path(result["candidate_spec"]["path"]).read_bytes())
    identities = {(record["figure_id"], record["id"]) for record in records}
    if any((decision.get("figure_id"), decision.get("id")) not in identities for decision in decisions):
        raise ValueError("Annotation revision names an unknown figure or annotation.")
    return records
