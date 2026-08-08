from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core import workflow
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.delivery.plan_binding import plan_source_figure_ids
from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_FIGURE_ID,
    DMA_TEMPERATURE_RULE_ID,
)
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.materials_rules import get_rule
from sciplot_core.studio_core.prepare_generated import generate_studio_document


EXPECTED_SAMPLE_ORDER = [
    "PBAT",
    "5 wt% UDC 2",
    "5 wt% UDC 3",
    "5 wt% UDC 4",
]


def _fixture() -> Path:
    source = resolve_fixture_path(
        str(get_rule(DMA_TEMPERATURE_RULE_ID).fixture_path or "")
    )
    assert source.is_file()
    return source


def _write_project(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "input": str(_fixture()),
                "rule_id": DMA_TEMPERATURE_RULE_ID,
                "template": "point_line",
                "explicit_template_selection": True,
                "explicit_render_option_keys": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return project_dir, request_path


def _assert_dma_spec(spec: dict[str, object], plan: ResolvedFigurePlan) -> None:
    assert (
        spec["source_request"]["resolved_figure_task"]
        == plan.tasks[  # type: ignore[index]
            0
        ].to_payload()
    )
    series = spec["series"]  # type: ignore[assignment]
    assert [item["label"] for item in series] == EXPECTED_SAMPLE_ORDER
    assert sum(len(item["y_values"]) for item in series) == 4074
    assert sum(value < 0.0 for item in series for value in item["y_values"]) == 1
    visibility = spec["axis_data_visibility"]["axes"]["y"]  # type: ignore[index]
    assert visibility["below_configured_min_count"] == 1
    assert visibility["configured_min_relaxed"] is True
    assert visibility["clipped_coordinate_count"] == 0
    assert visibility["data_min"] == pytest.approx(-0.00076029)
    assert spec["axes"]["y"]["min"] < 0.0  # type: ignore[index]


def _dma_preparation_step(ledger: dict[str, object]) -> dict[str, object]:
    return next(
        step
        for step in ledger["steps"]  # type: ignore[index]
        if step.get("operation") == "extract_and_convert_dma_temperature_curves"
    )


@pytest.mark.comprehensive
def test_dma_studio_activates_one_source_bound_task_and_spec(tmp_path: Path) -> None:
    project_dir, request_path = _write_project(tmp_path)

    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=DMA_TEMPERATURE_RULE_ID,
        template=None,
        project_name=None,
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    assert plan.selected_figure_ids == (DMA_TEMPERATURE_FIGURE_ID,)
    assert list(plan.tasks[0].sample_order) == EXPECTED_SAMPLE_ORDER
    registry = json.loads(
        (project_dir / "studio" / "figure_set.json").read_text(encoding="utf-8")
    )
    assert registry["version"] == 2
    assert [item["figure_id"] for item in registry["figures"]] == [
        DMA_TEMPERATURE_FIGURE_ID
    ]
    document = Path(str(prepared["document"]))
    spec = json.loads(document.with_name("spec.json").read_text(encoding="utf-8"))
    _assert_dma_spec(spec, plan)
    assert spec["source_request"]["study_model"]["figure_queue"][0]["id"] == (
        DMA_TEMPERATURE_FIGURE_ID
    )
    step = _dma_preparation_step(request["transform_ledger"])
    parameters = step["parameters"]
    assert parameters["canonical_y_unit"] == "Pa"
    assert parameters["display_y_unit"] == "MPa"
    assert parameters["negative_display_point_count"] == 1
    assert parameters["configured_default_y_min"] == 0.0
    assert parameters["below_configured_default_y_min_count"] == 1
    assert parameters["final_axis_clipping_authority"] == ("spec.axis_data_visibility")
    assert parameters["source_attestation"]["source_tree_sha256_after"] == (
        plan.source_sha256
    )


@pytest.mark.comprehensive
def test_dma_workflow_delivers_the_same_completed_single_task(tmp_path: Path) -> None:
    request_path = tmp_path / "workflow_request.json"
    output_dir = tmp_path / "workflow_output"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(_fixture()),
                "output": str(output_dir),
                "rule_id": DMA_TEMPERATURE_RULE_ID,
                "exports": ["pdf", "tiff_300"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = workflow.run_request(request_path)

    plan = ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"])
    assert plan.status == "ready"
    assert plan.selected_figure_ids == (DMA_TEMPERATURE_FIGURE_ID,)
    assert len(manifest["result"]["veusz_specs"]) == 1
    assert len(manifest["result"]["veusz_documents"]) == 1
    assert (
        manifest["result"]["terminal_render_requests"][0]["resolved_figure_task"]
        == plan.tasks[0].to_payload()
    )
    spec = json.loads(
        Path(manifest["result"]["veusz_specs"][0]).read_text(encoding="utf-8")
    )
    _assert_dma_spec(spec, plan)
    assert plan_source_figure_ids(plan) == {
        artifact: DMA_TEMPERATURE_FIGURE_ID
        for artifact in plan.outcomes[0].artifacts
        if Path(artifact).suffix.casefold() in {".vsz", ".pdf", ".tiff"}
    }
    delivery = manifest["delivery_package"]
    assert [item["figure_id"] for item in delivery["project_documents"]] == [
        DMA_TEMPERATURE_FIGURE_ID
    ]
    assert {item["figure_id"] for item in delivery["figures"]} == {
        DMA_TEMPERATURE_FIGURE_ID
    }
    assert len(delivery["project_documents"]) == 1
    assert len(delivery["figures"]) == 2
    step = _dma_preparation_step(manifest["transform_ledger"])
    assert step["parameters"]["negative_display_point_count"] == 1
    assert manifest["publish_gates"]["passed"] is True
