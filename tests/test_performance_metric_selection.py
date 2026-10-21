"""Generated long-table controls for explicit performance metric metadata."""

from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.performance_comparison import (
    PerformanceComparisonError,
    prepare_performance_comparison,
)
from sciplot_core.performance_comparison.metadata import inspect_performance_metadata
from sciplot_core.performance_veusz import build_performance_veusz_spec
from sciplot_core.source_coverage.managed_documents import _derive_prepared_data
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot


def generated_table(root: Path, *, missing_units: bool = False) -> Path:
    source = root / "observed.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Material", "Role", "Metric", "Value", "Unit"])
        for index in range(7):
            role = "sample" if index < 4 else "reference"
            density = "1.2345678901234567" if index < 3 else str(1.3 + index / 10)
            strength = "NaN" if index == 6 else str(25.25 + index % 3)
            for metric, value, unit in (
                ("density", density, "g/cm^3"),
                ("specific_impact_strength", strength, "kJ*m/kg"),
                ("impact_strength_mean", str(1000 + index), "kJ/m^2"),
            ):
                writer.writerow(
                    [
                        f"Material {index}",
                        role,
                        metric,
                        value,
                        "" if missing_units else unit,
                    ]
                )
    return source


def selection_for(source: Path, *, declarations: bool = False) -> dict:
    return {
        "kind": "sciplot_performance_metric_selection",
        "version": 1,
        "source_sha256": file_sha256(source),
        "x_metric": "density",
        "y_metric": "specific_impact_strength",
        "scatter_x_display": "preserve_original",
        "unit_declarations": [
            {
                "metric_id": metric,
                "unit": unit,
                "user_statement": f"I confirm the original {metric} unit is {unit}.",
            }
            for metric, unit in (
                ("density", "g/cm^3"),
                ("specific_impact_strength", "kJ*m/kg"),
            )
        ]
        if declarations
        else [],
    }


def test_selected_scatter_preserves_density_duplicates_missing_and_roles(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path)
    before = source.read_bytes()
    selection = selection_for(source)
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selection
    )
    assert source.read_bytes() == before
    assert payload["x_metric"]["metric_id"] == "density"
    assert payload["y_metric"]["metric_id"] == "specific_impact_strength"
    points = {item["source_materials"][0]: item for item in payload["series"]}
    exact = float("1.2345678901234567")
    assert [points[f"Material {i}"]["x_values"][0] for i in range(3)] == [exact] * 3
    assert (
        points["Material 0"]["y_values"] == points["Material 3"]["y_values"] == [25.25]
    )
    assert len(points) == payload["valid_pair_count"] == 6
    assert payload["source_material_count"] == 7
    assert payload["source_row_count"] == 21
    assert payload["selected_row_count"] == 14
    assert payload["missing_pair_count"] == 1
    assert payload["source_observations"][-1]["y_value"] is None
    assert payload["source_observations"][-1]["y_source_rows"] == [21]
    assert payload["source_observations"][-1]["valid_pair"] is False
    assert payload["visual_data_transforms"] == []
    assert {item["role"] for item in payload["legend_items"]} == {"sample", "reference"}
    assert payload["performance_selection"] == selection


def test_missing_units_require_per_metric_current_source_user_statements(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path, missing_units=True)
    before = source.read_bytes()
    facts = inspect_performance_metadata(source)
    assert facts["read_only"] is True
    assert facts["source_sha256"] == file_sha256(source)
    assert facts["source_row_count"] == 21
    schema = facts["selection_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(facts["selection_template"])
    declaration = schema["properties"]["unit_declarations"]["items"]
    assert declaration["additionalProperties"] is False
    assert set(declaration["required"]) == {"metric_id", "unit", "user_statement"}
    assert [item["metric_id"] for item in facts["metrics"]] == [
        "density",
        "specific_impact_strength",
        "impact_strength_mean",
    ]
    assert all(item["missing_unit_count"] == 7 for item in facts["metrics"])
    assert "values" not in str(facts)
    for declaration in facts["selection_template"]["unit_declarations"]:
        assert declaration["unit"] == declaration["user_statement"] == ""
    with pytest.raises(PerformanceComparisonError, match="density") as caught:
        prepare_performance_comparison(
            source, template_id="scatter", selection=selection_for(source)
        )
    assert caught.value.reason_code == "performance_metric_unit_confirmation_required"
    confirmed = selection_for(source, declarations=True)
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=confirmed
    )
    assert payload["x_metric"]["unit"] == "g/cm^3"
    assert payload["y_metric"]["unit"] == "kJ*m/kg"
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "change", ["unknown", "partial", "same", "stale", "display", "declaration"]
)
def test_selection_rejects_nonclosed_or_unbound_metadata(
    tmp_path: Path, change: str
) -> None:
    source = generated_table(tmp_path)
    selection = selection_for(source)
    if change == "unknown":
        selection["extra"] = True
    elif change == "partial":
        del selection["unit_declarations"]
    elif change == "same":
        selection["y_metric"] = "density"
    elif change == "stale":
        selection["source_sha256"] = "0" * 64
    elif change == "display":
        selection["scatter_x_display"] = "almost_raw"
    else:
        selection["unit_declarations"] = [
            {"metric_id": "density", "unit": "kg/m^3", "user_statement": "confirmed"}
        ]
    with pytest.raises(PerformanceComparisonError):
        prepare_performance_comparison(
            source, template_id="scatter", selection=selection
        )


