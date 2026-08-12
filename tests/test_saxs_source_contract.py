from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

import sciplot_core.semantic_contract_probe as semantic_contract_probe
import sciplot_core.smoke.semantic_parser as semantic_parser
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic import prepare_semantic_source


def _source_contract() -> tuple[Path, dict[str, object]]:
    rule = get_rule("saxs_profile")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    provenance = json.loads(
        (source.parent / "source_provenance.json").read_text(encoding="utf-8")
    )
    return source, provenance


def test_saxs_rule_matches_official_axes_and_source_headers() -> None:
    source, provenance = _source_contract()
    rule = get_rule("saxs_profile")
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    source_columns = provenance["source_columns"]
    assert isinstance(source_columns, dict)
    assert rows[1][::2] == [source_columns["x"]["header"]] * (
        len(rows[1]) // 2
    )
    assert rows[1][1::2] == [source_columns["y"]["header"]] * (
        len(rows[1]) // 2
    )

    axis_evidence = provenance["figure_axis_evidence"]
    assert isinstance(axis_evidence, dict)
    assert rule.x_axis.scale == axis_evidence["x"]["scale"] == "linear"
    assert rule.y_axis.display_label == axis_evidence["y"]["axis_label"]
    assert rule.y_axis.scale == axis_evidence["y"]["scale"] == "log"
    assert rule.x_axis.canonical_unit == source_columns["x"]["unit"]
    assert rule.y_axis.canonical_unit == source_columns["y"]["unit"]

    stored_transform = provenance["stored_transform"]
    assert stored_transform == {
        "status": "unknown_not_stated_by_source",
        "numeric_conversion": "none",
        "policy": (
            "Preserve every reported numeric value without inferring or applying "
            "a transform."
        ),
    }
    assert "log-log" not in rule.reason.casefold()
    assert rule.scientific_source_adapter == "registered_paired_curve"
    assert rule.figure_plan_adapter == "registered_single_curve"
    assert rule.preparation_adapter == "curve_family"

    analysis = rule.analysis[0]
    assert "highest interior discrete local-intensity maximum" in analysis.method
    assert "no structural assignment is inferred" in analysis.method


def test_saxs_nonpositive_diagnostics_equal_each_source_y_column(
    tmp_path: Path,
) -> None:
    source, _ = _source_contract()
    source_table = pd.read_csv(source, header=None)
    expected_counts = [
        int(
            (
                pd.to_numeric(source_table.iloc[2:, column_index], errors="coerce")
                <= 0.0
            ).sum()
        )
        for column_index in range(1, source_table.shape[1], 2)
    ]

    result = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={"semantic_family": "saxs_profile"},
    )
    diagnostics = result["transform_steps"][0]["parameters"]["source_selections"]

    assert [
        int(item["excluded_nonpositive_log_y_count"]) for item in diagnostics
    ] == expected_counts


def test_saxs_probes_do_not_embed_real_samples_or_tail_count_bounds() -> None:
    _, provenance = _source_contract()
    smoke_source = Path(semantic_parser.__file__).read_text(encoding="utf-8")
    probe_source = Path(semantic_contract_probe.__file__).read_text(encoding="utf-8")

    assert all(sample not in smoke_source for sample in provenance["samples"])
    assert "Series A" in smoke_source and "Series B" in smoke_source
    assert 'get("scale")\n        == "linear"' in smoke_source
    assert "excluded_counts == source_nonpositive_counts" in probe_source
    assert "3 <= count <= 12" not in probe_source
