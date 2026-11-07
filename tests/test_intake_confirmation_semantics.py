"""Confirmation facts survive materialization and reach the science consumer."""

from copy import deepcopy
import hashlib
import json

import anyio
import pandas as pd
import pytest

from sciplot_core.intake import application, session_adapter as adapter
from sciplot_core.intake.catalog import intake_catalog_payload
from sciplot_core.intake.models import IncomingFile, IntakeGroupInput
from sciplot_core.intake.project.source_materialization import materialize_intake_groups
from sciplot_core.intake.session import _selected_column_confirmations
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.confirmation_contract import (
    bind_materialized_confirmations, confirmation_capabilities, request_column_confirmations,
)
from sciplot_core.semantic_sources.rheology_sweep_domain import resolve_rheology_frequency_domain
from sciplot_core.semantic_sources.scientific_source_single_curve import resolve_single_curve_transform
from sciplot_core.semantic_sources.rheology_sweep_sources import _read_rheology_temperature_comparison_samples
from sciplot_core.semantic_sources.rheology_sweep_domain import resolve_rheology_temperature_domain

from test_intake_session_adapter import _save, _write, _confirmation


def _columns():
    return [{"index": 0, "name": "Angular Frequency", "confirmed_type": "numeric", "role": "x"},
            {"index": 1, "name": "Storage Modulus", "confirmed_type": "ignore", "role": "ignore"},
            {"index": 2, "name": "Storage Modulus chosen", "confirmed_type": "numeric", "role": "y"}]


def _sources(tmp_path, *, reverse=False):
    groups, confirmations, original = [], [], {}
    for sample, values in [("A", (900, 700)), ("B", (1900, 1700))]:
        path = tmp_path / sample / "run.csv"
        path.parent.mkdir()
        content = ("Angular Frequency,Storage Modulus,Storage Modulus chosen\nrad/s,Pa,Pa\n"
                   f"1,100,{values[0]}\n10,80,{values[1]}\n").encode()
        path.write_bytes(content)
        original[path] = content
        groups.append(IntakeGroupInput(sample, (IncomingFile(path.name, content, str(path)),)))
        confirmations.append({"sample": sample, "file_name": path.name, "source_path": str(path),
                              "source_sha256": hashlib.sha256(content).hexdigest(), "columns": _columns()})
    if reverse:
        groups.reverse()
    root, _, manifest = materialize_intake_groups(project_dir=tmp_path / "project", groups=groups)
    return root, manifest, confirmations, original


@pytest.mark.parametrize("reverse_groups", [False, True])
@pytest.mark.parametrize("reverse_confirmations", [False, True])
def test_same_named_originals_bind_exactly_and_explicit_columns_override_auto(
    tmp_path, reverse_groups, reverse_confirmations,
):
    source, manifest, choices, original = _sources(tmp_path, reverse=reverse_groups)
    auto = resolve_rheology_frequency_domain(source, request={})
    assert all(sample.rows[0]["storage_modulus"] == 100 for sample in auto.raw_samples)
    if reverse_confirmations:
        choices.reverse()
    bound = bind_materialized_confirmations(choices, manifest)
    domain = resolve_rheology_frequency_domain(source, request={"column_confirmations": bound})
    assert {sample.source.name: [row["storage_modulus"] for row in sample.rows]
            for sample in domain.raw_samples} == {"A__run.csv": [900, 700], "B__run.csv": [1900, 1700]}
    assert {sample.source for sample in domain.raw_samples} == set(domain.selected_sources)
    assert all(path.read_bytes() == content for path, content in original.items())
    assert {item["source_path"] for item in bound} == {
        item["source_path"] for group in manifest for item in group["files"]}