def test_unknown_metric_is_not_replaced_by_mean_or_ratio(tmp_path: Path) -> None:
    source = generated_table(tmp_path)
    selection = selection_for(source)
    selection["y_metric"] = "specific_impact_strength_typo"
    with pytest.raises(PerformanceComparisonError) as caught:
        prepare_performance_comparison(
            source, template_id="scatter", selection=selection
        )
    assert caught.value.reason_code == "performance_metric_unknown"


def test_existing_unit_conflict_and_duplicate_pairing_stay_closed(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path)
    source.write_text(source.read_text().replace("25.25,kJ*m/kg", "25.25,MPa", 1))
    facts = inspect_performance_metadata(source)
    assert facts["metrics"][1]["unit_conflict"] is True
    with pytest.raises(PerformanceComparisonError) as caught:
        prepare_performance_comparison(
            source, template_id="scatter", selection=selection_for(source)
        )
    assert caught.value.reason_code == "performance_metric_unit_conflict"
    source = generated_table(tmp_path)
    with source.open("a", encoding="utf-8") as stream:
        stream.write("Material 0,sample,specific_impact_strength,25.25,kJ*m/kg\n")
    with pytest.raises(PerformanceComparisonError) as caught:
        prepare_performance_comparison(
            source, template_id="scatter", selection=selection_for(source)
        )
    assert caught.value.reason_code == "performance_material_metric_duplicate"


def test_source_audit_replays_selection_and_refuses_drift(tmp_path: Path) -> None:
    source = generated_table(tmp_path, missing_units=True)
    selection = selection_for(source, declarations=True)
    request = {
        "input": str(source),
        "rule_id": "performance_comparison",
        "template": "scatter",
        "performance_selection": selection,
    }
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selection
    )
    spec = build_performance_veusz_spec(payload=payload, request=request)
    derived = _derive_prepared_data(request=request, private_sources=[source])
    assert derived["status"] == "passed"
    assert [item["y_values"] for item in derived["units"]] == [
        item["y_values"] for item in spec["series"]
    ]
    broken = deepcopy(request)
    broken["performance_selection"]["unit_declarations"][0]["unit"] = "kg/m^3"
    # A changed declaration changes the source-derived scientific axis label.
    changed = _derive_prepared_data(request=broken, private_sources=[source])
    assert (
        changed["units"][0]["axes"]["x"]["label"]
        != derived["units"][0]["axes"]["x"]["label"]
    )
    source.write_text(source.read_text() + "\n", encoding="utf-8")
    with pytest.raises(PerformanceComparisonError) as caught:
        _derive_prepared_data(request=request, private_sources=[source])
    assert caught.value.reason_code == "performance_selection_source_changed"


def test_missing_mask_and_unit_statement_are_audited_from_source(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path, missing_units=True)
    selection = selection_for(source, declarations=True)
    request = {
        "input": str(source),
        "rule_id": "performance_comparison",
        "template": "scatter",
        "performance_selection": selection,
    }
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selection
    )
    spec = build_performance_veusz_spec(payload=payload, request=request)
    snapshots = [_stable_file_snapshot(source, label="generated source")]
    assert _verify_prepared_data(spec, snapshots)["status"] == "passed"
    for field in ("valid_pair", "y_value"):
        tampered = deepcopy(spec)
        tampered["performance_comparison"]["source_observations"][-1][field] = 9
        with pytest.raises(ValueError, match="missing masks"):
            _verify_prepared_data(tampered, snapshots)
    tampered = deepcopy(spec)
    tampered["source_request"]["performance_selection"]["unit_declarations"][0][
        "user_statement"
    ] = "Different statement"
    with pytest.raises(ValueError, match="unit declarations"):
        _verify_prepared_data(tampered, snapshots)
    tampered = deepcopy(spec)
    del tampered["performance_comparison"]["source_observations"]
    with pytest.raises(ValueError, match="evidence is incomplete"):
        _verify_prepared_data(tampered, snapshots)


