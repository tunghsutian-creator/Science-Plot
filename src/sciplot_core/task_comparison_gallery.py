"""Read-only native alternative comparison, with explicit handoff back to the caller."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.task_review_html import badge, copy_field, evidence_panel, image_href, image_link, text, write_page


def _value(value: Any) -> str:
    value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text(value if len(value) <= 240 else value[:240] + "…")


def _changes(root: Path, entry: dict[str, Any]) -> str:
    if "change_count" not in entry:
        return ""
    rows = []
    for change in entry["changes"]:
        setting = change.get("setting_path", change.get("op", "") + " " + change.get("id", ""))
        rows.append(f'<tr><th scope="row">{text(setting)}</th><td>{_value(change.get("old_value", change.get("before")))}</td>'
                    f'<td>{_value(change.get("new_value", change.get("after")))}</td></tr>')
    audit = "数值审计通过" if entry.get("scientific_audit_status") == "passed" else "数值审计未确认"
    note = '<p>这里显示前 12 项，完整差异见候选记录。</p>' if entry.get("changes_truncated") else ""
    href = image_href(root, {"path": entry["review_path"]})
    return (f'<details class="changes"><summary>{entry["change_count"]} 处修改 · {audit}</summary>'
            '<div class="diff"><table><thead><tr><th>设置</th><th>原值</th><th>候选值</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>{note}<a href="{text(href)}">完整候选记录 ↗</a></details>')


def _selection_note(result: dict[str, Any], entry: dict[str, Any]) -> str:
    return (f'请重新检查这个 SciPlot 比较；若比较标识和可选状态仍一致，'
            f'{"保留原图" if entry["id"] == "baseline" else "采用候选「" + entry["label"] + "」"}。\n'
            f'比较目录：{result["comparison_dir"]}\n候选 ID：{entry["id"]}\n'
            f'预期比较标识：{result["comparison_id"]}\n若已变化，请先展示当前状态，不要套用旧选择。')


def _card(root: Path, result: dict[str, Any], entry: dict[str, Any]) -> str:
    selected = result.get("selection", {}).get("candidate_id") == entry["id"]
    label = "比较时的原图" if entry["id"] == "baseline" else "候选 · 未应用"
    if entry["status"] == "unchanged":
        label = "与原图一致"
    if selected:
        label = "当时保留原图" if entry["id"] == "baseline" and result["status"] == "complete" else (
            "当时采用" if result["status"] == "complete" else "已锁定选择 · 待完成")
    body = [image_link(root, entry.get("preview"), entry["label"])]
    if entry.get("rationale"):
        body.append(f'<p>{text(entry["rationale"])}</p>')
    if entry.get("error"):
        body.append(f'<p class="problem">{text(entry["error"])}</p>')
    body.append(_changes(root, entry))
    if entry.get("preview") and entry["id"] != "baseline" and result["baseline"].get("preview"):
        body.append(f'<button type="button" class="compare-button" data-compare="{text(entry["id"])}">与原图并排查看</button>')
    if entry.get("selectable"):
        body.append(copy_field(f'select-{entry["id"]}', "选择说明", _selection_note(result, entry)))
    return (f'<article class="review-card {"selected" if selected else ""}" data-candidate="{text(entry["id"])}">'
            f'<header><h2>{text(entry["label"])}</h2>{badge(label, "good" if selected and result["status"] == "complete" else "neutral")}</header>'
            f'{"".join(body)}</article>')


def _compare_view(root: Path, result: dict[str, Any]) -> str:
    candidates = [entry for entry in result["candidates"] if entry.get("preview")]
    if not result["baseline"].get("preview") or not candidates:
        return ""
    options = ''.join(f'<option value="{text(entry["id"])}" data-image="{text(image_href(root, entry["preview"]))}">{text(entry["label"])}</option>' for entry in candidates)
    return ('<section class="compare-view" id="compare-view" hidden aria-labelledby="compare-title"><div class="toolbar">'
            '<h2 id="compare-title" tabindex="-1">并排比较</h2><label>查看候选<select id="candidate-picker">' + options + '</select></label>'
            '<button type="button" id="close-compare">收起并排比较</button></div><div class="pair">'
            '<div><h3>比较时的原图</h3>' + image_link(root, result["baseline"]["preview"], "比较时的原图") + '</div>'
            '<div><h3 id="pair-label"></h3><a class="image" id="pair-link" data-zoom><img id="pair-image" alt=""></a></div>'
            '</div><p class="muted">两侧均为比较时的预览，使用相同查看区域；选择下拉项只切换展示。</p></section>')


def write_comparison_gallery(root: Path, result: dict[str, Any]) -> str:
    selected = result.get("selection", {}).get("candidate_id")
    message = "查看候选与差异。确定后展开并复制选择说明，交给 AI 继续；复制说明不会应用修改。"
    if selected:
        message = "此页保留比较时的原图与候选，以及已记录的选择。当前项目状态单独列于下方。"
    elif result.get("blocker"):
        message = result["blocker"]["message"]
    elif not result.get("can_select"):
        message = "当前比较尚不可选择，请让 AI 查询并处理未完成的步骤。"
    problem = result.get("current_error") or (result.get("blocker") or {}).get("message")
    state = '<p class="problem">' + text(problem) + '</p>' if problem else ""
    current = result.get("current_figure") or {}
    evidence = result.get("current_evidence") or {}
    state += evidence_panel(evidence)
    paths = [("document", "当前保存图路径", current.get("document")),
             ("delivery", "交付目录", (evidence.get("delivery") or {}).get("path"))]
    state += '<div class="paths">' + ''.join(copy_field(f'current-{key}', label, value) for key, label, value in paths) + '</div>'
    cards = ''.join(_card(root, result, entry) for entry in [result["baseline"], *result["candidates"]])
    return write_page(root, title=result["title"], kind="方案比较", intro=message,
                      queried_at=result["queried_at"], record="comparison.json",
                      content=f'<p class="summary-line">1 张原图 · {len(result["candidates"])} 个候选 · 比较快照</p>'
                      + state + _compare_view(root, result) + '<div class="grid comparison-grid">' + cards + '</div>')