@pytest.mark.parametrize("failure", ["partial", "duplicate", "wrong_path", "wrong_version", "basename_only"])
def test_confirmations_never_guess_or_silently_drop_another_source(tmp_path, failure):
    source, manifest, choices, _ = _sources(tmp_path)
    bound = bind_materialized_confirmations(choices, manifest)
    if failure == "partial":
        bound.pop()
    elif failure == "duplicate":
        bound.append(deepcopy(bound[0]))
    elif failure == "wrong_path":
        bound[0]["source_path"] += ".other"
    elif failure == "wrong_version":
        bound[0]["source_sha256"] = "0" * 64
    else:
        for item in bound:
            item.pop("source_path")
    with pytest.raises(ValueError):
        resolve_rheology_frequency_domain(source, request={"column_confirmations": bound})


def test_old_recorded_sample_map_rebinds_history_without_basename_inference(tmp_path):
    source, manifest, choices, _ = _sources(tmp_path)
    old_model = {"samples": [{"name": group["sample"], "replicates": [{"source_file": item} for item in group["files"]]}
                              for group in manifest]}
    for group in manifest:
        for item in group["files"]:
            item.pop("original_source_path")  # The previous stored format never had it.
    for choice in choices:
        choice.pop("source_path")  # Only already recorded sample/name/version may fill an absent locator.
    request = {"study_model": old_model, "column_confirmations": choices}
    bound = request_column_confirmations(request)
    result = resolve_rheology_frequency_domain(source, request={**request, "column_confirmations": bound})
    assert {sample.source.name: sample.rows[0]["storage_modulus"] for sample in result.raw_samples} == {
        "A__run.csv": 900, "B__run.csv": 1900}
    assert request["column_confirmations"] == choices  # Read-side interpretation never rewrites saved history.


def test_unknown_historical_locator_is_not_replaced_by_a_recorded_basename(tmp_path):
    _, manifest, choices, _ = _sources(tmp_path)
    for group in manifest:
        for item in group["files"]:
            item.pop("original_source_path")
    with pytest.raises(ValueError, match="reconfirm"):
        bind_materialized_confirmations(choices, manifest)


def test_real_session_creation_binds_materialized_files_before_scientific_preparation(tmp_path, monkeypatch):
    _, _, choices, original = _sources(tmp_path)
    catalog = intake_catalog_payload()
    data_type, experiment = next((data_type, experiment) for data_type in catalog["data_types"]
        for experiment in data_type["experiments"] if experiment.get("rule_id") == "rheology_frequency_sweep")
    payload = {"project_name": "Bound sources", "output_root": str(tmp_path / "new-projects"),
               "data_type_id": data_type["id"], "experiment_type_id": experiment["id"],
               "replicate_mode": "individual", "column_confirmations": choices,
               "groups": [{"sample": choice["sample"], "files": [{
                   "name": choice["file_name"], "source_path": choice["source_path"],
                   "sha256": choice["source_sha256"], "size_bytes": len(original[next(path for path in original if str(path) == choice["source_path"])])}]}
                   for choice in choices]}
    seen = []

    def inspect(project_dir, **_kwargs):
        request = json.loads((project_dir / "plot_request.json").read_text())
        domain = resolve_rheology_frequency_domain(project_dir / "source", request=request)
        seen.append({sample.source.name: sample.rows[0]["storage_modulus"] for sample in domain.raw_samples})
        for item in request["column_confirmations"]:
            assert item["source_path"] == str(project_dir / "source" / f"{item['sample']}__run.csv")
            assert item["source_sha256"] == next(choice["source_sha256"] for choice in choices if choice["sample"] == item["sample"])
        raise RuntimeError("Controlled stop after real science, before any renderer")

    monkeypatch.setattr(application, "prepare_studio_document", inspect)
    created = application.create_intake_project_from_session(payload)
    assert seen == [{"A__run.csv": 900, "B__run.csv": 1900}]
    assert created["studio"]["status"] == "blocked"
    assert "Controlled stop after real science" in created["studio"]["error"]
    assert all(path.read_bytes() == content for path, content in original.items())


