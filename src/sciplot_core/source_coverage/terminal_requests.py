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

    if isinstance(result.get("multi_metric_bundle"), dict):
        raise ValueError(
            "Mapped multi-metric bundles require an independently persisted "
            "authoritative panel plan before they can produce source evidence."
        )
    if isinstance(result.get("auto_split"), dict):
        raise ValueError(
            "Mapped auto-split output cannot become source evidence until the "
            "split policy is explicitly confirmed in the authoritative request."
        )
    base_request = authoritative_terminal_render_request(authoritative_request)
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
