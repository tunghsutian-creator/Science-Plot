"""Resolve declared and authoritative terminal render requests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.split import build_split_plan, normalize_split_policy
from sciplot_core.terminal_request import (
    authoritative_terminal_render_request,
    normalize_terminal_render_request,
)


def _declared_terminal_render_requests(
    result: dict[str, Any],
    *,
    spec_count: int,
) -> list[dict[str, Any]] | None:
    raw_requests = result.get("terminal_render_requests")
    if raw_requests is None:
        return None
    if (
        not isinstance(raw_requests, list)
        or len(raw_requests) != spec_count
        or any(not isinstance(item, dict) for item in raw_requests)
    ):
        raise ValueError(
            "Mapped render terminal-request inventory does not match its "
            "Veusz specification inventory."
        )
    return [
        normalize_terminal_render_request(
            raw,
            label=f"terminal render request {index}",
        )
        for index, raw in enumerate(raw_requests, start=1)
    ]


def _authoritative_terminal_render_requests(
    *,
    result: dict[str, Any],
    authoritative_request: dict[str, Any],
    declared_requests: list[dict[str, Any]] | None,
    private_sources: list[Path],
    spec_count: int,
) -> list[dict[str, Any]]:
    from sciplot_core.studio_render import derive_terminal_render_data_contract

    multi_metric_bundle = result.get("multi_metric_bundle")
    if isinstance(multi_metric_bundle, dict):
        return _authoritative_task_bundle_requests(
            result=result,
            bundle=multi_metric_bundle,
            authoritative_request=authoritative_request,
            declared_requests=declared_requests,
            spec_count=spec_count,
        )
    if isinstance(result.get("auto_split"), dict):
        raise ValueError(
            "Mapped auto-split output cannot become source evidence until the "
            "split policy is explicitly confirmed in the authoritative request."
        )
    authoritative_context = _task_aware_authoritative_request(
        authoritative_request,
        declared_requests=declared_requests,
    )
    base_request = authoritative_terminal_render_request(authoritative_context)
    baseline = derive_terminal_render_data_contract(
        request=base_request,
        terminal_sources=private_sources,
    )
    baseline_units = baseline.get("units")
    if not isinstance(baseline_units, list) or not baseline_units:
        raise ValueError("Authoritative terminal request produced no baseline units.")
    split_plan = result.get("split_plan")
    requested_policy = normalize_split_policy(authoritative_request.get("split_policy"))
    expected_requests: list[dict[str, Any]]
    if split_plan is None:
        if requested_policy is not None:
            raise ValueError(
                "Mapped render omitted the explicitly confirmed split plan."
            )
        if spec_count != 1:
            raise ValueError(
                "A mapped multi-panel render has no authoritative split plan."
            )
        expected_requests = [base_request]
    else:
        if not isinstance(split_plan, dict) or requested_policy is None:
            raise ValueError(
                "Mapped render split metadata is not bound to an explicit "
                "authoritative split policy."
            )
        labels = [
            str(unit.get("label") or "")
            for unit in baseline_units
            if isinstance(unit, dict) and unit.get("kind") == "series"
        ]
        if not labels or any(not label for label in labels):
            raise ValueError(
                "Authoritative split planning requires stable series labels."
            )
        expected_plan = build_split_plan(labels, policy=requested_policy)
        if json_safe(split_plan) != json_safe(expected_plan):
            raise ValueError(
                "Mapped render split plan does not reproduce from the "
                "authoritative request and exact terminal tables."
            )
        chunks = [
            list(chunk["series"])
            for chunk in expected_plan["chunks"]
            if isinstance(chunk, dict)
        ]
        if len(chunks) != spec_count:
            raise ValueError(
                "Authoritative split plan and Veusz specification counts disagree."
            )
        expected_requests = []
        for chunk in chunks:
            panel_request = {
                **base_request,
                "render_options": {
                    **dict(base_request["render_options"]),
                    "series_include": list(chunk),
                    "series_order": list(chunk),
                },
            }
            expected_requests.append(panel_request)
    if declared_requests is not None and declared_requests != expected_requests:
        raise ValueError(
            "Declared terminal render requests do not reproduce from the "
            "authoritative request and exact terminal tables."
        )
    return expected_requests


def _authoritative_task_bundle_requests(
    *,
    result: dict[str, Any],
    bundle: dict[str, Any],
    authoritative_request: dict[str, Any],
    declared_requests: list[dict[str, Any]] | None,
    spec_count: int,
) -> list[dict[str, Any]]:
    """Rebuild a task-aware bundle from its selected FigurePlan."""

    from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
    from sciplot_core.figure_plan.terminal_binding import (
        bind_terminal_figure_evidence,
    )

    plan = resolved_figure_plan_from_payload(
        authoritative_request.get("resolved_figure_plan")
    )
    if plan is None:
        raise ValueError(
            "Task-aware multi-metric source reconstruction requires a selected "
            "FigurePlan."
        )
    request_rule = authoritative_request.get("rule_id")
    if request_rule is not None and request_rule != plan.rule_id:
        raise ValueError(
            "Authoritative terminal request rule does not match its FigurePlan."
        )
    if declared_requests is None or len(declared_requests) != spec_count:
        raise ValueError(
            "Task-aware multi-metric source reconstruction requires one declared "
            "terminal request per Veusz specification."
        )
    if bundle.get("figure_ids") != list(plan.selected_figure_ids):
        raise ValueError(
            "Mapped multi-metric bundle FigureTask inventory does not match the "
            "authoritative FigurePlan."
        )
    declared_templates = bundle.get("templates")
    if declared_templates is not None and declared_templates != [
        task.template for task in plan.tasks
    ]:
        raise ValueError(
            "Mapped multi-metric bundle template inventory does not match the "
            "authoritative FigurePlan."
        )

    binding = bind_terminal_figure_evidence(
        selected_plan=plan,
        result={
            **result,
            "terminal_render_requests": declared_requests,
        },
    )
    if binding is None or not binding.terminal_tasks:
        raise ValueError(
            "Task-aware multi-metric source reconstruction requires exact "
            "FigureTask evidence."
        )

    expected_requests: list[dict[str, Any]] = []
    for task, declared in zip(
        binding.terminal_tasks,
        declared_requests,
        strict=True,
    ):
        render_options = declared.get("render_options")
        if not isinstance(render_options, dict):
            raise ValueError(
                "Task-aware terminal render request has no render_options object."
            )
        task_context = {
            **authoritative_request,
            "rule_id": plan.rule_id,
            "template": task.template,
            "render_options": dict(render_options),
            "resolved_figure_task": task.to_payload(),
        }
        expected_requests.append(authoritative_terminal_render_request(task_context))
    if declared_requests != expected_requests:
        raise ValueError(
            "Declared terminal render requests do not reproduce from the "
            "authoritative FigurePlan and request."
        )
    return expected_requests


def _task_aware_authoritative_request(
    authoritative_request: dict[str, Any],
    *,
    declared_requests: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if not declared_requests or not any(
        "resolved_figure_task" in request for request in declared_requests
    ):
        return authoritative_request
    if any("resolved_figure_task" not in request for request in declared_requests):
        raise ValueError(
            "Declared terminal render requests mix legacy and task-aware evidence."
        )
    from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload

    plan = resolved_figure_plan_from_payload(
        authoritative_request.get("resolved_figure_plan")
    )
    if plan is None or len(plan.tasks) != 1:
        raise ValueError(
            "Task-aware authoritative terminal reconstruction requires one "
            "selected FigureTask."
        )
    request_rule = authoritative_request.get("rule_id")
    if request_rule is not None and request_rule != plan.rule_id:
        raise ValueError(
            "Authoritative terminal request rule does not match its FigurePlan."
        )
    task_payload = plan.tasks[0].to_payload()
    if any(
        request.get("resolved_figure_task") != task_payload
        for request in declared_requests
    ):
        raise ValueError(
            "Declared terminal FigureTask does not match the authoritative plan."
        )
    return {
        **authoritative_request,
        "rule_id": plan.rule_id,
        "resolved_figure_task": task_payload,
    }
