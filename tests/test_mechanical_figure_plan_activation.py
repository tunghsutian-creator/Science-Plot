from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.semantic as semantic_module
import sciplot_core.studio_core.figure_set_prepare as figure_set_prepare_module
from sciplot_core import workflow
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.delivery.plan_binding import plan_source_figure_ids
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.materials_rules import get_rule
from sciplot_core.mechanical_figure_contract import mechanical_figure_contract
from sciplot_core.policy import DEFAULT_PALETTE_COLORS, DEFAULT_PALETTE_PRESET
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.publish_run import publish_studio_export_run


EXPECTED_COUNTS = {
    "tensile_curve": 9,
    "compression_curve": 6,
    "flexural_curve": 6,
}
EXPECTED_MEDIANS = {
    "tensile_curve": {
        "strength_MPa": 34.2,
        "elongation_at_break_percent": 8.68,
        "modulus_MPa": 799.41,
        "toughness_MJ_m3": 1.99043617702,
    },
    "compression_curve": {"compressive_strength_MPa": 0.7091375},
    "flexural_curve": {"flexural_strength_MPa": 63.69094},
}


def _fixture(rule_id: str) -> Path:
    source = resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))
    assert source.exists()
    return source


def _write_project(tmp_path: Path, rule_id: str) -> tuple[Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "input": str(_fixture(rule_id)),
                "rule_id": rule_id,
                "template": "curve",
                "explicit_template_selection": True,
                "explicit_render_option_keys": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return project_dir, request_path


def _assert_palette(spec: dict[str, Any]) -> None:
    palette = spec["palette_resolution"]
    assert palette["kind"] == "sciplot_palette_resolution"
    assert palette["palette_id"] == DEFAULT_PALETTE_PRESET
    assert palette["colors"] == list(DEFAULT_PALETTE_COLORS)
    assert palette["custom_colors"] is False


def _assert_summary_spec(
    spec: dict[str, Any],
    *,
    task_payload: dict[str, Any],
    n: int,
) -> None:
    assert spec["template"] == "box_strip"
    assert spec["source_request"]["resolved_figure_task"] == task_payload
    categorical = spec["categorical"]
    assert categorical["presentation_kind"] == "box_strip"
    assert categorical["summary_statistic"] == "median_iqr"
    assert categorical["raw_values_preserved"] is True
    assert categorical["raw_replicate_count"] == n
    assert categorical["mean_marker_visible"] is False
    assert all(group["raw_points_visible"] for group in categorical["groups"])
    _assert_palette(spec)


@pytest.mark.comprehensive
def test_tensile_studio_publishes_the_complete_source_bound_figure_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_id = "tensile_curve"
    project_dir, request_path = _write_project(tmp_path, rule_id)
    preparation_calls: list[Path] = []
    real_prepare = semantic_module.prepare_semantic_source

    def prepare_spy(source: Path, **kwargs: Any) -> dict[str, Any]:
        preparation_calls.append(source.expanduser().resolve())
        return real_prepare(source, **kwargs)

    monkeypatch.setattr(semantic_module, "prepare_semantic_source", prepare_spy)
    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )

    assert preparation_calls == [_fixture(rule_id).resolve()]
    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    contract = mechanical_figure_contract(rule_id)
    assert plan.selected_figure_ids == tuple(task.figure_id for task in contract.tasks)
    assert plan.status == "planned"
    registry = json.loads(
        (project_dir / "studio" / "figure_set.json").read_text(encoding="utf-8")
    )
    assert [item["figure_id"] for item in registry["figures"]] == list(
        plan.selected_figure_ids
    )
    assert (
        ResolvedFigurePlan.from_payload(registry["resolved_figure_plan"]).status
        == "editable"
    )
    task_source_root = project_dir / "studio" / "processed" / "mechanical_task_sources"
    assert len([path for path in task_source_root.iterdir() if path.is_dir()]) == 1
    for index, (task, entry) in enumerate(
        zip(plan.tasks, registry["figures"], strict=True)
    ):
        assert entry["resolved_figure_task"] == task.to_payload()
        spec = json.loads(Path(entry["spec"]).read_text(encoding="utf-8"))
        terminal_source = (
            task_source_root
            / next(path.name for path in task_source_root.iterdir() if path.is_dir())
            / f"{task.artifact_stem}.csv"
        )
        assert Path(spec["source_request"]["input"]).resolve() == (
            terminal_source.resolve()
        )
        assert all(
            [item["path"] for item in series["source_artifacts"]]
            == [str(terminal_source.resolve())]
            for series in spec["series"]
        )
        if index == 0:
            assert spec["template"] == "curve"
            assert spec["source_request"]["resolved_figure_task"] == task.to_payload()
            _assert_palette(spec)
        else:
            _assert_summary_spec(spec, task_payload=task.to_payload(), n=9)

    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )
    assert len([path for path in task_source_root.iterdir() if path.is_dir()]) == 1
    document = Path(str(prepared["document"]))
    exported = export_studio_document(document, formats=["pdf", "tiff_300"])
    studio_run = publish_studio_export_run(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document,
        exports=exported["exports"],
        export_document_sha256=str(exported["document_sha256"]),
    )
    completed = ResolvedFigurePlan.from_payload(studio_run["resolved_figure_plan"])
    assert completed.status == "ready"
    assert all(outcome.delivery_artifacts_complete for outcome in completed.outcomes)
    delivery = studio_run["delivery_package"]
    assert delivery["full_figure_set_complete"] is True
    assert {item["figure_id"] for item in delivery["figures"]} == set(
        plan.selected_figure_ids
    )
    assert [item["figure_id"] for item in delivery["project_documents"]] == list(
        plan.selected_figure_ids
    )
    assert len(delivery["figures"]) == 2 * len(plan.tasks)
    assert len(delivery["project_documents"]) == len(plan.tasks)


