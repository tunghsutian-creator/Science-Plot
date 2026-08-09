from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from sciplot_core.figure_plan import (
    FigureOutcome,
    FigureTask,
    ResolvedFigurePlan,
    merge_figure_outcomes,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.presentation_identity import (
    resolve_selected_presentation_identity,
)
from sciplot_core.studio_core.publish_inventory import StudioExportInventory
from sciplot_core.studio_core.rule_readiness import (
    resolve_studio_rule_publication_readiness,
)
from sciplot_core.studio_core.publish_manifest import (
    _studio_manifest_block,
    _studio_snapshot_documents,
    build_studio_export_result,
    build_studio_run_manifest,
)
from sciplot_core.studio_core.publish_sources import StudioRunSources


def _figure_plan(tmp_path: Path, *, complete: bool = False) -> ResolvedFigurePlan:
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="x",
        y_metric="y",
        template="curve",
        artifact_stem="figure_a",
        document_stem="figure_a",
    )
    planned = ResolvedFigurePlan.planned(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    if not complete:
        return planned
    return merge_figure_outcomes(
        planned,
        (
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=(
                    str(tmp_path / "figure_a.vsz"),
                    str(tmp_path / "figure_a.pdf"),
                    str(tmp_path / "figure_a_300dpi.tiff"),
                ),
            ),
        ),
    )


