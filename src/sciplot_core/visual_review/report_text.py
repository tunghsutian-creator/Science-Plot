# ruff: noqa: E501
"""Build CSV, Markdown, and HTML visual-review reports."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _markdown_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# SciPlot physical-size QA and review preview",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Physical size passed: {summary['physical_size_passed_count']}/{summary['eligible_rule_count']}",
        f"- Uncalibrated review previews: {summary['contact_sheet_count']}",
        f"- Automated status: `{summary['automated_status']}`",
        f"- Manual visual status: `{summary['manual_visual_status']}`",
        "",
        "| Rule | Expected mm | PDF mm | TIFF mm | DPI | Size status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for record in payload["records"]:
        expected = record.get("expected_size_mm") or ["-", "-"]
        pdf = (record.get("pdf") or {}).get("physical_size_mm") or ["-", "-"]
        tiff = (record.get("tiff") or {}).get("physical_size_mm") or ["-", "-"]
        dpi = (record.get("tiff") or {}).get("dpi") or ["-", "-"]
        lines.append(
            f"| `{record['rule_id']}` | {expected[0]}x{expected[1]} | {pdf[0]}x{pdf[1]} | "
            f"{tiff[0]}x{tiff[1]} | {dpi[0]}x{dpi[1]} | `{record['status']}` |"
        )
    lines.extend(
        [
            "",
            "## Review boundary",
            "",
            "Physical dimensions and TIFF DPI are machine-checked. Contact sheets are uncalibrated screen "
            "previews for visible corruption, clipping, occlusion, and basic distinguishability only. They do "
            "not establish final-size legibility. Inspect the canonical PDF/TIFF at a calibrated physical size "
            "when final-size readability is required. This artifact does not claim journal compliance.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(_markdown_text(payload), encoding="utf-8")


def _html_text(
    payload: dict[str, Any], contact_sheets: list[Path], *, parent: Path
) -> str:
    summary = payload["summary"]
    rows = []
    for record in payload["records"]:
        expected = record.get("expected_size_mm") or ["-", "-"]
        pdf = (record.get("pdf") or {}).get("physical_size_mm") or ["-", "-"]
        tiff = (record.get("tiff") or {}).get("physical_size_mm") or ["-", "-"]
        dpi = (record.get("tiff") or {}).get("dpi") or ["-", "-"]
        css = (
            "ok"
            if record["status"] == "passed"
            else ("muted" if record["status"] == "not_run" else "bad")
        )
        rows.append(
            f"<tr><td><code>{html.escape(record['rule_id'])}</code></td>"
            f"<td>{expected[0]}x{expected[1]}</td><td>{pdf[0]}x{pdf[1]}</td>"
            f"<td>{tiff[0]}x{tiff[1]}</td><td>{dpi[0]}x{dpi[1]}</td>"
            f'<td><span class="pill {css}">{html.escape(record["status"])}</span></td></tr>'
        )
    images = "".join(
        f'<figure><img src="{html.escape(sheet.relative_to(parent).as_posix(), quote=True)}" '
        f'alt="Uncalibrated review preview {index}"><figcaption>Uncalibrated review preview {index}</figcaption></figure>'
        for index, sheet in enumerate(contact_sheets, start=1)
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SciPlot physical-size QA and review preview</title><style>
:root{{--ink:#17211d;--muted:#607068;--line:#dbe3de;--paper:#f5f7f5;--green:#176b46;--red:#9f2d2d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:34px 28px 60px}}h1{{margin:0 0 4px;font-size:28px}}.lede{{color:var(--muted)}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}}.card{{background:white;border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:180px}}.card strong{{display:block;font-size:24px}}
.table-wrap{{overflow:auto;background:white;border:1px solid var(--line);border-radius:12px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{background:#eef2ef}}
.pill{{border-radius:999px;padding:2px 8px;font-size:12px}}.pill.ok{{background:#e3f3ea;color:var(--green)}}.pill.bad{{background:#f8e2e2;color:var(--red)}}.pill.muted{{background:#eef1ef;color:var(--muted)}}
figure{{margin:24px 0;background:white;border:1px solid var(--line);border-radius:12px;padding:12px}}img{{display:block;width:100%;height:auto}}figcaption{{color:var(--muted);padding-top:8px}}
</style></head><body><main><h1>SciPlot physical-size QA and review preview</h1>
<p class="lede">Physical dimensions are machine-checked. The mosaics below are uncalibrated screen previews and do not establish final-size legibility.</p>
<section class="cards"><article class="card"><span>Eligible rules</span><strong>{summary["eligible_rule_count"]}</strong></article>
<article class="card"><span>Physical size passed</span><strong>{summary["physical_size_passed_count"]}</strong></article>
<article class="card"><span>Review previews</span><strong>{summary["contact_sheet_count"]}</strong></article>
<article class="card"><span>Manual visual status</span><strong>{html.escape(summary["manual_visual_status"])}</strong></article></section>
<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Expected mm</th><th>PDF mm</th><th>TIFF mm</th><th>TIFF dpi</th><th>Status</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<section>{images}</section></main></body></html>"""
    return document


def _write_html(
    path: Path, payload: dict[str, Any], contact_sheets: list[Path]
) -> None:
    path.write_text(
        _html_text(payload, contact_sheets, parent=path.parent),
        encoding="utf-8",
    )
