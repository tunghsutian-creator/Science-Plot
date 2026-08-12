from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from sciplot_core.figure_plan import (
    FigureOutcome,
    FigurePlanResolutionError,
    FigureTask,
    ResolvedFigurePlan,
    merge_figure_outcomes,
    resolve_current_figure_plan,
)
from sciplot_core.presentation_identity import SelectedPresentationIdentity
from sciplot_core.study_model import STUDY_MODEL_KIND, STUDY_MODEL_VERSION
from sciplot_core.studio_core.rule_readiness import (
    resolve_studio_rule_publication_readiness,
)
from sciplot_core.studio_core.publish_sources import StudioRunSources


def _completed_impact_plan(
    tmp_path: Path,
) -> tuple[ResolvedFigurePlan, tuple[Path, Path, Path]]:
    artifacts = (
        tmp_path / "figure.vsz",
        tmp_path / "figure.pdf",
        tmp_path / "figure_300dpi.tiff",
    )
    for path in artifacts:
        path.write_bytes(path.suffix.encode("ascii"))
    task = FigureTask(
        figure_id="impact_strength_by_sample",
        order=1,
        title="Impact strength by sample",
        x_metric="sample",
        y_metric="impact_strength",
        template="point_line",
        artifact_stem="impact_strength_by_sample",
        document_stem="impact_strength_by_sample",
    )
    planned = ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy="explicit_condition_order",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
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
    assert completed.complete is True
    return completed, artifacts


def _impact_study_model() -> dict[str, Any]:
    return {
        "kind": STUDY_MODEL_KIND,
        "version": STUDY_MODEL_VERSION,
        "samples": [],
        "figure_queue": [
            {
                "id": "impact_strength_by_sample",
                "order": 1,
                "status": "planned",
                "title": "Impact strength by sample",
                "metric": "impact_strength",
                "x_metric": "sample",
                "y_metric": "impact_strength",
                "default_template": "point_line",
            }
        ],
    }


