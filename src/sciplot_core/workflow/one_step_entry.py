"""Create and execute the public one-step project route."""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.policy import (
    AUTOPLOT_RENDER_OPTIONS,
    DEFAULT_EXPORT_FORMATS_POLICY,
)
from sciplot_core.request_contract import normalize_render_options

from sciplot_core.workflow.project_state import (
    _next_run_dir,
    _one_step_project_dir,
)

from sciplot_core.workflow.request_run import (
    run_request,
)


def run_one_step(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    _request_runner: Callable[[Path], dict[str, Any]] = run_request,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if rule_id is not None and (
        not isinstance(rule_id, str) or not rule_id or rule_id.strip() != rule_id
    ):
        raise ValueError("Autoplot rule_id must be one non-empty canonical identifier.")
    project_dir = _one_step_project_dir(input_path, output_root, project_name)
    project_dir.mkdir(parents=True, exist_ok=True)
    run_dir = _next_run_dir(project_dir)
    request_path = project_dir / "plot_request.json"
    request = {
        "recipe": "auto",
        "input": str(input_path),
        "output": str(run_dir),
        "exports": list(DEFAULT_EXPORT_FORMATS_POLICY),
        "render_options": normalize_render_options(AUTOPLOT_RENDER_OPTIONS),
        "explicit_render_option_keys": [],
    }
    if rule_id is not None:
        request["rule_id"] = rule_id
    if template is not None and str(template).strip():
        request["template"] = str(template).strip()
        request["explicit_template_selection"] = True
    if delivery_root is not None:
        request["delivery_output"] = str(delivery_root.expanduser().resolve())
    request_path.write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    try:
        manifest = _request_runner(request_path)
    except ValueError as exc:
        status_path = run_dir / "one_step_status.json"
        if not status_path.exists():
            raise
        status = json.loads(status_path.read_text(encoding="utf-8"))
        return {
            "kind": "sciplot_one_step_result",
            "status": status.get("state") or "needs_rule_repair",
            "project_dir": str(project_dir),
            "request_path": str(request_path),
            "run_output": str(run_dir),
            "one_step": status,
            "error": str(exc),
        }
    return {
        "kind": "sciplot_one_step_result",
        "status": manifest.get("state") or "needs_rule_repair",
        "project_dir": str(project_dir),
        "request_path": str(request_path),
        "run_output": str(run_dir),
        "one_step": manifest.get("one_step", {}),
        "manifest": manifest,
    }
