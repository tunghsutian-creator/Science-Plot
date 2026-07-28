"""Extract compact figure QA status."""

from __future__ import annotations

from typing import Any


def _figure_qa(one_step: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    figure_qa = (
        one_step.get("figure_qa_report")
        if isinstance(one_step.get("figure_qa_report"), dict)
        else {}
    )
    if figure_qa:
        return figure_qa
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    figure_qa = (
        manifest_one_step.get("figure_qa_report")
        if isinstance(manifest_one_step.get("figure_qa_report"), dict)
        else {}
    )
    return figure_qa
