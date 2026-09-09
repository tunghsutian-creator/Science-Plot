"""Shared read-only review presentation; all evidence comes from existing owners."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote


def text(value: object) -> str:
    return escape(str(value))


def badge(label: str, tone: str = "neutral") -> str:
    return f'<span class="badge {tone}">{text(label)}</span>'


def evidence_panel(evidence: dict[str, Any], *, source_changed: bool = False) -> str:
    labels = (
        ("source", "数据", "未变化", "已变化 / 需核查", "状态未知"),
        ("qa", "导出", "匹配当前保存图", "需更新 / 核查", "暂无当前证据"),
        ("delivery", "交付", "与当前版本一致", "需更新 / 核查", "状态未知"),
    )
    rows = []
    for key, name, yes, no, unknown in labels:
        current = (evidence.get(key) or {}).get("current")
        if key == "source" and source_changed:
            current = False
        label, tone = (yes, "good") if current is True else (no, "attention") if current is False else (unknown, "neutral")
        rows.append(f'<div><dt>{name}</dt><dd>{badge(label, tone)}</dd></div>')
    return '<div class="evidence"><p class="eyebrow">当前已保存项目 · 查询时状态</p><dl>' + ''.join(rows) + '</dl></div>'


def needs_attention(item: dict[str, Any]) -> bool:
    evidence = item.get("current_evidence") or {}
    return bool(
        item.get("status") != "complete" or item.get("blocker") or item.get("source_current") is False
        or any((evidence.get(key) or {}).get("current") is not True for key in ("source", "qa", "delivery"))
        or any(figure.get("preview_error") for figure in item.get("figures", []))
    )


def copy_field(identifier: str, label: str, value: object, *, expanded: bool = False) -> str:
    if not value:
        return ""
    return (f'<details class="copy-field" {"open" if expanded else ""}><summary>{text(label)}</summary>'
            f'<textarea id="{text(identifier)}" aria-label="{text(label)}" readonly rows="2">{text(value)}</textarea>'
            f'<button type="button" data-copy="{text(identifier)}">复制{ text(label) }</button></details>')


def image_href(root: Path, preview: dict[str, Any]) -> str:
    path = Path(preview["path"]).resolve()
    return quote(str(path.relative_to(root.resolve())))


def image_link(root: Path, preview: dict[str, Any] | None, label: str) -> str:
    if not preview:
        return '<div class="image empty-image">暂无可用预览</div>'
    href = text(image_href(root, preview))
    return (f'<a class="image" href="{href}" data-zoom aria-label="查看大图：{text(label)}">'
            f'<img loading="lazy" src="{href}" alt="{text(label)}"></a>')


def write_page(root: Path, *, title: str, kind: str, intro: str, queried_at: str,
               record: str, content: str) -> str:
    assets = Path(__file__).with_name("task_review_assets")
    css = (assets / "review.css").read_text(encoding="utf-8")
    script = (assets / "review.js").read_text(encoding="utf-8")
    try:
        queried_at = datetime.fromisoformat(queried_at).astimezone().isoformat(sep=" ", timespec="seconds")
    except ValueError:
        pass
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{text(title)} · SciPlot</title>
<style>{css}</style></head><body><a class="skip" href="#content">跳到内容</a>
<header class="topbar"><a class="brand" href="#content">SciPlot<span> / {text(kind)}</span></a>
<a href="{text(record)}">查看记录 ↗</a></header><main id="content">
<div class="page-heading"><p class="eyebrow">{text(kind)}</p><h1>{text(title)}</h1><p>{text(intro)}</p>
<p class="snapshot">查询于 {text(queried_at)}。此页是查询快照；请让 AI 重新查询，再打开更新后的总览。</p></div>
{content}<footer>预览来自 Veusz。页面只用于审阅；数据、保存图和交付状态分别列出。</footer></main>
<dialog id="image-dialog" aria-labelledby="image-title"><div class="dialog-bar"><h2 id="image-title">预览</h2>
<button type="button" data-close-dialog>关闭大图</button></div><img id="large-image" alt=""></dialog>
<p class="toast" id="notice" role="status" hidden></p><script type="module">{script}</script></body></html>'''
    temporary = root / "overview.tmp"
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(root / "overview.html")
    return str(root / "overview.html")
