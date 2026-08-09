from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.mechanical_fact_models import (
    MechanicalSourceFactsError,
    MechanicalSummaryObservation,
)
from sciplot_core.semantic_sources.mechanical_facts import (
    load_mechanical_source_facts,
)


def _fixture(rule_id: str) -> Path:
    return resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))


def _write_curves(
    path: Path,
    *,
    labels: tuple[str, ...],
    maxima: tuple[float, ...],
    stress_label: str = "Compressive stress",
) -> None:
    rows: list[list[object]] = [[], [], []]
    for label in labels:
        rows[0].extend(["Strain", stress_label])
        rows[1].extend(["%", "MPa"])
        rows[2].extend([label, label])
    for point_index in range(3):
        row: list[object] = []
        for maximum in maxima:
            row.extend([point_index, -maximum * point_index / 2.0])
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, header=False, index=False)


@pytest.mark.parametrize(
    ("rule_id", "sample", "count", "metric", "values", "representative"),
    (
        (
            "tensile_curve",
            "E0 2MM",
            9,
            "strength_MPa",
            (34.13, 30.09, 32.67, 36.0, 37.28, 33.39, 37.22, 38.99, 34.2),
            "E0 2MM_9_1",
        ),
        (
            "compression_curve",
            "Conventional PU foam",
            6,
            "compressive_strength_MPa",
            (0.4183888, 0.8878399, 0.5304351, 0.9161088, 0.5232712, 1.882154),
            "repeat 3",
        ),
        (
            "flexural_curve",
            "A_HA56",
            6,
            "flexural_strength_MPa",
            (62.50074, 64.26244, 65.79404, 63.11944, 66.74096, 60.98504),
            "specimen 2",
        ),
    ),
)
def test_real_mechanical_facts_preserve_every_observation_and_select_by_median(
    rule_id: str,
    sample: str,
    count: int,
    metric: str,
    values: tuple[float, ...],
    representative: str,
) -> None:
    facts = load_mechanical_source_facts(_fixture(rule_id), rule_id=rule_id)

    assert facts.sample_order == (sample,)
    assert facts.replicate_counts == ((sample, count),)
    assert all(
        isinstance(row, MechanicalSummaryObservation) for row in facts.summary_rows
    )
    assert tuple(row.sample for row in facts.summary_rows) == (sample,) * count
    assert tuple(row.metric_value(metric) for row in facts.summary_rows) == values
    selected = facts.representative_curve_series[0].diagnostics or {}
    assert selected.get("replicate_label") == representative
    assert len(facts.selected_sources) == (9 if rule_id == "tensile_curve" else 1)
    assert facts.x_unit == "%"
    assert facts.y_unit == "MPa"


def test_mechanical_grouping_requires_explicit_replicate_words(
    tmp_path: Path,
) -> None:
    generic = tmp_path / "generic_numbers.csv"
    explicit = tmp_path / "explicit_repeats.csv"
    _write_curves(generic, labels=("Foam 1", "Foam 2"), maxima=(1.0, 3.0))
    _write_curves(
        explicit,
        labels=("Foam repeat 1", "Foam repeat 2"),
        maxima=(1.0, 3.0),
    )

    generic_facts = load_mechanical_source_facts(generic, rule_id="compression_curve")
    explicit_facts = load_mechanical_source_facts(explicit, rule_id="compression_curve")

    assert generic_facts.sample_order == ("Foam 1", "Foam 2")
    assert generic_facts.replicate_counts == (("Foam 1", 1), ("Foam 2", 1))
    assert explicit_facts.sample_order == ("Foam",)
    assert explicit_facts.replicate_counts == (("Foam", 2),)
    assert (explicit_facts.representative_curve_series[0].diagnostics or {})[
        "replicate_label"
    ] == "repeat 1"


def test_mechanical_preparation_is_attested_and_rejects_curve_mean_before_writes(
    tmp_path: Path,
) -> None:
    source = _fixture("compression_curve")
    semantic = semantic_payload_from_rule(get_rule("compression_curve"), confidence=1.0)
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "representative",
        semantic=semantic,
        replicate_mode="representative",
    )

    processed = Path(str(prepared["processed_source"]))
    parameters = prepared["transform_steps"][0]["parameters"]
    attestation = prepared["source_attestation"]
    assert processed.is_file()
    assert processed.with_name(f"{processed.stem}_all.csv").is_file()
    assert processed.with_name(f"{processed.stem}_summary.csv").is_file()
    assert parameters["replicate_counts"] == {"Conventional PU foam": 6}
    assert parameters["representative_selections"][0]["replicate"] == "repeat 3"
    assert tuple(Path(item.path) for item in attestation.selected_sources) == (
        source.resolve(),
    )
    attestation.verify_current(source_root=source, prepared_source=processed)

    rejected_dir = tmp_path / "mean"
    with pytest.raises(MechanicalSourceFactsError) as exc_info:
        prepare_semantic_source(
            source,
            output_dir=rejected_dir,
            semantic=semantic,
            replicate_mode="mean",
        )
    assert exc_info.value.reason_code == "mechanical_curve_mean_unsupported"
    assert not any(path.is_file() for path in rejected_dir.rglob("*"))


def test_mechanical_individual_mode_materializes_every_explicit_curve(
    tmp_path: Path,
) -> None:
    source = _fixture("flexural_curve")
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path,
        semantic=semantic_payload_from_rule(get_rule("flexural_curve"), confidence=1.0),
        replicate_mode="individual",
    )

    curve = pd.read_csv(Path(str(prepared["processed_source"])), header=None)
    labels = curve.iloc[2, ::2].tolist()
    assert labels == [f"A_HA56__specimen {index}" for index in range(1, 7)]
    parameters = prepared["transform_steps"][0]["parameters"]
    assert parameters["applied_curve_replicate_mode"] == "individual"
    assert parameters["summary_raw_specimen_count"] == 6


def test_curated_mechanical_summary_unit_conflict_fails_before_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "compression_workbooks"
    source.mkdir()
    workbook = source / "foam.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame(
            [
                ["Strain", "Compressive stress"],
                ["%", "MPa"],
                ["Foam", "Foam"],
                [0.0, 0.0],
                [1.0, -1.0],
            ]
        ).to_excel(
            writer,
            sheet_name="Representative_Curve",
            header=False,
            index=False,
        )
        pd.DataFrame(
            [["repeat 1", 800.0], ["repeat 2", 900.0]],
            columns=["Specimen", "Strength (kPa)"],
        ).to_excel(writer, sheet_name="All_Specimens", index=False)
        pd.DataFrame([["label", "Foam"]]).to_excel(
            writer,
            sheet_name="DataStudio_Metadata",
            header=False,
            index=False,
        )

    with pytest.raises(MechanicalSourceFactsError) as exc_info:
        prepare_semantic_source(
            source,
            output_dir=tmp_path / "out",
            semantic=semantic_payload_from_rule(
                get_rule("compression_curve"), confidence=1.0
            ),
            replicate_mode="representative",
        )

    assert exc_info.value.reason_code == "mechanical_summary_unit_unverified"
    assert not any(path.is_file() for path in (tmp_path / "out").rglob("*"))
