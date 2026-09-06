"""Create a resumable native project from a verified public scientific plan."""

from __future__ import annotations

import json
import io
from contextlib import redirect_stdout
from typing import Any

from sciplot_core.output_contract import UserOutputLayout, resolve_user_output_layout
from sciplot_core.cli.value_io import _print_json
from sciplot_core.plan_preview import verify_expected_plan
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.studio_core.studio_command import run_studio_command


def _require_new_layout(layout: UserOutputLayout) -> None:
    for path in (layout.delivery_root, layout.workspace_root):
        canonical_path(path)
        if path.exists():
            raise ValueError(
                f"Project creation requires a new delivery and workspace: {path}. "
                "Inspect an existing project or choose a new --out directory."
            )


def _creation_result(payload: dict[str, Any], returncode: int) -> dict[str, Any]:
    """Project the existing Studio receipt without duplicating scientific arrays."""
    run = payload.get("studio_run")
    if not isinstance(run, dict):
        raise ValueError("Studio creation returned no managed export result.")
    ready = returncode == 0 and run.get("ready_to_use") is True
    state = run.get("state")
    reason = run.get("failure_reason")
    if returncode and not reason:
        reason = f"Studio creation returned exit status {returncode}."
    if not ready and not reason:
        reason = "The created project did not pass its export and delivery gates."
    if not ready and state == "ready":
        state = "failed"
    delivery_value = run.get("delivery_package")
    delivery = delivery_value if isinstance(delivery_value, dict) else {}
    registry_value = payload.get("figure_set")
    registry = registry_value if isinstance(registry_value, dict) else {}
    artifacts = delivery.get("figures") or []
    figures = []
    for item in registry.get("figures", []):
        if not isinstance(item, dict):
            continue
        figures.append(
            {
                "figure_id": item.get("figure_id"),
                "title": item.get("title"),
                "document": item.get("document"),
                "exports": [
                    {"format": artifact.get("format"), "path": artifact.get("path")}
                    for artifact in artifacts
                    if isinstance(artifact, dict)
                    and artifact.get("figure_id") == item.get("figure_id")
                ],
            }
        )
    return {
        "kind": "sciplot_project_creation_result",
        "version": 1,
        "status": "created" if ready else "blocked",
        "project_dir": payload.get("project_dir"),
        "document": payload.get("document"),
        "request": payload.get("request"),
        "primary_figure_id": registry.get("primary_figure_id"),
        "figures": figures,
        "studio_run": {
            "ready_to_use": ready,
            "state": state,
            "manifest": run.get("manifest"),
            "delivery_package": {
                "path": delivery.get("path"),
                "complete": delivery.get("complete") is True,
            },
            "failure_stage": run.get("failure_stage"),
            "failure_reason": reason,
        },
    }


def dispatch_project_create(args: Any) -> int:
    """Validate before output allocation and reuse Studio's one preparation/export."""
    source = canonical_path(args.target)
    plan_path = canonical_path(args.expected_plan)
    expected = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(expected, dict):
        raise ValueError("--expected-plan requires the complete successful plan JSON.")
    rule_id, template = expected.get("rule_id"), expected.get("template")
    if (rule_id is not None and not isinstance(rule_id, str)) or not isinstance(
        template, str
    ):
        raise ValueError("The expected plan has invalid rule/template identities.")
    verified = verify_expected_plan(
        source, expected, rule_id=rule_id, template=template
    )
    visible = canonical_path(args.out) if args.out is not None else None
    layout = resolve_user_output_layout(source, requested_delivery_root=visible)
    _require_new_layout(layout)

    # Lock the workspace identity, so distinct visible spellings that normalize
    # to one workspace cannot race. Validation above leaves stale plans zero-write.
    canonical_path(layout.workspace_root.parent)
    layout.workspace_root.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(layout.workspace_root):
        _require_new_layout(layout)
        original = [
            "project",
            "create",
            str(source),
            "--expected-plan",
            str(plan_path),
            "--json",
        ]
        if visible is not None:
            original.extend(["--out", str(visible)])
        captured = io.StringIO()
        with redirect_stdout(captured):
            returncode = run_studio_command(
                target=source,
                output_root=layout.workspace_root / "projects",
                delivery_root=layout.delivery_root,
                rule_id=verified["rule_id"],
                template=verified["template"],
                export="pdf,tiff_300",
                json_output=True,
                original_argv=original,
            )
        payload = json.loads(captured.getvalue())
        if not isinstance(payload, dict):
            raise ValueError("Studio creation returned an invalid JSON result.")
        result = _creation_result(payload, returncode)
        _print_json(result)
        return returncode or (0 if result["status"] == "created" else 1)


__all__ = ["dispatch_project_create"]
