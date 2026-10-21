"""Generated identifier and typed-evidence boundaries for selected long tables."""

from __future__ import annotations

import csv
from copy import deepcopy
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest
from pandas._libs.parsers import STR_NA_VALUES

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.performance_comparison import (
    inspect_performance_metadata,
    prepare_performance_comparison,
)
from sciplot_core.performance_comparison.source_tables import _read_source_frame
from sciplot_core.performance_veusz import build_performance_veusz_spec
from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data


def choice(source: Path, x_metric: str = "NA", y_metric: str = "N/A") -> dict:
    return {
        "kind": "sciplot_performance_metric_selection",
        "version": 1,
        "source_sha256": file_sha256(source),
        "x_metric": x_metric,
        "y_metric": y_metric,
        "scatter_x_display": "preserve_original",
        "unit_declarations": [],
    }


def save_frame(root: Path, frame: pd.DataFrame, suffix: str) -> Path:
    source = root / f"literal_identifiers.{suffix}"
    if suffix == "xlsx":
        frame.to_excel(source, index=False)
    else:
        frame.to_csv(source, index=False)
    return source


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_metric_material_and_unit_na_text_are_literal_identifiers(
    tmp_path: Path, suffix: str
) -> None:
    frame = pd.DataFrame(
        [
            ["NA", "sample", "NA", "1.1", "NA"],
            ["NA", "sample", "N/A", "9", "J/kg"],
            ["N/A", "reference", "NA", "1.2", "NA"],
            ["N/A", "reference", "N/A", "10", "J/kg"],
        ],
        columns=["Material", "Role", "Metric", "Value", "Unit"],
    )
    source = save_frame(tmp_path, frame, suffix)
    original = source.read_bytes()
    facts = inspect_performance_metadata(source)
    assert [item["metric_id"] for item in facts["metrics"]] == ["NA", "N/A"]
    assert facts["metrics"][0]["original_units"] == ["NA"]
    assert facts["metrics"][0]["missing_unit_count"] == 0
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=choice(source)
    )
    assert [item["source_materials"] for item in payload["series"]] == [["NA"], ["N/A"]]
    assert payload["valid_pair_count"] == 2
    assert payload["x_metric"]["unit"] == "NA"
    spec = build_performance_veusz_spec(
        payload=payload, request={"template": "scatter"}
    )
    assert spec["axes"]["y"]["label"].startswith("N/A (")
    assert (
        spec["axes"]["y"]["label_text_policy"]
        == "literal_identifier_with_formatted_unit"
    )
    assert pd.isna(_read_source_frame(source)["Metric"]).all()
    assert source.read_bytes() == original


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_selected_value_keeps_the_existing_pandas_missing_grammar(
    tmp_path: Path, suffix: str
) -> None:
    tokens = sorted(STR_NA_VALUES)
    rows = [
        ["valid", "sample", "x_id", "1.2345678901234567", "g/cm^3"],
        ["valid", "sample", "y_id", "9", "J/kg"],
    ]
    for index, token in enumerate(tokens):
        material = f"observation_{index}"
        rows.extend(
            [
                [material, "reference", "x_id", "1.2345678901234567", "g/cm^3"],
                [material, "reference", "y_id", token, "J/kg"],
            ]
        )
    frame = pd.DataFrame(rows, columns=["Material", "Role", "Metric", "Value", "Unit"])
    source = save_frame(tmp_path, frame, suffix)
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=choice(source, "x_id", "y_id")
    )
    assert payload["source_row_count"] == len(frame)
    assert payload["valid_pair_count"] == 1
    assert payload["missing_pair_count"] == len(tokens)
    assert all(item["y_value"] is None for item in payload["source_observations"][1:])
    assert payload["series"][0]["x_values"] == [float("1.2345678901234567")]


def test_blank_physical_records_and_unselected_na_ids_keep_their_roles(
    tmp_path: Path,
) -> None:
    source = tmp_path / "with_blank.csv"
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Material", "Role", "Metric", "Value", "Unit"])
    writer.writerow(["NA", "sample", "rho", "1.25", "g/cm^3"])
    writer.writerow([])
    writer.writerow(["NA", "sample", "energy", "7", "J/kg"])
    writer.writerow(["NA", "sample", "NULL", "unselected text", ""])
    source.write_text(output.getvalue())
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=choice(source, "rho", "energy")
    )
    assert payload["source_observations"][0]["y_source_rows"] == [4]
    assert payload["source_row_count"] == 3
    assert payload["excluded_metrics"] == ["NULL"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("valid_pair", 1),
        ("x_value", True),
        ("x_source_rows", [2.0]),
        ("y_value", float("nan")),
        ("y_value", float("inf")),
    ],
)
def test_source_audit_rejects_json_type_confusion_and_nonfinite_evidence(
    tmp_path: Path, field: str, replacement: object
) -> None:
    frame = pd.DataFrame(
        [["A", "sample", "x", "1", "g/cm^3"], ["A", "sample", "y", "9", "J/kg"]],
        columns=["Material", "Role", "Metric", "Value", "Unit"],
    )
    source = save_frame(tmp_path, frame, "csv")
    selected = choice(source, "x", "y")
    request = {
        "input": str(source),
        "rule_id": "performance_comparison",
        "template": "scatter",
        "performance_selection": selected,
    }
    payload = prepare_performance_comparison(
        source, template_id="scatter", selection=selected
    )
    spec = build_performance_veusz_spec(payload=payload, request=request)
    snapshots = [_stable_file_snapshot(source, label="generated typed-evidence source")]
    assert _verify_prepared_data(spec, snapshots)["status"] == "passed"
    tampered = deepcopy(spec)
    tampered["performance_comparison"]["source_observations"][0][field] = replacement
    with pytest.raises(ValueError):
        _verify_prepared_data(tampered, snapshots)
