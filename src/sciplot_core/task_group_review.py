"""Current native previews and a read-only experiment gallery; never a plot renderer."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core.document_edit import preview_project_document
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_group_storage import active_step, step_state
from sciplot_core.task_group_gallery import write_group_gallery as _write_gallery
from sciplot_core.task_next_step import task_next_step


def _valid_image(image: dict[str, Any]) -> bool:
    path = canonical_path(Path(image["path"]))
    return path.is_file() and file_sha256(path) == image["sha256"]


def _saved_preview(root: Path, project: str, figure: dict[str, Any]) -> dict[str, Any]:
    identity = {"project": project, "figure_id": figure["figure_id"],
                "document_sha256": figure["document_sha256"], "spec_sha256": figure["spec_sha256"]}
    folder = canonical_path(root / "previews" / canonical_json_sha256(identity))
    metadata = canonical_path(folder.with_suffix(".json"))
    if metadata.is_file():
        try:
            cached = json.loads(metadata.read_text())
        except ValueError:
            cached = {}
        if (cached.get("project") == project and cached.get("figure_id") == figure["figure_id"]
                and cached.get("document", {}).get("sha256") == figure["document_sha256"]
                and Path(cached["preview"]["path"]).is_relative_to(root)
                and _valid_image(cached["preview"])):
            return dict(cached["preview"])
    # Preserve incomplete or altered evidence and use a new native preview directory.
    output = folder if not folder.exists() else folder.with_name(folder.name + "-" + uuid4().hex)
    fresh = preview_project_document(Path(project), figure_id=figure["figure_id"], output_dir=output)
    if fresh["document"]["sha256"] != figure["document_sha256"]:
        raise ValueError("图在生成预览期间发生变化，请重新查询。")
    atomic_write_json(metadata, fresh)
    return dict(fresh["preview"])


def _item_overview(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    step, child = active_step(item)
    status = item["status"]
    if child and child["status"] != "complete":
        status = child["status"]
    elif not item.get("finished") and not item.get("blocker"):
        status = "pending"
    result: dict[str, Any] = {"id": item["id"], "label": item["label"], "status": status, "figures": [],
                              "task_dir": step["task_dir"]}
    if item.get("blocker"):
        result["blocker"] = item["blocker"]
    if child:
        result["task"] = {key: child[key] for key in (
            "task_dir", "status", "phase", "question", "blocker", "operation_id",
        ) if key in child}
        result["task"]["next_step"] = task_next_step(child)
        result["export_images"] = [export["path"]
                                   for figure in (child.get("result") or {}).get("figures", [])
                                   for export in figure.get("exports", [])
                                   if export.get("format") in {"tiff", "tiff_300", "tiff_600"}]
        if child["request"]["action"] == "edit":
            result["task"]["preview_revision"] = len(child.get("edit_revisions") or []) + 1
        if child.get("preview") and child["status"] == "needs_review":
            result["task"]["review_path"] = child["preview"]["review_path"]
            result["task"]["changes"] = child["preview"]["changes"]
            result["task"]["scientific_audit_status"] = child["preview"]["scientific_audit"]["status"]
    first = step_state(item["steps"][0])
    original = item["steps"][0]["request"]
    if original["action"] == "create":
        result["source"] = original["source"]
        expected_source = (first or {}).get("source_sha256")
        result["source_current"] = (source_tree_sha256(Path(original["source"])) == expected_source
                                    if expected_source else None)
    project = (child or {}).get("project") or (first or {}).get("project")
    if not project:
        return result
    current = inspect_project(Path(project))
    result.update(project=current["project"], ready_to_use=current["ready_to_use"],
                  current_evidence={key: current.get(key) for key in ("source", "qa", "delivery")})
    for figure in current["figures"]:
        preview = {"figure_id": figure["figure_id"], "title": figure.get("title", figure["figure_id"]), "document_sha256": figure["document_sha256"],
                   "document": figure["document"], "scope": "saved", "samples": figure.get("sample_styles", [])}
        try:
            candidate = child and child["status"] == "needs_review" and (
                child["request"].get("figure_id", current["primary_figure_id"]) == figure["figure_id"])
            if candidate:
                assert child is not None
                image = child["preview"]["image"]
                signed = json.loads(canonical_path(Path(child["preview"]["review_path"])).read_text())
                spec_relative = str(Path(figure["spec"]).relative_to(project))
                if (not isinstance(signed, dict) or signed.get("operation_id") != child["operation_id"]
                        or signed.get("base_state", {}).get("project_files", {}).get(spec_relative) != figure["spec_sha256"]
                        or child["request"]["expected_document_sha256"] != figure["document_sha256"] or not _valid_image(image)):
                    raise ValueError("待审预览与当前文档不一致，请查询并重新生成该预览。")
                preview.update(scope="candidate", preview=image, operation_id=child["operation_id"])
            else:
                preview["preview"] = _saved_preview(root, project, figure)
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            preview["preview_error"] = str(exc)
        result["figures"].append(preview)
    if child and child["status"] == "needs_review" and (
            result.get("source_current") is False or (current.get("source") or {}).get("current") is False):
        result["task"]["next_step"] = {
            "action": "resolve_source_change",
            "message": "The original source changed after preview; resolve its scientific revision without accepting the old candidate.",
        }
    elif child and child["status"] == "needs_review" and not any(
            figure.get("scope") == "candidate" and "preview" in figure
            for figure in result["figures"]):
        result["task"]["next_step"] = {
            "action": "resolve_preview_evidence",
            "message": "The current candidate image or document binding is unavailable; do not accept a stale preview.",
        }
    return result


def group_overview(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in state["items"]:
        try:
            items.append(_item_overview(root, item))
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            items.append({"id": item["id"], "label": item["label"], "status": "blocked", "figures": [],
                          "blocker": {"reason_code": "group_inspection_failed", "message": str(exc)}})
    counts = dict(Counter(item["status"] for item in items))
    complete = all(item["status"] == "complete" for item in items)
    previews = [{"item_id": item["id"], **{key: figure[key] for key in ("figure_id", "scope", "preview")}}
                for item in items for figure in item["figures"] if "preview" in figure]
    result = {"kind": "sciplot_task_group_result", "version": 1, "group_dir": str(root),
              "title": state["request"]["title"], "updated_at": state["updated_at"],
              "queried_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
              "status": "complete" if complete else "needs_attention", "counts": counts,
              "items": items, "previews": previews,
              "ready_to_use": None, "readiness_evaluated": False, "model_calls_by_sciplot": 0,
              "preview_scope": "Native saved documents or explicitly marked pending candidates; a gallery is not a publication layout."}
    result["ordered_figures"] = [
        {"item_id": item["id"], "item_label": item["label"], "project": item["project"],
         "figure_id": figure["figure_id"], "document_sha256": figure["document_sha256"],
         "ready_to_use": item.get("ready_to_use")}
        for item in items if "project" in item for figure in item["figures"]
    ]
    if complete:
        result["next_step"] = {
            "action": "review_exports_and_deliver_group",
            "images": [image for item in items for image in item.get("export_images", [])],
            "paper_cli_argv_template": ["sciplot", "task", "paper", "start", "--group", str(root),
                                        "--out", "NEW_OUTPUT_DIRECTORY", "--paper-dir", "NEW_PAPER_TASK_DIRECTORY", "--json"],
            "message": "Review the returned final images and each item's current evidence. An ordered group can be selected locally for paper delivery; completion alone does not certify publication readiness.",
        }
    else:
        steps = [{"item_id": item["id"], "task_dir": item.get("task_dir"),
                  "next_step": item.get("task", {}).get("next_step", {"action": "inspect_blocker_and_saved_state"})}
                 for item in items if item["status"] != "complete"]
        result["next_step"] = {
            "action": "review_group_items_then_resume",
            "items": steps,
            "responses_template": [
                {"item_id": entry["item_id"], "task_dir": entry["task_dir"],
                 "response": entry["next_step"]["response_template"]}
                for entry in steps if "response_template" in entry["next_step"]
            ],
            "cli_argv_template": ["sciplot", "task", "group", "resume", str(root),
                                  "--responses", "RESPONSES_JSON_FILE", "--json"],
            "message": "Review every candidate image and scientific audit, then answer the bound items together. Keep unanswered scientific questions and rejected candidates pending; no automatic acceptance.",
        }
    result["overview"] = _write_gallery(root, result)
    return result
