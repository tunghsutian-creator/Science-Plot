"""Persist and recover only the files chosen for a semantic first figure."""
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.task_output_choice import creation_output
from sciplot_core.task_semantic_next_step import selected_repair
from sciplot_core.task_semantic_owner import handoff_managed
from sciplot_core.task_storage import save_task

if TYPE_CHECKING:
    from sciplot_core.project_lifecycle.figure_handoff import FigureInstall

IDENTITY_FIELDS = ("plot_id", "revision", "scientific_hash", "presentation_hash")


def _selection(state: dict[str, Any]) -> dict[str, Any]:
    out = resolve_user_output_layout(state["request"]["sources"][0], requested_delivery_root=creation_output(state))
    return {"output_dir": str(out.delivery_root), "formats": state["request"]["formats"],
            **{key: state["result"][key] for key in ("plot_id", "revision")}}


def _check_token(state: dict[str, Any], receipt: "FigureInstall") -> None:
    if any(receipt["revision_token"][key] != state["result"][key] for key in IDENTITY_FIELDS):
        raise EngineError("figure_handoff_revision_conflict", "The selected figure no longer matches the task's saved result.")


def _inspect_install(state: dict[str, Any]) -> dict[str, Any]:
    receipt = state["figure_install"]
    _check_token(state, receipt)
    return handoff_managed(Path(state["project"]), state["delivery_request"], installed=receipt)


def finish_selected(root: Path, state: dict[str, Any]) -> None:
    if "delivery_request" not in state:
        state["delivery_request"] = _selection(state)
    state.update(status="running", phase="delivering")
    state.pop("blocker", None)
    save_task(root, state)
    request = state["delivery_request"]

    def freeze(receipt: "FigureInstall") -> None:
        _check_token(state, receipt)
        state["figure_install"] = receipt
        save_task(root, state)

    out = Path(request["output_dir"])
    # A lost response after install is not a request to copy again. A frozen
    # attempt without an installed directory can still use its original target.
    if "figure_install" in state and (out.exists() or out.is_symlink()):
        delivery = _inspect_install(state)
    else:
        delivery = handoff_managed(Path(state["project"]), request, before_install=freeze)
    state.update(status="complete", phase="finished", delivery_result=delivery)
    save_task(root, state)


def current_selected_result(state: dict[str, Any], summary: dict[str, Any], *,
                            assert_sources_current: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    try:
        assert_sources_current(state)
        delivery = _inspect_install(state)
    except (ValueError, OSError, RuntimeError) as exc:
        code = getattr(exc, "reason_code", "figure_handoff_check_failed")
        summary.pop("delivery_result", None)  # A historical successful copy is not today's deliverable.
        summary.update(status="blocked", ready_to_use=False, readiness_evaluated=True, figure_handoff_current=False,
                       blocker={"reason_code": code, "message": str(exc)}, next_step=selected_repair(state, code))
        return summary
    files = {entry["format"]: entry["path"] for entry in delivery["exports"]}
    identity = {key: state["result"][key] for key in IDENTITY_FIELDS}
    summary.update(ready_to_use=True, readiness_evaluated=True, figure_handoff_current=True,
                   current_project={"status": "current", "plot_type": "ManagedPlot", "plot": state["project"], **identity})
    summary["next_step"] = {"action": "review_exports_and_deliver", "task": state["task_dir"],
                            "files": [files], "delivery": delivery["output_dir"], "plot": state["project"],
                            **({"images": [files["tiff_300"]]} if "tiff_300" in files else {}),
                            "message": "Review the selected figure files. Open the saved Managed plot to continue editing."}
    return summary
