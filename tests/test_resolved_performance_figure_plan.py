from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import sciplot_core.figure_plan.performance_resolution as performance_resolution
import sciplot_core.figure_plan.resolution as figure_plan_resolution
import sciplot_core.materials_rules.catalog as rule_catalog
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigurePlanResolutionError,
    OrderedMetricsBinding,
    ResolvedFigurePlan,
    REQUIRED_FIGURE_PLAN_RULE_IDS,
    SUPPORTED_FIGURE_PLAN_RULE_IDS,
    resolve_figure_plan,
    source_tree_sha256,
)
from sciplot_core.figure_plan.performance_resolution import resolve_performance_plan
from sciplot_core.materials_rules import get_rule, iter_rules
from sciplot_core.readiness.rule_contract import rule_contract_hashes


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)
DENSE_SCATTER_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_dense_16.csv"
)
EXPECTED_RADAR_METRICS = (
    "density",
    "specific_impact_strength",
    "tensile_strength",
    "elongation_at_break",
)
EXPECTED_MATERIAL_ORDER = ("Own A", "Own B", "Own C", "PA6", "ABS", "CFRP")


def _resolve(source: Path, request: dict[str, object]) -> ResolvedFigurePlan:
    return resolve_performance_plan(
        input_path=source,
        request=request,
    )


def test_default_performance_plan_binds_real_scatter_and_radar_metrics() -> None:
    plan = _resolve(FIXTURE, {"template": "scatter"})

    assert plan.rule_id == "performance_comparison"
    assert plan.selection_policy == "default_scatter_then_polar"
    assert plan.selected_figure_ids == (
        "performance_scatter",
        "performance_polar_curve",
    )
    assert plan.primary_figure_id == "performance_scatter"
    assert tuple(task.order for task in plan.tasks) == (1, 2)
    assert tuple(task.template for task in plan.tasks) == ("scatter", "polar_curve")
    assert plan.source_sha256 == source_tree_sha256(FIXTURE)
    assert all(task.to_payload()["version"] == 2 for task in plan.tasks)
    assert all(task.sample_order == EXPECTED_MATERIAL_ORDER for task in plan.tasks)

    scatter_binding = plan.tasks[0].metric_binding
    radar_binding = plan.tasks[1].metric_binding
    assert scatter_binding == CartesianMetricBinding(
        x_metric="density",
        y_metric="specific_impact_strength",
    )
    assert radar_binding == OrderedMetricsBinding(
        metric_ids=EXPECTED_RADAR_METRICS,
    )
    assert ResolvedFigurePlan.from_payload(plan.to_payload()) == plan


@pytest.mark.parametrize("marker", [None, False, 1, "true"])
def test_only_literal_true_selects_one_performance_template(marker: object) -> None:
    request: dict[str, object] = {
        "template": "polar_curve",
        "explicit_template_selection": marker,
    }

    plan = _resolve(FIXTURE, request)

    assert plan.selected_figure_ids == (
        "performance_scatter",
        "performance_polar_curve",
    )
    assert plan.primary_figure_id == "performance_scatter"


@pytest.mark.parametrize(
    ("request_payload", "expected_figure_id", "expected_template"),
    [
        (
            {"template": "scatter", "explicit_template_selection": True},
            "performance_scatter",
            "scatter",
        ),
        (
            {"template": "polar_curve", "explicit_template_selection": True},
            "performance_polar_curve",
            "polar_curve",
        ),
        (
            {"explicit_template_selection": True},
            "performance_scatter",
            "scatter",
        ),
    ],
)
def test_explicit_performance_plan_selects_one_task(
    request_payload: dict[str, object],
    expected_figure_id: str,
    expected_template: str,
) -> None:
    plan = _resolve(FIXTURE, request_payload)

    assert plan.selection_policy == "explicit_supported_template"
    assert plan.selected_figure_ids == (expected_figure_id,)
    assert plan.primary_figure_id == expected_figure_id
    assert plan.tasks[0].order == 1
    assert plan.tasks[0].template == expected_template


def test_explicit_scatter_does_not_require_radar_metadata() -> None:
    scatter_plan = _resolve(
        DENSE_SCATTER_FIXTURE,
        {"template": "scatter", "explicit_template_selection": True},
    )

    assert scatter_plan.selected_figure_ids == ("performance_scatter",)
    with pytest.raises(FigurePlanResolutionError) as polar_error:
        _resolve(
            DENSE_SCATTER_FIXTURE,
            {"template": "polar_curve", "explicit_template_selection": True},
        )
    assert polar_error.value.reason_code == "performance_radar_needs_three_metrics"
    with pytest.raises(FigurePlanResolutionError) as default_error:
        _resolve(DENSE_SCATTER_FIXTURE, {"template": "scatter"})
    assert default_error.value.reason_code == "performance_radar_needs_three_metrics"


