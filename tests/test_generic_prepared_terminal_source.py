from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from sciplot_core.studio_core import series_request
from sciplot_core.workflow import request_rendering
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent


RULE_ID = "rheology_stress_relaxation"


def test_semantic_workflow_marks_generic_terminal_source_prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared_source = tmp_path / "prepared.csv"
    semantic_step = {"id": "semantic_preparation", "operation": "normalize"}
    render_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        request_rendering,
        "prepare_semantic_source",
        lambda *_args, **_kwargs: {
            "source": str(prepared_source),
            "processed": True,
            "processed_source": str(prepared_source),
            "transform_steps": [semantic_step],
        },
    )
    monkeypatch.setattr(
        request_rendering,
        "_render_with_auto_split",
        lambda *_args, **kwargs: render_calls.append(kwargs)
        or {"qa_reports": []},
    )
    monkeypatch.setattr(
        request_rendering,
        "compute_analysis_metrics",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        request_rendering,
        "_write_auto_report",
        lambda *_args, **_kwargs: None,
    )

    transform_steps: list[dict[str, Any]] = []
    rendered = request_rendering._render_semantic_plan_request(
        request={},
        route_intent=resolve_workflow_route_intent({}),
        semantic={
            "semantic_family": RULE_ID,
            "rule_id": RULE_ID,
            "template": "curve",
        },
        study_model={},
        input_path=tmp_path / "raw",
        output_dir=tmp_path / "out",
        base_dir=tmp_path,
        transform_steps=transform_steps,
        selected_figure_plan=None,
        final_recipe=None,
        named_recipe_binding=None,
    )

    assert rendered.plotted_data_source == prepared_source
    assert transform_steps == [semantic_step]
    assert len(render_calls) == 1
    assert render_calls[0]["_terminal_source_prepared"] is True


def test_prepared_terminal_source_skips_second_semantic_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared_source = tmp_path / "relaxation_prepared.csv"
    pd.DataFrame(
        [
            ["Time", "Normalized stress", "Time", "Normalized stress"],
            ["s", "", "s", ""],
            ["E2", "E2", "E3", "E3"],
            [0.13, 1.0, 0.29, 1.0],
            [0.4, 0.82, 0.51, 0.74],
            [1.4, 0.55, 1.7, 0.42],
        ]
    ).to_csv(prepared_source, header=False, index=False)
    monkeypatch.setattr(
        series_request,
        "_studio_source_for_request",
        lambda *_args, **_kwargs: pytest.fail(
            "prepared terminal source entered semantic preparation twice"
        ),
    )

    series, axis_info, transform_steps, source_root = (
        series_request._series_from_request(
            {
                "input": str(prepared_source),
                "rule_id": RULE_ID,
                "template": "curve",
                "series_order": ["E2", "E3"],
            },
            base_dir=tmp_path,
            _terminal_source_prepared=True,
        )
    )

    assert source_root == prepared_source.resolve()
    assert transform_steps == []
    assert [item.label for item in series] == ["E2", "E3"]
    assert [item.x_values[0] for item in series] == [0.13, 0.29]
    assert [item.y_values[0] for item in series] == [1.0, 1.0]
    assert axis_info["semantic_terminal_series_order"] == ["E2", "E3"]
