"""Checkpoint an explicit paper selection; never mutate its original projects."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.delivery import native_snapshot
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.plot_engine.managed_delivery_contract import normalize_request as normalize_managed_delivery
from sciplot_core.source_coverage.file_snapshots import _assert_snapshot_current
from sciplot_core.source_coverage.managed_documents import verify_managed_document_sources, source_records
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_contract import normalize_paper_request, paper_stem, paper_request_schema
from sciplot_core.task_paper_delivery import assert_sealed_item, publish_paper
from sciplot_core.task_paper_sources import capture_selection, assert_selection_current
from sciplot_core.task_paper_publication import capture_publication, assert_publication_current
from sciplot_core.task_paper_status import _verify_delivery, _summary, _current_summary
from sciplot_core.task_semantic_owner import managed_task_call
from sciplot_core.task_storage import task_location


_MANAGED_SELECTION = "sciplot_task_paper_managed_selection"


def _save(root: Path, state: dict[str, Any]) -> None:
    state["state_sha256"] = canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)
    atomic_write_json(root / "paper.json", state)


def _path(path: Path) -> Path:
    value = canonical_path(path)
    return value.parent if value.name == "paper.json" else value


def _load(root: Path) -> dict[str, Any]:
    state = json.loads((root / "paper.json").read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("kind") not in {"sciplot_task_paper", _MANAGED_SELECTION}
            or state.get("version") != 1 or state.get("paper_dir") != str(root)
            or state.get("state_sha256") != canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)):
        raise TaskControlError("paper_record_changed", "Paper task location, version or checkpoint changed.")
    if state["kind"] == _MANAGED_SELECTION:
        normalize_managed_delivery(state["request"])
        return dict(state)
    request = state["request"]
    normalize_paper_request(request, stored_group=any("group_item_id" in item for item in request["items"]))
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
                              "output_policy": "New caller-selected directory; never replace existing output.",
                              "publication_policy": "Consume complete current sealed PDF/TIFF; never render/export for packaging.",
                              "group_start": "task paper start --group GROUP --out NEW_OUTPUT --paper-dir NEW_CHECKPOINT"}
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


def _seal(root: Path, state: dict[str, Any], selection: dict[str, Any], item: dict[str, Any]) -> None:
    assert_selection_current(selection)
    if not selection.get("publication"):
        raise TaskControlError("paper_publication_unsealed", "This old incomplete selection has no frozen publication; preserve it and start a new selection.")
    assert_publication_current(selection["publication"], selection)
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
    try:
        native_snapshot.copy_sealed_file(original_spec, target_spec, selection["version"]["spec_sha256"])
        portable = native_snapshot.capture_native(
            original, target, attempt / "data/imports" / item["stem"],
            original_sha256=selection["version"]["document_sha256"], selected_imports=selection["source_files"])
    except native_snapshot.SnapshotSealChanged as exc:
        raise TaskControlError("paper_selection_changed", str(exc)) from exc
    except native_snapshot.NativeSnapshotError as exc:
        raise TaskControlError("paper_native_copy_failed", str(exc)) from exc
    # Packaging consumes the existing sealed exports; it never renders.
    exports = []
    for record in selection["publication"]["exports"]:
        original_export = Path(record["path"])
        target_export = attempt / "exports" / original_export.name
        target_export.parent.mkdir(exist_ok=True)
        try:
            native_snapshot.copy_sealed_file(original_export, target_export, record["sha256"])
        except native_snapshot.SnapshotSealChanged as exc:
            raise TaskControlError("paper_publication_changed", str(exc)) from exc
        exports.append({**record, "path": str(target_export)})
    exported = {"exports": exports, "mode": "copied_current_sealed_publication"}
    copied_audit = run_document_worker("audit-spec-data", target, target_spec, "--allow-presentation-edits")
    scientific_hash = canonical_json_sha256(audit["units"], allow_nan=False)
    if canonical_json_sha256(copied_audit["units"], allow_nan=False) != scientific_hash:
        raise TaskControlError("paper_science_changed", "The copied native document changed its scientific dataset identity.")
    qa = selection["publication"]["qa"]
    assert_publication_current(selection["publication"], selection)
    assert_selection_current(selection)
    item.update(status="sealed", portable_native=portable, scientific_sha256=scientific_hash,
                prepared_source_sha256=canonical_json_sha256(source_verification["documents"][0]["prepared_source_derivation"], allow_nan=False),
                exports=exported, qa=qa, files=file_inventory(attempt))
    _save(root, state)


def _run(root: Path, state: dict[str, Any]) -> None:
    try:
        for selection in state["selections"]:
            assert_selection_current(selection)
            if selection.get("publication"):
                assert_publication_current(selection["publication"], selection)
            elif state["status"] != "complete":
                raise TaskControlError("paper_publication_unsealed", "The incomplete historical selection has no sealed publication. Start a new selection; nothing was redrawn.")
        if state["status"] == "complete":
            _verify_delivery(state)
            return
        if Path(state["request"]["out"]).exists():
            # A reply may be lost after atomic publication but before final receipt save.
            candidate = state.get("publication_candidate")
            if candidate and native_snapshot.installed_snapshot_matches(
                    Path(state["request"]["out"]), candidate["files"], pending_candidate=Path(candidate["path"])):
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
        delivery = publish_paper(state, checkpoint=lambda: _save(root, state))
        state.update(status="complete", delivery=delivery,
                     delivery_files=file_inventory(Path(state["request"]["out"])))
        state.pop("blocker", None)
        _save(root, state)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        state.update(status="blocked", blocker={"reason_code": getattr(exc, "reason_code", "paper_export_failed"), "message": str(exc)})
        _save(root, state)


def start_paper(request: object, *, paper_dir: Path, base_dir: Path | None = None,
                selection_origin: dict[str, Any] | None = None,
                group_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_paper_request(request, base_dir=base_dir, current_group=group_snapshot is not None)
    root = _path(paper_dir)
    _validate_locations(root, normalized)
    if not root.exists():
        from sciplot_core.foundation.research_destination import require_data_destination
        require_data_destination(root)
        require_data_destination(Path(normalized["out"]))
    root.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(root):
        if root.exists():
            state = _load(root)
            same_selection = (state.get("selection_origin") == selection_origin if group_snapshot is not None
                              else state["request"] == normalized)
            if state["kind"] != "sciplot_task_paper" or not same_selection:
                raise TaskControlError("paper_already_exists", "This paper task already owns a different ordered selection.")
            return _current_summary(root, state)
        else:
            if Path(normalized["out"]).exists():
                raise TaskControlError("paper_output_exists", "Choose a new paper output; existing output is preserved.")
            selections = [capture_selection(Path(item["project"]), item["figure_id"]) for item in normalized["items"]]
            identities = [(item["project"], item["figure_id"]) for item in selections]
            if len(identities) != len(set(identities)):
                raise TaskControlError("duplicate_paper_figure", "Project path aliases cannot select the same exact figure twice.")
            if group_snapshot is not None:
                _assert_snapshot_current(group_snapshot, label="paper current group selection", expected_sha256=group_snapshot["sha256"])
                for source, item in zip(selections, normalized["items"], strict=True):
                    if any(source["version"][key] != expected for key, expected in item["expected_version"].items()):
                        raise TaskControlError("paper_selection_changed", "A registered group figure changed during selection. Start again from the current group.")
                    item["expected_version"] = source["version"]
            elif any(source["version"] != item["expected_version"] for source, item in zip(selections, normalized["items"], strict=True)):
                raise TaskControlError("paper_selection_changed", "Use each selected figure's exact current version from paper capabilities.")
            _validate_source_locations(root, Path(normalized["out"]), selections)
            for selection in selections:
                selection["publication"] = capture_publication(selection)
            if group_snapshot is not None:
                for selection in selections:
                    assert_selection_current(selection)
            root.mkdir(mode=0o700)
            state = {"kind": "sciplot_task_paper", "version": 1, "paper_dir": str(root), "request": normalized,
                     "status": "pending", "selections": selections, "selection_origin": selection_origin,
                     "items": [{"stem": paper_stem(index, item), "status": "pending"}
                               for index, item in enumerate(normalized["items"], 1)]}
            _save(root, state)
            _run(root, state)
        return _summary(state)


def _managed_summary(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    complete = result.get("status") == "complete" and result.get("ready_to_use") is True
    return {**result, "paper_dir": state["paper_dir"], "title": state["request"]["title"], "out": state["request"]["out"],
            "selection_origin": state["selection_origin"], "delivery_request": state["request"],
            "next_step": {"action": "review_selected_exports_and_deliver" if complete else "inspect_and_retry_exact_selection",
                          "paper_dir": state["paper_dir"]},
            "model_calls_by_sciplot": 0, "journal_acceptance_evaluated": False}


def _read_managed(state: dict[str, Any], *, paper_dir: Path | None = None) -> dict[str, Any]:
    from sciplot_core.task_semantic_owner import inspect_managed_delivery

    return inspect_managed_delivery(state["request"], paper_dir=paper_dir)


def _inspect(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state["kind"] == _MANAGED_SELECTION:
        return _managed_summary(state, _read_managed(state))
    return _current_summary(root, state)


def _deliver_managed(state: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.task_semantic_owner import deliver_managed

    return _managed_summary(state, deliver_managed(state["request"]))


def start_managed_group_paper(root: Path, *, out: Path, title: str, items: list[dict[str, Any]],
                             selection_origin: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.foundation.research_destination import require_data_destination

    request = normalize_managed_delivery({"out": str(out), "title": title, "mode": "native_snapshot", "items": items,
        "idempotency_key": "paper-group:" + canonical_json_sha256([str(root), selection_origin, items], allow_nan=False)})
    require_data_destination(root)
    require_data_destination(out)
    # Refuse overlap before allocating even the paper lease in a selected namespace.
    state = {"kind": _MANAGED_SELECTION, "version": 1, "paper_dir": str(root),
             "request": request, "selection_origin": selection_origin}
    _read_managed(state, paper_dir=root)
    root.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(root):
        if root.exists():
            saved = _load(root)
            if (saved["kind"], saved["request"], saved.get("selection_origin")) != (_MANAGED_SELECTION, request, selection_origin):
                raise TaskControlError("paper_already_exists", "This paper checkpoint owns another frozen selection.")
            return _inspect(root, saved)
        if out.exists():
            raise TaskControlError("paper_output_exists", "Choose a new paper output; existing output is preserved.")
        root.mkdir(mode=0o700)
        _save(root, state)
        return _deliver_managed(state)


@managed_task_call
def inspect_paper(paper: Path) -> dict[str, Any]:
    root = _path(paper)
    with external_project_session(root):
        return _inspect(root, _load(root))


@managed_task_call
def resume_paper(paper: Path) -> dict[str, Any]:
    root = _path(paper)
    with external_project_session(root):
        state = _load(root)
        if state["kind"] == _MANAGED_SELECTION:
            return _deliver_managed(state)
        if state["status"] == "complete":
            return _current_summary(root, state)
        _validate_locations(root, state["request"])
        _validate_source_locations(root, Path(state["request"]["out"]), state["selections"])
        _run(root, state)
        return _summary(state)
