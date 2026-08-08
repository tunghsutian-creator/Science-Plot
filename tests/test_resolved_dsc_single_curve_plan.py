from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import sciplot_core.figure_plan.dsc_resolution as dsc_resolution
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigurePlanResolutionError,
    ResolvedFigurePlan,
    SUPPORTED_FIGURE_PLAN_RULE_IDS,
    resolve_figure_plan,
)
from sciplot_core.figure_plan.dsc_resolution import (
    DscSelectedInventory,
    load_dsc_single_curve_source_facts,
    resolve_dsc_single_curve_plan,
)
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import get_rule


RULE_ID = "dsc_curve"
FIGURE_ID = "dsc_heat_flow_vs_temperature"
EXPECTED_SAMPLE_ORDER = ("UDC 2", "UDC 3", "UDC 4")
EXPECTED_POINT_COUNTS = (196, 194, 193)


def _fixture() -> Path:
    source = resolve_fixture_path(str(get_rule(RULE_ID).fixture_path or ""))
    assert source.is_file()
    return source


def _copy_fixture(tmp_path: Path) -> Path:
    source = _fixture()
    copied = tmp_path / source.name
    shutil.copy2(source, copied)
    shutil.copy2(source.with_name("digitization_provenance.json"), tmp_path)
    return copied


def _rewrite_output_hash(source: Path) -> None:
    provenance_path = source.with_name("digitization_provenance.json")
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    payload["output_csv_sha256"] = file_sha256(source)
    provenance_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def test_private_dsc_plan_binds_exact_digitized_single_curve_contract() -> None:
    source = _fixture()

    facts = load_dsc_single_curve_source_facts(source)
    plan = resolve_dsc_single_curve_plan(
        input_path=source,
        request={"template": "curve"},
    )

    assert facts.sample_order == EXPECTED_SAMPLE_ORDER
    assert facts.point_counts == EXPECTED_POINT_COUNTS
    assert facts.temperature_unit == "C"
    assert facts.heat_flow_unit == "W/g"
    assert facts.source_data_status == (
        "digitized_from_authorized_publication_figure_not_instrument_raw"
    )
    assert facts.source_sha256 == plan.source_sha256
    assert facts.csv_sha256 == file_sha256(source)
    assert facts.provenance_sha256 == file_sha256(
        source.with_name("digitization_provenance.json")
    )

    assert plan.rule_id == RULE_ID
    assert plan.selection_policy == "registered_publication_digitized_single_curve"
    assert plan.primary_figure_id == FIGURE_ID
    assert plan.selected_figure_ids == (FIGURE_ID,)
    assert plan.status == "planned"
    task = plan.tasks[0]
    assert task.figure_id == FIGURE_ID
    assert task.order == 1
    assert task.template == "curve"
    assert task.artifact_stem == FIGURE_ID
    assert task.document_stem == FIGURE_ID
    assert task.sample_order == EXPECTED_SAMPLE_ORDER
    assert task.replicate_counts == tuple(
        (sample, 1) for sample in EXPECTED_SAMPLE_ORDER
    )
    assert task.metric_binding == CartesianMetricBinding(
        x_metric="temperature",
        y_metric="heat_flow",
    )
    assert task.to_payload()["version"] == 2
    assert ResolvedFigurePlan.from_payload(plan.to_payload()) == plan
    assert not any(
        token in json.dumps(plan.to_payload()).casefold()
        for token in ("cooling", "heating", "phase", "stacked_curve")
    )


def test_dsc_single_curve_source_and_provenance_are_loaded_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_calls: list[Path] = []
    provenance_calls: list[Path] = []
    real_csv_loader = dsc_resolution._read_dsc_csv
    real_provenance_loader = dsc_resolution._read_provenance

    def counted_csv_loader(source: Path):
        csv_calls.append(source)
        return real_csv_loader(source)

    def counted_provenance_loader(source: Path):
        provenance_calls.append(source)
        return real_provenance_loader(source)

    monkeypatch.setattr(dsc_resolution, "_read_dsc_csv", counted_csv_loader)
    monkeypatch.setattr(
        dsc_resolution,
        "_read_provenance",
        counted_provenance_loader,
    )

    resolve_dsc_single_curve_plan(input_path=_fixture(), request={})

    assert csv_calls == [_fixture()]
    assert provenance_calls == [_fixture().with_name("digitization_provenance.json")]


def test_dsc_single_curve_resolution_rejects_selected_inventory_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stable = dsc_resolution._selected_inventory(
        _fixture(),
        _fixture().with_name("digitization_provenance.json"),
    )
    inventories = iter((stable, replace(stable, source_sha256="b" * 64)))
    monkeypatch.setattr(
        dsc_resolution,
        "_selected_inventory",
        lambda _source, _provenance: next(inventories),
    )

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_dsc_single_curve_plan(input_path=_fixture(), request={})

    assert exc_info.value.reason_code == (
        "dsc_single_curve_source_changed_during_resolution"
    )