def _inventory(
    tmp_path: Path,
    *,
    pending_rule_review: bool = False,
    request_payload: dict[str, object] | None = None,
) -> tuple[StudioExportInventory, tuple[Path, Path], tuple[Path, Path]]:
    project = tmp_path / "project"
    output = project / "runs" / "run_001"
    primary = project / "studio" / "document.vsz"
    secondary = project / "studio" / "figures" / "secondary.vsz"
    snapshot_primary = output / "studio" / "document.vsz"
    snapshot_secondary = output / "studio" / "figures" / "secondary.vsz"
    for path, content in (
        (primary, b"primary-v1"),
        (secondary, b"secondary-v1"),
        (snapshot_primary, b"primary-v1"),
        (snapshot_secondary, b"secondary-v1"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (output / "studio" / "spec.json").write_text("{}", encoding="utf-8")
    (output / "studio" / "figures" / "secondary.spec.json").write_text(
        "{}",
        encoding="utf-8",
    )
    hashes = {
        str(primary.resolve()): str(existing_file_sha256(primary)),
        str(secondary.resolve()): str(existing_file_sha256(secondary)),
    }
    request = (
        dict(request_payload)
        if request_payload is not None
        else {"pending_rule_review": True}
        if pending_rule_review
        else {}
    )
    rule_readiness = resolve_studio_rule_publication_readiness(request)
    presentation_identity = resolve_selected_presentation_identity(
        request,
        current_rule=rule_readiness.current_rule,
    )
    request["template"] = presentation_identity.template
    inventory = StudioExportInventory(
        project_dir=project,
        request_path=project / "plot_request.json",
        document_path=primary,
        request=request,
        presentation_identity=presentation_identity,
        resolved_figure_plan=None,
        rule_readiness=rule_readiness,
        figure_set_export_scope=None,
        exports=[],
        veusz_documents=[primary, secondary],
        veusz_document_hashes=hashes,
        effective_request={},
        data_mapping_application=None,
        document_state={
            "authority": "generated_current",
            "manual_edit_detected": False,
        },
        export_document_sha256=hashes[str(primary.resolve())],
        output_dir=output,
    )
    return (
        inventory,
        (primary, secondary),
        (snapshot_primary, snapshot_secondary),
    )


def _presentation_payload(
    inventory: StudioExportInventory,
) -> dict[str, object]:
    return inventory.presentation_identity.to_payload()


def test_studio_snapshot_documents_bind_run_local_paths_and_hashes(
    tmp_path: Path,
) -> None:
    inventory, sources, snapshots = _inventory(tmp_path)

    documents, hashes = _studio_snapshot_documents(inventory)
    sources[1].write_bytes(b"source-changed-after-snapshot")
    documents_after_source_change, hashes_after_source_change = (
        _studio_snapshot_documents(inventory)
    )

    assert documents == list(snapshots)
    assert hashes == {
        str(path.resolve()): existing_file_sha256(path) for path in snapshots
    }
    assert documents_after_source_change == list(snapshots)
    assert hashes_after_source_change == hashes


@pytest.mark.parametrize("failure", ["missing", "changed"])
def test_studio_snapshot_documents_never_fall_back_to_live_project(
    tmp_path: Path,
    failure: str,
) -> None:
    inventory, _sources, snapshots = _inventory(tmp_path)
    secondary = snapshots[1]
    if failure == "missing":
        secondary.unlink()
    else:
        secondary.write_bytes(b"snapshot-was-mutated")

    with pytest.raises(RuntimeError, match="snapshot is missing or changed"):
        _studio_snapshot_documents(inventory)


def test_studio_durable_document_fields_use_only_run_local_snapshots(
    tmp_path: Path,
) -> None:
    inventory, sources, snapshots = _inventory(tmp_path)
    inventory = replace(inventory, resolved_figure_plan=_figure_plan(tmp_path))
    run_sources = StudioRunSources(
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
    result = build_studio_export_result(
        inventory=inventory,
        sources=run_sources,
        copied_exports=[
            {
                "document": str(sources[0]),
                "path": str(tmp_path / "figure.pdf"),
                "format": "pdf",
            }
        ],
        figures=[str(tmp_path / "figure.pdf")],
    )
    studio = _studio_manifest_block(inventory)
    evidence = SimpleNamespace(
        semantic={},
        study_model={},
        publication_intent={},
        transform_ledger={},
        publication_profile={},
        publication_qa={},
        publication_artifacts={},
        qa={},
        layout_quality={},
    )
    manifest = build_studio_run_manifest(
        inventory=inventory,
        sources=run_sources,
        evidence=evidence,
        result=result,
        figures=[str(tmp_path / "figure.pdf")],
    )

    assert result["document"] == str(snapshots[0])
    assert result["veusz_document"] == str(snapshots[0])
    assert result["veusz_spec"] == str(snapshots[0].parent / "spec.json")
    assert result["exports"][0]["document"] == str(snapshots[0])
    assert studio["document"] == str(snapshots[0])
    assert studio["spec"] == str(snapshots[0].parent / "spec.json")
    assert Path(studio["spec"]).is_file()
    assert result["veusz_documents"] == [str(path) for path in snapshots]
    assert result["rule_readiness"] == inventory.rule_readiness.to_payload()
    assert manifest["veusz_document"] == str(snapshots[0])
    assert manifest["veusz_spec"] == str(snapshots[0].parent / "spec.json")
    assert manifest["studio"]["document"] == str(snapshots[0])
    assert manifest["rule_readiness"] == inventory.rule_readiness.to_payload()
    assert manifest["resolved_figure_plan"] == result["resolved_figure_plan"]
    assert "figure_outcomes" not in manifest
    assert "figure_outcomes" not in result
    durable_json = json.dumps(manifest)
    assert str(sources[0]) not in durable_json
    assert str(sources[1]) not in durable_json

    sources[0].write_bytes(b"live-source-mutated-after-snapshot")
    repeated = build_studio_export_result(
        inventory=inventory,
        sources=run_sources,
        copied_exports=[],
        figures=[],
    )
    assert repeated["document"] == str(snapshots[0])


def test_finalize_returns_snapshot_bound_exports_from_durable_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.studio_core.publish_finalize as finalize_module

    inventory, sources, snapshots = _inventory(tmp_path)
    live_export = {"document": str(sources[0]), "path": str(tmp_path / "figure.pdf")}
    durable_export = {
        "document": str(snapshots[0]),
        "path": str(tmp_path / "figure.pdf"),
    }
    canonical_rule_readiness = inventory.rule_readiness.to_payload()
    identity = _presentation_payload(inventory)
    projections = {
        "pending_rule_review": inventory.pending_rule_review,
        "publication_rule_blocked": inventory.publication_rule_blocked,
        "autonomous_rule_ready": not inventory.publication_rule_blocked,
    }
    completed_plan = _figure_plan(tmp_path, complete=True)
    manifest = {
        "result": {
            "exports": [durable_export],
            "template": inventory.presentation_identity.template,
            "presentation_identity": identity,
            "rule_readiness": canonical_rule_readiness,
            "resolved_figure_plan": completed_plan.to_payload(),
            **projections,
        },
        "semantic": {
            "presentation_identity": identity,
            "studio_rule_publication_readiness": canonical_rule_readiness,
            "publication_rule_ready": (not inventory.publication_rule_blocked),
        },
        "template": inventory.presentation_identity.template,
        "presentation_identity": identity,
        "studio": {"presentation_identity": identity},
        "scope": "project_delivery",
        "rule_readiness": canonical_rule_readiness,
        "resolved_figure_plan": completed_plan.to_payload(),
        **projections,
    }

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
        target = kwargs["manifest"]
        assert isinstance(target, dict)
        target["package_contract"] = {"complete": True}
        target["delivery_package"] = {"complete": True}
        target["delivery_verification"] = {"passed": True}

    monkeypatch.setattr(
        finalize_module,
        "_finalize_delivery_contracts",
        finalize_contracts,
    )
    registered: list[dict[str, object]] = []
    monkeypatch.setattr(
        finalize_module,
        "_register_studio_run",
        lambda _project, _manifest, *, studio_run: registered.append(studio_run),
    )

    payload = finalize_module.finalize_studio_run(
        inventory=inventory,
        evidence=SimpleNamespace(qa={"status": "passed"}),
        manifest=manifest,
        copied_exports=[live_export],
        figures=[str(tmp_path / "figure.pdf")],
    )

    assert payload["exports"] == [durable_export]
    assert payload["state"] == "ready"
    assert payload["ready_to_use"] is True
    assert payload["failure_stage"] is None
    assert payload["failure_reason"] is None
    assert payload["rule_readiness"] == inventory.rule_readiness.to_payload()
    assert payload["resolved_figure_plan"] == completed_plan.to_payload()
    assert "figure_outcomes" not in payload
    assert "figure_outcomes" not in manifest["result"]
    assert (
        manifest["result"]["rule_readiness"]
        == manifest["rule_readiness"]
        == payload["rule_readiness"]
        == registered[0]["rule_readiness"]
    )
    assert manifest["publish_gates"]["gates"] == {
        "qa_passed": True,
        "package_contract_complete": True,
        "delivery_package_complete": True,
        "delivery_verification_passed": True,
        "resolved_figure_plan_complete": True,
    }
    assert registered[0]["exports"] == [durable_export]
    assert registered[0]["state"] == "ready"


@pytest.mark.parametrize(
    ("request_payload", "expected_stage", "expected_reason"),
    [
        (
            {"pending_rule_review": True},
            "rule_readiness_gate",
            "This Studio project retains rule-review evidence but has no canonical "
            "request rule. Reprepare it with an explicit ready rule before handoff.",
        ),
        (
            {"rule_id": "swelling_curve"},
            "rule_contract_gate",
            "This rule-bearing Studio project has no prepare-time rule-contract "
            "binding. Reprepare it with the current certified rule before handoff.",
        ),
    ],
)
def test_finalize_blocks_rule_prerequisites_after_all_artifact_gates_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_payload: dict[str, object],
    expected_stage: str,
    expected_reason: str,
) -> None:
    import sciplot_core.studio_core.publish_finalize as finalize_module

    inventory, _sources, _snapshots = _inventory(
        tmp_path,
        request_payload=request_payload,
    )
    canonical_rule_readiness = inventory.rule_readiness.to_payload()
    identity = _presentation_payload(inventory)
    projections = {
        "pending_rule_review": inventory.pending_rule_review,
        "publication_rule_blocked": True,
        "autonomous_rule_ready": False,
    }
    manifest = {
        "result": {
            "exports": [],
            "template": inventory.presentation_identity.template,
            "presentation_identity": identity,
            "rule_readiness": canonical_rule_readiness,
            **projections,
        },
        "semantic": {
            "presentation_identity": identity,
            "studio_rule_publication_readiness": canonical_rule_readiness,
            "publication_rule_ready": False,
        },
        "template": inventory.presentation_identity.template,
        "presentation_identity": identity,
        "studio": {"presentation_identity": identity},
        "scope": "project_delivery",
        "rule_readiness": canonical_rule_readiness,
        **projections,
    }
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
        target = kwargs["manifest"]
        assert isinstance(target, dict)
        target["package_contract"] = {"complete": True}
        target["delivery_package"] = {"complete": True}
        target["delivery_verification"] = {"passed": True}

    monkeypatch.setattr(
        finalize_module,
        "_finalize_delivery_contracts",
        finalize_contracts,
    )
    registered: list[dict[str, object]] = []
    monkeypatch.setattr(
        finalize_module,
        "_register_studio_run",
        lambda _project, _manifest, *, studio_run: registered.append(studio_run),
    )

    payload = finalize_module.finalize_studio_run(
        inventory=inventory,
        evidence=SimpleNamespace(qa={"status": "passed"}),
        manifest=manifest,
        copied_exports=[],
        figures=[],
    )

    assert manifest["state"] == "needs_rule_repair"
    assert manifest["ready_to_use"] is False
    assert manifest["publish_complete"] is True
    assert manifest["package_contract"]["complete"] is True
    assert manifest["delivery_package"]["complete"] is True
    assert manifest["delivery_verification"]["passed"] is True
    assert manifest["publish_gates"]["gates"] == {
        "qa_passed": True,
        "package_contract_complete": True,
        "delivery_package_complete": True,
        "delivery_verification_passed": True,
        "prerequisite_state_ready": False,
    }
    assert manifest["publish_gates"]["failed_gates"] == ["prerequisite_state_ready"]
    assert manifest["failure_stage"] == expected_stage
    assert manifest["failure_reason"] == expected_reason
    assert payload["state"] == "needs_rule_repair"
    assert payload["ready_to_use"] is False
    assert payload["pending_rule_review"] is inventory.pending_rule_review
    assert payload["publication_rule_blocked"] is True
    assert payload["autonomous_rule_ready"] is False
    assert payload["failure_stage"] == expected_stage
    assert payload["failure_reason"] == expected_reason
    assert payload["rule_readiness"] == inventory.rule_readiness.to_payload()
    assert registered == [payload]


@pytest.mark.parametrize(
    "location",
    [
        "manifest_readiness",
        "result_readiness",
        "semantic_readiness",
        "manifest_publication_blocked",
        "result_autonomous_rule_ready",
        "semantic_publication_rule_ready",
    ],
)
def test_finalize_rejects_split_rule_readiness_before_any_write_or_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    import sciplot_core.studio_core.publish_finalize as finalize_module

    inventory, _sources, _snapshots = _inventory(tmp_path)
    canonical_rule_readiness = inventory.rule_readiness.to_payload()
    identity = _presentation_payload(inventory)
    projections = {
        "pending_rule_review": inventory.pending_rule_review,
        "publication_rule_blocked": inventory.publication_rule_blocked,
        "autonomous_rule_ready": not inventory.publication_rule_blocked,
    }
    manifest = {
        "result": {
            "exports": [],
            "template": inventory.presentation_identity.template,
            "presentation_identity": identity,
            "rule_readiness": canonical_rule_readiness,
            **projections,
        },
        "semantic": {
            "presentation_identity": identity,
            "studio_rule_publication_readiness": canonical_rule_readiness,
            "publication_rule_ready": (not inventory.publication_rule_blocked),
        },
        "template": inventory.presentation_identity.template,
        "presentation_identity": identity,
        "studio": {"presentation_identity": identity},
        "scope": "project_delivery",
        "rule_readiness": canonical_rule_readiness,
        **projections,
    }
    if location == "manifest_readiness":
        manifest["rule_readiness"] = {"pending_rule_review": False}
    elif location == "result_readiness":
        manifest["result"]["rule_readiness"] = {"pending_rule_review": False}
    elif location == "semantic_readiness":
        manifest["semantic"]["studio_rule_publication_readiness"] = {
            "pending_rule_review": False
        }
    elif location == "manifest_publication_blocked":
        manifest["publication_rule_blocked"] = True
    elif location == "result_autonomous_rule_ready":
        manifest["result"]["autonomous_rule_ready"] = False
    else:
        manifest["semantic"]["publication_rule_ready"] = False
    effects: list[str] = []
    monkeypatch.setattr(
        finalize_module,
        "_write_studio_revision_brief",
        lambda *_args, **_kwargs: effects.append("revision"),
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_studio_review_html",
        lambda *_args, **_kwargs: effects.append("review"),
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_json_atomic",
        lambda *_args, **_kwargs: effects.append("json"),
    )
    monkeypatch.setattr(
        finalize_module,
        "_register_studio_run",
        lambda *_args, **_kwargs: effects.append("register"),
    )

    with pytest.raises(RuntimeError, match="does not match"):
        finalize_module.finalize_studio_run(
            inventory=inventory,
            evidence=SimpleNamespace(qa={"status": "passed"}),
            manifest=manifest,
            copied_exports=[],
            figures=[],
        )

    assert effects == []
