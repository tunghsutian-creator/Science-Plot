from __future__ import annotations

from pathlib import Path

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    FigureOutcome,
    FigureTask,
    ResolvedFigurePlan,
    merge_figure_outcomes,
    resolve_figure_plan,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.study_model import (
    attach_run_artifacts_to_study_model,
    experiment_recommendation_payload,
)


def test_uvvis_recommendation_uses_the_resolved_plan_task_identity(
    tmp_path: Path,
) -> None:
    rule = get_rule("uvvis_spectrum")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    recommendation = experiment_recommendation_payload(rule_id=rule.rule_id)
    model = {
        "kind": "sciplot_study_model",
        "version": 2,
        "samples": [],
        "figure_queue": recommendation["figure_queue"],
    }
    plan = resolve_figure_plan(
        rule_id=rule.rule_id,
        template=rule.template,
        study_model=model,
        input_path=source,
        request={"template": rule.template},
    )
    assert plan is not None
    assert tuple(item["id"] for item in recommendation["figure_queue"]) == (
        plan.selected_figure_ids
    )

    task = plan.tasks[0]
    artifact = tmp_path / f"{task.artifact_stem}.pdf"
    artifact.write_bytes(b"figure")
    completed = merge_figure_outcomes(
        plan,
        (
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=(str(artifact),),
            ),
        ),
    )

    updated = attach_run_artifacts_to_study_model(
        model,
        output_dir=tmp_path,
        figures=[str(artifact)],
        resolved_figure_plan=completed.to_payload(),
    )

    queue_item = updated["figure_queue"][0]
    assert queue_item["id"] == task.figure_id
    assert queue_item["status"] == "rendered"
    assert [item["path"] for item in queue_item["artifacts"]] == [str(artifact)]
    assert updated["run"]["unbound_figure_artifacts"] == []


def test_artifact_binding_uses_shared_case_insensitive_dpi_stem(tmp_path: Path) -> None:
    model = {
        "kind": "sciplot_study_model",
        "version": 2,
        "samples": [],
        "figure_queue": [{"id": "Figure_A", "metric": "primary"}],
    }
    figures = [
        str(tmp_path / "Figure_A.pdf"),
        str(tmp_path / "Figure_A_600DPI.png"),
    ]

    updated = attach_run_artifacts_to_study_model(
        model,
        output_dir=tmp_path,
        figures=figures,
    )

    queue = updated["figure_queue"]
    assert queue[0]["status"] == "rendered"
    assert [item["path"] for item in queue[0]["artifacts"]] == figures
    assert updated["run"]["unbound_figure_artifacts"] == []


def test_impact_plan_expansion_does_not_bind_unselected_queue_entries(
    tmp_path: Path,
) -> None:
    task = FigureTask(
        figure_id="impact_condition_a",
        order=1,
        title="Impact condition A",
        x_metric="sample",
        y_metric="impact_strength",
        template="box_strip",
        artifact_stem="impact_condition_a",
        document_stem="impact_condition_a",
    )
    planned = ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy="all_workbook_conditions",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    artifacts = (
        tmp_path / "impact_condition_a.vsz",
        tmp_path / "impact_condition_a.pdf",
        tmp_path / "impact_condition_a_300dpi.tiff",
    )
    for path in artifacts:
        path.write_bytes(b"impact")
    completed = merge_figure_outcomes(
        planned,
        (
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=tuple(str(path) for path in artifacts),
            ),
        ),
    )
    model = {
        "kind": "sciplot_study_model",
        "version": 2,
        "experiment": {"rule_id": "impact_metric"},
        "samples": [],
        "figure_queue": [
            {
                "id": "impact_strength_by_sample",
                "metric": "impact_strength",
            },
            {
                "id": "unrelated_science_figure",
                "metric": "unrelated_metric",
            },
        ],
    }

    updated = attach_run_artifacts_to_study_model(
        model,
        output_dir=tmp_path,
        figures=[str(path) for path in artifacts[1:]],
        resolved_figure_plan=completed.to_payload(),
    )

    aggregate, unrelated = updated["figure_queue"]
    assert aggregate["status"] == "rendered"
    assert aggregate["resolved_figure_ids"] == ["impact_condition_a"]
    assert unrelated.get("status") == "planned"
    assert unrelated.get("artifacts") in (None, [])
    run = updated["run"]
    assert run["resolved_figure_plan"] == completed.to_payload()
    assert "resolved_figure_plan_id" not in run
    assert "resolved_figure_plan_sha256" not in run
    assert "figure_outcomes" not in run