def test_unregistered_dsc_source_requires_adjacent_provenance(tmp_path: Path) -> None:
    source = tmp_path / "udc_dsc_digitized.csv"
    shutil.copy2(_fixture(), source)
    rows = source.read_text(encoding="utf-8").splitlines()
    rows[3] = rows[3].replace("42.101147", "42.101148")
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_dsc_single_curve_plan(input_path=source, request={})

    assert exc_info.value.reason_code == "dsc_single_curve_provenance_unavailable"


def test_dsc_single_curve_rejects_provenance_csv_hash_mismatch(
    tmp_path: Path,
) -> None:
    source = _copy_fixture(tmp_path)
    provenance_path = source.with_name("digitization_provenance.json")
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    payload["output_csv_sha256"] = "0" * 64
    provenance_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_dsc_single_curve_plan(input_path=source, request={})

    assert exc_info.value.reason_code == "dsc_single_curve_provenance_mismatch"


def test_dsc_single_curve_rejects_noncanonical_units(tmp_path: Path) -> None:
    source = _copy_fixture(tmp_path)
    rows = source.read_text(encoding="utf-8").splitlines()
    rows[1] = rows[1].replace("W/g", "mW/g")
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    _rewrite_output_hash(source)

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_dsc_single_curve_plan(input_path=source, request={})

    assert exc_info.value.reason_code == "dsc_single_curve_contract_invalid"


def test_dsc_single_curve_rejects_series_order_drift(tmp_path: Path) -> None:
    source = _copy_fixture(tmp_path)
    rows = source.read_text(encoding="utf-8").splitlines()
    rows[2] = "UDC 3,UDC 3,UDC 2,UDC 2,UDC 4,UDC 4"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    _rewrite_output_hash(source)

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_dsc_single_curve_plan(input_path=source, request={})

    assert exc_info.value.reason_code == "dsc_single_curve_contract_invalid"


def test_dsc_single_curve_rejects_raw_instrument_status(tmp_path: Path) -> None:
    source = _copy_fixture(tmp_path)
    provenance_path = source.with_name("digitization_provenance.json")
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    payload["traces"][0]["source_data_status"] = "instrument_raw"
    provenance_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_dsc_single_curve_plan(input_path=source, request={})

    assert exc_info.value.reason_code == "dsc_single_curve_provenance_mismatch"


def test_dsc_single_curve_rejects_digitized_peak_that_disagrees_with_csv(
    tmp_path: Path,
) -> None:
    source = _copy_fixture(tmp_path)
    provenance_path = source.with_name("digitization_provenance.json")
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    trace = payload["traces"][0]
    trace["digitized_peak_temperature_C"] = 179.5
    trace["peak_temperature_absolute_error_C"] = abs(
        trace["digitized_peak_temperature_C"] - trace["published_peak_temperature_C"]
    )
    provenance_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_dsc_single_curve_plan(input_path=source, request={})

    assert exc_info.value.reason_code == "dsc_single_curve_provenance_mismatch"


def test_dsc_single_curve_rejects_phase_template_and_cycle_source(
    tmp_path: Path,
) -> None:
    with pytest.raises(FigurePlanResolutionError) as template_error:
        resolve_dsc_single_curve_plan(
            input_path=_fixture(),
            request={"template": "stacked_curve"},
        )
    assert template_error.value.reason_code == "dsc_single_curve_template_invalid"

    workbook = tmp_path / "cycle.xlsx"
    workbook.write_bytes(b"not a single-curve CSV")
    with pytest.raises(FigurePlanResolutionError) as source_error:
        resolve_dsc_single_curve_plan(input_path=workbook, request={})
    assert source_error.value.reason_code == "dsc_single_curve_phase_source_unsupported"


def test_dsc_single_curve_is_registered_in_the_global_source_bound_resolver() -> None:
    assert RULE_ID in SUPPORTED_FIGURE_PLAN_RULE_IDS
    plan = resolve_figure_plan(
        rule_id=RULE_ID,
        template="curve",
        study_model={},
        input_path=_fixture(),
        request={"template": "curve"},
    )

    assert plan is not None
    assert plan.selected_figure_ids == (FIGURE_ID,)
    assert (
        plan.source_sha256
        == load_dsc_single_curve_source_facts(_fixture()).source_sha256
    )


def test_registered_dsc_copy_resolves_without_copying_provenance(
    tmp_path: Path,
) -> None:
    copied_root = tmp_path / "source"
    copied_root.mkdir()
    copied = copied_root / "sample__udc_dsc_digitized.csv"
    shutil.copy2(_fixture(), copied)

    original = load_dsc_single_curve_source_facts(_fixture())
    copied_facts = load_dsc_single_curve_source_facts(copied_root)

    assert copied_facts.source_sha256 == original.source_sha256
    assert copied_facts.csv_sha256 == original.csv_sha256
    assert copied_facts.provenance_sha256 == original.provenance_sha256


def test_selected_inventory_type_is_closed_to_two_files() -> None:
    inventory = dsc_resolution._selected_inventory(
        _fixture(),
        _fixture().with_name("digitization_provenance.json"),
    )

    assert isinstance(inventory, DscSelectedInventory)
    assert set(inventory.to_payload()) == {
        "csv_sha256",
        "provenance_sha256",
        "source_sha256",
    }