def test_missing_unit_column_and_unselected_missing_values_are_supported(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path)
    lines = source.read_text().splitlines()
    source.write_text("\n".join(line.rsplit(",", 1)[0] for line in lines) + "\n")
    selection = selection_for(source, declarations=True)
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selection
    )
    assert payload["valid_pair_count"] == 6
    assert payload["excluded_metrics"] == ["impact_strength_mean"]


def test_selection_does_not_change_historical_default_jitter(tmp_path: Path) -> None:
    source = generated_table(tmp_path)
    text = source.read_text().replace("Value,Unit", "Value,Unit,ScatterAxis")
    rows = text.splitlines()
    for index in range(1, len(rows)):
        if ",density," in rows[index]:
            rows[index] += ",x"
        elif ",specific_impact_strength," in rows[index]:
            rows[index] = rows[index].replace(",NaN,", ",29.0,") + ",y"
        else:
            rows[index] += ","
    source.write_text("\n".join(rows) + "\n")
    default = prepare_performance_comparison(source, template_id="scatter")
    selected = prepare_performance_comparison(
        source, template_id="scatter", selection=selection_for(source)
    )
    assert default["visual_data_transforms"]
    assert selected["visual_data_transforms"] == []
    assert "performance_selection" not in default


@pytest.mark.parametrize(
    ("x_metric", "y_metric", "x_unit", "y_unit"),
    [
        ("bulk_density", "energy_per_mass", "kg/m^3", "J/kg"),
        ("rho_observed", "specific_strength_trial", "g/L", "N*m/kg"),
    ],
)
def test_metric_selection_uses_arbitrary_original_ids_and_units(
    tmp_path: Path, x_metric: str, y_metric: str, x_unit: str, y_unit: str
) -> None:
    source = generated_table(tmp_path)
    source.write_text(
        source.read_text()
        .replace("density", x_metric)
        .replace("specific_impact_strength", y_metric)
        .replace("g/cm^3", x_unit)
        .replace("kJ*m/kg", y_unit)
    )
    selection = selection_for(source)
    selection.update({"x_metric": x_metric, "y_metric": y_metric})
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selection
    )
    assert payload["x_metric"]["unit"] == x_unit
    assert payload["y_metric"]["unit"] == y_unit
    assert payload["series"][0]["x_values"] == [float("1.2345678901234567")]
    assert payload["series"][0]["y_values"] == [25.25]


def test_source_row_mask_keeps_blank_record_positions(tmp_path: Path) -> None:
    source = generated_table(tmp_path)
    lines = source.read_text().splitlines()
    lines.insert(2, "")
    source.write_text("\n".join(lines) + "\n")
    selected = prepare_performance_comparison(
        source, template_id="scatter", selection=selection_for(source)
    )
    assert selected["source_observations"][0]["x_source_rows"] == [2]
    assert selected["source_observations"][0]["y_source_rows"] == [4]
    assert selected["source_row_count"] == 21


def test_selected_default_metric_labels_are_literal_but_units_keep_exponents(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path)
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selection_for(source)
    )
    spec = build_performance_veusz_spec(
        payload=payload, request={"template": "scatter"}
    )
    assert spec["axes"]["y"]["label"].startswith(r"specific\_impact\_strength (")
    assert "kg⁻¹" in spec["axes"]["y"]["label"]
    assert payload["y_metric"]["metric_id"] == "specific_impact_strength"
    source.write_text(source.read_text().replace("density", "rho_{trial}^x"))
    chosen = selection_for(source)
    chosen["x_metric"] = "rho_{trial}^x"
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=chosen
    )
    spec = build_performance_veusz_spec(
        payload=payload, request={"template": "scatter"}
    )
    assert spec["axes"]["x"]["label"].startswith(r"rho\_\{trial\}\^x (")


def test_selected_explicit_display_labels_keep_existing_markup(tmp_path: Path) -> None:
    source = generated_table(tmp_path)
    lines = source.read_text().splitlines()
    lines[0] += ",DisplayLabel"
    for index in range(1, len(lines)):
        lines[index] += "," + (
            r"E_{obs}" if ",specific_impact_strength," in lines[index] else ""
        )
    source.write_text("\n".join(lines) + "\n")
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selection_for(source)
    )
    spec = build_performance_veusz_spec(
        payload=payload, request={"template": "scatter"}
    )
    assert spec["axes"]["y"]["label"].startswith(r"E_{obs} (")
    assert "specific_impact_strength" not in payload["literal_metric_labels"]
