from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe
from sciplot_core.workflow import run_one_step

AUTOPLOT_MODEL_KIND = "sciplot_autoplot_result"
AUTOPLOT_MODEL_VERSION = 1


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _truthy_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _manifest_path(run_output: Path) -> Path:
    return run_output / "manifest.json"


def _one_step_status_path(run_output: Path) -> Path:
    return run_output / "one_step_status.json"


def _delivery_package(one_step: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    for payload in (one_step.get("delivery_package"), manifest.get("delivery_package")):
        if isinstance(payload, dict):
            return payload
    return {}


def _figure_qa(one_step: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    figure_qa = one_step.get("figure_qa_report") if isinstance(one_step.get("figure_qa_report"), dict) else {}
    if figure_qa:
        return figure_qa
    manifest_one_step = manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    figure_qa = (
        manifest_one_step.get("figure_qa_report")
        if isinstance(manifest_one_step.get("figure_qa_report"), dict)
        else {}
    )
    return figure_qa


def _intervention_package(one_step: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    intervention = (
        one_step.get("intervention_package") if isinstance(one_step.get("intervention_package"), dict) else {}
    )
    if intervention:
        return intervention
    manifest_one_step = manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    intervention = (
        manifest_one_step.get("intervention_package")
        if isinstance(manifest_one_step.get("intervention_package"), dict)
        else {}
    )
    return intervention


def _route_package(one_step: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    source = one_step.get("source_package") if isinstance(one_step.get("source_package"), dict) else {}
    mapping = one_step.get("mapping_package") if isinstance(one_step.get("mapping_package"), dict) else {}
    render_request = (
        one_step.get("render_request") if isinstance(one_step.get("render_request"), dict) else {}
    )
    semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    return {
        "mode": "one_step",
        "source_kind": source.get("source_kind") or "unknown",
        "semantic_family": mapping.get("semantic_family") or semantic.get("semantic_family") or "unknown",
        "rule_id": mapping.get("rule_id") or semantic.get("rule_id"),
        "confidence_band": source.get("confidence_band") or mapping.get("confidence_band") or "unknown",
        "recipe": render_request.get("recipe"),
        "template": render_request.get("template") or manifest.get("result", {}).get("template"),
        "figure_size": render_request.get("figure_size"),
        "exports": render_request.get("exports") or [],
    }


def build_autoplot_summary(one_step_result: dict[str, Any]) -> dict[str, Any]:
    run_output = _truthy_path(one_step_result.get("run_output")) or Path(".")
    project_dir = _truthy_path(one_step_result.get("project_dir")) or run_output.parent
    status_path = _one_step_status_path(run_output)
    manifest_path = _manifest_path(run_output)
    one_step = one_step_result.get("one_step") if isinstance(one_step_result.get("one_step"), dict) else {}
    if not one_step:
        one_step = _read_json_if_exists(status_path)
    manifest = _read_json_if_exists(manifest_path)
    if not one_step and isinstance(manifest.get("one_step"), dict):
        one_step = manifest["one_step"]

    state = str(one_step_result.get("status") or one_step.get("state") or "needs_rule_repair")
    delivery = _delivery_package(one_step, manifest)
    figure_qa = _figure_qa(one_step, manifest)
    intervention = _intervention_package(one_step, manifest)
    delivery_path = _truthy_path(delivery.get("path"))
    delivery_complete = bool(delivery.get("complete"))
    image_review_required = bool(figure_qa.get("image_review_required"))
    codex_required = bool(intervention.get("required")) or state == "needs_rule_repair"

    summary = {
        "kind": AUTOPLOT_MODEL_KIND,
        "version": AUTOPLOT_MODEL_VERSION,
        "state": state,
        "ready_to_use": state == "ready" and delivery_complete,
        "project_dir": str(project_dir),
        "run_output": str(run_output),
        "request_path": one_step_result.get("request_path"),
        "manifest": str(manifest_path) if manifest_path.exists() else None,
        "one_step_status": str(status_path) if status_path.exists() else None,
        "delivery": str(delivery_path) if delivery_path is not None else None,
        "delivery_complete": delivery_complete,
        "review_html": str(run_output / "review.html") if (run_output / "review.html").exists() else None,
        "revision_brief": str(run_output / "revision_brief.md")
        if (run_output / "revision_brief.md").exists()
        else None,
        "route": _route_package(one_step, manifest),
        "quality": {
            "qa_status": figure_qa.get("qa_status"),
            "layout_review_mode": figure_qa.get("layout_review_mode") or "structured_qa_only",
            "issue_ids": figure_qa.get("issue_ids") or [],
            "quality_actions": figure_qa.get("quality_actions") or [],
            "image_review_required": image_review_required,
        },
        "token_policy": {
            "default_codex_context": "structured_qa_summary",
            "codex_reads_images_by_default": False,
            "image_review_required": image_review_required,
            "image_review_allowed_only_when": [
                "qa_failure",
                "low_confidence_semantics",
                "explicit_user_request",
            ],
            "codex_role": "rule_repair_or_user_requested_visual_refinement",
        },
        "codex_handoff": {
            "required": codex_required,
            "read_first": [
                path
                for path in (
                    str(status_path) if status_path.exists() else None,
                    str(manifest_path) if manifest_path.exists() else None,
                    str(run_output / "revision_brief.md")
                    if (run_output / "revision_brief.md").exists()
                    else None,
                )
                if path
            ],
            "image_review_required": image_review_required,
            "intervention_package": json_safe(intervention),
        },
    }
    return summary


def run_autoplot(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
) -> dict[str, Any]:
    result = run_one_step(input_path, output_root=output_root, project_name=project_name)
    summary = build_autoplot_summary(result)
    run_output = Path(str(summary["run_output"]))
    run_output.mkdir(parents=True, exist_ok=True)
    summary_path = run_output / "autoplot_summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(json_safe(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


__all__ = [
    "AUTOPLOT_MODEL_KIND",
    "AUTOPLOT_MODEL_VERSION",
    "build_autoplot_summary",
    "run_autoplot",
]