def test_normalization_preserves_csv_version_and_rejects_unknown_semantics():
    value = [{"file_name": "run.csv", "source_sha256": "a" * 64, "columns": _columns()}]
    assert _selected_column_confirmations(value)[0]["source_sha256"] == "a" * 64
    for field in ("confirmed_type", "role"):
        invalid = deepcopy(value)
        invalid[0]["columns"][0][field] = "invented"
        with pytest.raises(ValueError, match="Unknown"):
            _selected_column_confirmations(invalid)


@pytest.mark.parametrize("case", ["empty_column", "decimal_comma"])
def test_explicit_columns_preserve_original_indices_and_selected_numeric_locale(tmp_path, case):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "plain.tsv"
    if case == "empty_column":
        path.write_text("Angular Frequency\t\tStorage Modulus\tStorage Modulus other\nrad/s\t\tPa\tPa\n1\t\t100\t900\n10\t\t80\t700\n")
        y_index, expected = 2, [(1, 100), (10, 80)]
    else:
        path.write_text("Angular Frequency\tStorage Modulus\nrad/s\tPa\n1,5\t100,5\n2,5\t99,5\n")
        y_index, expected = 1, [(1.5, 100.5), (2.5, 99.5)]
    choice = {"source_path": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "columns": [{"index": 0, "name": "Angular Frequency", "role": "x"},
                          {"index": y_index, "name": "Storage Modulus", "role": "y"}]}
    domain = resolve_rheology_frequency_domain(source, request={"column_confirmations": [choice]})
    assert [(row["x"], row["storage_modulus"]) for row in domain.raw_samples[0].rows] == expected
    if case == "decimal_comma":
        automatic = resolve_rheology_frequency_domain(source, request={})
        assert automatic.raw_samples[0].rows == domain.raw_samples[0].rows


@pytest.mark.parametrize("scope", ["instrument_tests", "plain_intervals"])
def test_explicit_columns_do_not_merge_original_tests_or_intervals(tmp_path, scope):
    from test_semantic_multitest_contract import _instrument_block

    source = tmp_path / "source"
    source.mkdir()
    path = source / "temperature.csv"
    if scope == "instrument_tests":
        path.write_text(_instrument_block("E0", temperature=True) + "\n\n" + _instrument_block("E2", temperature=True))
        indices = (2, 3)
        automatic = _read_rheology_temperature_comparison_samples(source)
        assert [sample.sample for sample in automatic] == ["E0", "E2"]
        rejection = "scope"
    else:
        path.write_text("Temperature,Storage Modulus\n°C,Pa\n10,100\n20,80\nTemperature,Storage Modulus\n°C,Pa\n30,900\n40,700\n")
        indices = (0, 1)
        automatic = _read_rheology_temperature_comparison_samples(source)
        assert [row["storage_modulus"] for row in automatic[0].rows] == [900, 700]
        rejection = "disconnected"
    before = path.read_bytes()
    choice = {"source_path": str(path), "source_sha256": hashlib.sha256(before).hexdigest(),
              "columns": [{"index": indices[0], "name": "Temperature", "role": "x"},
                          {"index": indices[1], "name": "Storage Modulus", "role": "y"}]}
    with pytest.raises(ValueError, match=rejection):
        resolve_rheology_temperature_domain(source, request={"column_confirmations": [choice]})
    assert path.read_bytes() == before


def test_disconnected_explicit_scope_rejects_before_project_factory(tmp_path, monkeypatch):
    source = tmp_path / "frequency.csv"
    block = "Angular Frequency,Storage Modulus,Storage Modulus chosen\nrad/s,Pa,Pa\n1,100,900\n10,80,700\n"
    source.write_text(block + block)
    path, _, value = _save(tmp_path, source=source)
    data_type, experiment = next((data_type, experiment) for data_type in intake_catalog_payload()["data_types"]
        for experiment in data_type["experiments"] if experiment.get("rule_id") == "rheology_frequency_sweep")
    value["request"].update(data_type_id=data_type["id"], experiment_type_id=experiment["id"])
    _write(path, value)
    confirmation = _confirmation(path, source, value)
    for column, intended in zip(confirmation["columns"], _columns(), strict=True):
        column.update(role=intended["role"], confirmed_type=intended["confirmed_type"])
    value["request"]["column_confirmations"] = [confirmation]
    _write(path, value)

    def forbidden(**_kwargs):
        raise AssertionError("Unsupported scientific scope allocated a project")

    monkeypatch.setattr(application, "create_intake_project", forbidden)
    with pytest.raises(ValueError, match="disconnected"):
        adapter.create_session(path)
    assert not (tmp_path / "projects").exists() and source.read_text() == block + block


