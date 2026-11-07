from __future__ import annotations

from delivery_identity_helpers import write_legacy_delivery_launcher

from copy import deepcopy
from pathlib import Path
import shutil
import pytest

from sciplot_core.delivery.contracts import (
    DELIVERY_BINDING_POLICY_LEGACY,
    DELIVERY_BINDING_POLICY_RESOLVED_PLAN,
)
from sciplot_core.delivery.package_builder import (
    _figure_ids_by_path,
    build_delivery_package,
)
from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.delivery.plan_binding import plan_source_figure_ids
from sciplot_core.delivery.project_documents import _copy_project_documents
import sciplot_core.delivery.package_builder as package_builder
import sciplot_core.delivery.package_transaction as package_transaction
from sciplot_core.figure_plan import (
    FigureOutcome,
    FigureTask,
    ResolvedFigurePlan,
    figure_plan_gate,
    merge_figure_outcomes,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers import (
    inspect_delivery_editor_launcher_contract,
    inspect_delivery_launcher_contract,
)
from sciplot_core.launchers.delivery_editor_launcher import _delivery_editor_launcher_lines


def _complete_plan(
    source_root: Path,
) -> tuple[ResolvedFigurePlan, dict[str, dict[str, Path]]]:
    tasks = tuple(
        FigureTask(
            figure_id=figure_id,
            order=order,
            title=f"Figure {figure_id}",
            x_metric="x",
            y_metric=figure_id,
            template="point_line",
            artifact_stem=figure_id,
            document_stem=figure_id,
        )
        for order, figure_id in enumerate(("figure_a", "figure_b"), start=1)
    )
    planned = ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy="test_selection",
        primary_figure_id=tasks[0].figure_id,
        tasks=tasks,
    )
    artifacts: dict[str, dict[str, Path]] = {}
    outcomes: list[FigureOutcome] = []
    for task in tasks:
        paths = {
            "vsz": source_root / "studio" / f"{task.figure_id}.vsz",
            "pdf": source_root / "figures" / f"{task.figure_id}.pdf",
            "tiff": (source_root / "figures" / f"{task.figure_id}_300dpi.tiff"),
        }
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{task.figure_id}:{path.suffix}".encode())
        artifacts[task.figure_id] = paths
        outcomes.append(
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=tuple(str(path) for path in paths.values()),
            )
        )
    return merge_figure_outcomes(planned, outcomes), artifacts


def _builder_manifest(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], ResolvedFigurePlan]:
    run = tmp_path / "builder_run"
    run.mkdir()
    (run / "manifest.json").write_text("{}\n", encoding="utf-8")
    plan, source_artifacts = _complete_plan(run / "source")
    data = run / "processed.csv"
    data.write_text(
        "x,y\ns,MPa\nsample,sample\n1,2\n",
        encoding="utf-8",
    )
    figures = [
        str(source_artifacts[figure_id][role])
        for figure_id in plan.selected_figure_ids
        for role in ("pdf", "tiff")
    ]
    documents = [
        str(source_artifacts[figure_id]["vsz"])
        for figure_id in reversed(plan.selected_figure_ids)
    ]
    exports = [
        {
            "path": str(source_artifacts[figure_id][role]),
            "figure_id": figure_id,
        }
        for figure_id in plan.selected_figure_ids
        for role in ("pdf", "tiff")
    ]
    qa = {
        "status": "passed",
        "pdfs": [
            {
                "path": str(source_artifacts[figure_id]["pdf"]),
                "sha256": existing_file_sha256(source_artifacts[figure_id]["pdf"]),
            }
            for figure_id in plan.selected_figure_ids
        ],
        "tiffs": [
            {
                "path": str(source_artifacts[figure_id]["tiff"]),
                "sha256": existing_file_sha256(source_artifacts[figure_id]["tiff"]),
            }
            for figure_id in plan.selected_figure_ids
        ],
    }
    plan_payload = plan.to_payload()
    return (
        run,
        {
            "output": str(run),
            "project": "typed_builder",
            "input": str(data),
            "semantic": {"rule_id": plan.rule_id},
            "request": {"rule_id": plan.rule_id},
            "figures": figures,
            "veusz_documents": documents,
            "veusz_document_hashes": {
                path: existing_file_sha256(Path(path)) for path in documents
            },
            "resolved_figure_plan": plan_payload,
            "result": {
                "processed_source": str(data),
                "resolved_figure_plan": plan_payload,
                "exports": exports,
            },
            "study_model": {
                "run": {
                    "resolved_figure_plan": plan_payload,
                }
            },
            "qa": qa,
        },
        plan,
    )


