from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.render import inspect_payload, render_to_dir


def _first_table_source(input_path: Path) -> Path:
    if input_path.is_file():
        return input_path
    if input_path.is_dir():
        for suffix in ("*.csv", "*.tsv", "*.txt", "*.xlsx", "*.xls"):
            match = next(iter(sorted(input_path.rglob(suffix))), None)
            if match is not None:
                return match
    raise FileNotFoundError(f"No table source found under {input_path}.")


def _write_report(output_dir: Path, *, recipe: str, source: Path, manifest: dict[str, Any]) -> None:
    lines = [
        f"# SciPlot Recipe: {recipe}",
        "",
        f"- Source: `{source}`",
        f"- Created: {manifest['created_at']}",
        f"- Template: `{manifest['template']}`",
        f"- Figures: {len(manifest.get('figures', []))}",
        "",
        "## Renderer",
        "",
        "This recipe prepares data and delegates figure generation to `sciplot_core.render_to_dir`.",
    ]
    (output_dir / "analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_source_table(source: Path, output_dir: Path) -> None:
    tables_dir = output_dir / "tables"
    try:
        if source.suffix.lower() in {".xlsx", ".xls"}:
            frame = pd.read_excel(source)
        else:
            frame = pd.read_csv(source)
        frame.head(200).to_csv(tables_dir / "source_preview.csv", index=False)
    except Exception as exc:
        (tables_dir / "source_preview_error.txt").write_text(str(exc), encoding="utf-8")


def run_material_recipe(
    recipe: str,
    input_path: Path,
    *,
    output_dir: Path,
    default_template: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for folder in ("processed", "figures", "tables"):
        (output_dir / folder).mkdir(parents=True, exist_ok=True)

    options = dict(options or {})
    render_options = dict(options.get("render_options") or {})
    export_formats = options.get("exports") or options.get("export_formats")
    template = str(options.get("template") or default_template)
    source = _first_table_source(input_path.expanduser())
    processed_source = output_dir / "processed" / source.name
    if source.resolve() != processed_source.resolve():
        shutil.copy2(source, processed_source)
    _write_source_table(source, output_dir)

    inspection = inspect_payload(processed_source)
    if not options.get("template"):
        recommendations = inspection.get("recommendations") or []
        if recommendations:
            template = str(recommendations[0].get("template_id") or template)
            defaults = recommendations[0].get("default_render_overrides") or {}
            if isinstance(defaults, dict):
                render_options = {**defaults, **render_options}

    render_payload = render_to_dir(
        processed_source,
        template=template,
        output_dir=output_dir / "figures",
        options=render_options,
        export_formats=export_formats,
    )
    manifest = {
        "kind": "sciplot_recipe",
        "recipe": recipe,
        "created_at": datetime.now(UTC).isoformat(),
        "input": str(input_path),
        "processed_source": str(processed_source),
        "template": template,
        "render_options": render_options,
        "export_formats": render_payload["export_formats"],
        "render_engine": render_payload.get("render_engine") or "veusz",
        "qa_target": render_payload.get("qa_target"),
        "veusz_documents": render_payload.get("veusz_documents", []),
        "veusz_specs": render_payload.get("veusz_specs", []),
        "exports": render_payload["exports"],
        "inspection": inspection,
        "figures": render_payload["outputs"],
        "qa_reports": render_payload["qa_reports"],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(output_dir, recipe=recipe, source=source, manifest=manifest)
    return manifest


__all__ = ["run_material_recipe"]
