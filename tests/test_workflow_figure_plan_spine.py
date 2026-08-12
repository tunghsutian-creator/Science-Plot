from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import sciplot_core.workflow.auto_split as auto_split
import sciplot_core.workflow.rheology_bundle as rheology_bundle
import sciplot_core.workflow.rheology_task_plan as rheology_task_plan
import sciplot_core.workflow.rheology_task_sources as rheology_task_sources
from sciplot_core.figure_plan.frequency_resolution import resolve_frequency_plan
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.terminal_request import project_terminal_render_request


def _frequency_source(path: Path) -> None:
    pd.DataFrame(
        [
            ["Angular Frequency", "Storage Modulus"],
            ["Sample A", "Sample A"],
            ["rad/s", "Pa"],
            [1.0, 100.0],
            [10.0, 120.0],
        ]
    ).to_excel(path, header=False, index=False)


def test_frequency_render_spine_reuses_one_typed_plan_and_parses_once_on_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "frequency.xlsx"
    _frequency_source(source)
    plan = resolve_frequency_plan(
        study_model={},
        input_path=source,
        request={},
    )
    assert plan is not None
    payload = plan.to_payload()
    request = {
        "rule_id": "rheology_frequency_sweep",
        "template": "point_line",
        "resolved_figure_plan": payload,
    }

    original_bundle = rheology_bundle._render_veusz_sweep_bundle
    original_source_builder = rheology_task_sources.build_rheology_task_sources
    original_selector = rheology_task_plan.selected_frequency_metric_keys
    spine_plans: list[object] = []
    terminal_tasks: list[dict[str, Any]] = []

    def selector_spy(
        available_metrics: list[str],
        *,
        request: dict[str, Any],
        _resolved_figure_plan: object = None,
    ) -> list[str]:
        assert _resolved_figure_plan is spine_plans[-1]
        return original_selector(
            available_metrics,
            request=request,
            _resolved_figure_plan=_resolved_figure_plan,
        )

    def source_builder_spy(source_path: Path, **kwargs: Any) -> Any:
        assert kwargs["_resolved_figure_plan"] is spine_plans[-1]
        return original_source_builder(source_path, **kwargs)

    def renderer_spy(source_path: Path, **kwargs: Any) -> dict[str, Any]:
        context = kwargs["request_context"]
        current_plan = spine_plans[-1]
        assert context["resolved_figure_task"] == current_plan.tasks[0].to_payload()
        terminal_tasks.append(context["resolved_figure_task"])
        render_dir = Path(kwargs["output_dir"])
        render_dir.mkdir(parents=True, exist_ok=True)
        exported = render_dir / f"{source_path.stem}.pdf"
        exported.write_bytes(b"typed figure plan spine")
        return {
            "exports": [{"path": str(exported), "format": "pdf"}],
            "outputs": [str(exported)],
            "qa_reports": [],
            "veusz_documents": [],
            "veusz_specs": [],
            "terminal_render_requests": [
                project_terminal_render_request(
                    template=kwargs["template"],
                    render_options=kwargs["options"],
                    request_context=context,
                )
            ],
        }

    def bundle_spy(input_path: Path, **kwargs: Any) -> dict[str, Any] | None:
        spine_plans.append(kwargs["_resolved_figure_plan"])
        return original_bundle(
            input_path,
            **kwargs,
            _source_builder=source_builder_spy,
            _renderer=renderer_spy,
        )

    monkeypatch.setattr(
        rheology_task_sources,
        "selected_frequency_metric_keys",
        selector_spy,
    )
    monkeypatch.setattr(auto_split, "_render_veusz_sweep_bundle", bundle_spy)

    parser_owners = (
        auto_split,
        rheology_bundle,
        rheology_task_sources,
        rheology_task_plan,
    )

    def reject_reparse(_value: object) -> None:
        raise AssertionError("typed Workflow plan was reparsed from request payload")

    for owner in parser_owners:
        monkeypatch.setattr(owner, "resolved_figure_plan_from_payload", reject_reparse)

    typed = auto_split._render_with_auto_split(
        source,
        template="point_line",
        output_dir=tmp_path / "typed",
        options={},
        export_formats=("pdf",),
        request=request,
        _resolved_figure_plan=plan,
    )

    assert spine_plans == [plan]
    assert spine_plans[0] is plan
    assert typed["multi_metric_bundle"]["figure_ids"] == list(
        plan.selected_figure_ids
    )

    parse_calls: list[object] = []

    def parse_once(value: object) -> Any:
        parse_calls.append(value)
        return resolved_figure_plan_from_payload(value)

    for owner in parser_owners:
        monkeypatch.setattr(owner, "resolved_figure_plan_from_payload", parse_once)

    fallback = auto_split._render_with_auto_split(
        source,
        template="point_line",
        output_dir=tmp_path / "fallback",
        options={},
        export_formats=("pdf",),
        request=request,
    )

    assert parse_calls == [payload]
    assert spine_plans[1] == plan
    assert fallback["multi_metric_bundle"]["figure_ids"] == list(
        plan.selected_figure_ids
    )
    assert terminal_tasks == [plan.tasks[0].to_payload()] * 2
