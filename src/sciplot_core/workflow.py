from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from sciplot_core.materials_rules import compute_analysis_metrics
from sciplot_core.qa import run_qa
from sciplot_core.render import json_safe, render_to_dir
from sciplot_core.semantic import build_intervention_request, classify_source, prepare_semantic_source
from sciplot_core.study_model import (
    attach_run_artifacts_to_study_model,
    build_output_package_contract,
    study_model_from_request,
)
from sciplot_recipes import run_recipe


def _load_request(request_path: Path) -> dict[str, Any]:
    if request_path.suffix.lower() != ".json":
        raise ValueError("Plot requests currently support JSON files. Use a .json request file.")
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Plot request must be a JSON object.")
    return payload


def _resolve_request_path(value: object, *, base_dir: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Plot request must define a non-empty `{field}` path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _resolve_optional_request_path(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _clear_managed_artifacts(output_dir: Path) -> None:
    for folder in ("processed", "figures", "tables", "raw"):
        path = output_dir / folder
        if path.exists():
            shutil.rmtree(path)
    for filename in (
        "request_snapshot.json",
        "manifest.json",
        "analysis_report.md",
        "revision_brief.md",
        "review.html",
        "intervention_request.json",
    ):
        path = output_dir / filename
        if path.exists():
            path.unlink()


def _request_options(request: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if "template" in request:
        options["template"] = request["template"]
    if "render_options" in request:
        options["render_options"] = request["render_options"]
    if "exports" in request:
        options["exports"] = request["exports"]
    return options


def _archive_raw_input(input_path: Path, output_dir: Path) -> dict[str, Any]:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / input_path.name
    if input_path.is_dir():
        shutil.copytree(input_path, destination)
        kind = "directory"
    else:
        shutil.copy2(input_path, destination)
        kind = "file"
    return {
        "kind": kind,
        "source": str(input_path),
        "path": str(destination),
    }


def _figures_from_result(result: dict[str, Any]) -> list[str]:
    figures = result.get("figures") or result.get("outputs") or []
    return [str(path) for path in figures]


def _write_render_report(output_dir: Path, *, request: dict[str, Any], result: dict[str, Any]) -> None:
    lines = [
        "# SciPlot Run",
        "",
        "- Route: `render`",
        f"- Template: `{result['template']}`",
        f"- Figures: {len(result.get('outputs', []))}",
        "",
        "## Review Notes",
        "",
    ]
    notes = request.get("review_notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_auto_report(
    output_dir: Path,
    *,
    request: dict[str, Any],
    result: dict[str, Any],
    semantic: dict[str, Any],
    final_recipe: str | None,
) -> None:
    lines = [
        "# SciPlot Run",
        "",
        "- Route: `auto`",
        f"- Semantic family: `{semantic['semantic_family']}`",
        f"- Final recipe: `{final_recipe or 'direct_render'}`",
        f"- Template: `{result['template']}`",
        f"- Figures: {len(result.get('outputs', []))}",
        "",
        "## Semantic Reason",
        "",
        f"- {semantic.get('reason', 'No semantic reason recorded.')}",
        "",
        "## Review Notes",
        "",
    ]
    notes = request.get("review_notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_review_html(output_dir: Path, *, manifest: dict[str, Any]) -> None:
    figures = [Path(path) for path in manifest.get("figures", [])]
    notes = manifest.get("request", {}).get("review_notes") or []
    revision_brief = manifest.get("revision_brief")
    figure_items = []
    for figure in figures:
        rel = figure.relative_to(output_dir) if figure.is_relative_to(output_dir) else figure
        label = escape(str(rel))
        if figure.suffix.lower() == ".png":
            figure_items.append(f'<li><a href="{label}">{label}</a><br><img src="{label}" alt="{label}"></li>')
        else:
            figure_items.append(f'<li><a href="{label}">{label}</a></li>')
    note_items = [f"<li>{escape(str(note))}</li>" for note in notes] or ["<li>No review notes supplied.</li>"]
    html = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>SciPlot Review</title>",
            "<style>",
            "body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}",
            "img{max-width:720px;border:1px solid #ddd}",
            "</style>",
            "</head>",
            "<body>",
            "<h1>SciPlot Review</h1>",
            f"<p>Route: <code>{escape(str(manifest.get('route')))}</code></p>",
            "<h2>Review Notes</h2>",
            "<ul>",
            *note_items,
            "</ul>",
            "<h2>Figures</h2>",
            "<ul>",
            *figure_items,
            "</ul>",
            "<h2>Revision</h2>",
            "<ul>",
            (
                f'<li><a href="{escape(str(revision_brief))}">Revision brief for Codex</a></li>'
                if isinstance(revision_brief, str) and revision_brief
                else "<li>No revision brief was generated.</li>"
            ),
            "</ul>",
            "</body>",
            "</html>",
        ]
    )
    (output_dir / "review.html").write_text(html + "\n", encoding="utf-8")


def _write_revision_brief(output_dir: Path, *, manifest: dict[str, Any]) -> str:
    figures = [Path(path) for path in manifest.get("figures", []) if isinstance(path, str)]
    figure_lines = []
    for figure in figures:
        rel = figure.relative_to(output_dir) if figure.exists() and figure.is_relative_to(output_dir) else figure
        figure_lines.append(f"- `{rel}`")
    semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    size = ""
    render_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    if isinstance(render_options.get("size"), str):
        size = str(render_options["size"])
    lines = [
        "# SciPlot Revision Brief",
        "",
        "Use this brief when asking Codex to revise the SciPlot rule, recipe, or style and rerun the export.",
        "",
        "## Run",
        "",
        f"- Output: `{output_dir}`",
        f"- Request: `{manifest.get('request_path')}`",
        f"- Route: `{manifest.get('route')}`",
        f"- Rule: `{semantic.get('rule_id') or ''}`",
        f"- Template: `{manifest.get('result', {}).get('template') or ''}`",
        f"- Size: `{size}`" if size else "- Size: not specified in request",
        f"- QA: `{manifest.get('qa', {}).get('status') or 'unknown'}`",
        "",
        "## Figures",
        "",
        *(figure_lines or ["- No figures were recorded."]),
        "",
        "## Tell Codex",
        "",
        "请按这些修改意见调整 SciPlot 规则/样式并重新导出：",
        "",
        "- 图类型/数据识别：",
        "- 坐标轴标题和单位：",
        "- x/y 轴范围、log、reverse、刻度数量：",
        "- legend 名称、顺序、位置：",
        "- 字体、线宽、marker、颜色：",
        "- 其他：",
    ]
    path = output_dir / "revision_brief.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "revision_brief.md"


def _update_intake_project_after_run(request_path: Path, manifest: dict[str, Any]) -> None:
    project_dir = request_path.parent
    intake_manifest_path = project_dir / "intake_manifest.json"
    if not intake_manifest_path.exists():
        return
    project_manifest = json.loads(intake_manifest_path.read_text(encoding="utf-8"))
    project_manifest["last_run"] = {
        "completed_at": manifest["created_at"],
        "output": manifest["output"],
        "figures": manifest["figures"],
        "analysis_metrics": manifest.get("result", {}).get("analysis_metrics", []),
        "qa": manifest.get("qa", {}),
        "revision_brief": manifest.get("revision_brief"),
        "package_contract": manifest.get("package_contract", {}),
    }
    if isinstance(manifest.get("study_model"), dict):
        project_manifest["study_model"] = manifest["study_model"]
        project_manifest["last_run"]["study_model"] = manifest["study_model"]
    if isinstance(manifest.get("package_contract"), dict):
        project_manifest["package_contract"] = manifest["package_contract"]
    intake_manifest_path.write_text(
        json.dumps(json_safe(project_manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    sciplot_paths = sorted(project_dir.glob("*.sciplot.json"))
    for path in sciplot_paths:
        path.write_text(
            json.dumps(json_safe(project_manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    from sciplot_core.intake import refresh_intake_project_zip

    refresh_intake_project_zip(project_dir)


def run_request(request_path: Path) -> dict[str, Any]:
    request_path = request_path.expanduser().resolve()
    request = _load_request(request_path)
    base_dir = request_path.parent
    input_path = _resolve_request_path(request.get("input"), base_dir=base_dir, field="input")
    output_dir = _resolve_request_path(request.get("output"), base_dir=base_dir, field="output")
    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_managed_artifacts(output_dir)
    raw_archive = _archive_raw_input(input_path, output_dir)
    (output_dir / "request_snapshot.json").write_text(
        json.dumps(request, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    requested_rule_id = request.get("rule_id") if isinstance(request.get("rule_id"), str) else None
    semantic = classify_source(input_path, requested_rule_id=requested_rule_id)
    study_model = study_model_from_request(request=request, semantic=semantic, input_path=input_path)
    final_recipe: str | None = None

    use_auto = request.get("recipe") == "auto" or (
        not request.get("recipe") and not request.get("template")
    )
    if use_auto:
        if semantic.get("needs_ai_intervention"):
            intervention = build_intervention_request(
                input_path=input_path,
                output_dir=output_dir,
                semantic=semantic,
                request=request,
            )
            (output_dir / "intervention_request.json").write_text(
                json.dumps(json_safe(intervention), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            raise ValueError(
                "SciPlot could not auto-detect this input. "
                f"Intervention request written to {output_dir / 'intervention_request.json'}."
            )
        route = "auto"
        final_recipe = semantic.get("recommended_recipe")
        prepared = prepare_semantic_source(
            input_path,
            output_dir=output_dir,
            semantic=semantic,
            curation_path=_resolve_optional_request_path(request.get("curation"), base_dir=base_dir),
            series_order=request.get("series_order"),
            column_confirmations=request.get("column_confirmations"),
            replicate_mode=request.get("replicate_mode"),
        )
        render_options = dict(semantic.get("render_options") or {})
        request_render_options = request.get("render_options")
        if isinstance(request_render_options, dict):
            render_options.update(request_render_options)
        template = request.get("template") or semantic["template"]
        result = render_to_dir(
            Path(str(prepared["source"])),
            template=str(template),
            output_dir=output_dir / "figures",
            options=render_options,
            export_formats=request.get("exports"),
        )
        processed_source = Path(str(prepared["processed_source"])) if prepared["processed_source"] else None
        analysis_metrics = compute_analysis_metrics(
            source_path=input_path,
            processed_source=processed_source,
            semantic=semantic,
            output_dir=output_dir,
        )
        result = {
            **result,
            "semantic_family": semantic["semantic_family"],
            "rule_id": semantic.get("rule_id"),
            "final_recipe": final_recipe,
            "processed": prepared["processed"],
            "processed_source": prepared["processed_source"],
            "analysis_metrics": analysis_metrics,
        }
        _write_auto_report(
            output_dir,
            request=request,
            result=result,
            semantic=semantic,
            final_recipe=final_recipe,
        )
    elif request.get("recipe"):
        route = "recipe"
        final_recipe = str(request["recipe"])
        result = run_recipe(
            str(request["recipe"]),
            input_path,
            output_dir=output_dir,
            options=_request_options(request),
        )
    else:
        route = "render"
        template = request.get("template")
        if not isinstance(template, str) or not template.strip():
            raise ValueError("Plot requests without `recipe` must define a non-empty `template`.")
        render_options = request.get("render_options")
        result = render_to_dir(
            input_path,
            template=template,
            output_dir=output_dir / "figures",
            options=render_options if isinstance(render_options, dict) else {},
            export_formats=request.get("exports"),
        )
        _write_render_report(output_dir, request=request, result=result)

    qa = run_qa(output_dir)
    figures = _figures_from_result(result)
    analysis_metrics = result.get("analysis_metrics") if isinstance(result.get("analysis_metrics"), list) else []
    study_model = attach_run_artifacts_to_study_model(
        study_model,
        output_dir=output_dir,
        figures=figures,
        analysis_metrics=analysis_metrics,
        qa=qa,
    )
    manifest = {
        "kind": "sciplot_run",
        "created_at": datetime.now(UTC).isoformat(),
        "request_path": str(request_path),
        "request": json_safe(request),
        "route": route,
        "semantic": json_safe(semantic),
        "final_recipe": final_recipe,
        "input": str(input_path),
        "raw_archive": json_safe(raw_archive),
        "output": str(output_dir),
        "figures": figures,
        "result": json_safe(result),
        "study_model": json_safe(study_model),
        "qa": qa,
    }
    manifest["revision_brief"] = _write_revision_brief(output_dir, manifest=manifest)
    _write_review_html(output_dir, manifest=manifest)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["package_contract"] = build_output_package_contract(output_dir, manifest=manifest)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _update_intake_project_after_run(request_path, manifest)
    return manifest


__all__ = ["run_request"]
