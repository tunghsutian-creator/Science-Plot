"""Managed comparison owns alternatives and the selection, never the original plot."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler, compiler_identity
from sciplot_core.project_lifecycle.managed_comparison import finish_selection, observe_baseline, prepare_preview
from sciplot_core.task_comparison_artifacts import read_review, seal_review
from sciplot_core.task_comparison_storage import save_comparison
from sciplot_core.task_contract import TaskControlError

if TYPE_CHECKING:
    from sciplot_core.plot_engine.service import PlotService


@contextmanager
def _compiler() -> Iterator[ManagedVeuszCompiler]:
    compiler = ManagedVeuszCompiler()
    try:
        yield compiler
    finally:
        compiler.close()


@contextmanager
def _owner() -> Iterator["PlotService"]:
    # A local composed application, not a task-to-CLI or socket round trip.
    from sciplot_core.plot_engine.service import PlotService

    service = PlotService(read_only_legacy=True)
    try:
        yield service
    finally:
        service.close()


def _patch(request: dict[str, Any], item: dict[str, Any], key: str) -> dict[str, Any]:
    return {**{field: request[field] for field in ("plot_id", "base_revision")},
            "idempotency_key": key, "intent_class": "presentation", "changes": item["changes"]}


def _chosen_item(request: dict[str, Any], identifier: str) -> dict[str, Any] | None:
    if identifier == "baseline":
        return None
    return next(item for item in request["candidates"] if item["id"] == identifier)


def generate(root: Path, state: dict[str, Any]) -> None:
    request = state["request"]
    plot = Path(request["plot"])
    state.update(status="generating")
    state.pop("blocker", None)
    runtime = compiler_identity()
    if state.setdefault("compiler_identity", runtime) != runtime:
        raise TaskControlError("comparison_compiler_changed", "The renderer changed; start a new comparison for like-for-like previews.")
    save_comparison(root, state)
    with _owner() as owner, _compiler() as compiler:
        if observe_baseline(owner, plot, location=root) != state["baseline"]:
            raise TaskControlError("comparison_baseline_stale", "The saved baseline changed; start a new comparison.")
        prepared = state.setdefault("prepared", {})
        errors = state.setdefault("candidate_errors", {})
        for item in [None, *request["candidates"]]:
            identifier = "baseline" if item is None else item["id"]
            if identifier in prepared:
                continue
            patch = _patch(request, item, "detached:" + identifier) if item is not None else None
            folder = Path(mkdtemp(prefix="candidate-", dir=root))
            try:
                evidence = prepare_preview(owner, compiler, plot, state["baseline"], folder, patch)
                if evidence["compiler_identity"] != runtime:
                    raise TaskControlError("comparison_compiler_changed", "The renderer changed while generating comparison previews.")
                prepared[identifier] = seal_review(folder, identifier, state["baseline"], evidence)
                errors.pop(identifier, None)
            except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
                errors[identifier] = {"reason_code": getattr(exc, "reason_code", "comparison_preview_failed"),
                                      "message": str(exc)}
            save_comparison(root, state)
    state["status"] = "needs_selection" if "baseline" in prepared and len(prepared) > 1 else "blocked"
    save_comparison(root, state)


def apply_selected(root: Path, state: dict[str, Any]) -> None:
    request, selection = state["request"], state["selection"]
    identifier = selection["candidate_id"]
    item = _chosen_item(request, identifier)
    key = "comparison:" + canonical_json_sha256([str(root), selection["expected_comparison_id"], identifier])
    patch = _patch(request, item, key) if item is not None else None

    def verify_choice() -> dict[str, Any]:
        proof = read_review(root, state["baseline"], identifier, state["prepared"][identifier])
        if (proof["operation_id"] != state["selected_operation_id"]
                or proof["compiler_identity"] != state["compiler_identity"]):
            raise TaskControlError("comparison_selection_changed", "The attached preview is not the exact selected candidate.")
        return proof

    state.update(status="applying")
    state.pop("blocker", None)
    save_comparison(root, state)
    with _owner() as owner:
        result = finish_selection(owner, Path(request["plot"]), state["baseline"], patch=patch,
                                  export=request["export"], verify_choice=verify_choice)
    state["selection_outcome"] = result
    save_comparison(root, state)
    if result.get("status") != "complete":
        error = result.get("error") or {}
        raise TaskControlError(error.get("reason_code", "comparison_apply_incomplete"),
                               error.get("message", "The selected patch has not finished; resume this comparison."))
    state["status"] = "complete"
    save_comparison(root, state)


def admit_baseline(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    with _owner() as owner:
        baseline = observe_baseline(owner, Path(request["plot"]), location=root)
    if (baseline["plot_id"], baseline["revision"]) != (request["plot_id"], request["base_revision"]):
        raise TaskControlError("comparison_baseline_stale", "Use the plot ID and revision returned by plot describe.")
    return baseline


def snapshot(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    request = state["request"]
    result: dict[str, Any] = {
        "kind": "sciplot_task_comparison_result", "version": 2, "comparison_dir": str(root),
        "title": request["title"], "plot": request["plot"], "plot_id": request["plot_id"],
        "document_authority": "managed_plot", "project": request["plot"], "figure_id": request["plot_id"],
        "status": state["status"], "updated_at": state["updated_at"],
        "queried_at": datetime.now(timezone.utc).isoformat(), "baseline_current": False,
        "candidates": [], "previews": [], "ready_to_use": None, "readiness_evaluated": False,
        "model_calls_by_sciplot": 0, "external_model_tokens": None,
    }
    for key in ("selection", "selection_outcome", "blocker"):
        if key in state:
            result[key] = state[key]
    try:
        with _owner() as owner:
            current = observe_baseline(owner, Path(request["plot"]), location=root)
        result.update(baseline_current=current == state["baseline"], current_figure=current)
    except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
        result["current_error"] = str(exc)
    for item in [{"id": "baseline", "label": "比较时的原图"}, *request["candidates"]]:
        entry = {key: item[key] for key in ("id", "label", "rationale") if key in item}
        identifier = entry["id"]
        entry.update(status="pending", selectable=False)
        try:
            if identifier in state.get("prepared", {}):
                review = read_review(root, state["baseline"], identifier, state["prepared"][identifier])
                changes = review["changes"]
                entry.update(status="ready" if changes or identifier == "baseline" else "unchanged",
                             operation_id=review["operation_id"], preview=review["preview"], review_path=review["review_path"],
                             change_count=len(changes), changes=changes[:12], changes_truncated=len(changes) > 12,
                             scientific_audit_status=review["scientific_audit"]["status"])
                result["previews"].append({"candidate_id": identifier, "figure_id": request["plot_id"],
                                           "scope": "baseline" if identifier == "baseline" else "candidate",
                                           "preview": entry["preview"]})
            elif identifier in state.get("candidate_errors", {}):
                error = state["candidate_errors"][identifier]
                entry.update(status="blocked", error=error["message"], reason_code=error["reason_code"])
        except (ValueError, OSError, RuntimeError) as exc:
            entry.update(status="blocked", error=str(exc))
        if identifier == "baseline":
            result["baseline"] = entry
        else:
            result["candidates"].append(entry)
    baseline, candidates = result["baseline"], result["candidates"]
    result["comparison_id"] = canonical_json_sha256({
        "request": request, "baseline": state["baseline"], "reviewed": [
            {key: entry[key] for key in ("id", "operation_id", "error") if key in entry} for entry in [baseline, *candidates]],
    })
    can_select = result["baseline_current"] and baseline["status"] == "ready" and "selection" not in state
    result["can_select"] = can_select
    for entry in [baseline, *candidates]:
        entry["selectable"] = can_select and entry["status"] in {"ready", "unchanged"}
    if "selection" not in state and not result["baseline_current"]:
        result["status"] = "blocked"
        result["blocker"] = {"reason_code": "comparison_baseline_unavailable",
                             "message": result.get("current_error", "The saved baseline changed; start a new comparison.")}
    return result
