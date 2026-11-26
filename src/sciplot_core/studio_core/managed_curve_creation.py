"""Use the existing Managed raw-curve task for verified project creation."""
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.output_contract import UserOutputLayout
from sciplot_core.plan_admission import expected_plan_request
from sciplot_core.semantic_sources.scientific_source_models import ResolvedScientificSource
from sciplot_core.task_semantic_creation import admit_raw_curve, current_result, run_creation
from sciplot_core.task_storage import load_task, save_task


def create_curve_project(source: Path, plan: dict[str, Any], layout: UserOutputLayout, *,
                         scientific_source: ResolvedScientificSource | None,
                         require_new: Callable[[UserOutputLayout], None]) -> dict[str, Any] | None:
    """Run the same source/plan/engine/delivery journal as ordinary Managed tasks."""
    workspace = layout.workspace_root
    journal = workspace / "creation"
    old = _source_request(source, plan, layout)
    expected = plan["preview_identity"]
    draft = {"kind": "sciplot_task", "version": 1, "task_dir": str(journal), "request": old,
             "source_sha256": expected["source_tree_sha256"],
             "project_creation_plan_sha256": canonical_json_sha256(plan, allow_nan=False),
             "phase": "planning", "status": "running", "created_at": datetime.now(timezone.utc).isoformat()}
    if not (journal / "task.json").is_file():
        if workspace.exists() or not admit_raw_curve(draft, plan, scientific_source):
            return None
        draft["project_creation_figure"] = plan["resolved_figure_plan"]["tasks"][0]
        require_new(layout)
        workspace.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(workspace):
        if not (journal / "task.json").is_file():
            require_new(layout)
            with TemporaryDirectory(prefix=".curve-creation-", dir=workspace.parent) as directory:
                candidate = Path(directory) / "workspace"
                # save_task seals the final exact task_dir value in this staged record.
                (candidate / journal.name).mkdir(parents=True)
                save_task(candidate / journal.name, draft)
                candidate.rename(workspace)
        with external_project_session(journal):
            return _continue(journal, load_task(journal), old, plan)


def resume_curve_project(source: Path, expected: dict[str, Any], layout: UserOutputLayout) -> dict[str, Any] | None:
    """Recover a verified creation without resolving a new scientific observation."""
    workspace = layout.workspace_root
    journal = workspace / "creation"
    if not (journal / "task.json").is_file():
        return None
    with external_project_session(workspace), external_project_session(journal):
        state = load_task(journal)
        if "project_creation_plan_sha256" not in state:
            return None  # Existing receipts still use full expected-plan validation.
        expected_plan_request(source, expected, rule_id=expected.get("rule_id"), template=expected["template"])
        return _continue(journal, state, _source_request(source, expected, layout), expected)


def _source_request(source: Path, plan: dict[str, Any], layout: UserOutputLayout) -> dict[str, Any]:
    return {"version": 1, "action": "create", "source": str(source), "out": str(layout.delivery_root),
            "rule_id": plan["rule_id"], "template": plan["template"]}


def _continue(journal: Path, state: dict[str, Any], old: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    frozen_hash = state.get("project_creation_plan_sha256")
    same_plan = (state.get("project_creation_plan") == plan["preview_identity"] if frozen_hash is None
                 else frozen_hash == canonical_json_sha256(plan, allow_nan=False))
    if not same_plan or state["initial_request"] != old:
        raise ValueError("This output belongs to a different source-bound Managed creation.")
    if state["status"] != "complete" or state.get("delivery_result", {}).get("status") != "complete":
        run_creation(journal, state)
    return _receipt(journal, state)


def _receipt(journal: Path, state: dict[str, Any]) -> dict[str, Any]:
    result = current_result(state)
    ready = result.get("ready_to_use") is True
    task = state["project_creation_figure"]
    plot = state.get("project")
    delivery = (state.get("delivery_result") or {}).get("delivery") or {}
    files = (result.get("next_step") or {}).get("files", [])
    artifacts = files[0] if files else {}
    exported = [{"format": name, "path": artifacts[name]} for name in ("pdf", "tiff_300") if name in artifacts]
    document = artifacts.get("editable")
    return {"kind": "sciplot_project_creation_result", "version": 1,
            "status": "created" if ready else "blocked", "project_dir": plot, "document": document,
            "request": str(journal / "task.json"), "primary_figure_id": task["figure_id"],
            "figures": ([{"figure_id": task["figure_id"], "title": task["title"], "plot": plot,
                          "document": document, "exports": exported}] if plot is not None else []),
            "document_authority": "managed_plot", "analysis_metrics": state.get("analysis_metrics", []),
            "next_step": {**result["next_step"], **({"open_cli_argv": ["sciplot", "plot", "open", plot, "--json"]}
                                                       if plot is not None else {})},
            "studio_run": {"ready_to_use": ready, "state": "ready" if ready else state["status"],
                           "manifest": str(Path(state["request"]["out"]) / "index.json") if ready else None,
                           "delivery_package": {"path": state["request"]["out"], "complete": ready},
                           "failure_stage": None if ready else state["phase"],
                           "failure_reason": None if ready else (state.get("blocker") or result["next_step"]).get("message"),
                           "managed_delivery": delivery}}
