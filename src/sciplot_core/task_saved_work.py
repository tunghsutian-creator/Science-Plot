"""Bounded discovery and explicit continuation of existing saved authorities.

No index, relocation rewrite, project creation, or task replay is performed here.
"""

from collections import deque
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers.delivery_binding import delivery_binding_from_content
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.policy import DELIVERY_LAUNCHER
from sciplot_core.studio_core.project_query_evidence import _tree_hash
from sciplot_core.studio_core.project_query_paths import bound_delivery_project, canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_next_step import task_next_step
from sciplot_core.task_storage import load_task
from sciplot_core.task_saved_work_evidence import (
    document_evidence, managed_evidence, project_evidence, record_path, source_relation,
)


MAX_SCAN_ENTRIES = 2000
MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_SCAN_DEPTH = 4
_PRUNED = {".git", ".venv", "node_modules"}


def _roots(source: Path, search_roots: list[Path] | None, tasks_root: Path | None) -> list[Path]:
    if search_roots is None:
        layout = resolve_user_output_layout(source)
        values = [layout.workspace_root, layout.delivery_root,
                  layout.workspace_root.parent / "tasks",
                  source.parent / ".sciplot_documents"]
    else:
        if not search_roots or len(search_roots) > 20:
            raise TaskControlError("invalid_search_roots", "Choose 1–20 explicit local search roots.")
        values = list(search_roots)
    if tasks_root is not None:
        values.append(tasks_root)
    roots = list(dict.fromkeys(canonical_path(Path(value)) for value in values))
    for root in roots:
        if root.exists() and not root.is_dir():
            raise TaskControlError("invalid_search_root", "Search roots must be directories.")
        if root == Path(root.anchor) or root == Path.home().resolve():
            raise TaskControlError("search_scope_too_broad", "Select project or data folders; filesystem and home roots are too broad.")
    return roots


def _small_file(path: Path) -> Path:
    path = canonical_path(path)
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("Saved identity record exceeds the bounded read budget.")
    return path


