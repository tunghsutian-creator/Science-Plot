"""Shared read-only review presentation; all evidence comes from existing owners."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sciplot_core.foundation.iso_timestamps import local_display_time


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
    license_text = (assets / "tavotto-LICENSE.txt").read_text(encoding="utf-8")
    try:
        queried_at = local_display_time(queried_at)
    except ValueError:
        pass
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{text(title)} · SciPlot</title>
<style>{css}</style></head><body><a class="skip" href="#content">跳到内容</a>
<header class="topbar"><a class="brand" href="#content">SciPlot<span> / {text(kind)}</span></a>
<nav id="view-switch" class="view-switch" aria-label="查看方式" hidden>
<button type="button" data-view="workspace" aria-pressed="true">画布</button>
<button type="button" data-view="gallery" aria-pressed="false">图库</button></nav>
<div class="topbar-actions"><a href="{text(record)}">查看记录</a>
<button type="button" data-about>关于界面</button></div></header><main id="content">
<div class="page-heading"><h1>{text(title)}</h1><p>{text(intro)}</p>
<p class="snapshot">查询于 {text(queried_at)}。此页是查询快照；请让 AI 重新查询，再打开更新后的总览。</p></div>
<section id="workspace-view" class="workbench" aria-label="图形工作台" hidden>
<aside class="figure-rail" aria-label="图形列表"><div class="rail-heading"><h2>图形</h2>
<span id="rail-count"></span></div><div id="rail-filter"></div>
<div id="rail-list" class="rail-list"></div></aside>
<section class="canvas-area" aria-label="原生图形预览"><div class="canvas-toolbar">
<div class="canvas-heading"><h2 id="canvas-title" tabindex="-1">选择图形</h2><p id="canvas-caption"></p></div>
<div class="canvas-tools" role="group" aria-label="画布工具">
<button type="button" id="zoom-out" aria-label="缩小预览" disabled>−</button>
<output id="zoom-level" aria-label="预览缩放比例">—</output>
<button type="button" id="zoom-in" aria-label="放大预览" disabled>+</button>
<button type="button" id="zoom-fit" disabled>适合窗口</button>
<button type="button" id="details-toggle" aria-controls="inspector" aria-expanded="true">详情</button>
</div></div>
<div id="canvas-viewport" class="canvas-viewport" tabindex="0" role="region" aria-label="预览画布，可拖动或方向键平移，使用加减键缩放，0 键适合窗口">
<img id="canvas-image" class="canvas-image" alt="" draggable="false" hidden>
<p id="canvas-empty" class="canvas-empty">选择图形查看预览</p></div>
<div class="canvas-status"><span id="canvas-position" aria-live="polite"></span>
<span>拖动 / 方向键平移 · + / − 缩放 · 0 适合窗口</span>
<div role="group" aria-label="切换图形"><button type="button" id="figure-prev" aria-label="上一张图形">上一张</button>
<button type="button" id="figure-next" aria-label="下一张图形">下一张</button></div></div></section>
<aside id="inspector" class="inspector" aria-label="当前图形详情"><div class="inspector-heading">
<h2 id="inspector-title">图形详情</h2><span>查询快照</span></div><div id="inspector-content"></div></aside>
</section>
<section id="gallery-view" aria-label="图形图库">{content}</section>
<footer class="page-footer">预览来自 Veusz。数据、保存图和交付状态分别列出；查看和复制说明不会应用修改。</footer></main>
<dialog id="image-dialog" aria-labelledby="image-title"><div class="dialog-bar"><h2 id="image-title">预览</h2>
<button type="button" data-close-dialog>关闭大图</button></div><img id="large-image" alt=""></dialog>
<dialog id="about-dialog" aria-labelledby="about-title"><div class="dialog-bar"><h2 id="about-title">关于 SciPlot 界面</h2>
<button type="button" data-close-about>关闭</button></div>
<p>界面设计与部分样式源自 Tavotto。SciPlot 沿用自己的绘图、数据审计和导出流程。</p>
<p><a href="https://github.com/Tavotto/Tavotto/tree/4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186">Tavotto 源码与出处</a>
 · AGPL-3.0-only · 修改版界面，不代表 Tavotto 官方版本。</p>
<p>本页内嵌未压缩的 HTML、CSS 和 JavaScript；保存页面或查看页面源代码即可取得这份浏览器界面源码。</p>
<details><summary>查看完整许可证</summary><pre class="license-text">{text(license_text)}</pre></details></dialog>
<p class="toast" id="notice" role="status" hidden></p><script type="module">{script}</script></body></html>'''
    temporary = root / "overview.tmp"
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(root / "overview.html")
    return str(root / "overview.html")
