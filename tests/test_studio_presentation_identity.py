from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.figure_plan import FigureTask, ResolvedFigurePlan
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
from sciplot_core.presentation_identity import (
    SelectedPresentationIdentity,
    resolve_selected_presentation_identity,
)
from sciplot_core.readiness import semantic_contract_sha256
from sciplot_core.studio import prepare_studio_document
from sciplot_core.studio_core import publish_finalize as finalize_module
from sciplot_core.studio_core import publish_inventory as inventory_module
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.publish_evidence import StudioPublicationEvidence
from sciplot_core.studio_core.publish_inventory import StudioExportInventory
from sciplot_core.studio_core.publish_manifest import (
    build_studio_export_result,
    build_studio_run_manifest,
)
from sciplot_core.studio_core.publish_run import publish_studio_export_run
from sciplot_core.studio_core.publish_sources import StudioRunSources
from sciplot_core.studio_core.registry_state import _veusz_spec_path
from sciplot_core.studio_core.rule_readiness import (
    resolve_studio_rule_publication_readiness,
)
from sciplot_core.studio_core.semantic_payloads import (
    _studio_export_semantic_payload,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)
RULE_ID = "performance_comparison"
DEFAULT_TEMPLATE = "scatter"
ALTERNATE_TEMPLATE = "polar_curve"


