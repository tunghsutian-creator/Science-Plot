from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.data_mapping import (
    create_data_mapping_confirmation,
    execute_data_mapping_proposal,
)
from sciplot_core.data_mapping.plan_binding import resolve_mapping_plan_request
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.plan_preview import build_plan_preview, verify_expected_plan
from sciplot_core.studio_core import project_creation
from sciplot_core.studio_core.project_query_evidence import source_indicators


def _mapped_case(tmp_path: Path, *, real: bool = False):
    source = tmp_path / "source.csv"
    if real:
        original = resolve_fixture_path("tests/fixtures/real_world/uvvis_spectrum") / "pda_uvvis_spectra.csv"
        source.write_bytes(original.read_bytes())
        headers = ("PDA-I", "PDA-I")
        header_row = 2
        sample = "PDA-I"
    else:
        source.write_text("Wavelength (nm),Absorbance (a.u.),Transmittance (%)\n400,0.3,50\n450,0.7,20\n500,0.4,40\n")
        headers = ("Wavelength (nm)", "Absorbance (a.u.)")
        header_row = 0
        sample = "source"
    base = tmp_path / "base.json"
    base.write_text(json.dumps({
        "input": str(source), "rule_id": "uvvis_spectrum", "template": "curve",
        "exports": ["pdf", "tiff_300"],
    }))
    proposal = DataMappingProposal(
        proposal_id="chosen_columns", base_request_sha256=file_sha256(base),
        provider="external_task", sources=(DataSourceReference(
            "sample", source.name, file_sha256(source), header_row=header_row,
        ),),
        columns=(
            DataColumnMapping("sample", 0, "Wavelength (nm)", "x", expected_header=headers[0]),
            DataColumnMapping("sample", 1, "Absorbance (a.u.)", "y", expected_header=headers[1]),
        ),
        sample_labels={"sample": sample},
        request_patch={"rule_id": "uvvis_spectrum", "template": "curve"},
    )
    confirmation = create_data_mapping_confirmation(
        proposal, source_root=tmp_path, request_path=base,
        output_root=tmp_path / "mappings", confirmed_by="test",
    )
    execution = execute_data_mapping_proposal(
        proposal, confirmation, source_root=tmp_path, request_path=base,
        output_root=tmp_path / "mappings",
    )
    selection = {
        "rule_id": "uvvis_spectrum", "template": "curve",
        "data_mapping_execution": str(Path(execution["output_root"]) / "execution.json"),
        "data_mapping_proposal_id": proposal.proposal_id,
    }
    return source, selection, execution


def test_mapping_plan_binds_original_and_effective_source_with_selected_values(tmp_path):
    source, selection, execution = _mapped_case(tmp_path)
    plan = build_plan_preview(source, request=selection)
    assert plan["status"] == "planned", plan["blocker"]
    assert plan["source"] == str(source)
    assert plan["preview_identity"]["source_tree_sha256"] == source_tree_sha256(source)
    assert plan["resolved_figure_plan"]["source_sha256"] == source_tree_sha256(Path(execution["effective_input"]))
    series = plan["scientific_transform"]["output"]["series"]
    assert series[0]["first_point"] == [400, 0.3]
    assert series[0]["point_count"] == 3
    assert verify_expected_plan(source, plan, rule_id="uvvis_spectrum", template="curve") == plan


@pytest.mark.parametrize("mutation", ["source", "effective", "proposal", "selection"])
def test_mapping_plan_rejects_changed_evidence_before_creation(tmp_path, mutation):
    source, selection, execution = _mapped_case(tmp_path)
    plan = build_plan_preview(source, request=selection)
    if mutation == "source":
        source.write_text(source.read_text().replace("0.7", "0.9"))
    elif mutation == "effective":
        mapped = Path(execution["effective_input"])
        mapped.write_text(mapped.read_text().replace("0.7", "0.9"))
    elif mutation == "proposal":
        proposal = Path(execution["proposal"])
        data = json.loads(proposal.read_text())
        data["columns"][1]["source_column_index"] = 2
        proposal.write_text(json.dumps(data))
    else:
        plan = deepcopy(plan)
        plan["data_mapping"]["data_mapping_proposal_id"] = "unreviewed"
    with pytest.raises(ValueError):
        verify_expected_plan(source, plan, rule_id="uvvis_spectrum", template="curve")