@pytest.mark.parametrize("case", ["missing_unit", "conflicting_unit", "unknown_y", "component_modulus", "component_viscosity"])
def test_explicit_frequency_selection_keeps_unit_and_quantity_refusals(tmp_path, case):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "table.csv"
    if case == "missing_unit":
        text = "Point No,Storage Modulus\n,Pa\n1,100\n2,80\n"
        x_name, expected = "Point No", "Missing explicit source unit"
    elif case == "conflicting_unit":
        text = "Angular Frequency (Hz),Storage Modulus\nrad/s,Pa\n1,100\n2,80\n"
        x_name, expected = "Angular Frequency (Hz)", "Conflicting explicit unit"
    else:
        other = {"unknown_y": "Other Signal", "component_modulus": "Real Complex Modulus",
                 "component_viscosity": "Imaginary Complex Viscosity"}[case]
        text = f"Angular Frequency,Storage Modulus,{other}\nrad/s,Pa,Pa\n1,100,900\n2,80,700\n"
        x_name, expected = "Angular Frequency", "Unsupported explicit Y"
    path.write_text(text)
    columns = [{"index": 0, "name": x_name, "role": "x"},
               {"index": 1, "name": "Storage Modulus", "role": "y"}]
    if case in {"unknown_y", "component_modulus", "component_viscosity"}:
        columns.append({"index": 2, "name": other, "role": "y"})
    with pytest.raises(ValueError, match=expected):
        resolve_rheology_frequency_domain(source, request={"column_confirmations": [{
            "source_path": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "columns": columns}]})
    assert path.read_text() == text


@pytest.mark.parametrize("units", ["header_only", "adjacent_with_spacer", "alias_with_spacer"])
def test_explicit_frequency_reuses_actual_header_and_unit_evidence_owner(tmp_path, units):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "table.csv"
    header = ("Angular Frequency (rad/s),Storage Modulus (Pa)\n" if units == "header_only"
              else "Angular Frequency,Storage Modulus\nrad/s,Pa\n,\n")
    if units == "alias_with_spacer":
        header = header.replace("Angular Frequency", "Frequency")
    path.write_text(header + "1.5,100.5\n2.5,99.5\n")
    automatic = resolve_rheology_frequency_domain(source, request={})
    result = resolve_rheology_frequency_domain(source, request={"column_confirmations": [{
        "source_path": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "columns": [{"index": 0, "name": "Angular Frequency", "role": "x"},
                    {"index": 1, "name": "Storage Modulus", "role": "y"}]}]})
    assert result.raw_samples[0].rows == automatic.raw_samples[0].rows
    assert result.raw_samples[0].x_unit == "rad s⁻¹"
    assert result.raw_samples[0].metric_units == automatic.raw_samples[0].metric_units
    assert result.raw_samples[0].x_conversion["source_unit_authority"] == (
        "header" if units == "header_only" else "adjacent_unit_row")