def _identity(template: str) -> dict[str, Any]:
    return {
        "kind": "sciplot_selected_presentation_identity",
        "version": 1,
        "rule_id": RULE_ID,
        "template": template,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _performance_project(
    tmp_path: Path,
    *,
    template: str | None,
) -> tuple[Path, Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    request: dict[str, Any] = {
        "input": str(source),
        "rule_id": RULE_ID,
    }
    if template is not None:
        request["template"] = template
        request["explicit_template_selection"] = True
    request_path = project_dir / "plot_request.json"
    _write_json(request_path, request)
    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )
    return project_dir, request_path, Path(prepared["document"])


def test_explicit_performance_template_beats_matching_recognition_default(
    tmp_path: Path,
) -> None:
    _project_dir, request_path, document_path = _performance_project(
        tmp_path,
        template=ALTERNATE_TEMPLATE,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    spec = json.loads(_veusz_spec_path(document_path).read_text(encoding="utf-8"))
    recognition = {
        "rule_id": RULE_ID,
        "semantic_family": RULE_ID,
        "template": DEFAULT_TEMPLATE,
        "reason": "Historical recognition selected the rule default.",
    }

    semantic = _studio_export_semantic_payload(
        request=request,
        intake_manifest={"recognition": recognition},
        document_path=document_path,
    )

    assert request["template"] == ALTERNATE_TEMPLATE
    assert spec["template"] == ALTERNATE_TEMPLATE
    assert semantic["template"] == DEFAULT_TEMPLATE
    assert semantic["presentation_identity"] == _identity(ALTERNATE_TEMPLATE)


def test_rule_default_is_used_when_performance_template_is_omitted(
    tmp_path: Path,
) -> None:
    project_dir, request_path, document_path = _performance_project(
        tmp_path,
        template=None,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    spec = json.loads(_veusz_spec_path(document_path).read_text(encoding="utf-8"))
    semantic = _studio_export_semantic_payload(
        request=request,
        intake_manifest={"recognition": {"rule_id": RULE_ID}},
        document_path=document_path,
    )

    assert request["template"] == DEFAULT_TEMPLATE
    assert spec["template"] == DEFAULT_TEMPLATE
    assert semantic["template"] == DEFAULT_TEMPLATE
    assert semantic["presentation_identity"] == _identity(DEFAULT_TEMPLATE)
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    assert plan.selected_figure_ids == (
        "performance_scatter",
        "performance_polar_curve",
    )
    registry = json.loads(
        (project_dir / "studio" / "figure_set.json").read_text(encoding="utf-8")
    )
    assert [item["figure_id"] for item in registry["figures"]] == list(
        plan.selected_figure_ids
    )
    assert (
        project_dir / "studio" / "figures" / "performance_polar_curve.vsz"
    ).is_file()


def test_unsupported_performance_template_fails_before_document_write(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    request_path = project_dir / "plot_request.json"
    _write_json(
        request_path,
        {
            "input": str(source),
            "rule_id": RULE_ID,
            "template": "bar",
            "explicit_template_selection": True,
        },
    )

    with pytest.raises(ValueError, match="is not supported by material rule"):
        generate_studio_document(
            project_dir=project_dir,
            request_path=request_path,
            rule_id=None,
            template=None,
            project_name=None,
        )

    assert not (project_dir / "studio" / "document.vsz").exists()
    assert not (project_dir / "studio" / "spec.json").exists()


def test_malformed_present_template_fails_before_document_write(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    request_path = project_dir / "plot_request.json"
    _write_json(
        request_path,
        {
            "input": str(source),
            "rule_id": RULE_ID,
            "template": True,
        },
    )

    with pytest.raises(ValueError):
        generate_studio_document(
            project_dir=project_dir,
            request_path=request_path,
            rule_id=None,
            template=None,
            project_name=None,
        )

    assert not (project_dir / "studio" / "document.vsz").exists()
    assert not (project_dir / "studio" / "spec.json").exists()


def test_categorical_alternate_resolves_without_changing_rule_semantics() -> None:
    rule = get_rule("impact_metric")
    identity = resolve_selected_presentation_identity(
        {
            "rule_id": rule.rule_id,
            "template": "point_line",
        },
        current_rule=rule,
    )
    semantic = semantic_payload_from_rule(
        rule,
        confidence=100.0,
        reason="Presentation identity hash control.",
    )
    baseline_hash = semantic_contract_sha256(semantic)
    semantic["presentation_identity"] = identity.to_payload()

    assert identity.template == "point_line"
    assert rule.template == "box_strip"
    assert semantic["template"] == "box_strip"
    assert semantic_contract_sha256(semantic) == baseline_hash


def _minimal_publish_project(
    tmp_path: Path,
    *,
    request: dict[str, Any],
    spec_template: str,
) -> tuple[Path, Path, Path, str]:
    project_dir = tmp_path / "project"
    request_path = project_dir / "plot_request.json"
    document_path = project_dir / "studio" / "document.vsz"
    _write_json(request_path, request)
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text("Add('page')\n", encoding="utf-8")
    _write_json(
        _veusz_spec_path(document_path),
        {
            "kind": "sciplot_veusz_plot_spec",
            "version": 1,
            "template": spec_template,
        },
    )
    document_hash = existing_file_sha256(document_path)
    assert document_hash is not None
    return project_dir, request_path, document_path, document_hash


def _stub_publish_collection(
    monkeypatch: pytest.MonkeyPatch,
    *,
    document_path: Path,
    document_hash: str,
) -> None:
    monkeypatch.setattr(
        inventory_module,
        "_verify_exact_current_export_binding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        inventory_module,
        "_validated_figure_set_scope",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        inventory_module,
        "_collect_figure_documents",
        lambda **_kwargs: [
            {
                "figure_id": "primary",
                "document": str(document_path),
                "document_sha256": document_hash,
                "exports": [],
            }
        ],
    )
    monkeypatch.setattr(
        inventory_module,
        "resolve_data_mapping_request",
        lambda request, *, base_dir: (dict(request), None),
    )


def test_publish_rejects_request_spec_template_mismatch_before_run_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    project_dir, request_path, document_path, document_hash = _minimal_publish_project(
        tmp_path,
        request={
            "input": str(source),
            "rule_id": RULE_ID,
            "template": ALTERNATE_TEMPLATE,
            "explicit_template_selection": True,
        },
        spec_template=DEFAULT_TEMPLATE,
    )
    _stub_publish_collection(
        monkeypatch,
        document_path=document_path,
        document_hash=document_hash,
    )
    allocations: list[Path] = []

    def allocate(current_project: Path) -> Path:
        allocations.append(current_project)
        output_dir = current_project / "runs" / "studio_001"
        output_dir.mkdir(parents=True)
        return output_dir

    monkeypatch.setattr(inventory_module, "_next_studio_run_dir", allocate)

    with pytest.raises(RuntimeError, match="presentation_identity_mismatch"):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=[],
            export_document_sha256=document_hash,
        )

    assert allocations == []
    assert not (project_dir / "runs").exists()


def test_publish_rejects_plan_template_mismatch_before_run_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    task = FigureTask(
        figure_id="performance_primary",
        order=1,
        title="Performance comparison",
        x_metric="metric",
        y_metric="value",
        template=DEFAULT_TEMPLATE,
        artifact_stem="performance_primary",
        document_stem="performance_primary",
    )
    stale_plan = ResolvedFigurePlan.planned(
        rule_id=RULE_ID,
        selection_policy="test_persisted_plan",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    project_dir, request_path, document_path, document_hash = _minimal_publish_project(
        tmp_path,
        request={
            "input": str(source),
            "rule_id": RULE_ID,
            "template": ALTERNATE_TEMPLATE,
            "explicit_template_selection": True,
            "resolved_figure_plan": stale_plan.to_payload(),
        },
        spec_template=ALTERNATE_TEMPLATE,
    )
    monkeypatch.setattr(
        inventory_module,
        "_verify_exact_current_export_binding",
        lambda **_kwargs: None,
    )
    allocations: list[Path] = []
    monkeypatch.setattr(
        inventory_module,
        "_next_studio_run_dir",
        lambda current_project: allocations.append(current_project),
    )

    with pytest.raises(RuntimeError, match="stale_resolved_figure_plan"):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=[],
            export_document_sha256=document_hash,
        )

    assert allocations == []
    assert not (project_dir / "runs").exists()


def _publish_projection_fixture(
    tmp_path: Path,
) -> tuple[
    StudioExportInventory,
    StudioRunSources,
    StudioPublicationEvidence,
]:
    source = tmp_path / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    project_dir, request_path, document_path, document_hash = _minimal_publish_project(
        tmp_path,
        request={
            "input": str(source),
            "rule_id": RULE_ID,
            "template": ALTERNATE_TEMPLATE,
            "explicit_template_selection": True,
        },
        spec_template=ALTERNATE_TEMPLATE,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    readiness = resolve_studio_rule_publication_readiness(request)
    output_dir = project_dir / "runs" / "studio_001"
    snapshot_document = output_dir / "studio" / "document.vsz"
    snapshot_document.parent.mkdir(parents=True)
    shutil.copyfile(document_path, snapshot_document)
    shutil.copyfile(
        _veusz_spec_path(document_path),
        _veusz_spec_path(snapshot_document),
    )
    semantic = {
        "rule_id": RULE_ID,
        "semantic_family": RULE_ID,
        "template": DEFAULT_TEMPLATE,
        "presentation_identity": _identity(ALTERNATE_TEMPLATE),
        "studio_rule_publication_readiness": readiness.to_payload(),
        "publication_rule_ready": not readiness.publication_blocked,
    }
    inventory = StudioExportInventory(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
        request=request,
        presentation_identity=SelectedPresentationIdentity(
            rule_id=RULE_ID,
            template=ALTERNATE_TEMPLATE,
        ),
        resolved_figure_plan=None,
        rule_readiness=readiness,
        figure_set_export_scope=None,
        exports=[],
        veusz_documents=[document_path],
        veusz_document_hashes={str(document_path.resolve()): document_hash},
        effective_request=dict(request),
        data_mapping_application=None,
        document_state={
            "authority": "sciplot_generated",
            "manual_edit_detected": False,
            "current_hash": document_hash,
        },
        export_document_sha256=document_hash,
        output_dir=output_dir,
    )
    sources = StudioRunSources(
        input_path=source,
        raw_archive={},
        existing_transform_ledger=None,
        snapshot_sources=[],
        snapshot_source=None,
        processed_source=None,
        semantic=semantic,
        metric_source=None,
        analysis_metrics=[],
    )
    evidence = StudioPublicationEvidence(
        study_model={},
        publication_intent={},
        publication_profile={},
        transform_ledger={},
        publication_artifacts={},
        qa={"status": "passed"},
        semantic=semantic,
        publication_qa={},
        layout_quality={},
    )
    return inventory, sources, evidence


def test_publish_result_manifest_payload_and_registry_share_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, sources, evidence = _publish_projection_fixture(tmp_path)
    result = build_studio_export_result(
        inventory=inventory,
        sources=sources,
        copied_exports=[],
        figures=[],
    )
    manifest = build_studio_run_manifest(
        inventory=inventory,
        sources=sources,
        evidence=evidence,
        result=result,
        figures=[],
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_studio_revision_brief",
        lambda *_args, **_kwargs: "revision_brief.md",
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_studio_review_html",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_json_atomic",
        lambda *_args, **_kwargs: None,
    )

    def finalize_contracts(**kwargs: object) -> None:
        current_manifest = kwargs["manifest"]
        assert isinstance(current_manifest, dict)
        current_manifest["package_contract"] = {"complete": True}
        current_manifest["delivery_package"] = {"complete": True}
        current_manifest["delivery_verification"] = {"passed": True}

    monkeypatch.setattr(
        finalize_module,
        "_finalize_delivery_contracts",
        finalize_contracts,
    )
    registered: list[dict[str, Any]] = []
    monkeypatch.setattr(
        finalize_module,
        "_register_studio_run",
        lambda _project, _manifest, *, studio_run: registered.append(studio_run),
    )

    payload = finalize_module.finalize_studio_run(
        inventory=inventory,
        evidence=evidence,
        manifest=manifest,
        copied_exports=[],
        figures=[],
    )

    for projection in (result, manifest, payload, registered[0]):
        assert projection["template"] == ALTERNATE_TEMPLATE
        assert projection["presentation_identity"] == _identity(ALTERNATE_TEMPLATE)


@pytest.mark.parametrize(
    "location",
    [
        "manifest_identity",
        "result_template",
        "semantic_identity",
        "studio_identity",
    ],
)
def test_finalize_rejects_split_presentation_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    inventory, sources, evidence = _publish_projection_fixture(tmp_path)
    result = build_studio_export_result(
        inventory=inventory,
        sources=sources,
        copied_exports=[],
        figures=[],
    )
    manifest = build_studio_run_manifest(
        inventory=inventory,
        sources=sources,
        evidence=evidence,
        result=result,
        figures=[],
    )
    if location == "manifest_identity":
        manifest["presentation_identity"] = _identity(DEFAULT_TEMPLATE)
    elif location == "result_template":
        manifest["result"]["template"] = DEFAULT_TEMPLATE
    elif location == "semantic_identity":
        manifest["semantic"]["presentation_identity"] = _identity(DEFAULT_TEMPLATE)
    else:
        manifest["studio"]["presentation_identity"] = _identity(DEFAULT_TEMPLATE)

    effects: list[str] = []
    monkeypatch.setattr(
        finalize_module,
        "_write_studio_revision_brief",
        lambda *_args, **_kwargs: effects.append("revision"),
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_json_atomic",
        lambda *_args, **_kwargs: effects.append("write"),
    )
    monkeypatch.setattr(
        finalize_module,
        "_register_studio_run",
        lambda *_args, **_kwargs: effects.append("register"),
    )

    with pytest.raises(RuntimeError, match="presentation_identity_mismatch"):
        finalize_module.finalize_studio_run(
            inventory=inventory,
            evidence=evidence,
            manifest=manifest,
            copied_exports=[],
            figures=[],
        )

    assert effects == []


def test_project_registry_records_selected_presentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sciplot_core.studio_core import registry_writes

    identity = _identity(ALTERNATE_TEMPLATE)
    project_manifest: dict[str, Any] = {"studio": {}}

    @contextmanager
    def edit_manifest(
        _project_dir: Path,
        *,
        snapshot_writer: object,
    ):
        assert snapshot_writer is not None
        yield project_manifest

    monkeypatch.setattr(
        registry_writes,
        "edit_intake_project_manifest_with_snapshot",
        edit_manifest,
    )
    registry_writes._register_studio_run(
        tmp_path,
        {
            "created_at": "2026-07-30T00:00:00Z",
            "output": str(tmp_path / "runs" / "studio_001"),
            "template": ALTERNATE_TEMPLATE,
            "presentation_identity": identity,
        },
        studio_run={
            "exports": [],
            "template": ALTERNATE_TEMPLATE,
            "presentation_identity": identity,
        },
    )

    assert project_manifest["last_run"]["template"] == ALTERNATE_TEMPLATE
    assert project_manifest["last_run"]["presentation_identity"] == identity
    assert project_manifest["studio"]["presentation_identity"] == identity
    assert (
        project_manifest["studio"]["last_export_run"]["presentation_identity"]
        == identity
    )


@pytest.mark.comprehensive
def test_explicit_alternate_survives_real_studio_publication(
    tmp_path: Path,
) -> None:
    prepared = prepare_studio_document(
        FIXTURE,
        output_root=tmp_path / "projects",
        delivery_root=tmp_path / "delivery",
        rule_id=RULE_ID,
        template=ALTERNATE_TEMPLATE,
    )
    project_dir = Path(prepared["project_dir"])
    request_path = Path(prepared["request"])
    document_path = Path(prepared["document"])
    exported = export_studio_document(
        document_path,
        formats=["pdf", "tiff_300"],
    )
    studio_run = publish_studio_export_run(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
        exports=exported["exports"],
        export_document_sha256=str(exported["document_sha256"]),
    )
    manifest = json.loads(Path(studio_run["manifest"]).read_text(encoding="utf-8"))
    project_manifest = json.loads(
        (project_dir / "intake_manifest.json").read_text(encoding="utf-8")
    )
    expected = _identity(ALTERNATE_TEMPLATE)

    assert manifest["semantic"]["template"] == DEFAULT_TEMPLATE
    for projection in (
        manifest["semantic"],
        manifest["result"],
        manifest,
        studio_run,
        project_manifest["last_run"],
        project_manifest["studio"],
        project_manifest["studio"]["last_export_run"],
    ):
        assert projection["presentation_identity"] == expected
    for projection in (
        manifest["result"],
        manifest,
        studio_run,
        project_manifest["last_run"],
        project_manifest["studio"]["last_export_run"],
    ):
        assert projection["template"] == ALTERNATE_TEMPLATE
