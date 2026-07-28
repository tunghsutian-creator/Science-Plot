"""Write the human-readable index for batch review artifacts."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any


def write_review_index(output_dir: Path, *, manifest: dict[str, Any]) -> None:
    run_items = []
    for run in manifest.get("runs", []):
        run_output = Path(str(run["output"]))
        rel = (
            run_output.relative_to(output_dir)
            if run_output.is_relative_to(output_dir)
            else run_output
        )
        review = rel / "review.html"
        rule_id = run.get("rule_id") or run.get("semantic_family") or "unknown"
        run_items.append(
            "<li>"
            f'<a href="{escape(str(review))}">'
            f"{escape(str(run.get('label', run_output.name)))}</a>"
            f" <code>{escape(str(rule_id))}</code>"
            f" <code>{escape(str(run.get('model', 'unknown')))}</code>"
            "</li>"
        )
    skipped_count = len(manifest.get("skipped", []))
    html = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>SciPlot Batch Review</title>",
            "<style>body{font-family:Arial,sans-serif;margin:32px;"
            "line-height:1.45}</style>",
            "</head>",
            "<body>",
            "<h1>SciPlot Batch Review</h1>",
            f"<p>Runs: {len(run_items)}; skipped: {skipped_count}</p>",
            "<ul>",
            *run_items,
            "</ul>",
            "</body>",
            "</html>",
        ]
    )
    (output_dir / "review_index.html").write_text(html + "\n", encoding="utf-8")
