from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil

from sciplot_core.delivery import DELIVERY_PACKAGE_CONTRACT_VERSION
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
from sciplot_core.figure_plan import (
    FigureOutcome,
    FigureTask,
    ResolvedFigurePlan,
    figure_plan_gate,
    merge_figure_outcomes,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
    write_delivery_launcher,
)


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
    launcher = write_delivery_launcher(delivery)
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
            "version": DELIVERY_PACKAGE_CONTRACT_VERSION,
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