def test_studio_publication_evidence_binds_completed_plan_to_study_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.studio_core.publish_evidence as evidence_module
    import sciplot_core.studio_core.publish_run as publish_run_module

    plan, (document, pdf, tiff) = _completed_impact_plan(tmp_path)
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request = {
        "rule_id": "impact_metric",
        "template": "point_line",
        "study_model": _impact_study_model(),
    }
    sources = StudioRunSources(
        input_path=None,
        raw_archive={},
        existing_transform_ledger=None,
        snapshot_sources=[],
        snapshot_source=None,
        processed_source=None,
        semantic={},
        metric_source=None,
        analysis_metrics=[],
    )
    inventory = SimpleNamespace(
        project_dir=project_dir,
        request_path=project_dir / "plot_request.json",
        document_path=document,
        request=request,
        presentation_identity=SelectedPresentationIdentity(
            rule_id="impact_metric",
            template="point_line",
        ),
        resolved_figure_plan=plan,
        rule_readiness=resolve_studio_rule_publication_readiness(request),
        effective_request=request,
        data_mapping_application=None,
        figure_set_export_scope=None,
        exports=[],
        veusz_documents=[document],
        output_dir=output_dir,
    )
    publication_events: list[str] = []
    binding_calls: list[tuple[object, object]] = []

    def record_source_binding(bound_plan: object, bound_sources: object) -> None:
        publication_events.append("binding")
        binding_calls.append((bound_plan, bound_sources))

    def record_studio_snapshot(**_kwargs: Any) -> None:
        publication_events.append("snapshot")

    monkeypatch.setattr(
        evidence_module,
        "build_publication_intent",
        lambda *_args, **_kwargs: {"target_profile_id": "test_profile"},
    )
    monkeypatch.setattr(
        evidence_module,
        "get_publication_profile",
        lambda _profile_id: {"id": "test_profile"},
    )
    monkeypatch.setattr(
        evidence_module,
        "build_transform_ledger",
        lambda *_args, **_kwargs: {"steps": []},
    )
    monkeypatch.setattr(
        evidence_module,
        "_attach_visual_presentation_step",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        evidence_module,
        "link_intent_to_transform_ledger",
        lambda intent, _ledger: intent,
    )
    monkeypatch.setattr(
        evidence_module,
        "write_publication_artifacts",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        evidence_module,
        "_write_studio_analysis_report",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        evidence_module,
        "_run_studio_qa",
        lambda *_args, **_kwargs: {"status": "passed", "publication": {}},
    )
    monkeypatch.setattr(
        evidence_module,
        "_verify_qa_artifact_hashes",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        evidence_module,
        "_semantic_payload_with_exact_current_axes",
        lambda semantic, **_kwargs: semantic,
    )
    monkeypatch.setattr(
        evidence_module,
        "_studio_layout_quality_from_spec",
        lambda _document: {},
    )
    monkeypatch.setattr(
        publish_run_module,
        "prepare_studio_export_inventory",
        lambda **_kwargs: inventory,
    )
    monkeypatch.setattr(
        publish_run_module,
        "copy_studio_run_exports",
        lambda **_kwargs: ([], [str(pdf), str(tiff)]),
    )
    monkeypatch.setattr(
        publish_run_module,
        "prepare_studio_run_sources",
        lambda **_kwargs: sources,
    )
    monkeypatch.setattr(
        publish_run_module,
        "verify_studio_run_source_binding",
        record_source_binding,
    )
    monkeypatch.setattr(
        publish_run_module,
        "_snapshot_studio_directory",
        record_studio_snapshot,
    )
    monkeypatch.setattr(
        publish_run_module,
        "_studio_snapshot_documents",
        lambda _inventory: ([document], {str(document.resolve()): "test-hash"}),
    )
    monkeypatch.setattr(
        publish_run_module,
        "_studio_snapshot_document_map",
        lambda _inventory, **_kwargs: {str(document.resolve()): document},
    )
    monkeypatch.setattr(
        publish_run_module,
        "build_studio_export_result",
        lambda **_kwargs: {
            "resolved_figure_plan": plan.to_payload(),
        },
    )
    monkeypatch.setattr(
        publish_run_module,
        "build_studio_run_manifest",
        lambda *, evidence, result, **_kwargs: {
            "study_model": evidence.study_model,
            "resolved_figure_plan": result["resolved_figure_plan"],
        },
    )
    monkeypatch.setattr(
        publish_run_module,
        "finalize_studio_run",
        lambda **kwargs: kwargs["manifest"],
    )

    manifest = publish_run_module.publish_studio_export_run(
        project_dir=project_dir,
        request_path=inventory.request_path,
        document_path=document,
        exports=[],
        export_document_sha256="test-hash",
    )

    run = manifest["study_model"]["run"]
    assert run["artifact_binding_policy"] == "resolved_figure_plan"
    assert run["resolved_figure_plan"] == plan.to_payload()
    assert "resolved_figure_plan_id" not in run
    assert "resolved_figure_plan_sha256" not in run
    assert "figure_outcomes" not in run
    assert publication_events == ["binding", "snapshot"]
    assert len(binding_calls) == 1
    assert binding_calls[0][0] is plan
    assert binding_calls[0][1] is sources


