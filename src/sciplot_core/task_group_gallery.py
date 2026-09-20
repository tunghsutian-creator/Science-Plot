"""Experiment gallery HTML, projected from the current group query."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.task_review_html import badge, copy_field, evidence_panel, image_link, needs_attention, text, write_page


_TASK_LABELS = {
    "complete": "任务完成", "needs_review": "待审修改", "needs_input": "待回答",
    "blocked": "处理受阻", "running": "处理中", "pending": "待处理", "cancelled": "已取消",
}


def _edit_request(item: dict[str, Any], figure: dict[str, Any], identifier: str) -> str:
    """Offer an intent handoff only for an identified native saved-figure snapshot."""
    project, document = item.get("project"), figure.get("document")
    revision, figure_id = figure.get("document_sha256"), figure.get("figure_id")
    preview = figure.get("preview")
    task = item.get("task") or {}
    source = (item.get("current_evidence") or {}).get("source") or {}
    if (
        figure.get("scope") != "saved"
        or not isinstance(project, str) or not project
        or not isinstance(document, str) or not document
        or not Path(project).is_absolute() or not Path(document).is_absolute()
        or ".." in Path(project).parts or ".." in Path(document).parts
        or not Path(document).is_relative_to(Path(project))
        or Path(document).suffix.lower() != ".vsz"
        or not isinstance(figure_id, str) or not figure_id.strip()
        or not isinstance(revision, str) or re.fullmatch(r"[a-f0-9]{64}", revision) is None
        or not isinstance(preview, dict) or not preview.get("path")
        or figure.get("preview_error") or item.get("blocker") or task.get("blocker")
        or item.get("status") in {"blocked", "cancelled"}
        or item.get("source_current") is False or source.get("current") is False
    ):
        return ""
    template = (
        "请先重新查询这个 SciPlot 项目及图形，核对当前文档路径和保存版本，再处理以下修改意图。\n"
        f"项目路径：{project}\n图形 ID：{figure_id}\n保存图路径：{document}\n"
        f"预期文档 SHA-256：{revision}\n"
        "若图形身份、文档或源数据已变化，请先展示当前状态，不要套用旧版本。"
        "请通过现有 SciPlot 任务生成修改预览，审阅后再按任务流程继续。\n"
        "本页是查询快照；复制说明仅提交修改意图，不代表修改已应用或保存。"
    )
    return (
        '<details class="edit-request" data-edit-request><summary>修改说明</summary>'
        f'<label for="{identifier}-instruction">想怎样修改这张图？</label>'
        f'<textarea id="{identifier}-instruction" data-edit-instruction rows="3" '
        'placeholder="例如：把 E0 曲线改为蓝色，并加粗线条。"></textarea>'
        f'<textarea data-edit-template readonly hidden aria-label="图形身份与复查要求">{text(template)}</textarea>'
        '<textarea data-edit-output readonly hidden aria-label="可复制的修改说明" rows="7"></textarea>'
        '<button type="button" data-copy-edit disabled>复制修改说明</button>'
        '<p class="muted">复制后粘贴给 AI；页面不会应用或保存修改。</p></details>'
    )


def _card(root: Path, item: dict[str, Any], figure: dict[str, Any], index: int) -> str:
    identity = {"item": item["id"], "figure": figure.get("figure_id", index)}
    identifier = 'group-' + canonical_json_sha256(identity)[:20]
    task = item.get("task") or {}
    problem = item.get("blocker") or task.get("blocker") or task.get("question") or {}
    title = figure.get("title", "等待生成图形")
    samples = [str(sample["sample"]) for sample in figure.get("samples", []) if sample.get("sample")]
    search = ' '.join([item["label"], title, *samples, str(item.get("source", ""))])
    candidate = figure.get("scope") == "candidate"
    kind = figure.get("scope") if figure.get("scope") in {"saved", "candidate"} else "unavailable"
    state_label = _TASK_LABELS.get(item["status"], "状态待核查")
    tags = badge("待审候选 · 未保存", "attention") if candidate else badge("已保存图") if kind == "saved" else ""
    body = [image_link(root, figure.get("preview"), f'{item["label"]} · {title}')]
    if samples:
        body.append('<p class="samples">样本 ' + ' · '.join(text(label) for label in samples) + '</p>')
    message = problem.get("message") or problem.get("prompt")
    if message:
        body.append(f'<p class="problem">{text(message)}</p>')
    if figure.get("preview_error"):
        body.append(f'<p class="problem">{text(figure["preview_error"])}</p>')
    body.append(evidence_panel(item.get("current_evidence") or {}, source_changed=item.get("source_current") is False))
    evidence = item.get("current_evidence") or {}
    source = item.get("source") or ((evidence.get("source") or {}).get("input") or {}).get("path")
    source_label = "原始数据路径" if item.get("source") else "项目数据路径"
    paths = [("source", source_label, source), ("document", "保存图路径", figure.get("document")),
             ("delivery", "交付目录", (evidence.get("delivery") or {}).get("path"))]
    body.extend(copy_field(f'{identifier}-{key}', label, value) for key, label, value in paths)
    if figure.get("document_sha256"):
        body.append(f'<p class="revision">保存版本 <code title="{text(figure["document_sha256"])}">{text(figure["document_sha256"][:12])}</code></p>')
    body.append(_edit_request(item, figure, identifier))
    return (f'<article class="review-card" id="{text(identifier)}" data-review-card data-search="{text(search)}" '
            f'data-title="{text(title)}" data-subtitle="{text(item["label"])}" data-kind="{text(kind)}" '
            f'data-attention="{str(needs_attention(item)).lower()}"><header><div><p class="eyebrow">{text(item["label"])}</p>'
            f'<h2>{text(title)}</h2></div>{badge(state_label, "attention" if item["status"] != "complete" else "neutral")}</header>'
            f'<div class="tags">{tags}</div>{"".join(body)}</article>')


def write_group_gallery(root: Path, result: dict[str, Any]) -> str:
    items = result["items"]
    attention = sum(needs_attention(item) for item in items)
    stats = (f'<div class="stats"><div><strong>{len(items)}</strong><span>个实验</span></div>'
             f'<div><strong>{len(result["previews"])}</strong><span>张预览</span></div>'
             f'<div><strong>{attention}</strong><span>个实验需关注</span></div></div>')
    toolbar = '''<div class="toolbar"><label class="search">搜索实验、图形或样本<input id="review-search" type="search" placeholder="例如 FTIR、E0" autocomplete="off"></label>
<label>显示<select id="review-filter"><option value="all">全部图形</option><option value="attention">需关注</option></select></label>
<output id="filter-count" aria-live="polite"></output></div>'''
    cards = ''.join(_card(root, item, figure, index) for item in items
                    for index, figure in enumerate(item["figures"] or [{}]))
    empty = '<p id="filter-empty" class="empty-state" hidden>没有匹配的图形。请更换搜索词或显示全部图形。</p>'
    return write_page(root, title=result["title"], kind="实验总览",
                      intro="集中查看各实验的保存图和待审修改。点击图片放大，按实验或样本定位。",
                      queried_at=result["queried_at"], record="group.json",
                      content=stats + toolbar + '<div class="grid">' + cards + '</div>' + empty)
