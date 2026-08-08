from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_ARTIFACT_STEM,
    DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
    DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
    DMA_TEMPERATURE_FIGURE_ID,
)
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigurePlanResolutionError,
    resolve_current_figure_plan,
    resolve_figure_plan,
)
from sciplot_core.figure_plan.dma_temperature_resolution import (
    load_dma_temperature_source_facts,
)
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import get_rule, match_rule, normalize_token
from sciplot_core.study_model import experiment_recommendation_payload


RULE_ID = "dma_temperature_sweep"
EXPECTED_SAMPLE_ORDER = (
    "PBAT",
    "5 wt% UDC 2",
    "5 wt% UDC 3",
    "5 wt% UDC 4",
)
EXPECTED_POINT_COUNTS = (613, 1133, 1128, 1200)


def _fixture() -> Path:
    source = resolve_fixture_path(str(get_rule(RULE_ID).fixture_path or ""))
    assert source.is_file()
    return source


def test_dma_rule_and_registered_fixture_share_one_unit_contract() -> None:
    rule = get_rule(RULE_ID)
    provenance = json.loads(
        (_fixture().parent / "source_provenance.json").read_text(encoding="utf-8")
    )

    assert rule.y_axis.canonical_unit == DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT
    assert DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT in rule.y_axis.display_label
    assert all("tan" not in normalize_token(value) for value in rule.y_axis.aliases)
    assert all("tan" not in normalize_token(value) for value in rule.column_aliases)
    assert provenance["fixture_file"] == _fixture().name
    assert provenance["fixture_sha256"] == file_sha256(_fixture())
    assert provenance["source_units"]["storage_modulus"] == "MPa"
    assert provenance["canonical_units"]["storage_modulus"] == "Pa"
    assert provenance["output_units"]["storage_modulus"] == "MPa"


def test_tan_delta_alone_cannot_match_dma_storage_modulus() -> None:
    evidence = "temperature tan delta"

    matched = match_rule(
        evidence=evidence,
        compact_evidence=normalize_token(evidence),
    )

    assert matched is None or matched.rule_id != RULE_ID


def test_dma_study_model_declares_the_exact_single_task() -> None:
    recommendation = experiment_recommendation_payload(
        rule_id=RULE_ID,
        semantic_family=RULE_ID,
    )

    assert recommendation["default_replicate_mode"] == "individual"
    assert recommendation["figure_queue"] == [
        {
            "id": DMA_TEMPERATURE_FIGURE_ID,
            "title": "Storage modulus vs temperature",
            "metric": "storage_modulus",
            "x_metric": "temperature",
            "y_metric": "storage_modulus",
            "default_template": "point_line",
        }
    ]


def test_real_dma_source_facts_preserve_every_point_and_negative_value() -> None:
    facts = load_dma_temperature_source_facts(_fixture())

    assert facts.sample_order == EXPECTED_SAMPLE_ORDER
    assert facts.point_counts == EXPECTED_POINT_COUNTS
    assert sum(facts.point_counts) == 4074
    assert facts.source_modulus_units == ("MPa",)
    assert facts.canonical_modulus_unit == "Pa"
    assert facts.display_modulus_unit == "MPa"
    assert facts.negative_display_point_count == 1
    assert facts.minimum_display_value_MPa == pytest.approx(-0.00076029)


def test_dma_plan_is_one_source_bound_v2_cartesian_task() -> None:
    facts = load_dma_temperature_source_facts(_fixture())

    plan = resolve_figure_plan(
        rule_id=RULE_ID,
        template="point_line",
        study_model={},
        input_path=_fixture(),
        request={"template": "point_line"},
    )

    assert plan is not None
    assert plan.selection_policy == "dma_temperature_storage_modulus_single_task"
    assert plan.primary_figure_id == DMA_TEMPERATURE_FIGURE_ID
    assert plan.selected_figure_ids == (DMA_TEMPERATURE_FIGURE_ID,)
    assert plan.source_sha256 == facts.source_sha256
    task = plan.tasks[0]
    assert task.metric_binding == CartesianMetricBinding(
        x_metric="temperature",
        y_metric="storage_modulus",
    )
    assert task.to_payload()["version"] == 2
    assert task.template == "point_line"
    assert task.artifact_stem == DMA_TEMPERATURE_ARTIFACT_STEM
    assert task.sample_order == EXPECTED_SAMPLE_ORDER
    assert task.replicate_counts == tuple(
        (sample, 1) for sample in EXPECTED_SAMPLE_ORDER
    )


def test_dma_plan_rejects_non_point_line_template() -> None:
    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_figure_plan(
            rule_id=RULE_ID,
            template="curve",
            study_model={},
            input_path=_fixture(),
            request={"template": "curve"},
        )

    assert exc_info.value.reason_code == "dma_temperature_template_invalid"


def test_dma_persisted_plan_is_stale_after_source_bytes_change(tmp_path: Path) -> None:
    source = tmp_path / _fixture().name
    shutil.copy2(_fixture(), source)
    plan = resolve_figure_plan(
        rule_id=RULE_ID,
        template="point_line",
        study_model={},
        input_path=source,
        request={"template": "point_line"},
    )
    assert plan is not None
    source.write_text(
        source.read_text(encoding="utf-8").replace("60.37265", "60.37264", 1),
        encoding="utf-8",
    )

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_current_figure_plan(
            persisted=plan.to_payload(),
            rule_id=RULE_ID,
            template="point_line",
            study_model={},
            input_path=source,
            request={"template": "point_line"},
        )

    assert exc_info.value.reason_code == "stale_resolved_figure_plan"