def find_saved_work(source: Path, *, search_roots: list[Path] | None = None,
                    tasks_root: Path | None = None, limit: int = 20) -> dict[str, Any]:
    """Read only known saved entries within explicit, budgeted local scopes."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise TaskControlError("invalid_find_limit", "limit must be an integer from 1 to 100.")
    source = canonical_path(source)
    roots = _roots(source, search_roots, tasks_root)
    source_sha, source_error = None, None
    try:
        source_sha = _tree_hash(source)
    except (OSError, ValueError) as exc:
        source_error = str(exc)[:500]
    issues: list[dict[str, str]] = []
    issues_count = 0

    def issue(path: Path, exc: Exception) -> None:
        nonlocal issues_count
        issues_count += 1
        if len(issues) < 10:
            issues.append({"path": str(path), "reason_code": getattr(exc, "reason_code", "unreadable_saved_work"),
                           "message": str(exc)[:500]})

    queue = deque((root, 0) for root in roots if root.is_dir())
    visited: set[Path] = set()
    projects: set[Path] = set()
    documents: set[Path] = set()
    deliveries: set[Path] = set()
    receipts: list[dict[str, Any]] = []
    linked: dict[Path, dict[str, Any]] = {}
    scanned, truncated = 0, False
    while queue:
        directory, depth = queue.popleft()
        if directory in visited:
            continue
        visited.add(directory)
        try:
            entries = sorted(directory.iterdir())
        except OSError as exc:
            issue(directory, exc)
            continue
        authority_directory = any((directory / name).is_file() for name in ("plot_request.json", "head.json", "task.json"))
        authority_directory = authority_directory or ((directory / DELIVERY_LAUNCHER).is_file()
                                                      and (directory / "project").is_dir())
        for entry in entries:
            if scanned >= MAX_SCAN_ENTRIES:
                truncated = True
                queue.clear()
                break
            scanned += 1
            try:
                if entry.is_symlink():
                    raise ValueError("Saved-work discovery does not follow symlinks.")
                if entry.is_dir():
                    if authority_directory or entry.name in _PRUNED:
                        continue
                    if depth < MAX_SCAN_DEPTH:
                        queue.append((entry, depth + 1))
                    else:
                        truncated = True
                    continue
                if entry.name == "plot_request.json":
                    _small_file(entry)
                    projects.add(directory)
                elif entry.name == "head.json":
                    _small_file(entry)
                    documents.add(directory)
                elif entry.name == DELIVERY_LAUNCHER and (directory / "project").is_dir():
                    _small_file(entry)
                    deliveries.add(directory)
                elif entry.name == "task.json":
                    _small_file(entry)
                    state = load_task(directory)
                    request = state["request"]
                    if request["action"] != "create":
                        continue
                    recorded = record_path(request["source"])
                    relation = source_relation(recorded, state.get("source_sha256"), source, source_sha)
                    if relation is None:
                        continue
                    project = record_path(state["project"]) if state.get("project") is not None else None
                    summary = {"task_dir": str(directory), "status": state["status"], "phase": state["phase"],
                               "source_relation": relation, "recorded_source": str(recorded),
                               "recorded_source_sha256": state.get("source_sha256"),
                               "project": str(project) if project else None,
                               "next_step": task_next_step(state),
                               "resume_available": relation == "recorded_path" and source_sha is not None
                               and source_sha == state.get("source_sha256")}
                    receipts.append(summary)
                    if project is not None:
                        projects.add(project)
                        linked[project] = summary
            except (OSError, ValueError, TypeError, KeyError) as exc:
                issue(entry, exc)
    matches: dict[str, dict[str, Any]] = {}
    for project in sorted(projects):
        try:
            if not project.exists():
                continue  # The receipt remains visible as historical evidence.
            _small_file(project / "plot_request.json")
            receipt = linked.get(project) or {}
            match = project_evidence(project, source, source_sha,
                receipt_sha256=receipt.get("recorded_source_sha256"),
                receipt_source=Path(receipt["recorded_source"]) if receipt else None)
            if match:
                match["tasks"] = [item for item in receipts if item["project"] == str(project)]
                unfinished = [item for item in match["tasks"] if item["status"] not in {"complete", "cancelled"}]
                if unfinished and match["continuation_available"]:
                    match.update(state="unfinished_task", continuation_available=False,
                                 next_step={"action": "task.inspect", "arguments": {"task": unfinished[0]["task_dir"]},
                                            "message": "Inspect the existing unfinished task and follow its bounded review or recovery before a new edit."})
                matches[match["target"]] = match
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            issue(project, exc)
    for document in sorted(documents):
        try:
            match = managed_evidence(document, source, source_sha)
            if match:
                matches[match["target"]] = match
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            issue(document, exc)
    for delivery in sorted(deliveries):
        try:
            launcher = _small_file(delivery / DELIVERY_LAUNCHER)
            binding = delivery_binding_from_content(launcher.read_text(encoding="utf-8"))
            if binding is None or binding.source is None:
                continue
            recorded = record_path(binding.source)
            # A delivery baseline seals exported native bytes, not raw data.
            # Content-only association requires existing source-bound project evidence.
            owner = record_path(binding.request).parent if binding.request is not None else None
            owner_match = matches.get(str(owner))
            owner_receipt = linked.get(owner) if owner is not None else None
            if recorded != source and owner_match is None and owner_receipt is None:
                continue
            copies = [{"path": str(canonical_path(delivery / "project" / name)),
                       "baseline_sha256": digest,
                       "current_sha256": existing_file_sha256(delivery / "project" / name)}
                      for name, digest in binding.documents]
            unchanged = all(item["baseline_sha256"] == item["current_sha256"] for item in copies)
            actual_documents = {canonical_path(path).name for path in (delivery / "project").glob("*.vsz")}
            unchanged = unchanged and actual_documents == dict(binding.documents).keys()
            bound = False
            if binding.root == str(delivery) and owner_match is not None:
                try:
                    bound = bound_delivery_project(delivery) == owner
                except (OSError, ValueError, TypeError, KeyError):
                    pass  # Remains an unbound snapshot; it cannot select an owner.
            if bound and unchanged and owner_match is not None:
                owner_match.setdefault("deliveries", []).append(str(delivery))
                continue
            delivery_state = "visible_edits_require_recovery" if bound else "export_snapshot"
            if bound and owner_match is not None:
                owner_match.update(state="visible_edits_require_recovery", continuation_available=False,
                    next_step={"action": "recover_visible_edits", "target": str(delivery),
                               "message": "Recover the separately saved visible edits before editing this canonical project."})
            matches[str(delivery)] = {"target": str(delivery), "kind": "delivery", "state": delivery_state,
                "source_relation": owner_receipt["source_relation"] if owner_receipt else
                                   "recorded_path" if recorded == source else "same_content_other_path",
                "recorded_source": owner_receipt["recorded_source"] if owner_receipt else str(recorded),
                "delivery_bound_source": str(recorded), "historical_project": str(owner) if owner else None,
                "authority": "export_snapshot", "documents": copies,
                "continuation_available": False, "ready_to_use": None, "readiness_evaluated": False,
                "next_step": {"action": "recover_visible_edits" if bound else "open_portable_copy",
                              "message": "This exported copy does not establish current project or source authority."}}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            issue(delivery, exc)
    values = sorted(matches.values(), key=lambda item: item["target"])
    for receipt in receipts:
        if receipt["project"] not in matches:
            values.append({"target": receipt["task_dir"], "kind": "task", "state": "historical_task",
                           "source_relation": receipt["source_relation"], "task": receipt,
                           "continuation_available": False, "ready_to_use": None,
                           "readiness_evaluated": False,
                           "next_step": {"action": "task.inspect", "arguments": {"task": receipt["task_dir"]},
                                         "message": "Inspect this recorded task; its project path is historical and was not repaired or recreated."}})
    values.sort(key=lambda item: item["target"])
    complete = not truncated and issues_count == 0 and source_error is None
    return {"kind": "sciplot_saved_work_search", "version": 1, "status": "ok",
            "source": str(source), "source_sha256": source_sha, "source_error": source_error,
            "search_roots": [str(root) for root in roots],
            "scope": "Explicit roots only, at most four descendant levels and 2000 entries; no index or global scan.",
            "scan_complete": complete, "scanned_entries": scanned, "issues": issues,
            "issue_count": issues_count, "tasks": receipts, "match_count": len(values),
            "matches": values[:limit], "has_more_matches": len(values) > limit,
            "selection_required": len(values) > 1 or not complete,
            "ready_to_use": None, "readiness_evaluated": False,
            "next_step": {"action": "select_saved_target" if len(values) > 1 or not complete else "continue_saved_work",
                          "message": "Choose an exact target when results are ambiguous or incomplete. Source hashes filter candidates; continuation rechecks its current authority."}}


def continue_saved_work(source: Path, *, search_roots: list[Path] | None = None,
                        tasks_root: Path | None = None, target: Path | None = None,
                        figure_id: str | None = None) -> dict[str, Any]:
    """Freshly query a selected authority and return existing-owner arguments.

    No edit, export, source rebinding, historical-task replay or import occurs.
    """
    found = find_saved_work(source, search_roots=search_roots, tasks_root=tasks_root, limit=100)
    base = {"kind": "sciplot_saved_work_continuation", "version": 1,
            "source": found["source"], "ready_to_use": None, "readiness_evaluated": False}
    if target is None and (found["selection_required"] or found["match_count"] != 1):
        return {**base, "status": "needs_selection" if found["match_count"] else "blocked",
                "reason_code": "saved_work_selection_required" if found["match_count"] else "saved_work_not_found",
                "search": found, "next_step": found["next_step"]}
    selected = canonical_path(target) if target is not None else Path(found["matches"][0]["target"])
    matches = [item for item in found["matches"] if item["target"] == str(selected)]
    if not matches:
        return {**base, "status": "blocked", "reason_code": "selected_target_not_discovered", "search": found}
    match = matches[0]
    if not match["continuation_available"]:
        next_step = match.get("next_step", {"action": "resolve_saved_authority"})
        if match["state"] == "source_revision_required" and found["source_sha256"]:
            request = {"version": 1, "action": "update_source", "project": match["target"], "source": found["source"]}
            next_step = {"action": "task.start", "arguments": {"request": request},
                         "message": "Use the existing source-update review for an explicit revision. Missing recorded raw or prepared files may first require restoration; that owner will reject unavailable evidence. Discovery did not rebind it."}
        return {**base, "status": "blocked", "reason_code": match["state"], "selected": match, "next_step": next_step}
    try:
        if match["kind"] == "managed_plot":
            current = document_evidence(selected)
            if not current["current"] or current != match["document"]:
                raise ValueError("The selected semantic document has a conflict or pending transaction.")
            next_step = {"action": "plot.open", "arguments": {"target": str(selected)},
                         "plot_id": current["plot_id"], "revision": current["revision"]}
        else:
            from sciplot_core.studio_core.document_edit_state import audit_edited_document
            from sciplot_core.studio_core.project_query import inspect_project

            identity = figure_id or match["primary_figure_id"]
            current = inspect_project(selected, figure_id=identity, native=True)
            if current["source"]["current"] is not True:
                raise ValueError("Current complete recorded scientific-source evidence is required.")
            figure = current["selected_figure"]
            audit = audit_edited_document(Path(figure["document"]), Path(figure["spec"]))
            if existing_file_sha256(Path(figure["document"])) != figure["document_sha256"]:
                raise ValueError("The native document changed during continuation inspection.")
            current["scientific_audit"] = audit
            fresh = project_evidence(selected, Path(found["source"]), found["source_sha256"],
                                     receipt_sha256=match["recorded_source_sha256"],
                                     receipt_source=Path(match["recorded_source"]))
            if fresh is None or not fresh["continuation_available"]:
                raise ValueError("The selected project or its existing document binding changed during continuation.")
            if fresh["identity_sha256"] != match["identity_sha256"]:
                raise ValueError("The project identity changed during continuation; inspect the current target.")
            request = {"version": 1, "action": "edit", "project": str(selected),
                       "figure_id": identity, "expected_document_sha256": figure["document_sha256"],
                       "operations": []}
            next_step = {"action": "fill_operations_then_start", "arguments": {"request": request},
                         "style_arguments": {"target": str(selected), "figure_id": identity},
                         "message": "Fill operations with the requested batch and use task.start, or use task.style with these current target arguments. The saved VSZ remains the visual authority."}
        return {**base, "status": "current", "selected": match, "current": current, "next_step": next_step}
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return {**base, "status": "blocked", "reason_code": getattr(exc, "reason_code", "saved_authority_changed"),
                "message": str(exc), "selected": match,
                "next_step": {"action": "inspect_selected_conflict", "target": str(selected)}}


__all__ = ["find_saved_work", "continue_saved_work"]