def test_confirmed_modulus_symbols_keep_prime_identity(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "symbols.csv"
    path.write_text("Angular Frequency,G′,G″\nrad/s,Pa,Pa\n1,100,20\n10,80,16\n")
    result = resolve_rheology_frequency_domain(source, request={"column_confirmations": [{
        "source_path": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "columns": [{"index": 0, "name": "Angular Frequency", "role": "x"},
                    {"index": 1, "name": "G′", "role": "y"},
                    {"index": 2, "name": "G″", "role": "y"}]}]})
    assert [(row["storage_modulus"], row["loss_modulus"]) for row in result.raw_samples[0].rows] == [(100, 20), (80, 16)]


@pytest.mark.parametrize("intent", ["role", "type", "worksheet"])
def test_unsupported_scientific_choices_reject_before_any_allocation(tmp_path, monkeypatch, intent):
    path, original, value = _save(tmp_path)
    if intent == "worksheet":
        original = tmp_path / "original.xlsx"
        pd.DataFrame({"Time": [0, 1], "Swelling": [1, 2]}).to_excel(original, index=False)
        _, _, value = _save(tmp_path, source=original)
        for data_type in intake_catalog_payload()["data_types"]:
            for experiment in data_type["experiments"]:
                if experiment.get("rule_id") == "swelling_curve":
                    value["request"].update(data_type_id=data_type["id"], experiment_type_id=experiment["id"])
        _write(path, value)
    confirmation = _confirmation(path, original, value)
    if intent == "role":
        confirmation["columns"][0]["role"] = "ignore"
    elif intent == "type":
        confirmation["columns"][0]["confirmed_type"] = "ignore"
    value["request"]["column_confirmations"] = [confirmation]
    _write(path, value)
    before = original.read_bytes()

    def forbidden(**_kwargs):
        raise AssertionError("Unsupported intent allocated a project")

    monkeypatch.setattr(application, "create_intake_project", forbidden)
    with pytest.raises(ValueError, match="not supported"):
        adapter.create_session(path)
    assert not (tmp_path / "projects").exists() and original.read_bytes() == before


def test_registered_paired_curve_rejects_nonauto_intent_at_actual_science_owner(tmp_path):
    source = tmp_path / "dsc.csv"
    source.write_text("Temperature (°C),Heat Flow (W/g)\n10,1\n20,2\n")
    with pytest.raises(ValueError, match="not supported"):
        resolve_single_curve_transform(source, rule=get_rule("dsc_curve"), column_confirmations=[{
            "columns": [{"index": 1, "name": "Heat Flow (W/g)", "confirmed_type": "ignore", "role": "ignore"}]}])


def test_advertised_capabilities_follow_the_actual_science_adapter():
    assert confirmation_capabilities(get_rule("dsc_curve"))["worksheet"] is True
    assert confirmation_capabilities(get_rule("dsc_curve"))["column_roles"] == ["auto"]
    frequency = confirmation_capabilities(get_rule("rheology_frequency_sweep"))
    assert frequency["worksheet"] is False and frequency["column_roles"] == ["auto", "ignore", "x", "y"]


def test_legacy_boolean_version_is_not_upgraded_into_integer_version(tmp_path, monkeypatch):
    path, _, value = _save(tmp_path)
    _write(path, {**value["request"], "kind": "sciplot_intake_session", "version": True})
    with pytest.raises(ValueError):
        adapter.create_session(path)
    assert not (tmp_path / "projects").exists()


def test_mcp_and_cli_preserve_failed_publication_effects_and_report_failure(tmp_path, monkeypatch, capsys):
    from sciplot_core import cli
    from sciplot_core.mcp_server.server import Adapter

    path, _, _ = _save(tmp_path)
    monkeypatch.setattr(application, "create_intake_project", lambda **_kwargs: {"project_dir": "created"})
    failed = {"kind": "sciplot_intake_project", "project_dir": "created", "run_failed": True,
              "last_run": {"ready_to_use": False, "failure": "actual publication refused"}}
    monkeypatch.setattr(adapter, "publish_prepared_intake_project", lambda _prepared: deepcopy(failed))
    assert cli.main(["intake", "create", str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"

    async def scenario():
        result = await Adapter().call("sciplot_intake_create", {"session": str(path)})
        assert result.is_error is True
        assert result.structured_content["project_dir"] == "created"
        assert result.structured_content["last_run"] == failed["last_run"]
        assert result.structured_content["run_failed"] is True

    anyio.run(scenario)
