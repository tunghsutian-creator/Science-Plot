"""Current native previews and a read-only experiment gallery; never a plot renderer."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core.document_edit import preview_project_document
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_group_storage import active_step, step_state


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
        result["source_current"] = bool(first and source_tree_sha256(Path(original["source"])) == first["source_sha256"])
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
    return result


def _write_gallery(root: Path, result: dict[str, Any]) -> str:
    cards = []
    for item in result["items"]:
        problem = item.get("blocker") or item.get("task", {}).get("blocker") or item.get("task", {}).get("question")
        for index, figure in enumerate(item["figures"] or [{}]):
            body = []
            caption = "待审修改" if figure.get("scope") == "candidate" else "已保存"
            title = figure.get("title", "等待处理")
            if figure.get("preview"):
                path = canonical_path(Path(figure["preview"]["path"]))
                href = quote(str(path.relative_to(root)))
                body.append(f'<a class="image" href="{href}" aria-label="查看大图：{escape(title)}"><img loading="lazy" src="{href}" alt="{escape(item["label"])} · {escape(title)}"></a>')
            else:
                body.append(f'<p class="problem">{escape(figure.get("preview_error", "暂无预览"))}</p>')
            if problem:
                message = problem.get("message") or problem.get("prompt") or "此项需要进一步确认。"
                body.append(f'<p class="problem">{escape(str(message))}</p>')
            if item.get("source_current") is False:
                body.append('<p class="problem">原始输入已变化或尚未完成绑定；请检查此项。</p>')
            cards.append(f'<section id="{item["id"]}-{index}"><p class="eyebrow">{escape(item["label"])}</p>'
                         f'<header><h2>{escape(title)}</h2><span>{caption if figure else "待处理"}</span></header>{"".join(body)}</section>')
    title = escape(result["title"])
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · SciPlot</title>
<style>body{{margin:0;background:#f4f6f8;color:#202b36;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1400px;margin:auto;padding:32px}}h1{{margin:0}}.intro{{color:#526170}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:20px}}
section{{background:white;border:1px solid #d9e1e7;border-radius:12px;padding:20px;min-width:0}}
header{{display:flex;justify-content:space-between;align-items:baseline;gap:12px}}h2{{font-size:18px;line-height:1.4;margin:8px 0 16px;min-height:50px}}
header span{{font-size:12px;color:#526170;white-space:nowrap;background:#eff4f8;padding:2px 8px;border-radius:20px}}
.image{{display:flex;align-items:center;justify-content:center;height:340px}}img{{width:100%;height:100%;object-fit:contain}}
.eyebrow{{font-size:13px;color:#526170;margin:0}}.problem{{color:#923f1b}}@media(max-width:500px){{main{{padding:20px}}.image{{height:310px}}}}
a{{color:#235ca2}}a:focus-visible{{outline:3px solid #235ca2;outline-offset:3px}}
</style></head><body><main><h1>{title}</h1>
<p class="intro">{len(result["items"])} 个实验 · {len(result["previews"])} 张预览 · 点击图片查看大图。更新状态后重新打开本页。</p>
<p class="intro">查询于 {escape(result["queried_at"])} · <a href="group.json">实验组记录</a></p>
<div class="grid">{"".join(cards)}</div></main></body></html>'''
    path = canonical_path(root / "overview.html")
    temporary = canonical_path(root / "overview.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(path)
    return str(path)


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
    result["overview"] = _write_gallery(root, result)
    return result
