"""Allocate project runs and persist run status and review metadata."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.figure_plan import sync_figure_plan_projection
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import (
    slug,
)
from sciplot_core.project_manifest import (
    edit_intake_project_manifest,
    read_intake_project_manifest,
)
from sciplot_core.one_step import build_quality_actions


def _object_field(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def _array_field(payload: dict[str, Any], name: str) -> list[Any]:
    value = payload.get(name)
    return value if isinstance(value, list) else []


def _write_one_step_status(output_dir: Path, payload: dict[str, Any]) -> None:
    (output_dir / "one_step_status.json").write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _next_run_dir(project_dir: Path) -> Path:
    runs_dir = project_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = runs_dir / f"run_{index:03d}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            index += 1
        else:
            return candidate


def _one_step_project_dir(
    input_path: Path, output_root: Path, project_name: str | None
) -> Path:
    name = (
        project_name
        or (input_path.stem if input_path.is_file() else input_path.name)
        or "sciplot_project"
    )
    return output_root / slug(name)


def _write_revision_brief(output_dir: Path, *, manifest: dict[str, Any]) -> str:
    figures = [
        Path(path) for path in manifest.get("figures", []) if isinstance(path, str)
    ]
    figure_lines = []
    for figure in figures:
        rel = (
            figure.relative_to(output_dir)
            if figure.exists() and figure.is_relative_to(output_dir)
            else figure
        )
        figure_lines.append(f"- `{rel}`")
    semantic = _object_field(manifest, "semantic")
    request = _object_field(manifest, "request")
    size = ""
    render_options = _object_field(request, "render_options")
    if isinstance(render_options.get("size"), str):
        size = str(render_options["size"])
    layout_quality = _object_field(manifest, "layout_quality")
    layout_issue_ids = _array_field(layout_quality, "issue_ids")
    layout_autofixes = _array_field(layout_quality, "autofixes_applied")
    quality_actions = build_quality_actions(
        issue_ids=[str(item) for item in layout_issue_ids],
        autofixes_applied=[str(item) for item in layout_autofixes],
        layout_summaries=_array_field(layout_quality, "summaries"),
    )
    quality_action_lines = [
        f"- `{action.get('status', 'suggested')}` {action.get('label', action.get('id', 'Quality action'))}: "
        f"{action.get('reason', '')}"
        for action in quality_actions
    ]
    split_plan = _object_field(layout_quality, "split_plan")
    if split_plan:
        split_policy = _object_field(split_plan, "policy")
        split_mode = split_policy.get("mode", "")
        split_line = (
            f"- Split: applied=`{bool(split_plan.get('applied'))}`, "
            f"chunks=`{split_plan.get('chunk_count', 0)}`, "
            f"policy=`{split_mode}`"
        )
    else:
        split_line = "- Split: none"
    lines = [
        "# SciPlot Revision Brief",
        "",
        "Use this brief for optional assisted repair of the SciPlot rule, recipe, style, or cleanup path.",
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
        f"- Layout review mode: `{layout_quality.get('review_mode') or 'structured_qa_only'}`",
        f"- Assisted repair suggested: `{bool(layout_quality.get('needs_ai_intervention', False))}`",
        "",
        "## Figures",
        "",
        *(figure_lines or ["- No figures were recorded."]),
        "",
        "## Layout QA",
        "",
        f"- Issues: `{', '.join(str(item) for item in layout_issue_ids) if layout_issue_ids else 'none'}`",
        f"- Autofixes: `{', '.join(str(item) for item in layout_autofixes) if layout_autofixes else 'none'}`",
        split_line,
        "- Review source: structured QA summaries in `manifest.json`; image review is only needed for "
        "QA failures or explicit visual review requests.",
        "",
        "## Quality Actions",
        "",
        *(quality_action_lines or ["- No QA repair actions were suggested."]),
        "",
        "## Assisted Repair Request",
        "",
        "请按这些修改意见调整 SciPlot 规则、样式或数据整理路径，然后重新导出：",
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


def _project_manifest_after_run(existing_project_manifest: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive the complete run registration without native preparation or IO."""
    project_manifest = deepcopy(existing_project_manifest)
    manifest = deepcopy(manifest)
    project_manifest["last_run"] = {
        "completed_at": manifest["created_at"],
        "output": manifest["output"],
        "figures": manifest["figures"],
        "analysis_metrics": manifest.get("result", {}).get("analysis_metrics", []),
        "qa": manifest.get("qa", {}),
        "revision_brief": manifest.get("revision_brief"),
        "package_contract": manifest.get("package_contract", {}),
        "delivery_package": manifest.get("delivery_package", {}),
        "layout_quality": manifest.get("layout_quality", {}),
        "one_step": manifest.get("one_step", {}),
        "publication_intent": manifest.get("publication_intent", {}),
        "transform_ledger": manifest.get("transform_ledger", {}),
        "journal_profile": manifest.get("journal_profile", {}),
        "publication_qa": manifest.get("publication_qa", {}),
    }
    if isinstance(manifest.get("study_model"), dict):
        project_manifest["study_model"] = manifest["study_model"]
        project_manifest["last_run"]["study_model"] = manifest["study_model"]
    if isinstance(manifest.get("package_contract"), dict):
        project_manifest["package_contract"] = manifest["package_contract"]
    if isinstance(manifest.get("layout_quality"), dict):
        project_manifest["layout_quality"] = manifest["layout_quality"]
    if isinstance(manifest.get("delivery_package"), dict):
        project_manifest["delivery_package"] = manifest["delivery_package"]
    if isinstance(manifest.get("one_step"), dict):
        project_manifest["one_step"] = manifest["one_step"]
    sync_figure_plan_projection(project_manifest, manifest)
    sync_figure_plan_projection(project_manifest["last_run"], manifest)
    for key in (
        "publication_intent",
        "transform_ledger",
        "journal_profile",
        "publication_qa",
    ):
        if isinstance(manifest.get(key), dict):
            project_manifest[key] = manifest[key]
    return project_manifest


def _update_intake_project_after_run(
    request_path: Path, manifest: dict[str, Any]
) -> None:
    project_dir = request_path.parent
    if read_intake_project_manifest(project_dir) is None:
        return
    from sciplot_core.intake.packaging import (
        _prepare_studio_project_package,
        refresh_intake_project_zip,
    )

    # Studio preparation may refresh the Studio block. Complete that lifecycle
    # before deriving the final project state so a failed preparation does not
    # publish new run metadata beside an older project ZIP.
    _prepare_studio_project_package(project_dir)
    with edit_intake_project_manifest(
        project_dir,
        require_existing=True,
    ) as project_manifest:
        assert project_manifest is not None
        updated = _project_manifest_after_run(project_manifest, manifest)
        project_manifest.clear()
        project_manifest.update(updated)
    refresh_intake_project_zip(project_dir)