def test_explicit_polar_does_not_require_scatter_axes(tmp_path: Path) -> None:
    frame = pd.read_csv(FIXTURE)
    frame["ScatterAxis"] = ""
    source = tmp_path / "radar_only.csv"
    frame.to_csv(source, index=False)

    polar_plan = _resolve(
        source,
        {"template": "polar_curve", "explicit_template_selection": True},
    )

    assert polar_plan.selected_figure_ids == ("performance_polar_curve",)
    with pytest.raises(FigurePlanResolutionError) as scatter_error:
        _resolve(
            source,
            {"template": "scatter", "explicit_template_selection": True},
        )
    assert scatter_error.value.reason_code == "performance_scatter_axes_invalid"
    with pytest.raises(FigurePlanResolutionError) as default_error:
        _resolve(source, {"template": "scatter"})
    assert default_error.value.reason_code == "performance_scatter_axes_invalid"


def test_radar_order_is_independent_from_csv_row_order(tmp_path: Path) -> None:
    frame = pd.read_csv(FIXTURE)
    source = tmp_path / "shuffled.csv"
    frame.sample(frac=1.0, random_state=47).to_csv(source, index=False)

    original = _resolve(FIXTURE, {"template": "scatter"})
    shuffled = _resolve(source, {"template": "scatter"})

    assert shuffled.selected_figure_ids == original.selected_figure_ids
    assert shuffled.primary_figure_id == original.primary_figure_id
    assert shuffled.selection_policy == original.selection_policy
    assert tuple(task.metric_binding for task in shuffled.tasks) == tuple(
        task.metric_binding for task in original.tasks
    )
    assert all(task.sample_order == EXPECTED_MATERIAL_ORDER for task in shuffled.tasks)
    assert shuffled.source_sha256 == source_tree_sha256(source)
    assert shuffled.source_sha256 != original.source_sha256


def test_performance_source_is_loaded_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_loader = performance_resolution.load_performance_comparison
    calls: list[Path] = []

    def _counted_loader(source: str | Path):
        calls.append(Path(source))
        return real_loader(source)

    monkeypatch.setattr(
        performance_resolution,
        "load_performance_comparison",
        _counted_loader,
    )

    _resolve(FIXTURE, {"template": "scatter"})

    assert calls == [FIXTURE]


def test_performance_resolution_rejects_source_drift_during_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stable_hash = source_tree_sha256(FIXTURE)
    assert stable_hash is not None
    fingerprints = iter((stable_hash, "b" * 64))
    monkeypatch.setattr(
        performance_resolution,
        "source_tree_sha256",
        lambda _source: next(fingerprints),
    )

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        _resolve(FIXTURE, {"template": "scatter"})

    assert exc_info.value.reason_code == "performance_source_changed_during_resolution"


def test_required_figure_plan_rules_match_the_rule_owned_adapters() -> None:
    expected = frozenset(
        {
            "dma_frequency_sweep",
            "dma_temperature_sweep",
            "dsc_curve",
            "dtg_curve",
            "ftir_spectrum",
            "impact_metric",
            "performance_comparison",
            "compression_curve",
            "flexural_curve",
            "rheology_frequency_sweep",
            "rheology_stress_relaxation",
            "rheology_temperature_sweep",
            "saxs_profile",
            "gpc_sec_chromatogram",
            "swelling_curve",
            "tensile_curve",
            "tga_curve",
            "uvvis_spectrum",
            "xrd_pattern",
        }
    )
    assert REQUIRED_FIGURE_PLAN_RULE_IDS == expected
    assert SUPPORTED_FIGURE_PLAN_RULE_IDS is REQUIRED_FIGURE_PLAN_RULE_IDS
    assert frozenset(
        rule.rule_id for rule in iter_rules() if rule.figure_plan_adapter is not None
    ) == expected


def test_figure_plan_adapter_is_read_from_the_semantic_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = get_rule("performance_comparison")
    monkeypatch.setattr(
        rule_catalog,
        "get_rule",
        lambda _rule_id: replace(base, figure_plan_adapter=None),
    )
    monkeypatch.setattr(
        figure_plan_resolution,
        "source_tree_sha256",
        lambda _source: pytest.fail("unadapted rules must not hash source trees"),
    )

    assert (
        resolve_figure_plan(
            rule_id="performance_comparison",
            template="scatter",
            study_model={},
            input_path=None,
            request={"template": "scatter"},
        )
        is None
    )


def test_figure_plan_adapter_is_internal_execution_metadata() -> None:
    original = get_rule("tga_curve")
    rerouted = replace(original, figure_plan_adapter="performance")

    assert rerouted.to_payload() == original.to_payload()
    assert rule_contract_hashes(rerouted) == rule_contract_hashes(original)


def test_performance_plan_resolves_through_the_selected_adapter() -> None:
    plan = resolve_figure_plan(
        rule_id="performance_comparison",
        template="scatter",
        study_model={},
        input_path=FIXTURE,
        request={"template": "scatter"},
    )
    assert plan == resolve_performance_plan(
        input_path=FIXTURE,
        request={"template": "scatter"},
    )


def test_explicit_unsupported_performance_template_fails_closed() -> None:
    with pytest.raises(FigurePlanResolutionError) as exc_info:
        _resolve(
            FIXTURE,
            {"template": "curve", "explicit_template_selection": True},
        )

    assert exc_info.value.reason_code == "performance_template_invalid"
