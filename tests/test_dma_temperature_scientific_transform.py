from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.materials_rules import get_rule
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.scientific_source import (
    resolve_scientific_source,
)
from sciplot_core.semantic_sources.dma_temperature_transform import (
    resolve_dma_temperature_transform,
)
from sciplot_core.terminal_source_attestation import (
    terminal_binding_from_preparation_attestation,
)
from sciplot_core.workflow.dma_temperature_plan import (
    require_dma_temperature_execution_plan,
)


RULE_ID = "dma_temperature_sweep"
EXPECTED_ORDER = ("PBAT", "5 wt% UDC 2", "5 wt% UDC 3", "5 wt% UDC 4")
EXPECTED_POINTS = (613, 1133, 1128, 1200)
EXPECTED_EMPTY_TAILS = (587, 67, 72, 0)


def _fixture() -> Path:
    source = resolve_fixture_path(str(get_rule(RULE_ID).fixture_path or ""))
    assert source.is_file()
    return source


def test_real_dma_transform_preserves_units_points_empty_tails_and_negative() -> None:
    resolved = resolve_dma_temperature_transform(_fixture())
    contract = resolved.contract.to_payload()

    assert resolved.selected_sources == (_fixture().resolve(),)
    assert tuple(contract["output"]["series_order"]) == EXPECTED_ORDER
    series_evidence = contract["output"]["series"]
    assert tuple(item["candidate_row_count"] for item in series_evidence) == (
        1200,
        1200,
        1200,
        1200,
    )
    assert tuple(item["retained_point_count"] for item in series_evidence) == (
        EXPECTED_POINTS
    )
    assert tuple(item["excluded_point_count"] for item in series_evidence) == (
        EXPECTED_EMPTY_TAILS
    )
    assert tuple(
        item["excluded_by_reason"] for item in series_evidence
    ) == tuple(
        {"empty_pair": count, "partial_or_nonnumeric": 0, "nonfinite": 0}
        for count in EXPECTED_EMPTY_TAILS
    )
    assert contract["anchor"] == {"scope": "none", "selections": []}
    assert contract["retain_anchor"] is None
    assert contract["normalizer"] == {
        "scope": "none",
        "operation": "none",
        "output_metric": "storage_modulus",
        "output_unit": "MPa",
    }
    assert contract["axis_compatibility"] == {
        "x": {
            "registered_scale": "linear",
            "finite_compatible": True,
            "log_compatible": True,
            "nonpositive_count": 0,
        },
        "y": {
            "registered_scale": "linear",
            "finite_compatible": True,
            "log_compatible": False,
            "nonpositive_count": 1,
        },
    }
    response_conversion = next(
        item
        for item in contract["unit_conversions"]
        if item["sample"] == "PBAT" and item["role"] == "response"
    )
    assert response_conversion == {
        "sample": "PBAT",
        "role": "response",
        "source_unit": "MPa",
        "canonical_unit": "Pa",
        "display_unit": "MPa",
        "source_to_canonical": {"factor": 1.0e6, "offset": 0.0},
        "canonical_to_display": {"factor": 1.0e-6, "offset": 0.0},
    }
    negative_points = [
        point
        for series in resolved.series
        for point in series.points
        if point[1] < 0.0
    ]
    assert len(negative_points) == 1
    assert negative_points[0] == pytest.approx((142.8437, -0.00076029))


@pytest.mark.parametrize("suffix", [".tsv", ".txt", ".xlsx"])
def test_dma_transform_preserves_supported_non_csv_sources(
    tmp_path: Path,
    suffix: str,
) -> None:
    source = tmp_path / f"dma{suffix}"
    rows = [
        ["Temperature (°C)", "Sample A Storage Modulus (MPa)"],
        [0.0, 1.0],
        [10.0, 0.5],
    ]
    if suffix == ".xlsx":
        pd.DataFrame(rows).to_excel(source, header=False, index=False)
    else:
        source.write_text(
            "\n".join("\t".join(str(value) for value in row) for row in rows),
            encoding="utf-8",
        )

    resolved = resolve_dma_temperature_transform(source)

    assert resolved.selected_sources == (source.resolve(),)
    assert resolved.contract.to_payload()["selected_sources"] == [
        str(source.resolve())
    ]
    assert resolved.series[0].points == ((0.0, 1.0), (10.0, 0.5))


