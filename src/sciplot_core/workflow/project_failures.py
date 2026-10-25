"""Publish pre-render repair evidence without replacing a usable project."""

from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate
from sciplot_core.studio_core.project_command_scope import command_for_binding


def publish_intervention(candidate: StudioPreparationCandidate, *, baseline: dict[str, Any],
                         output: str, intent: dict[str, Any], error: str) -> None:
    """Only a new, exact run slot may receive a known pre-render outcome."""
    prefix = output + "/"
    if any(name.startswith(prefix) for name in baseline["files"]):
        # Preserve the existing managed-output rollback contract. A failed retry
        # cannot replace the status or raw archive of the previous usable run.
        return
    status_name = prefix + "one_step_status.json"
    current = candidate.capture()
    if current.get(status_name) is None:
        raise ValueError("A pre-render intervention requires its complete saved status.")
    writes = {name: value for name, value in current.items() if name.startswith(prefix) and value is not None}
    request = {"family": "workflow_intervention", "workflow_intent": intent}
    key = "workflow-intervention:" + canonical_json_sha256({"generation": baseline["generation"], "request": request})
    command = command_for_binding(candidate.store, baseline, kind="publish", key=key,
                                  writes=list(writes), request=request)
    status = candidate.resource_path(status_name)
    ProjectCommands(candidate.store).execute(command, lambda: ProjectMutation(writes, {"error": error,
        "status": "needs_rule_repair", "diagnostic": candidate.logical_path(str(status))}))