def _delivery_record(
    tmp_path: Path,
) -> tuple[dict[str, object], Path]:
    run = tmp_path / "run"
    delivery = run / "delivery"
    data_dir = delivery / "data"
    figures_dir = delivery / "figures"
    project_dir = delivery / "project"
    for directory in (data_dir, figures_dir, project_dir):
        directory.mkdir(parents=True, exist_ok=True)
    plan, source_artifacts = _complete_plan(run / "source")
    documents = [
        source_artifacts[figure_id]["vsz"]
        for figure_id in reversed(plan.selected_figure_ids)
    ]
    manifest = {
        "resolved_figure_plan": plan.to_payload(),
        "veusz_documents": [str(path) for path in documents],
        "veusz_document_hashes": {
            str(path.resolve()): existing_file_sha256(path) for path in documents
        },
    }
    project_records = _copy_project_documents(
        manifest,
        output_dir=run,
        project_dir=project_dir,
    )
    data = data_dir / "figure_plot_data.csv"
    data.write_text("x,y\n1,2\n", encoding="utf-8")
    figure_records: list[dict[str, object]] = []
    for figure_id in plan.selected_figure_ids:
        for role, export_format in (("pdf", "pdf"), ("tiff", "tiff_300")):
            source = source_artifacts[figure_id][role]
            destination = figures_dir / source.name
            shutil.copy2(source, destination)
            figure_records.append(
                {
                    "source": str(source),
                    "path": str(destination),
                    "figure_id": figure_id,
                    "export_format": export_format,
                    "source_sha256": existing_file_sha256(source),
                    "delivery_sha256": existing_file_sha256(destination),
                    "copy_hash_matches": True,
                }
            )
    manifest_path = run / "manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    launcher = write_legacy_delivery_launcher(delivery)
    launcher_contract = inspect_delivery_launcher_contract(delivery)
    plan_details = figure_plan_gate(plan.to_payload())
    assert plan_details is not None
    artifacts = [
        {"id": "data", "path": str(data_dir), "exists": True},
        {"id": "figures", "path": str(figures_dir), "exists": True},
        {"id": "project", "path": str(project_dir), "exists": True},
        {"id": "launcher", "path": str(launcher), "exists": True},
        {
            "id": "resolved_figure_plan_complete",
            "path": str(manifest_path),
            "exists": True,
            "details": plan_details,
        },
    ]
    return (
        {
            "kind": "sciplot_user_delivery_package",
            "version": 6,  # Explicit historical v1 launcher fixture.
            "binding_policy": DELIVERY_BINDING_POLICY_RESOLVED_PLAN,
            "path": str(delivery),
            "data_csvs": [
                {
                    "path": str(data),
                    "exists": True,
                    "sha256": existing_file_sha256(data),
                }
            ],
            "figures": figure_records,
            "project_documents": project_records,
            "resolved_figure_plan": plan.to_payload(),
            "open_in_veusz": str(launcher),
            "open_in_veusz_sha256": launcher_contract["content_sha256"],
            "launcher_contract": launcher_contract,
            "artifacts": artifacts,
            "complete": True,
        },
        delivery,
    )


def _expected_manifest(record: dict[str, object]) -> dict[str, object]:
    plan = record["resolved_figure_plan"]
    assert isinstance(plan, dict)
    return {
        "semantic": {"rule_id": plan["rule_id"]},
        "request": {"rule_id": plan["rule_id"]},
        "resolved_figure_plan": plan,
    }


def test_package_builder_consumes_typed_gate_and_nullable_json_objects(
    tmp_path: Path,
) -> None:
    run, manifest, plan = _builder_manifest(tmp_path)

    record = build_delivery_package(run, manifest=manifest)

    assert record["complete"] is True
    assert record["binding_policy"] == DELIVERY_BINDING_POLICY_RESOLVED_PLAN
    assert record["resolved_figure_plan"] == plan.to_payload()
    assert record["verification"]["passed"] is True
    plan_artifact = next(
        item
        for item in record["artifacts"]
        if item["id"] == "resolved_figure_plan_complete"
    )
    assert plan_artifact["exists"] is True
    assert plan_artifact["details"]["valid"] is True
    assert plan_artifact["details"]["complete"] is True
    assert plan_artifact["details"]["plan_id"] == plan.plan_id
    assert plan_artifact["details"]["selected_figure_ids"] == list(
        plan.selected_figure_ids
    )
    assert plan_artifact["details"]["delivered_figure_ids"] == list(
        plan.selected_figure_ids
    )
    assert plan_artifact["details"]["editable_project_figure_ids"] == list(
        plan.selected_figure_ids
    )
    assert all(plan_artifact["details"]["projection_consistency"].values())

    (run / "publication_intent.json").write_text("{}\n", encoding="utf-8")
    nullable = deepcopy(manifest)
    nullable["qa"] = None
    nullable["publication_intent"] = None
    nullable["result"] = None

    rejected = build_delivery_package(run, manifest=nullable)

    assert rejected["complete"] is False
    rejected_artifacts = {item["id"]: item for item in rejected["artifacts"]}
    assert rejected_artifacts["qa_passed"]["exists"] is False
    assert "publication_qa_passed" not in rejected_artifacts
    assert {item["figure_id"] for item in rejected["figures"]} == set(
        plan.selected_figure_ids
    )
    rejected_plan_artifact = next(
        item
        for item in rejected["artifacts"]
        if item["id"] == "resolved_figure_plan_complete"
    )
    assert rejected_plan_artifact["exists"] is False
    assert rejected_plan_artifact["details"]["valid"] is True
    assert rejected_plan_artifact["details"]["complete"] is False
    assert (
        rejected_plan_artifact["details"]["reason"]
        == "resolved_figure_plan_projection_mismatch"
    )
    assert (
        rejected_plan_artifact["details"]["projection_consistency"][
            "result_plan_matches"
        ]
        is False
    )


def test_package_builder_distinguishes_legacy_and_required_plan_gates(
    tmp_path: Path,
) -> None:
    run, manifest, _plan = _builder_manifest(tmp_path)
    legacy = deepcopy(manifest)
    legacy.pop("resolved_figure_plan")
    legacy["semantic"] = {"rule_id": "legacy_custom_rule"}
    legacy["request"] = {"rule_id": "legacy_custom_rule"}
    legacy_result = deepcopy(legacy["result"])
    legacy_result.pop("resolved_figure_plan")
    legacy["result"] = legacy_result
    legacy["study_model"] = {"run": {}}

    legacy_record = build_delivery_package(run, manifest=legacy)

    assert legacy_record["complete"] is True
    assert legacy_record["binding_policy"] == DELIVERY_BINDING_POLICY_LEGACY
    assert "resolved_figure_plan" not in legacy_record
    assert legacy_record["verification"]["passed"] is True
    assert (
        legacy_record["verification"]["checks"]["resolved_figure_plan_record_bindings"]
        is True
    )
    assert legacy_record["verification"]["resolved_figure_plan_binding"] == {
        "passed": True,
        "reason": "explicit_legacy_without_resolved_plan",
    }
    assert "resolved_figure_plan_complete" not in {
        item["id"] for item in legacy_record["artifacts"]
    }

    required = deepcopy(legacy)
    required["semantic"] = {"rule_id": "impact_metric"}
    required["request"] = {"rule_id": "impact_metric"}

    rejected = build_delivery_package(run, manifest=required)

    assert rejected["complete"] is False
    assert rejected["binding_policy"] == DELIVERY_BINDING_POLICY_RESOLVED_PLAN
    assert rejected["resolved_figure_plan"] is None
    assert rejected["verification"]["passed"] is False
    assert rejected["verification"]["checks"]["binding_policy_current"] is False
    assert rejected["verification"]["resolved_figure_plan_binding"] == {
        "passed": False,
        "reason": "resolved_plan_missing_or_invalid",
    }
    plan_artifact = next(
        item
        for item in rejected["artifacts"]
        if item["id"] == "resolved_figure_plan_complete"
    )
    assert plan_artifact["exists"] is False
    assert plan_artifact["details"]["valid"] is False
    assert (
        plan_artifact["details"]["reason"]
        == "resolved_figure_plan_required_for_supported_rule"
    )


