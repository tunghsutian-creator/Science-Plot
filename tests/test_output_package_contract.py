from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from sciplot_core.figure_plan import (
    FigureOutcome,
    FigureTask,
    ResolvedFigurePlan,
    merge_figure_outcomes,
)
from sciplot_core.study_model import (
    build_output_package_contract,
    verify_output_package_contract,
)


def _base_manifest(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir()
    for relative, content in {
        "request_snapshot.json": "{}\n",
        "manifest.json": "{}\n",
        "review.html": "<html></html>\n",
        "revision_brief.md": "# Review\n",
    }.items():
        (output_dir / relative).write_text(content, encoding="utf-8")
    figures = output_dir / "figures"
    figures.mkdir()
    pdf = figures / "figure_a.pdf"
    tiff = figures / "figure_a_300dpi.tiff"
    pdf.write_bytes(b"pdf")
    tiff.write_bytes(b"tiff")
    return {
        "figures": [str(pdf), str(tiff)],
        "qa": {"status": "passed"},
        "result": {},
        "semantic": {"rule_id": "legacy_custom_rule"},
        "request": {"rule_id": "legacy_custom_rule"},
    }


def _artifact_by_id(contract: dict[str, object]) -> dict[str, dict[str, object]]:
    artifacts = contract["artifacts"]
    assert isinstance(artifacts, list)
    return {
        str(item["id"]): item
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _write_contract(path: Path, *, kind: str) -> None:
    path.write_text(
        json.dumps({"kind": kind}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_output_package_contract_handles_nullable_manifest_objects(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "base"
    manifest = _base_manifest(output_dir)
    manifest.update(
        {
            "result": None,
            "raw_archive": None,
            "publication_intent": None,
            "transform_ledger": None,
            "publication_qa": None,
            "qa": None,
        }
    )

    incomplete = build_output_package_contract(output_dir, manifest=manifest)

    assert incomplete["complete"] is False
    assert [(item["id"], item["exists"]) for item in incomplete["artifacts"]] == [
        ("request_snapshot", True),
        ("manifest", True),
        ("review_html", True),
        ("revision_brief", True),
        ("pdf", True),
        ("tiff_300", True),
        ("qa", False),
    ]

    manifest["qa"] = {"status": "passed"}
    complete = build_output_package_contract(output_dir, manifest=manifest)
    verification = verify_output_package_contract(
        complete,
        output_dir=output_dir,
        manifest=manifest,
    )

    assert complete["complete"] is True
    assert verification["passed"] is True
    assert verification["recorded"] == complete
    assert verification["expected"] == complete


def test_output_package_contract_tracks_optional_and_live_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "optional"
    manifest = _base_manifest(output_dir)
    tables = output_dir / "tables"
    tables.mkdir()
    metrics = tables / "analysis_metrics.csv"
    metrics.write_text("metric,value\nx,1\n", encoding="utf-8")
    raw_archive = output_dir / "raw" / "source.csv"
    raw_archive.parent.mkdir()
    raw_archive.write_text("x,y\n1,2\n", encoding="utf-8")
    contract_kinds = {
        "publication_intent.json": "sciplot_publication_intent",
        "transform_ledger.json": "sciplot_transform_ledger",
        "journal_profile.json": "sciplot_publication_profile",
        "publication_qa.json": "sciplot_publication_qa",
    }
    for filename, kind in contract_kinds.items():
        _write_contract(output_dir / filename, kind=kind)
    manifest.update(
        {
            "result": {"analysis_metrics": [{"metric": "x", "value": 1}]},
            "raw_archive": {"path": str(raw_archive)},
            "publication_intent": {"target_status": "confirmed"},
            "transform_ledger": {"status": "runtime_recorded"},
            "publication_qa": {"status": "passed"},
        }
    )

    contract = build_output_package_contract(output_dir, manifest=manifest)
    artifact_ids = [item["id"] for item in contract["artifacts"]]

    assert contract["complete"] is True
    assert artifact_ids == [
        "request_snapshot",
        "manifest",
        "review_html",
        "revision_brief",
        "analysis_metrics",
        "raw_archive",
        "publication_intent",
        "transform_ledger",
        "journal_profile",
        "publication_qa",
        "pdf",
        "tiff_300",
        "qa",
        "transform_lineage_reviewed",
        "publication_intent_valid_contract",
        "transform_ledger_valid_contract",
        "journal_profile_valid_contract",
        "publication_qa_valid_contract",
        "publication_qa_passed",
    ]

    draft_manifest = deepcopy(manifest)
    draft_manifest["publication_intent"] = {"target_status": "draft"}
    draft_manifest["publication_qa"] = None
    draft_contract = build_output_package_contract(
        output_dir,
        manifest=draft_manifest,
    )
    assert draft_contract["complete"] is True
    assert "publication_qa_passed" not in {
        item["id"] for item in draft_contract["artifacts"]
    }

    confirmed_nullable = deepcopy(manifest)
    confirmed_nullable["transform_ledger"] = None
    confirmed_nullable["publication_qa"] = None
    nullable_contract = build_output_package_contract(
        output_dir,
        manifest=confirmed_nullable,
    )
    nullable_artifacts = _artifact_by_id(nullable_contract)
    assert nullable_contract["complete"] is False
    assert nullable_artifacts["transform_lineage_reviewed"]["exists"] is False
    assert nullable_artifacts["publication_qa_passed"]["exists"] is False

    forged = deepcopy(contract)
    forged["artifacts"][0]["path"] = str(output_dir / "forged.json")
    forged_check = verify_output_package_contract(
        forged,
        output_dir=output_dir,
        manifest=manifest,
    )
    assert forged_check["passed"] is False
    assert forged_check["checks"]["live_complete"] is True
    assert forged_check["checks"]["artifact_records_match_live"] is False
    assert forged_check["failed_checks"] == ["artifact_records_match_live"]

    metrics.unlink()
    live_check = verify_output_package_contract(
        contract,
        output_dir=output_dir,
        manifest=manifest,
    )
    assert live_check["passed"] is False
    assert live_check["checks"]["live_complete"] is False
    assert live_check["checks"]["artifact_records_match_live"] is False
    assert (
        _artifact_by_id(live_check["expected"])["analysis_metrics"]["exists"] is False
    )


def test_output_package_contract_preserves_figure_plan_gate_states(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "plans"
    manifest = _base_manifest(output_dir)
    manifest.update(
        {
            "semantic": {"rule_id": "impact_metric"},
            "request": {"rule_id": "impact_metric"},
        }
    )

    missing = build_output_package_contract(output_dir, manifest=manifest)
    missing_gate = _artifact_by_id(missing)["resolved_figure_plan_complete"]
    assert missing["complete"] is False
    assert missing_gate["exists"] is False
    assert (
        missing_gate["details"]["reason"]
        == "resolved_figure_plan_required_for_supported_rule"
    )

    invalid_manifest = deepcopy(manifest)
    invalid_manifest["resolved_figure_plan"] = {"version": 999}
    invalid = build_output_package_contract(
        output_dir,
        manifest=invalid_manifest,
    )
    invalid_gate = _artifact_by_id(invalid)["resolved_figure_plan_complete"]
    assert invalid["complete"] is False
    assert invalid_gate["exists"] is False
    assert invalid_gate["details"]["reason"].startswith("invalid_resolved_figure_plan:")

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
        rule_id="impact_metric",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    figures = [Path(path) for path in manifest["figures"]]
    vsz = output_dir / "studio" / "figure_a.vsz"
    vsz.parent.mkdir()
    vsz.write_text("# Veusz saved document\n", encoding="utf-8")
    plan = merge_figure_outcomes(
        planned,
        (
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=(str(vsz), *(str(path) for path in figures)),
            ),
        ),
    )
    plan_payload = plan.to_payload()
    manifest.update(
        {
            "resolved_figure_plan": plan_payload,
            "result": {
                "resolved_figure_plan": plan_payload,
            },
            "study_model": {
                "run": {
                    "resolved_figure_plan": plan_payload,
                }
            },
        }
    )

    complete = build_output_package_contract(output_dir, manifest=manifest)
    complete_gate = _artifact_by_id(complete)["resolved_figure_plan_complete"]
    assert complete["complete"] is True
    assert complete_gate["exists"] is True
    assert complete_gate["details"]["valid"] is True
    assert complete_gate["details"]["complete"] is True
    assert complete_gate["details"]["plan_id"] == plan.plan_id
