"""Experiment gallery HTML, projected from the current group query."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.task_review_html import badge, copy_field, evidence_panel, image_link, needs_attention, text, write_page


_TASK_LABELS = {
    "complete": "任务完成", "needs_review": "待审修改", "needs_input": "待回答",
    "blocked": "处理受阻", "running": "处理中", "pending": "待处理", "cancelled": "已取消",
}


def _card(root: Path, item: dict[str, Any], figure: dict[str, Any], index: int) -> str:
    identifier = f'{item["id"]}-{index}'
    task = item.get("task") or {}
    problem = item.get("blocker") or task.get("blocker") or task.get("question") or {}
    title = figure.get("title", "等待生成图形")
    samples = [str(sample["sample"]) for sample in figure.get("samples", []) if sample.get("sample")]
    search = ' '.join([item["label"], title, *samples, str(item.get("source", ""))])
    candidate = figure.get("scope") == "candidate"
    state_label = _TASK_LABELS.get(item["status"], "状态待核查")
    tags = badge("待审候选 · 未保存", "attention") if candidate else badge("已保存图") if figure else ""
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
    return (f'<article class="review-card" id="{text(identifier)}" data-review-card data-search="{text(search)}" '
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