def test_workflow_projects_completed_plan_into_intake_top_level_and_last_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.intake.packaging as intake_packaging
    import sciplot_core.workflow.project_state as project_state

    plan, (_document, pdf, tiff) = _completed_impact_plan(tmp_path)
    plan_payload = plan.to_payload()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    project_manifest: dict[str, Any] = {"kind": "sciplot_intake_project"}
    calls: list[str] = []

    def prepare_studio(_project_dir: Path) -> None:
        calls.append("prepare")
        project_manifest["resolved_figure_plan"] = {"status": "planned"}
        project_manifest["figure_outcomes"] = []

    @contextmanager
    def edit_manifest(
        _project_dir: Path,
        *,
        require_existing: bool = False,
        **_kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        assert require_existing is True
        calls.append("edit")
        yield project_manifest

    def refresh_zip(_project_dir: Path) -> Path:
        calls.append("zip")
        return tmp_path / "project.zip"

    monkeypatch.setattr(
        project_state,
        "read_intake_project_manifest",
        lambda _project_dir: project_manifest,
    )
    monkeypatch.setattr(
        project_state,
        "edit_intake_project_manifest",
        edit_manifest,
    )
    monkeypatch.setattr(
        intake_packaging,
        "_prepare_studio_project_package",
        prepare_studio,
    )
    monkeypatch.setattr(
        intake_packaging,
        "refresh_intake_project_zip",
        refresh_zip,
    )
    run_manifest = {
        "created_at": "2026-07-30T00:00:00+00:00",
        "output": str(tmp_path / "run"),
        "figures": [str(pdf), str(tiff)],
        "result": {},
        "resolved_figure_plan": plan_payload,
    }

    project_state._update_intake_project_after_run(request_path, run_manifest)

    assert calls == ["prepare", "edit", "zip"]
    assert project_manifest["resolved_figure_plan"] == plan_payload
    assert "figure_outcomes" not in project_manifest
    assert project_manifest["last_run"]["resolved_figure_plan"] == plan_payload
    assert "figure_outcomes" not in project_manifest["last_run"]

    legacy_manifest = {
        "created_at": "2026-07-30T00:01:00+00:00",
        "output": str(tmp_path / "legacy-run"),
        "figures": [],
        "result": {},
    }
    project_state._update_intake_project_after_run(request_path, legacy_manifest)

    assert "resolved_figure_plan" not in project_manifest
    assert "figure_outcomes" not in project_manifest
    assert "resolved_figure_plan" not in project_manifest["last_run"]
    assert "figure_outcomes" not in project_manifest["last_run"]


def test_studio_registration_replaces_and_removes_plan_projection_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.intake.packaging as intake_packaging
    import sciplot_core.studio_core.registry_writes as registry_writes

    plan, _artifacts = _completed_impact_plan(tmp_path)
    payload: dict[str, Any] = {
        "resolved_figure_plan": {"stale": True},
        "figure_outcomes": [{"stale": True}],
    }

    @contextmanager
    def edit_manifest(
        _project_dir: Path,
        **_kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        yield payload

    monkeypatch.setattr(
        registry_writes,
        "edit_intake_project_manifest",
        edit_manifest,
    )
    monkeypatch.setattr(
        intake_packaging,
        "converge_intake_project_launchers",
        lambda _project_dir: None,
    )

    registry_writes._register_studio_block(
        tmp_path,
        {"resolved_figure_plan": plan.to_payload()},
    )

    assert payload["resolved_figure_plan"] == plan.to_payload()
    assert "figure_outcomes" not in payload

    registry_writes._register_studio_block(tmp_path, {})

    assert "resolved_figure_plan" not in payload
    assert "figure_outcomes" not in payload


def test_supported_missing_plan_fails_closed_but_unsupported_legacy_is_optional(
    tmp_path: Path,
) -> None:
    empty_study_model = {
        "kind": STUDY_MODEL_KIND,
        "version": STUDY_MODEL_VERSION,
        "samples": [],
        "figure_queue": [],
    }

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_current_figure_plan(
            persisted=None,
            rule_id="rheology_frequency_sweep",
            template="point_line",
            study_model=empty_study_model,
            input_path=tmp_path / "frequency.xlsx",
            request={},
        )

    assert exc_info.value.reason_code == "resolved_figure_plan_unavailable"
    assert (
        resolve_current_figure_plan(
            persisted=None,
            rule_id="legacy_custom_rule",
            template="curve",
            study_model={},
            input_path=tmp_path / "legacy.csv",
            request={},
        )
        is None
    )
