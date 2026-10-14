"""Checkpoint an explicit paper selection; never mutate its original projects."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.source_coverage.managed_documents import verify_managed_document_sources, source_records
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_contract import normalize_paper_request, paper_stem, paper_request_schema
from sciplot_core.task_paper_delivery import assert_sealed_item, publish_paper
from sciplot_core.task_paper_sources import capture_selection, assert_selection_current
from sciplot_core.task_storage import task_location
from sciplot_core.veusz_runtime import veusz_worker_environment


def _save(root: Path, state: dict[str, Any]) -> None:
    state["state_sha256"] = canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)
    atomic_write_json(root / "paper.json", state)


def _path(path: Path) -> Path:
    value = canonical_path(path)
    return value.parent if value.name == "paper.json" else value


def _load(root: Path) -> dict[str, Any]:
    state = json.loads((root / "paper.json").read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("kind") != "sciplot_task_paper"
            or state.get("version") != 1 or state.get("paper_dir") != str(root)
            or state.get("state_sha256") != canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)):
        raise TaskControlError("paper_record_changed", "Paper task location, version or checkpoint changed.")
    normalize_paper_request(state["request"])
    for item in state["items"]:
        if item.get("attempt"):
            attempt = canonical_path(Path(item["attempt"]))
            if not attempt.is_relative_to(root / "attempts"):
                raise TaskControlError("paper_record_changed", "The selected staging path escaped its task.")
    return dict(state)


def _validate_locations(root: Path, request: dict[str, Any]) -> None:
    out = Path(request["out"])
    if root == out or root.is_relative_to(out) or out.is_relative_to(root):
        raise TaskControlError("paper_path_overlap", "Keep the paper task receipt outside its visible output.")
    for item in request["items"]:
        export_request = {"version": 1, "action": "export", "project": item["project"]}
        task_location(export_request, root)
        task_location(export_request, out)  # Reuse original input/project/delivery overlap policy.


def _validate_source_locations(root: Path, out: Path, selections: list[dict[str, Any]]) -> None:
    for selection in selections:
        for value in {*selection["source_files"], *selection["source_memberships"]}:
            source = Path(value)
            if any(path == source or path.is_relative_to(source) or source.is_relative_to(path) for path in (root, out)):
                raise TaskControlError("paper_source_overlap", "Paper output and checkpoint must not overlap selected scientific or native imported sources.")


def paper_capabilities(*, project: Path | None = None, figure_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": "sciplot_paper_capabilities", "version": 1,
                              "request_schema": paper_request_schema(), "actions": ["start", "inspect", "resume"],
                              "order": "items array order", "formats": ["pdf", "tiff_300", "editable_vsz"],
                              "selection": "Exact canonical project and registered figure_id; saved native state is preserved.",
                              "output_policy": "New caller-selected directory; never replace existing output."}
    if project is not None:
        if figure_id is None:
            raise TaskControlError("paper_figure_required", "Specify an exact registered figure_id to read its version.")
        selected = capture_selection(project, figure_id)
        result["selection"] = {"project": selected["project"], "figure_id": figure_id,
                               "expected_version": selected["version"], "source_files": selected["source_files"],
                               "document_authority": selected["document_authority"]}
    elif figure_id is not None:
        raise TaskControlError("paper_project_required", "A figure identity requires its project.")
    return result


def _portable(source: Path, target: Path, imports: Path) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, "-m", "sciplot_core.task_paper_native", "save", str(source), str(target),
                                "--imports", str(imports)], env=veusz_worker_environment(), capture_output=True,
                               text=True, timeout=120, check=False)
    if completed.returncode:
        raise TaskControlError("paper_native_copy_failed", completed.stderr[-2000:])
    payload = json.loads(completed.stdout)
    if payload.get("status") != "passed":
        raise TaskControlError("paper_native_copy_failed", "Native portable Save did not pass.")
    return dict(payload)


def _seal(root: Path, state: dict[str, Any], selection: dict[str, Any], item: dict[str, Any]) -> None:
    assert_selection_current(selection)
    attempt = root / "attempts" / item["stem"] / uuid4().hex
    item.update(status="exporting", attempt=str(attempt))
    _save(root, state)  # An interrupted attempt is never silently reused or overwritten.
    (attempt / "project").mkdir(parents=True)
    original = Path(selection["document"])
    original_spec = Path(selection["spec"])
    audit = run_document_worker("audit-spec-data", original, original_spec, "--allow-presentation-edits")
    spec = json.loads(original_spec.read_text(encoding="utf-8"))
    source_verification = verify_managed_document_sources(
        {"veusz_documents": [str(original)], "data_snapshot_sources": [str(p) for p in source_records(spec)]},
        native_audits={str(original): audit})
    target = attempt / "project" / f"{item['stem']}.vsz"
    target_spec = target.with_suffix(".spec.json")
    target_spec.write_bytes(original_spec.read_bytes())
    portable = _portable(original, target, attempt / "data/imports" / item["stem"])
    # Reopen and export the copied document in its new location, using native export.
    exported = export_studio_document(target, formats=["pdf", "tiff_300"], output_dir=attempt / "exports")
    copied_audit = run_document_worker("audit-spec-data", target, target_spec, "--allow-presentation-edits")
    scientific_hash = canonical_json_sha256(audit["units"], allow_nan=False)
    if canonical_json_sha256(copied_audit["units"], allow_nan=False) != scientific_hash:
        raise TaskControlError("paper_science_changed", "The copied native document changed its scientific dataset identity.")
    from sciplot_core.qa.run import run_qa

    qa = run_qa(attempt / "exports", veusz_documents=[target])
    if qa["status"] != "passed" or qa["pdf_count"] != 1 or qa["tiff_count"] != 1:
        raise TaskControlError("paper_export_qa_failed", "Selected single-figure PDF/TIFF QA failed.")
    assert_selection_current(selection)
    item.update(status="sealed", portable_native=portable, scientific_sha256=scientific_hash,
                prepared_source_sha256=canonical_json_sha256(source_verification["documents"][0]["prepared_source_derivation"], allow_nan=False),
                exports=exported, qa=qa, files=file_inventory(attempt))
    _save(root, state)


def _run(root: Path, state: dict[str, Any]) -> None:
    try:
        for selection in state["selections"]:
            assert_selection_current(selection)
        if state["status"] == "complete":
            _verify_delivery(state)
            return
        if Path(state["request"]["out"]).exists():
            # A reply may be lost after atomic publication but before final receipt save.
            candidate = state.get("publication_candidate")
            if candidate and file_inventory(Path(state["request"]["out"])) == candidate["files"]:
                if Path(candidate["path"]).exists():
                    raise TaskControlError("paper_output_exists", "Both a private candidate and visible output exist; no files were replaced.")
                state.update(status="complete", delivery=candidate["delivery"], delivery_files=candidate["files"])
                state.pop("blocker", None)
                _save(root, state)
                return
            raise TaskControlError("paper_output_exists", "The requested paper output already exists; no files were replaced.")
        for selection, item in zip(state["selections"], state["items"], strict=True):
            if item["status"] == "sealed":
                assert_sealed_item(item)
            else:
                _seal(root, state, selection, item)
        state["status"] = "publishing"
        _save(root, state)
        delivery = publish_paper(root, state, checkpoint=lambda: _save(root, state))
        state.update(status="complete", delivery=delivery,
                     delivery_files=file_inventory(Path(state["request"]["out"])))
        state.pop("blocker", None)
        _save(root, state)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        state.update(status="blocked", blocker={"reason_code": getattr(exc, "reason_code", "paper_export_failed"), "message": str(exc)})
        _save(root, state)


def _verify_delivery(state: dict[str, Any]) -> None:
    if file_inventory(Path(state["request"]["out"])) != state["delivery_files"]:
        raise TaskControlError("paper_delivery_changed", "The published paper package changed; no file was replaced.")


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    return {"kind": state["kind"], "version": 1, "paper_dir": state["paper_dir"], "status": state["status"],
            "title": state["request"]["title"], "out": state["request"]["out"],
            "items": [{"stem": item["stem"], "status": item["status"], "project": source["project"],
                       "figure_id": source["figure_id"], "version": source["version"],
                       **({"scientific_sha256": item["scientific_sha256"]} if item["status"] == "sealed" else {})}
                      for source, item in zip(state["selections"], state["items"], strict=True)],
            **({"blocker": state["blocker"]} if state.get("blocker") else {}),
            **({"result": state["delivery"]} if state.get("delivery") else {}),
            "next_step": {"action": "review_selected_exports_and_deliver" if state["status"] == "complete" else "inspect_and_retry_exact_selection",
                          "paper_dir": state["paper_dir"]},
            "model_calls_by_sciplot": 0, "journal_acceptance_evaluated": False}


def start_paper(request: object, *, paper_dir: Path, base_dir: Path | None = None) -> dict[str, Any]:
    normalized = normalize_paper_request(request, base_dir=base_dir)
    root = _path(paper_dir)
    _validate_locations(root, normalized)
    root.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(root):
        if root.exists():
            state = _load(root)
            if state["request"] != normalized:
                raise TaskControlError("paper_already_exists", "This paper task already owns a different ordered selection.")
            return _current_summary(root, state)
        else:
            if Path(normalized["out"]).exists():
                raise TaskControlError("paper_output_exists", "Choose a new paper output; existing output is preserved.")
            selections = [capture_selection(Path(item["project"]), item["figure_id"]) for item in normalized["items"]]
            identities = [(item["project"], item["figure_id"]) for item in selections]
            if len(identities) != len(set(identities)):
                raise TaskControlError("duplicate_paper_figure", "Project path aliases cannot select the same exact figure twice.")
            if any(source["version"] != item["expected_version"] for source, item in zip(selections, normalized["items"], strict=True)):
                raise TaskControlError("paper_selection_changed", "Use each selected figure's exact current version from paper capabilities.")
            _validate_source_locations(root, Path(normalized["out"]), selections)
            root.mkdir(mode=0o700)
            state = {"kind": "sciplot_task_paper", "version": 1, "paper_dir": str(root), "request": normalized,
                     "status": "pending", "selections": selections,
                     "items": [{"stem": paper_stem(index, item["label"]), "status": "pending"}
                               for index, item in enumerate(normalized["items"], 1)]}
            _save(root, state)
            _run(root, state)
        return _summary(state)


def _current_summary(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Project currentness under the caller's existing lease without writes."""
    current = []
    for selection in state["selections"]:
        try:
            assert_selection_current(selection)
            current.append({"project": selection["project"], "figure_id": selection["figure_id"], "current": True})
        except (OSError, ValueError) as exc:
            current.append({"project": selection["project"], "figure_id": selection["figure_id"], "current": False, "message": str(exc)})
    summary = _summary(state)
    summary["recorded_status"] = state["status"]
    summary["selection_scope"] = "frozen_selected_versions"
    summary["result_scope"] = "historical_frozen_delivery"
    summary["current_selections"] = current
    summary["source_versions_current"] = all(item["current"] for item in current)
    summary["delivery_current"] = None
    if state.get("delivery_files"):
        try:
            _verify_delivery(state)
            summary["delivery_current"] = True
        except (OSError, ValueError):
            summary["delivery_current"] = False
    summary["ready_to_use"] = bool(state["status"] == "complete"
                                   and summary["source_versions_current"]
                                   and summary["delivery_current"] is True)
    summary["readiness_evaluated"] = True
    summary["readiness_scope"] = "Frozen package and selected source byte identities; no fresh native audit."
    if summary["delivery_current"] is False:
        summary.update(status="blocked", blocker={
            "reason_code": "paper_delivery_changed",
            "message": "The published paper package differs from its frozen inventory. Preserve the changed package and choose a new output for a new selection.",
        }, repair={"action": "preserve_changed_package_and_start_new_selection",
                   "output": state["request"]["out"], "new_output_required": True,
                   "automatic_overwrite": False},
            next_step={"action": "preserve_changed_package_and_start_new_selection", "paper_dir": str(root)})
    elif not summary["source_versions_current"]:
        summary.update(status="blocked", blocker={
            "reason_code": "paper_selection_changed",
            "message": "The package retains the frozen selected versions; its original projects or sources have changed. Review those changes and start a new current selection.",
        }, repair={"action": "review_changed_sources_and_start_new_selection",
                   "new_output_required": True, "automatic_overwrite": False},
            next_step={"action": "review_changed_sources_and_start_new_selection", "paper_dir": str(root)})
    elif state["status"] == "complete" and summary["delivery_current"] is not True:
        summary.update(status="blocked", blocker={
            "reason_code": "paper_delivery_unverified",
            "message": "The completed receipt has no verifiable frozen package inventory. Preserve it and inspect its evidence.",
        }, repair={"action": "inspect_paper_delivery_evidence", "automatic_overwrite": False},
            next_step={"action": "inspect_paper_delivery_evidence", "paper_dir": str(root)})
    return summary


def inspect_paper(paper: Path) -> dict[str, Any]:
    root = _path(paper)
    with external_project_session(root):
        return _current_summary(root, _load(root))


def resume_paper(paper: Path) -> dict[str, Any]:
    root = _path(paper)
    with external_project_session(root):
        state = _load(root)
        if state["status"] == "complete":
            return _current_summary(root, state)
        _validate_locations(root, state["request"])
        _validate_source_locations(root, Path(state["request"]["out"]), state["selections"])
        _run(root, state)
        return _summary(state)