@pytest.mark.parametrize("token", ["NaN", "Inf"])
def test_dma_transform_rejects_nonfinite_only_sibling_series(
    tmp_path: Path,
    token: str,
) -> None:
    source = tmp_path / "dma.csv"
    source.write_text(
        "Temperature (°C),Good Storage Modulus (MPa),"
        "Temperature (°C),Bad Storage Modulus (MPa)\n"
        f"0,1,0,{token}\n"
        f"10,0.5,10,{token}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="nonfinite"):
        resolve_dma_temperature_transform(source)


def test_dma_plan_parses_one_domain_snapshot_and_reuses_its_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.figure_plan.dma_temperature_resolution as dma_resolution

    original = dma_resolution.resolve_dma_temperature_transform
    calls = 0

    def counted_resolver(
        source: Path,
        *,
        series_order: object = None,
    ):
        nonlocal calls
        calls += 1
        return original(source, series_order=series_order)

    monkeypatch.setattr(
        dma_resolution,
        "resolve_dma_temperature_transform",
        counted_resolver,
    )

    preview = build_plan_preview(
        _fixture(),
        request={
            "rule_id": RULE_ID,
            "template": "point_line",
            "series_order": list(reversed(EXPECTED_ORDER)),
        },
    )

    assert calls == 1
    assert preview["status"] == "planned"
    assert preview["blocker"] is None
    assert preview["scientific_transform"] is not None
    assert preview["scientific_transform"]["output"]["series_order"] == list(
        reversed(EXPECTED_ORDER)
    )
    plan = preview["resolved_figure_plan"]
    assert plan is not None
    assert plan["tasks"][0]["sample_order"] == list(reversed(EXPECTED_ORDER))

    monkeypatch.setattr(
        dma_resolution,
        "resolve_dma_temperature_transform",
        original,
    )
    resolved_plan = resolved_figure_plan_from_payload(plan)
    assert resolved_plan is not None
    execution_facts = require_dma_temperature_execution_plan(
        resolved_plan,
        source=_fixture(),
    )
    assert execution_facts.sample_order == tuple(reversed(EXPECTED_ORDER))


def test_dma_preparation_materializes_the_same_resolved_contract(
    tmp_path: Path,
) -> None:
    resolved = resolve_dma_temperature_transform(_fixture())

    prepared = prepare_semantic_source(
        _fixture(),
        output_dir=tmp_path / "prepared",
        semantic={"semantic_family": RULE_ID, "rule_id": RULE_ID},
    )

    step = prepared["transform_steps"][0]
    assert step["parameters"]["scientific_transform"] == (
        resolved.contract.to_payload()
    )


def test_resolved_dma_snapshot_materializes_without_a_second_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = resolve_scientific_source(
        _fixture(),
        rule_id=RULE_ID,
        request={"series_order": list(EXPECTED_ORDER)},
        template="point_line",
    )
    assert resolved is not None
    assert resolved.figure_plan is not None

    import sciplot_core.semantic_sources.prepare_curve_families as preparation
    import sciplot_core.semantic as semantic_module

    monkeypatch.setattr(
        preparation,
        "resolve_dma_temperature_transform",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic preparation reparsed the DMA source")
        ),
    )
    monkeypatch.setattr(
        semantic_module,
        "source_tree_sha256",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic preparation rehashed the resolved source")
        ),
    )
    monkeypatch.setattr(
        PreparationSourceAttestation,
        "verify_current",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("same-transaction preparation evidence was reverified")
        ),
    )
    prepared = prepare_semantic_source(
        _fixture(),
        output_dir=tmp_path / "prepared_once",
        semantic={"semantic_family": RULE_ID, "rule_id": RULE_ID},
        series_order=list(EXPECTED_ORDER),
        resolved_scientific_source=resolved,
    )

    assert prepared["transform_steps"][0]["parameters"][
        "scientific_transform"
    ] == resolved.transform.contract.to_payload()


def test_dma_execution_facts_reuse_the_same_resolved_transform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = resolve_scientific_source(
        _fixture(),
        rule_id=RULE_ID,
        request={},
        template="point_line",
    )
    assert resolved is not None
    assert resolved.figure_plan is not None

    import sciplot_core.workflow.dma_temperature_plan as execution

    monkeypatch.setattr(
        execution,
        "load_dma_temperature_source_facts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("execution reparsed the raw DMA source")
        ),
    )
    facts = execution.require_dma_temperature_execution_plan(
        resolved.figure_plan,
        source=_fixture(),
        resolved_scientific_source=resolved,
    )

    assert facts.sample_order == EXPECTED_ORDER
    assert facts.point_counts == EXPECTED_POINTS


def test_dma_execution_rejects_a_snapshot_from_another_source(
    tmp_path: Path,
) -> None:
    resolved = resolve_scientific_source(
        _fixture(),
        rule_id=RULE_ID,
        request={},
        template="point_line",
    )
    assert resolved is not None
    assert resolved.figure_plan is not None

    with pytest.raises(ValueError, match="scientific_source_mismatch"):
        require_dma_temperature_execution_plan(
            resolved.figure_plan,
            source=tmp_path / "different_source.csv",
            resolved_scientific_source=resolved,
        )


def test_terminal_binding_reuses_preparation_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    prepared = tmp_path / "prepared.csv"
    prepared.write_text("x,y\n1,2\n", encoding="utf-8")
    from sciplot_core.foundation.source_tree import source_tree_sha256

    source_hash = source_tree_sha256(source)
    assert source_hash is not None
    attestation = PreparationSourceAttestation.capture(
        rule_id=RULE_ID,
        source_root=source,
        source_tree_sha256_before=source_hash,
        selected_sources=(source,),
        prepared_source=prepared,
    )
    import sciplot_core.terminal_source_binding as binding_module

    monkeypatch.setattr(
        binding_module,
        "file_sha256",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("terminal binding rehashed captured artifacts")
        ),
    )

    binding = terminal_binding_from_preparation_attestation(
        task_key="dma_temperature_storage_modulus",
        rule_id=RULE_ID,
        template="point_line",
        x_metric="temperature",
        y_metric="storage_modulus",
        source_attestation=attestation,
        terminal_source=prepared,
        sample_order=("sample A",),
        point_counts={"sample A": 1},
    )

    assert binding.raw_sources[0].sha256 == attestation.selected_sources[0].sha256
    assert binding.prepared_source.sha256 == attestation.prepared_source.sha256