def test_project_documents_map_vsz_paths_to_plan_ids_not_list_order(
    tmp_path: Path,
) -> None:
    record, _delivery = _delivery_record(tmp_path)
    by_source = {
        Path(str(item["source"])).stem: item["figure_id"]
        for item in record["project_documents"]
    }

    assert by_source == {
        "figure_a": "figure_a",
        "figure_b": "figure_b",
    }


def test_delivery_revalidation_rejects_identity_and_hash_tampering(
    tmp_path: Path,
) -> None:
    record, delivery = _delivery_record(tmp_path)
    expected_manifest = _expected_manifest(record)
    baseline = verify_delivery_package(
        record,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert baseline["passed"] is True
    assert baseline["resolved_figure_plan_binding"]["passed"] is True
    assert set(baseline["resolved_figure_plan_binding"]) == {
        "passed",
        "figure_records",
        "project_records",
    }

    different_plan, _different_artifacts = _complete_plan(tmp_path / "different_source")
    plan_mismatch = verify_delivery_package(
        record,
        expected_root=delivery,
        expected_manifest={
            "semantic": {"rule_id": different_plan.rule_id},
            "request": {"rule_id": different_plan.rule_id},
            "resolved_figure_plan": different_plan.to_payload(),
        },
    )
    assert plan_mismatch["passed"] is False
    assert plan_mismatch["checks"]["binding_policy_current"] is False
    assert plan_mismatch["checks"]["resolved_figure_plan_record_current"] is False
    assert plan_mismatch["resolved_figure_plan_binding"]["passed"] is True

    delivered_pdf = next(
        Path(str(item["path"]))
        for item in record["figures"]
        if item["export_format"] == "pdf"
    )
    original_pdf = delivered_pdf.read_bytes()
    try:
        delivered_pdf.write_bytes(original_pdf + b"\ntampered delivery bytes")
        live_hash_check = verify_delivery_package(
            record,
            expected_root=delivery,
            expected_manifest=expected_manifest,
        )
    finally:
        delivered_pdf.write_bytes(original_pdf)
    assert live_hash_check["passed"] is False
    assert live_hash_check["checks"]["pdf_files_current"] is False
    assert live_hash_check["checks"]["resolved_figure_plan_figure_hashes"] is False
    assert live_hash_check["checks"]["resolved_figure_plan_record_bindings"] is True

    swapped_formats = deepcopy(record)
    tiff_records = [
        item
        for item in swapped_formats["figures"]
        if item["export_format"] == "tiff_300"
    ]
    tiff_records[0]["figure_id"], tiff_records[1]["figure_id"] = (
        tiff_records[1]["figure_id"],
        tiff_records[0]["figure_id"],
    )
    swapped_check = verify_delivery_package(
        swapped_formats,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert swapped_check["passed"] is False
    assert swapped_check["checks"]["resolved_figure_plan_coverage"] is False

    duplicate_project_id = deepcopy(record)
    duplicate_project_id["project_documents"][1]["figure_id"] = duplicate_project_id[
        "project_documents"
    ][0]["figure_id"]
    duplicate_check = verify_delivery_package(
        duplicate_project_id,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert duplicate_check["passed"] is False
    assert (
        duplicate_check["checks"]["resolved_figure_plan_project_document_coverage"]
        is False
    )

    false_hash_attestation = deepcopy(record)
    false_hash_attestation["project_documents"][1]["hash_matches_export"] = False
    hash_check = verify_delivery_package(
        false_hash_attestation,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert hash_check["passed"] is False
    assert hash_check["checks"]["resolved_figure_plan_project_document_hashes"] is False

    coherent_id_swap = deepcopy(record)
    for item in coherent_id_swap["figures"]:
        item["figure_id"] = (
            "figure_b" if item["figure_id"] == "figure_a" else "figure_a"
        )
    for item in coherent_id_swap["project_documents"]:
        item["figure_id"] = (
            "figure_b" if item["figure_id"] == "figure_a" else "figure_a"
        )
    coherent_check = verify_delivery_package(
        coherent_id_swap,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert coherent_check["passed"] is False
    assert coherent_check["checks"]["resolved_figure_plan_record_bindings"] is False

    duplicate_project_path = deepcopy(record)
    first_project = duplicate_project_path["project_documents"][0]
    second_project = duplicate_project_path["project_documents"][1]
    for key in (
        "source",
        "path",
        "relative_path",
        "source_sha256",
        "expected_sha256",
        "delivery_sha256",
        "copy_hash_matches",
        "hash_matches_export",
        "exists",
    ):
        second_project[key] = first_project[key]
    duplicate_path_check = verify_delivery_package(
        duplicate_project_path,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert duplicate_path_check["passed"] is False
    assert duplicate_path_check["checks"]["project_files_current"] is False


def test_resolved_delivery_cannot_downgrade_by_deleting_plan_fields(
    tmp_path: Path,
) -> None:
    record, delivery = _delivery_record(tmp_path)
    expected_manifest = _expected_manifest(record)
    downgraded = deepcopy(record)
    downgraded.pop("resolved_figure_plan")
    downgraded["artifacts"] = [
        item
        for item in downgraded["artifacts"]
        if item.get("id") != "resolved_figure_plan_complete"
    ]
    for collection in ("figures", "project_documents"):
        for item in downgraded[collection]:
            item.pop("figure_id", None)

    check = verify_delivery_package(
        downgraded,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )

    assert check["passed"] is False
    assert check["checks"]["binding_policy_current"] is False
    assert check["checks"]["resolved_figure_plan_record_current"] is False
    assert check["checks"]["resolved_figure_plan_record_bindings"] is False

    downgraded["binding_policy"] = "legacy_unplanned"
    policy_check = verify_delivery_package(
        downgraded,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert policy_check["passed"] is False
    assert policy_check["checks"]["binding_policy_current"] is False
    assert policy_check["resolved_figure_plan_binding"] == {
        "passed": False,
        "reason": "explicit_legacy_without_resolved_plan",
    }

    invalid_policy = deepcopy(downgraded)
    invalid_policy["binding_policy"] = "unknown_policy"
    invalid_policy_check = verify_delivery_package(
        invalid_policy,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert invalid_policy_check["passed"] is False
    assert invalid_policy_check["checks"]["binding_policy_current"] is False
    assert invalid_policy_check["resolved_figure_plan_binding"] == {
        "passed": False,
        "reason": "delivery_binding_policy_missing_or_invalid",
    }

    missing_policy = deepcopy(downgraded)
    missing_policy.pop("binding_policy")
    missing_policy_check = verify_delivery_package(
        missing_policy,
        expected_root=delivery,
        expected_manifest=expected_manifest,
    )
    assert missing_policy_check["passed"] is False
    assert missing_policy_check["checks"]["binding_policy_current"] is False
    assert missing_policy_check["resolved_figure_plan_binding"] == {
        "passed": False,
        "reason": "delivery_binding_policy_missing_or_invalid",
    }

    supported_manifest_without_plan = {
        "semantic": {"rule_id": "impact_metric"},
        "request": {"rule_id": "impact_metric"},
    }
    coordinated_check = verify_delivery_package(
        downgraded,
        expected_root=delivery,
        expected_manifest=supported_manifest_without_plan,
    )
    assert coordinated_check["passed"] is False
    assert coordinated_check["checks"]["binding_policy_current"] is False


def test_result_export_ids_cannot_override_outcome_authority(
    tmp_path: Path,
) -> None:
    plan, artifacts = _complete_plan(tmp_path / "source")
    swapped = {
        "figure_a": "figure_b",
        "figure_b": "figure_a",
    }
    result_exports = [
        {
            "path": str(artifacts[figure_id][role]),
            "figure_id": swapped[figure_id],
        }
        for figure_id in plan.selected_figure_ids
        for role in ("pdf", "tiff")
    ]

    try:
        _figure_ids_by_path(
            {
                "resolved_figure_plan": plan.to_payload(),
                "result": {"exports": result_exports},
            }
        )
    except ValueError as exc:
        assert "conflicts with the resolved outcome" in str(exc)
    else:
        raise AssertionError("A full PDF/TIFF figure-id swap was accepted.")


def test_outcome_vsz_cannot_be_swapped_between_tasks(
    tmp_path: Path,
) -> None:
    plan, artifacts = _complete_plan(tmp_path / "source")
    swapped_outcomes = [
        FigureOutcome(
            figure_id=figure_id,
            status="ready",
            artifacts=(
                str(artifacts[figure_id]["pdf"]),
                str(artifacts[figure_id]["tiff"]),
                str(
                    artifacts["figure_b" if figure_id == "figure_a" else "figure_a"][
                        "vsz"
                    ]
                ),
            ),
        )
        for figure_id in plan.selected_figure_ids
    ]
    swapped_plan = merge_figure_outcomes(plan, swapped_outcomes)

    try:
        _figure_ids_by_path(
            {
                "resolved_figure_plan": swapped_plan.to_payload(),
                "result": {"exports": []},
            }
        )
    except ValueError as exc:
        assert "VSZ path does not match" in str(exc)
    else:
        raise AssertionError("Cross-task VSZ outcomes were accepted.")


def test_vsz_binding_does_not_accept_arbitrary_matching_ancestor_names(
    tmp_path: Path,
) -> None:
    tasks = tuple(
        FigureTask(
            figure_id=figure_id,
            order=order,
            title=figure_id,
            x_metric="x",
            y_metric=figure_id,
            template="point_line",
            artifact_stem=figure_id,
            document_stem=figure_id,
        )
        for order, figure_id in enumerate(("figure_a", "figure_b"), start=1)
    )
    planned = ResolvedFigurePlan.planned(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id="figure_a",
        tasks=tasks,
    )
    nested = tmp_path / "figure_a" / "figure_b"
    nested.mkdir(parents=True)
    outcomes: list[FigureOutcome] = []
    for task in tasks:
        pdf = tmp_path / f"{task.figure_id}.pdf"
        tiff = tmp_path / f"{task.figure_id}_300dpi.tiff"
        swapped_vsz = nested / (
            "figure_b.vsz" if task.figure_id == "figure_a" else "figure_a.vsz"
        )
        for path in (pdf, tiff, swapped_vsz):
            path.write_bytes(task.figure_id.encode())
        outcomes.append(
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=(str(pdf), str(tiff), str(swapped_vsz)),
            )
        )
    completed = merge_figure_outcomes(planned, outcomes)

    try:
        plan_source_figure_ids(completed)
    except ValueError as exc:
        assert "VSZ path does not match" in str(exc)
    else:
        raise AssertionError("Arbitrary matching VSZ ancestors were accepted.")


def test_plan_binding_honors_portable_mixed_case_artifact_stems(
    tmp_path: Path,
) -> None:
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="x",
        y_metric="y",
        template="point_line",
        artifact_stem="Figure_A_Export",
        document_stem="Figure_A_Document",
    )
    planned = ResolvedFigurePlan.planned(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    paths = (
        tmp_path / "Figure_A_Document.vsz",
        tmp_path / "Figure_A_Export.pdf",
        tmp_path / "Figure_A_Export_300dpi.tiff",
    )
    for path in paths:
        path.write_bytes(b"mixed-case")
    completed = merge_figure_outcomes(
        planned,
        (
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=tuple(str(path) for path in paths),
            ),
        ),
    )

    assert set(plan_source_figure_ids(completed).values()) == {"figure_a"}


def test_single_primary_plan_accepts_canonical_studio_document_exports(
    tmp_path: Path,
) -> None:
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
    paths = (
        tmp_path / "studio" / "document.vsz",
        tmp_path / "figures" / "document.pdf",
        tmp_path / "figures" / "document_300dpi.tiff",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"canonical-studio-export")
    completed = merge_figure_outcomes(
        planned,
        (
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=tuple(str(path) for path in paths),
            ),
        ),
    )

    assert set(plan_source_figure_ids(completed).values()) == {
        "impact_strength_by_sample"
    }
    export_ids = _figure_ids_by_path(
        {
            "resolved_figure_plan": completed.to_payload(),
            "result": {
                "exports": [
                    {"path": str(path), "figure_id": "primary"} for path in paths[1:]
                ]
            },
        }
    )
    assert set(export_ids.values()) == {"impact_strength_by_sample"}


def test_primary_document_fallback_must_be_the_run_local_studio_document(
    tmp_path: Path,
) -> None:
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="x",
        y_metric="y",
        template="point_line",
        artifact_stem="figure_a",
        document_stem="figure_a",
    )
    planned = ResolvedFigurePlan.planned(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    paths = (
        tmp_path / "unrelated" / "studio" / "document.vsz",
        tmp_path / "run" / "figures" / "figure_a.pdf",
        tmp_path / "run" / "figures" / "figure_a_300dpi.tiff",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unrelated-primary")
    completed = merge_figure_outcomes(
        planned,
        (
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=tuple(str(path) for path in paths),
            ),
        ),
    )

    try:
        plan_source_figure_ids(completed)
    except ValueError as exc:
        assert "VSZ path does not match" in str(exc)
    else:
        raise AssertionError("An unrelated primary document.vsz was accepted.")


def _package_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _historical_editor(record: dict[str, object]) -> Path:
    root = Path(record["path"])
    path = root / "Open_in_SciPlot.command"
    path.write_text("\n".join(_delivery_editor_launcher_lines()) + "\n", encoding="utf-8")
    path.chmod(0o751)
    contract = inspect_delivery_editor_launcher_contract(root)
    record.update(open_in_sciplot=str(path),
                  open_in_sciplot_sha256=existing_file_sha256(path),
                  editor_launcher_contract=contract)
    record["artifacts"].append({"id": "open_in_sciplot", "path": str(path),
                                "exists": True, "details": contract})
    return path


def test_fresh_delivery_has_no_editor_entry_or_requirement(tmp_path: Path):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    assert record["complete"] is True
    assert record["version"] == 7
    assert not (root / "Open_in_SciPlot.command").exists()
    assert not {"open_in_sciplot", "open_in_sciplot_sha256", "editor_launcher_contract"} & record.keys()
    assert "open_in_sciplot" not in {item["id"] for item in record["artifacts"]}
    assert record["verification"]["checks"]["editor_launcher_current"] is True
    assert record["verification"]["editor_launcher"] is None
    assert (root / "SciPlot_delivery.json").is_file()
    assert not (root / "Open_in_Veusz.command").exists()


def test_recorded_legacy_editor_remains_readable_and_preserved_on_publication(tmp_path: Path):
    run, manifest, _ = _builder_manifest(tmp_path)
    historical = build_delivery_package(run, manifest=manifest)
    root = Path(historical["path"])
    editor = _historical_editor(historical)
    before = _package_bytes(root)
    mode = editor.stat().st_mode
    assert verify_delivery_package(historical, expected_root=root, expected_manifest=manifest)["passed"] is True
    assert _package_bytes(root) == before
    manifest["delivery_package"] = historical
    record = build_delivery_package(run, manifest=manifest)
    assert record["complete"] is True
    assert record["verification"]["passed"] is True
    assert record["open_in_sciplot_sha256"] == historical["open_in_sciplot_sha256"]
    assert editor.stat().st_mode == mode
    assert _package_bytes(root) == before
    assert "open_in_sciplot" not in {item["id"] for item in record["artifacts"]}
    editor.write_text(editor.read_text() + "# changed after publication\n")
    result = verify_delivery_package(record, expected_root=root, expected_manifest=manifest)
    assert result["passed"] is False
    assert "editor_launcher_current" in result["failed_checks"]


def test_explicit_previous_delivery_binds_staged_and_public_builder(tmp_path: Path):
    run, manifest, _ = _builder_manifest(tmp_path)
    historical = build_delivery_package(run, manifest=manifest)
    root = Path(historical["path"])
    editor = _historical_editor(historical)
    before = _package_bytes(root)
    # Explicit saved evidence takes priority over an unrelated run field.
    manifest["delivery_package"] = {"path": str(tmp_path / "other")}
    stage = tmp_path / "private_preparation"
    staged = package_builder._build_staged_delivery(
        run, manifest=manifest, delivery_dir=stage, final_root=root,
        previous_delivery=historical,
    )
    assert staged["complete"] is True
    assert staged["verification"]["passed"] is True
    assert (stage / editor.name).read_bytes() == editor.read_bytes()
    assert _package_bytes(root) == before
    installed = build_delivery_package(run, manifest=manifest, previous_delivery=historical)
    assert installed["verification"]["passed"] is True
    assert _package_bytes(root) == before


def test_delivery_without_legacy_editor_stays_without_it_on_publication(tmp_path: Path):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    assert verify_delivery_package(record, expected_root=root, expected_manifest=manifest)["passed"] is True
    manifest["delivery_package"] = record
    upgraded = build_delivery_package(run, manifest=manifest)
    assert upgraded["complete"] is True
    assert "open_in_sciplot" not in upgraded
    assert not (root / "Open_in_SciPlot.command").exists()


@pytest.mark.parametrize("missing", ["open_in_sciplot", "open_in_sciplot_sha256", "editor_launcher_contract"])
def test_partial_editor_entry_record_is_not_treated_as_legacy(tmp_path: Path, missing: str):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    _historical_editor(record)
    record.pop(missing)
    result = verify_delivery_package(record, expected_root=root, expected_manifest=manifest)
    assert result["passed"] is False
    assert "editor_launcher_current" in result["failed_checks"]
    before = _package_bytes(root)
    manifest["delivery_package"] = record
    with pytest.raises(ValueError, match="unregistered or changed"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before


def test_unregistered_canonical_editor_is_not_adopted_or_deleted(tmp_path: Path):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    manifest["delivery_package"] = deepcopy(record)
    _historical_editor(record)
    before = _package_bytes(root)
    unregistered = verify_delivery_package(manifest["delivery_package"], expected_root=root, expected_manifest=manifest)
    assert "minimal_top_level" in unregistered["failed_checks"]
    with pytest.raises(ValueError, match="unregistered or changed"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before


@pytest.mark.parametrize("change", ["command", "hash", "executable", "symlink", "directory"])
def test_changed_legacy_editor_is_refused_without_replacing_package(tmp_path: Path, change: str):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    editor = _historical_editor(record)
    manifest["delivery_package"] = record
    if change == "command":
        editor.write_text(editor.read_text().replace('edit "${DELIVERY_DIR}"', 'studio "${DELIVERY_DIR}"'))
    elif change == "hash":
        # Portable assignments remain structurally valid but exact bytes differ.
        editor.write_text(editor.read_text().replace("FALLBACK_REPO=", "FALLBACK_REPO=/other"))
        assert inspect_delivery_editor_launcher_contract(root)["ready"] is True
    elif change == "executable":
        editor.chmod(0o644)
    elif change == "symlink":
        target = tmp_path / "old_editor"
        editor.rename(target)
        editor.symlink_to(target)
    else:
        editor.unlink()
        editor.mkdir()
    before = _package_bytes(root)
    with pytest.raises(ValueError):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before


def test_legacy_editor_copy_failure_preserves_original_package(tmp_path: Path, monkeypatch):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    editor = _historical_editor(record)
    manifest["delivery_package"] = record
    before = _package_bytes(root)
    original = shutil.copy2

    def fail_editor(source, target, *args, **kwargs):
        result = original(source, target, *args, **kwargs)
        if Path(source) == editor:
            raise OSError("legacy preservation copy failure")
        return result

    monkeypatch.setattr(package_transaction.shutil, "copy2", fail_editor)
    with pytest.raises(OSError, match="legacy preservation copy failure"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert not list(root.parent.glob(f".{root.name}.sciplot-*"))


@pytest.mark.parametrize("change", ["bytes", "mode"])
def test_legacy_editor_race_is_refused_without_losing_concurrent_bytes(tmp_path: Path, monkeypatch, change: str):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    editor = _historical_editor(record)
    manifest["delivery_package"] = record
    original = shutil.copy2
    observed = {}

    def change_editor(source, target, *args, **kwargs):
        result = original(source, target, *args, **kwargs)
        if Path(source) == editor:
            if change == "bytes":
                editor.write_bytes(b"concurrent user change must survive")
            else:
                editor.chmod(0o700)
            observed.update(_package_bytes(root))
        return result

    monkeypatch.setattr(package_transaction.shutil, "copy2", change_editor)
    with pytest.raises(RuntimeError, match="changed during"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == observed
    if change == "mode":
        assert editor.stat().st_mode & 0o777 == 0o700
    assert not list(root.parent.glob(f".{root.name}.sciplot-*"))


def test_legacy_editor_mode_change_after_staging_is_not_lost(tmp_path: Path, monkeypatch):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    editor = _historical_editor(record)
    manifest["delivery_package"] = record
    before = _package_bytes(root)
    original = package_builder._build_staged_delivery

    def change_after_staging(*args, **kwargs):
        result = original(*args, **kwargs)
        editor.chmod(0o700)
        return result

    monkeypatch.setattr(package_builder, "_build_staged_delivery", change_after_staging)
    with pytest.raises(RuntimeError, match="visible delivery changed"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert editor.stat().st_mode & 0o777 == 0o700
    assert not list(root.parent.glob(f".{root.name}.sciplot-*"))


def test_non_launcher_modes_keep_existing_hash_only_snapshot_contract(tmp_path: Path):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    before = package_transaction._package_snapshot(root)
    Path(record["figures"][0]["path"]).chmod(0o600)
    Path(record["data_csvs"][0]["path"]).chmod(0o600)
    Path(record["project_documents"][0]["path"]).chmod(0o600)
    assert package_transaction._package_snapshot(root) == before


def test_legacy_editor_final_verification_failure_restores_complete_original(tmp_path: Path, monkeypatch):
    run, manifest, _ = _builder_manifest(tmp_path)
    record = build_delivery_package(run, manifest=manifest)
    root = Path(record["path"])
    editor = _historical_editor(record)
    manifest["delivery_package"] = record
    before = _package_bytes(root)
    mode = editor.stat().st_mode
    original = package_transaction.verify_delivery_package

    def reject_installed(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result["passed"] is True
        assert editor.read_bytes() == before[editor.name]
        return {**result, "passed": False}

    monkeypatch.setattr(package_transaction, "verify_delivery_package", reject_installed)
    with pytest.raises(RuntimeError, match="previous package was restored"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert editor.stat().st_mode == mode
    assert not list(root.parent.glob(f".{root.name}.sciplot-*"))


def test_delivery_copy_failure_keeps_previous_visible_package(
    tmp_path: Path, monkeypatch
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    before = _package_bytes(root)
    original = shutil.copy2

    def fail_copy(source, target, *args, **kwargs):
        if Path(target).suffix == ".pdf":
            raise OSError("simulated copy failure")
        return original(source, target, *args, **kwargs)

    monkeypatch.setattr(package_builder.shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="simulated copy failure"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert not list(root.parent.glob(f".{root.name}.sciplot-stage-*"))


def test_delivery_replacement_failure_restores_previous_package(
    tmp_path: Path, monkeypatch
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    before = _package_bytes(root)
    original = Path.replace

    def fail_stage(self, target):
        if (
            self.name.startswith(f".{root.name}.sciplot-stage-")
            and Path(target) == root
        ):
            raise OSError("simulated replacement failure")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", fail_stage)
    with pytest.raises(OSError, match="simulated replacement failure"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert not list(root.parent.glob(f".{root.name}.sciplot-previous-*"))


def test_delivery_post_install_failure_rolls_back(tmp_path: Path, monkeypatch) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    before = _package_bytes(root)
    monkeypatch.setattr(
        package_transaction,
        "verify_delivery_package",
        lambda *args, **kwargs: {"passed": False},
    )
    with pytest.raises(RuntimeError, match="previous package was restored"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before


def test_incomplete_delivery_is_diagnostic_and_does_not_replace_visible_package(
    tmp_path: Path,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    before = _package_bytes(root)
    invalid = deepcopy(manifest)
    invalid["qa"] = None
    rejected = build_delivery_package(run, manifest=invalid)
    assert rejected["complete"] is False
    assert Path(rejected["path"]).is_relative_to(run / "failed_delivery")
    assert Path(rejected["path"]).is_dir()
    assert _package_bytes(root) == before


def test_delivery_preserves_user_edited_visible_vsz(tmp_path: Path) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    edited = Path(first["project_documents"][0]["path"])
    edited.write_text("unique user edits", encoding="utf-8")
    before = _package_bytes(root)
    with pytest.raises(ValueError, match="edited or unverified") as error:
        build_delivery_package(run, manifest=manifest)
    assert str(edited) in str(error.value)
    assert _package_bytes(root) == before


def test_delivery_second_publication_accepts_new_canonical_revision(
    tmp_path: Path,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    for value in manifest["veusz_documents"]:
        document = Path(value)
        document.write_bytes(document.read_bytes() + b"\ncanonical edit")
        manifest["veusz_document_hashes"][value] = existing_file_sha256(document)
    second = build_delivery_package(run, manifest=manifest)
    assert first["path"] == second["path"]
    assert second["complete"] is True
    assert second["verification"]["passed"] is True
    assert all(
        Path(item["path"]).read_bytes().endswith(b"canonical edit")
        for item in second["project_documents"]
    )
    assert not list(Path(second["path"]).parent.glob(".*.sciplot-previous-*"))


def test_delivery_malformed_plan_preserves_previous_package(tmp_path: Path) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    before = _package_bytes(root)
    invalid = deepcopy(manifest)
    invalid["resolved_figure_plan"] = {"invalid": True}
    with pytest.raises(ValueError, match="unsupported fields"):
        build_delivery_package(run, manifest=invalid)
    assert _package_bytes(root) == before


def test_delivery_accepts_visible_edits_after_exact_reconciliation(
    tmp_path: Path,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    item = first["project_documents"][0]
    Path(item["path"]).write_bytes(b"reconciled user edit")
    Path(item["source"]).write_bytes(b"reconciled user edit")
    manifest["veusz_document_hashes"][item["source"]] = existing_file_sha256(
        Path(item["source"])
    )
    second = build_delivery_package(run, manifest=manifest)
    assert second["complete"] is True
    assert Path(item["path"]).read_bytes() == b"reconciled user edit"


def test_delivery_preserves_unrecorded_nested_editable_copy(tmp_path: Path) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    manual = root / "project" / "my_revision" / "saved.VSZ"
    manual.parent.mkdir()
    manual.write_bytes(b"only copy of an alternate edit")
    before = _package_bytes(root)
    with pytest.raises(ValueError, match="edited or unverified"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before


def test_delivery_finder_metadata_is_current_and_preserved_on_replacement(
    tmp_path: Path,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    metadata = {}
    for directory in (root, *(path for path in root.iterdir() if path.is_dir()), root / "project" / "view"):
        directory.mkdir(exist_ok=True)
        path = directory / ".DS_Store"
        path.write_bytes(f"Finder view for {directory.name}".encode())
        metadata[str(path.relative_to(root))] = path.read_bytes()
    before = _package_bytes(root)
    verified = verify_delivery_package(first, expected_root=root, expected_manifest=manifest)
    assert verified["passed"] is True
    assert verified["top_level"]["ignored_finder_metadata"] == [".DS_Store"]
    second = build_delivery_package(run, manifest=manifest)
    assert second["verification"]["passed"] is True
    assert _package_bytes(root) == before
    assert all((root / name).read_bytes() == data for name, data in metadata.items())


@pytest.mark.parametrize("location", ["", "project"])
@pytest.mark.parametrize("kind", ["directory", "symlink", "hardlink"])
def test_delivery_finder_metadata_name_does_not_hide_linked_or_directory_content(
    tmp_path: Path, location: str, kind: str,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    path = root / location / ".DS_Store"
    target = tmp_path / "precious_content"
    target.write_bytes(b"must remain untouched")
    if kind == "directory":
        path.mkdir()
        (path / "real_file.txt").write_bytes(target.read_bytes())
    elif kind == "symlink":
        path.symlink_to(target)
    else:
        path.hardlink_to(target)
    before = _package_bytes(root)
    verified = verify_delivery_package(first, expected_root=root, expected_manifest=manifest)
    assert verified["passed"] is False
    assert "filesystem_metadata_safe" in verified["failed_checks"]
    with pytest.raises(ValueError):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert target.read_bytes() == b"must remain untouched"


@pytest.mark.parametrize("location", ["", "project"])
def test_delivery_finder_metadata_exception_does_not_hide_other_dotfiles(
    tmp_path: Path, location: str,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    (root / ".DS_Store").write_bytes(b"Finder state")
    (root / location / ".my_notes").write_bytes(b"only copy of personal notes")
    before = _package_bytes(root)
    with pytest.raises(ValueError):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before


@pytest.mark.parametrize("change_artifact", [False, True])
def test_delivery_finder_metadata_changes_during_build_keep_artifact_snapshot_guard(
    tmp_path: Path, monkeypatch, change_artifact: bool,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    metadata = root / "project" / ".DS_Store"
    metadata.write_bytes(b"old Finder state")
    original = package_builder._build_staged_delivery
    changed_bytes = {}

    def build_with_finder_change(*args, **kwargs):
        result = original(*args, **kwargs)
        metadata.write_bytes(b"latest Finder state")
        (root / ".DS_Store").write_bytes(b"new Finder state")
        if change_artifact:
            Path(first["figures"][0]["path"]).write_bytes(b"concurrent real artifact edit")
        changed_bytes.update(_package_bytes(root))
        return result

    monkeypatch.setattr(package_builder, "_build_staged_delivery", build_with_finder_change)
    if change_artifact:
        with pytest.raises(RuntimeError, match="visible delivery changed"):
            build_delivery_package(run, manifest=manifest)
    else:
        second = build_delivery_package(run, manifest=manifest)
        assert second["verification"]["passed"] is True
    assert _package_bytes(root) == changed_bytes


def test_delivery_metadata_preservation_failure_restores_previous_package(
    tmp_path: Path, monkeypatch,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    (root / ".DS_Store").write_bytes(b"original Finder state")
    before = _package_bytes(root)
    original = package_transaction._preserve_finder_metadata

    def fail_after_copy(previous, candidate):
        original(previous, candidate)
        raise OSError("simulated metadata preservation failure")

    monkeypatch.setattr(package_transaction, "_preserve_finder_metadata", fail_after_copy)
    with pytest.raises(OSError, match="metadata preservation failure"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert not list(root.parent.glob(f".{root.name}.sciplot-previous-*"))


def test_delivery_metadata_does_not_hide_edited_vsz_or_artifact_hash_drift(
    tmp_path: Path,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    (root / ".DS_Store").write_bytes(b"Finder state")
    (root / "project" / ".DS_Store").write_bytes(b"Finder project state")
    Path(first["project_documents"][0]["path"]).write_bytes(b"unique user edits")
    Path(first["figures"][0]["path"]).write_bytes(b"changed figure bytes")
    before = _package_bytes(root)
    verified = verify_delivery_package(first, expected_root=root, expected_manifest=manifest)
    assert verified["passed"] is False
    assert verified["checks"]["minimal_top_level"] is True
    assert verified["checks"]["project_files_current"] is False
    with pytest.raises(ValueError, match="edited or unverified"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before


def test_delivery_preservation_rechecks_real_artifacts_after_previous_package_moves(
    tmp_path: Path, monkeypatch,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    (root / ".DS_Store").write_bytes(b"original Finder state")
    original = package_transaction._preserve_finder_metadata
    changed_bytes = {}

    def copy_with_concurrent_edit(previous, candidate):
        original(previous, candidate)
        document = previous / Path(first["project_documents"][0]["path"]).relative_to(root)
        document.write_bytes(b"new user edit through the previous directory")
        changed_bytes.update(_package_bytes(previous))

    monkeypatch.setattr(package_transaction, "_preserve_finder_metadata", copy_with_concurrent_edit)
    with pytest.raises(RuntimeError, match="changed during metadata preservation"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == changed_bytes
    assert not list(root.parent.glob(f".{root.name}.sciplot-previous-*"))


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_delivery_metadata_preservation_does_not_overwrite_linked_candidate_target(
    tmp_path: Path, monkeypatch, kind,
) -> None:
    run, manifest, _ = _builder_manifest(tmp_path)
    first = build_delivery_package(run, manifest=manifest)
    root = Path(first["path"])
    (root / ".DS_Store").write_bytes(b"original Finder state")
    before = _package_bytes(root)
    target = tmp_path / "precious_file"
    target.write_bytes(b"outside content")
    original = package_transaction._preserve_finder_metadata

    def copy_with_linked_target(previous, candidate):
        metadata = candidate / ".DS_Store"
        if kind == "symlink":
            metadata.symlink_to(target)
        else:
            metadata.hardlink_to(target)
        original(previous, candidate)

    monkeypatch.setattr(package_transaction, "_preserve_finder_metadata", copy_with_linked_target)
    with pytest.raises(ValueError, match="Candidate Finder metadata"):
        build_delivery_package(run, manifest=manifest)
    assert _package_bytes(root) == before
    assert target.read_bytes() == b"outside content"


def test_v6_delivery_migrates_to_inert_v7_without_losing_recorded_browser_history(tmp_path):
    from sciplot_core.delivery_identity import read_delivery_binding, DELIVERY_IDENTITY

    run, manifest, _ = _builder_manifest(tmp_path)
    previous = build_delivery_package(run, manifest=manifest)
    root = Path(previous["path"])
    binding = read_delivery_binding(root)
    launcher = write_legacy_delivery_launcher(root, binding=binding)
    (root / DELIVERY_IDENTITY).unlink()
    previous["version"] = 6
    for key in ("identity", "identity_sha256", "identity_contract"):
        previous.pop(key)
    contract = inspect_delivery_launcher_contract(root)
    previous.update(open_in_veusz=str(launcher), open_in_veusz_sha256=contract["content_sha256"], launcher_contract=contract)
    for artifact in previous["artifacts"]:
        if artifact["id"] == "delivery_identity":
            artifact.update(id="open_in_veusz", path=str(launcher), details=contract)
    _historical_editor(previous)
    old_editor = (root / "Open_in_SciPlot.command").read_bytes()
    assert verify_delivery_package(previous, expected_root=root, expected_manifest=manifest)["passed"]
    record = build_delivery_package(run, manifest=manifest, previous_delivery=previous)
    assert record["version"] == 7 and record["complete"] is True
    assert (root / "Open_in_SciPlot.command").read_bytes() == old_editor
    assert (root / DELIVERY_IDENTITY).is_file()
    assert not (root / "Open_in_Veusz.command").exists()
    assert record["verification"]["passed"]
