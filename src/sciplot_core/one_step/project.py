"""Assemble the complete one-step project contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import slug
from sciplot_core.policy import (
    LayoutPolicy,
    layout_policy_payload,
)
from sciplot_core.readiness import (
    evaluate_validated_envelope,
)

from sciplot_core.one_step.quality_catalog import (
    ONE_STEP_MODEL_KIND,
    ONE_STEP_MODEL_VERSION,
)

from sciplot_core.one_step.confidence import (
    _now,
)

from sciplot_core.one_step.packages import (
    build_source_package,
    build_mapping_package,
    build_render_request_package,
    build_figure_qa_report,
)

from sciplot_core.one_step.readiness import (
    _readiness,
)

from sciplot_core.one_step.intervention import (
    build_intervention_package,
)


def build_one_step_project(
    *,
    input_path: Path,
    request_path: Path,
    request: dict[str, Any],
    semantic: dict[str, Any],
    raw_archive: dict[str, Any] | None,
    study_model: dict[str, Any] | None,
    layout_policy: LayoutPolicy,
    layout_quality: dict[str, Any] | None,
    qa: dict[str, Any] | None,
    delivery_package: dict[str, Any] | None = None,
    intervention_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_package = build_source_package(
        input_path=input_path, raw_archive=raw_archive, semantic=semantic
    )
    mapping_package = build_mapping_package(
        request=request, semantic=semantic, study_model=study_model
    )
    render_request = build_render_request_package(
        request_path=request_path, request=request
    )
    figure_qa_report = build_figure_qa_report(
        qa=qa,
        layout_quality=layout_quality,
        delivery_package=delivery_package,
    )
    validated_envelope = evaluate_validated_envelope(
        semantic=semantic,
        source_package=source_package,
        mapping_package=mapping_package,
        render_request=render_request,
    )
    state, reasons = _readiness(
        source_package=source_package,
        mapping_package=mapping_package,
        render_request=render_request,
        figure_qa_report=figure_qa_report,
        validated_envelope=validated_envelope,
    )
    return {
        "kind": ONE_STEP_MODEL_KIND,
        "version": ONE_STEP_MODEL_VERSION,
        "created_at": _now(),
        "project": slug(Path(request_path).parent.name or Path(input_path).stem),
        "state": state,
        "state_reasons": reasons,
        "source_package": source_package,
        "mapping_package": mapping_package,
        "render_request": render_request,
        "layout_policy": layout_policy_payload(layout_policy),
        "figure_qa_report": figure_qa_report,
        "validated_envelope": validated_envelope,
        "intervention_package": build_intervention_package(
            intervention_request=intervention_request,
            state=state,
            figure_qa_report=figure_qa_report,
        ),
        "delivery_package": json_safe(delivery_package or {}),
    }