@pytest.mark.comprehensive
@pytest.mark.parametrize(
    "rule_id",
    ["tensile_curve", "compression_curve", "flexural_curve"],
)
def test_mechanical_workflow_delivers_exact_real_figure_plan(
    tmp_path: Path,
    rule_id: str,
) -> None:
    request_path = tmp_path / f"{rule_id}_request.json"
    output_dir = tmp_path / f"{rule_id}_output"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(_fixture(rule_id)),
                "output": str(output_dir),
                "rule_id": rule_id,
                "exports": ["pdf", "tiff_300"],
                "explicit_render_option_keys": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = workflow.run_request(request_path)
    plan = ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"])
    contract = mechanical_figure_contract(rule_id)
    assert plan.status == "ready"
    assert plan.selected_figure_ids == tuple(task.figure_id for task in contract.tasks)
    result = manifest["result"]
    assert [
        item["resolved_figure_task"] for item in result["terminal_render_requests"]
    ] == [task.to_payload() for task in plan.tasks]
    assert len(result["veusz_documents"]) == len(plan.tasks)
    assert len(result["veusz_specs"]) == len(plan.tasks)
    assert len(result["exports"]) == 2 * len(plan.tasks)
    for index, (task, spec_path) in enumerate(
        zip(plan.tasks, result["veusz_specs"], strict=True)
    ):
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        if index == 0:
            assert spec["source_request"]["resolved_figure_task"] == task.to_payload()
            _assert_palette(spec)
        else:
            _assert_summary_spec(
                spec,
                task_payload=task.to_payload(),
                n=EXPECTED_COUNTS[rule_id],
            )

    evidence = result["mechanical_execution_evidence"]
    assert evidence["plan_sha256"] == plan.plan_sha256
    assert evidence["figure_ids"] == list(plan.selected_figure_ids)
    summary_evidence = {
        item["metric_binding"]["y_metric"]: item
        for item in evidence["tasks"]
        if item["task_kind"] == "summary"
    }
    for metric, median in EXPECTED_MEDIANS[rule_id].items():
        item = summary_evidence[metric]
        assert item["summary_groups"][0]["n"] == EXPECTED_COUNTS[rule_id]
        assert item["summary_groups"][0]["median"] == pytest.approx(median)
        assert item["raw_values_preserved"] is True
        assert item["raw_points_visible"] is True

    assert plan_source_figure_ids(plan) == {
        artifact: outcome.figure_id
        for outcome in plan.outcomes
        for artifact in outcome.artifacts
        if Path(artifact).suffix.casefold() in {".vsz", ".pdf", ".tiff"}
    }
    delivery = manifest["delivery_package"]
    assert {item["figure_id"] for item in delivery["figures"]} == set(
        plan.selected_figure_ids
    )
    assert [item["figure_id"] for item in delivery["project_documents"]] == list(
        plan.selected_figure_ids
    )
    assert len(delivery["figures"]) == 2 * len(plan.tasks)
    assert len(delivery["project_documents"]) == len(plan.tasks)
    assert manifest["publish_gates"]["passed"] is True


@pytest.mark.comprehensive
def test_mechanical_studio_secondary_failure_rolls_back_the_whole_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir, request_path = _write_project(tmp_path, "tensile_curve")
    original_request = request_path.read_bytes()

    def reject_secondary(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic mechanical secondary failure")

    monkeypatch.setattr(
        figure_set_prepare_module,
        "_write_veusz_document",
        reject_secondary,
    )
    with pytest.raises(RuntimeError, match="mechanical secondary failure"):
        generate_studio_document(
            project_dir=project_dir,
            request_path=request_path,
            rule_id=None,
            template=None,
            project_name=None,
        )

    assert request_path.read_bytes() == original_request
    assert not (project_dir / "studio" / "document.vsz").exists()
    assert not (project_dir / "studio" / "spec.json").exists()
    assert not (project_dir / "studio" / "figure_set.json").exists()
    assert not list((project_dir / "studio").rglob("*.vsz"))
    assert not list(
        (project_dir / "studio" / "processed" / "mechanical_task_sources").glob("rfp_*")
    )