def test_mapping_does_not_allow_rule_override_or_a_foreign_task_source(tmp_path):
    source, selection, _execution = _mapped_case(tmp_path)
    overridden = build_plan_preview(source, request={**selection, "rule_id": "xrd_pattern"})
    assert overridden["status"] == "blocked"
    assert overridden["blocker"]["reason_code"] == "plan_mapping_invalid"
    foreign = tmp_path / "foreign.csv"
    foreign.write_bytes(source.read_bytes())
    rejected = build_plan_preview(foreign, request=selection)
    assert rejected["status"] == "blocked"
    assert "original task source" in rejected["blocker"]["message"]


def test_mapped_creation_enters_existing_canonical_request_studio_route(tmp_path, monkeypatch):
    source, selection, _execution = _mapped_case(tmp_path)
    plan = build_plan_preview(source, request=selection)
    calls = []

    def prepare(target):
        request = json.loads(target.read_text())
        calls.append(request)
        return {"project_dir": str(target.parent), "request": str(target),
                "document": str(target.parent / "studio/document.vsz")}

    monkeypatch.setattr(project_creation, "prepare_studio_document", prepare)
    monkeypatch.setattr(project_creation, "_publish", lambda payload: payload)
    result = project_creation.create_project(source, expected_plan=plan)
    assert len(calls) == 1
    assert Path(result["request"]).name == "plot_request.json"
    assert calls[0]["input"] == str(source)
    assert calls[0]["data_mapping_execution"] == selection["data_mapping_execution"]
    assert calls[0]["data_mapping_plan_binding"] == plan["data_mapping"]
    assert calls[0]["resolved_figure_plan"] == plan["resolved_figure_plan"]


def test_mapping_source_indicator_checks_original_and_effective_bytes(tmp_path):
    source, selection, execution = _mapped_case(tmp_path)
    request, binding = resolve_mapping_plan_request(source, selection)
    request["resolved_figure_plan"] = build_plan_preview(source, request=selection)["resolved_figure_plan"]
    request["data_mapping_plan_binding"] = binding
    effective = Path(execution["effective_input"])
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(effective), "sha256": file_sha256(effective)}
    ]}]}))
    figures = [{"status": "ready", "spec": str(spec)}]
    current = source_indicators(tmp_path, request, figures)
    assert current["current"] is True
    assert current["input"]["effective_input"] == str(effective)
    source.write_text(source.read_text().replace("0.7", "0.9"))
    stale = source_indicators(tmp_path, request, figures)
    assert stale["current"] is False
    assert stale["input"]["mapping_verified"] is False


def test_real_pda_mapping_preserves_selected_sample_measurements(tmp_path):
    source, selection, _execution = _mapped_case(tmp_path, real=True)
    plan = build_plan_preview(source, request=selection)
    assert plan["status"] == "planned", plan["blocker"]
    output = plan["scientific_transform"]["output"]
    assert output["series_order"] == ["PDA-I"]
    assert output["series"][0]["point_count"] == 501
    assert output["series"][0]["first_point"] == [800, 0.677513659]


@pytest.mark.comprehensive
def test_mapped_native_creation_retains_original_archive_and_passes_source_audit(tmp_path):
    from sciplot_core.studio_core.project_query import inspect_project

    source, selection, execution = _mapped_case(tmp_path, real=True)
    plan = build_plan_preview(source, request=selection)
    result = project_creation.create_project(source, expected_plan=plan)
    assert result["studio_run"]["ready_to_use"] is True
    project = Path(result["project_dir"])
    state = inspect_project(project)
    assert state["source"]["current"] is True
    manifests = sorted((project / "runs").glob("studio_*/manifest.json"))
    manifest = json.loads(manifests[-1].read_text())
    assert manifest["data_mapping_application"]["proposal_id"] == "chosen_columns"
    archive = manifest["raw_archive"]["original_input"]
    assert Path(archive["path"]).read_bytes() == source.read_bytes()
    assert Path(execution["effective_input"]).read_bytes() != source.read_bytes()
