"""Literal paired-source controls across attested preparation and terminal replay."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from sciplot_core.data_mapping import create_data_mapping_confirmation, execute_data_mapping_proposal
from sciplot_core.data_mapping.table_choice import proposal_for_table_columns, select_table, table_choice_snapshot, verify_table_confirmation
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.figure_plan.execution import request_for_figure_task
from sciplot_core.mapping_contract import DataMappingProposal
from sciplot_core.mapping_contract.categorical_identity import validate_categorical_correspondence
from sciplot_core.plan_preview import build_plan_preview, verify_expected_plan
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_core.source_update_review import scientific_summary
from sciplot_core.studio_core.figure_task_evidence import validate_veusz_spec_figure_task
from sciplot_core.veusz_worker.style_transfer import _series_identity
from test_categorical_source_identity import snapshots, written


def paired(tmp_path, *, aliases=("display/a || wet", "display (z)/B"), legacy=False, name="pairs",
           samples=("A", "B")):
    source = tmp_path / "original.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
        f"{samples[0]},{samples[0]},{samples[1]},{samples[1]}\n400,1,405,3\n450,4,455,5\n500,2,,\n")
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2,
                 "data_start_row": 3, "data_end_row": 6}
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"input": str(source), "rule_id": "uvvis_spectrum", "template": "curve",
        "study_model": {"kind": "sciplot_study_model", "version": 2, "samples": [], "figure_queue": []},
        "render_options": {"series_styles": [{"label": aliases[0], "color": "#123456"}]}}))
    choices = [{"x_column": 0, "y_column": 1, "label": aliases[0]},
               {"x_column": 2, "y_column": 3, "label": aliases[1],
                "table_selection": {**selection, "data_end_row": 5}}]
    proposal = proposal_for_table_columns(select_table(table_choice_snapshot(source, "uvvis_spectrum"), selection),
        request_path=seed, proposal_id=name, created_at="2026-10-21T00:00:00Z", pairs=choices,
        structured_identity=not legacy)
    receipt = create_data_mapping_confirmation(proposal, source_root=tmp_path, request_path=seed,
        output_root=tmp_path / ("mapping_" + name), confirmed_by="literal-test")
    execution = execute_data_mapping_proposal(proposal, receipt, source_root=tmp_path,
        request_path=seed, output_root=tmp_path / ("mapping_" + name))
    return source, proposal, execution, json.loads(Path(execution["request_seed"]).read_text())


def test_aliases_enter_only_after_original_sample_science_and_survive_replay(tmp_path, monkeypatch):
    source, proposal, execution, request = paired(tmp_path)
    original = source.read_bytes()
    assert list(proposal.sample_labels.values()) == ["A", "B"]
    assert list(proposal.display_labels.values()) == ["display/a || wet", "display (z)/B"]
    ids = [item.source_id for item in proposal.sources]
    assert request["series_order"] == ids
    assert [Path(item["path"]).stem for item in execution["outputs"]] == [item.source_id for item in proposal.sources]
    plan = build_plan_preview(source, request=request)
    assert plan["status"] == "planned", plan.get("blocker")
    assert plan["scientific_transform"]["output"]["series_order"] == ids
    assert verify_expected_plan(source, plan, rule_id="uvvis_spectrum", template="curve") == plan
    series, info, steps, _ = _series_from_request(request, base_dir=tmp_path)
    assert [item.label for item in series] == list(proposal.display_labels.values())
    assert info["semantic_terminal_series_order"] == [item.source_id for item in proposal.sources]
    assert [list(item.x_values) for item in series] == [[400., 450., 500.], [405., 455.]]
    assert [list(item.y_values) for item in series] == [[1., 4., 2.], [3., 5.]]
    assert len(steps) > 1  # The semantic preparation still runs after the mapping.
    assert series[0].color == "#123456"
    spec = written(request, tmp_path, monkeypatch, "paired_spec")
    assert "source_category_ids" not in spec and spec["categorical"] is None
    assert [item["source_binding"]["sample"] for item in spec["series"]] == ["A", "B"]
    validate_categorical_correspondence(spec)
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"
    assert written(json.loads(json.dumps(request)), tmp_path, monkeypatch, "paired_reopen")["series"] == spec["series"]
    edited = deepcopy(spec)
    for item in edited["series"]:
        item["label"] = item["legend_key"] = "different/alias || literal"
    assert scientific_summary(edited) == scientific_summary(spec)
    assert [_series_identity(item) for item in edited["series"]] == [_series_identity(item) for item in spec["series"]]
    assert source.read_bytes() == original
    Path(execution["outputs"][0]["path"]).write_text("Wavelength (nm),Absorbance (a.u.)\n400,999\n")
    with pytest.raises(ValueError):
        _series_from_request(request, base_dir=tmp_path)


def test_new_alias_confirmation_keeps_group_style_and_scientific_identity(tmp_path, monkeypatch):
    _, _, _, one = paired(tmp_path, aliases=("left/name || a", "right/name"), name="first")
    before = written(one, tmp_path, monkeypatch, "first_spec")
    _, _, _, two = paired(tmp_path, aliases=("right/name", "left/name || a"), name="swapped")
    after = written(two, tmp_path, monkeypatch, "swapped_spec")
    assert [item["label"] for item in after["series"]] == [item["label"] for item in before["series"]][::-1]
    assert [item["name"] for item in before["series"]] == [item["name"] for item in after["series"]]
    assert [item["color"] for item in before["series"]] == [item["color"] for item in after["series"]]
    assert scientific_summary(before) == scientific_summary(after)
    assert _verify_prepared_data(after, snapshots(after))["status"] == "passed"


def test_real_figure_task_projection_keeps_science_order_and_id_only_terminal_encoding(tmp_path, monkeypatch):
    source, proposal, _, request = paired(tmp_path)
    preview = build_plan_preview(source, request=request)
    plan = resolved_figure_plan_from_payload(preview["resolved_figure_plan"])
    assert plan is not None
    task = next(task for task in plan.tasks if task.figure_id == plan.primary_figure_id)
    assert list(task.sample_order) == [item.source_id for item in proposal.sources]
    request["resolved_figure_plan"] = preview["resolved_figure_plan"]
    projected = request_for_figure_task(request, task)
    series, info, _, _ = _series_from_request(projected, base_dir=tmp_path)
    assert info["semantic_terminal_series_order"] == [item.source_id for item in proposal.sources]
    assert [item.label for item in series] == list(proposal.display_labels.values())
    spec = written(projected, tmp_path, monkeypatch, "task_projected")
    validate_veusz_spec_figure_task(spec, expected=task, source="literal canonical task")
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"


def test_literal_original_samples_are_retained_without_filename_or_factor_reinterpretation(tmp_path, monkeypatch):
    samples = ("A || original", "B/original")
    _, proposal, _, request = paired(tmp_path, samples=samples)
    assert list(proposal.sample_labels.values()) == list(samples)
    series, info, _, _ = _series_from_request(request, base_dir=tmp_path)
    assert info["semantic_terminal_series_order"] == [item.source_id for item in proposal.sources]
    assert [info["source_bindings"][item.x_name]["sample"] for item in series] == list(samples)
    spec = written(request, tmp_path, monkeypatch, "literal_original")
    assert spec["legend"].get("presentation_kind") != "factorized_curve"
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"


@pytest.mark.parametrize("family", ["ftir_spectrum", "rheology_stress_relaxation"])
@pytest.mark.parametrize("same_sample", [False, True])
def test_existing_specialized_science_preparation_retains_original_samples_before_aliases(tmp_path, monkeypatch, family, same_sample):
    from test_task_initial_mapping import ftir_workbook_mapping

    if family == "ftir_spectrum":
        source, mapping = ftir_workbook_mapping(tmp_path)
        selection = mapping["table_selection"]
        choices = mapping["column_mapping"]["pairs"]
        confirmations = mapping["metadata_confirmations"]
        expected_samples = ["original 1", "original 2 after"]
        if same_sample:
            from openpyxl import load_workbook

            book = load_workbook(source)
            book["Spectra"]["B2"] = book["Spectra"]["D2"] = "A"
            book.save(source)
            for confirmation in confirmations:
                confirmation["source_sha256"] = file_sha256(source)
                if confirmation["field"] == "sample":
                    confirmation["value"] = confirmation["evidence"]["text"] = "A"
            expected_samples = ["A", "A"]
    else:
        source = tmp_path / "relaxation.csv"
        source.write_text("A|t_s,A|sigma_over_sigma0,B|t_s,B|sigma_over_sigma0\n0,1,0,1\n1,.8,1,.7\n2,.5,2,.4\n3,.3,,\n")
        selection = {"sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 5}
        choices = [{"x_column": 0, "y_column": 1}, {"x_column": 2, "y_column": 3,
                   "table_selection": {**selection, "data_end_row": 4}}]
        confirmations = []
        expected_samples = ["A", "B"]
        if same_sample:
            source.write_text(source.read_text().replace("B|", "A|"))
            expected_samples = ["A", "A"]
    aliases = ["display/a || b", "display/c (sheet)"]
    choices = [{**choice, "label": alias} for choice, alias in zip(choices, aliases, strict=True)]
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"input": str(source), "rule_id": family, "template": "curve"}))
    proposal = proposal_for_table_columns(select_table(table_choice_snapshot(source, family), selection, confirmations),
        request_path=seed, proposal_id="specialized", created_at="2026-10-21T00:00:00Z", pairs=choices)
    receipt = create_data_mapping_confirmation(proposal, source_root=tmp_path, request_path=seed,
        output_root=tmp_path / "mapping", confirmed_by="literal-test")
    execution = execute_data_mapping_proposal(proposal, receipt, source_root=tmp_path,
        request_path=seed, output_root=tmp_path / "mapping")
    request = json.loads(Path(execution["request_seed"]).read_text())
    series, info, steps, _ = _series_from_request(request, base_dir=tmp_path)
    assert [item.label for item in series] == aliases
    assert info["semantic_terminal_series_order"] == [item.source_id for item in proposal.sources]
    assert len(steps) > 1
    spec = written(request, tmp_path, monkeypatch, "specialized_spec")
    assert [item["source_binding"]["sample"] for item in spec["series"]] == expected_samples
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"


def test_same_original_sample_distinct_xy_views_are_not_renamed_or_pooled(tmp_path, monkeypatch):
    _, proposal, execution, request = paired(tmp_path, samples=("A", "A"))
    ids = [item.source_id for item in proposal.sources]
    assert len(set(ids)) == 2 and list(proposal.sample_labels.values()) == ["A", "A"]
    assert [item["sample_label"] for item in execution["outputs"]] == ["A", "A"]
    assert request["study_model"]["sample_order"] == ids
    assert [item["name"] for item in request["study_model"]["samples"]] == ids
    assert [len(item["replicates"]) for item in request["study_model"]["samples"]] == [1, 1]
    spec = written(request, tmp_path, monkeypatch, "same_sample_distinct_views")
    assert [item["name"] for item in spec["series"]] == ids
    assert [item["source_binding"]["sample"] for item in spec["series"]] == ["A", "A"]
    assert [item["x_values"] for item in spec["series"]] == [[400., 450., 500.], [405., 455.]]
    assert [item["y_values"] for item in spec["series"]] == [[1., 4., 2.], [3., 5.]]
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"
    reordered = deepcopy(request)
    reordered["series_order"] = ids[::-1]
    reordered["render_options"]["series_order"] = ids[::-1]
    after = written(reordered, tmp_path, monkeypatch, "same_sample_reordered")
    assert [item["name"] for item in after["series"]] == ids[::-1]
    original_groups = {item["name"]: item for item in spec["series"]}
    for item in after["series"]:
        previous = original_groups[item["name"]]
        for key in ("source_binding", "x_values", "y_values"):
            assert item[key] == previous[key]
        if item["name"] == ids[0]:
            assert item["color"] == previous["color"] == "#123456"
    assert _verify_prepared_data(after, snapshots(after))["status"] == "passed"


def test_same_sample_nonoverlapping_regions_keep_exact_domains_initial_append_and_reopen(tmp_path, monkeypatch):
    source = tmp_path / "two_regions.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n450,4\n500,2\n550,8\n")
    original = source.read_bytes()
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2,
        "data_start_row": 3, "data_end_row": 7}
    selected = select_table(table_choice_snapshot(source, "uvvis_spectrum"), selection)
    choices = [{"x_column": 0, "y_column": 1, "label": "early/a || view",
                "table_selection": {**selection, "data_end_row": 5}},
               {"x_column": 0, "y_column": 1, "label": "late/view (A)",
                "table_selection": {**selection, "data_start_row": 5}}]
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"input": str(source), "rule_id": "uvvis_spectrum", "template": "curve"}))

    def confirmed(name, pairs):
        proposal = proposal_for_table_columns(selected, request_path=seed, proposal_id=name,
            created_at="2026-10-21T00:00:00Z", pairs=pairs)
        receipt = create_data_mapping_confirmation(proposal, source_root=tmp_path, request_path=seed,
            output_root=tmp_path / name, confirmed_by="literal-test")
        execution = execute_data_mapping_proposal(proposal, receipt, source_root=tmp_path,
            request_path=seed, output_root=tmp_path / name)
        return proposal, json.loads(Path(execution["request_seed"]).read_text())

    initial, one = confirmed("initial", choices[:1])
    expanded, all_at_once = confirmed("expanded", choices)
    before = written(one, tmp_path, monkeypatch, "first_region")
    after = written(all_at_once, tmp_path, monkeypatch, "both_regions")
    assert initial.sources[0].source_id == expanded.sources[0].source_id
    assert [item["x_values"] for item in after["series"]] == [[400., 450.], [500., 550.]]
    assert [item["y_values"] for item in after["series"]] == [[1., 4.], [2., 8.]]
    for key in ("name", "source_binding", "x_values", "y_values", "color"):
        assert after["series"][0][key] == before["series"][0][key]
    assert [item["source_binding"]["sample"] for item in after["series"]] == ["A", "A"]
    assert _verify_prepared_data(after, snapshots(after))["status"] == "passed"
    assert written(json.loads(json.dumps(all_at_once)), tmp_path, monkeypatch, "regions_cold")["series"] == after["series"]
    with pytest.raises(ValueError, match="Overlapping"):
        confirmed("overlap", [choices[0], {**choices[0], "label": "different alias"}])
    assert source.read_bytes() == original


def test_saved_absent_pair_identity_keeps_original_receipt_and_alias_sample_semantics(tmp_path):
    source, proposal, _, request = paired(tmp_path, aliases=("oldA", "oldB"), legacy=True)
    payload = proposal.to_dict()
    assert "display_labels" not in payload and all("identity" not in item for item in payload["sources"])
    assert list(proposal.sample_labels.values()) == ["oldA", "oldB"]
    assert DataMappingProposal.from_dict(payload).to_dict() == payload
    verify_table_confirmation(proposal, source)
    series, info, _, _ = _series_from_request(request, base_dir=tmp_path)
    assert [item.label for item in series] == ["oldA", "oldB"]
    assert "source_bindings" not in info
    with pytest.raises(ValueError, match="reproduce"):
        verify_table_confirmation(replace(proposal, sample_labels={"series_000": "other", "series_001": "oldB"}), source)
    assert file_sha256(source) == proposal.sources[0].sha256
