from __future__ import annotations

from pathlib import Path

import pytest

import sciplot_core.figure_plan.temperature_resolution as temperature_resolution
import sciplot_core.semantic_sources.rheology_temperature_domain as temperature_domain
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigurePlanResolutionError,
    ResolvedFigurePlan,
    REQUIRED_FIGURE_PLAN_RULE_IDS,
    resolve_figure_plan,
    source_tree_sha256,
)
from sciplot_core.figure_plan.temperature_resolution import (
    resolve_temperature_plan,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.rheology_temperature_domain import (
    resolve_rheology_temperature_domain,
)


RULE_ID = "rheology_temperature_sweep"
TEMPLATE = "point_line"
EXPECTED_SAMPLE_ORDER = ("PA-2", "D-PA", "SD-PA", "S-PA")
EXPECTED_TASKS = (
    (
        "storage_modulus_vs_temperature",
        "storage_modulus",
        "temp_storage_modulus",
    ),
    ("tan_delta_vs_temperature", "loss_factor", "temp_loss_factor"),
)


def _fixture() -> Path:
    path = resolve_fixture_path(str(get_rule(RULE_ID).fixture_path or ""))
    assert path.is_dir()
    return path


def _resolve(request: dict[str, object] | None = None) -> ResolvedFigurePlan:
    return resolve_temperature_plan(
        input_path=_fixture(),
        request=dict(request or {}),
    )


def test_default_temperature_plan_binds_exact_two_real_metric_tasks() -> None:
    plan = _resolve()

    assert plan.rule_id == RULE_ID
    assert plan.selection_policy == "default_storage_modulus_then_loss_factor"
    assert plan.primary_figure_id == "storage_modulus_vs_temperature"
    assert plan.selected_figure_ids == tuple(item[0] for item in EXPECTED_TASKS)
    assert tuple(task.order for task in plan.tasks) == (1, 2)
    assert tuple(task.template for task in plan.tasks) == (TEMPLATE, TEMPLATE)
    assert tuple(task.artifact_stem for task in plan.tasks) == tuple(
        item[2] for item in EXPECTED_TASKS
    )
    assert plan.source_sha256 == source_tree_sha256(_fixture())
    assert all(task.to_payload()["version"] == 2 for task in plan.tasks)
    assert all(task.sample_order == EXPECTED_SAMPLE_ORDER for task in plan.tasks)
    assert all(
        task.replicate_counts == tuple((sample, 1) for sample in EXPECTED_SAMPLE_ORDER)
        for task in plan.tasks
    )
    assert tuple(task.metric_binding for task in plan.tasks) == tuple(
        CartesianMetricBinding(x_metric="temperature", y_metric=y_metric)
        for _figure_id, y_metric, _stem in EXPECTED_TASKS
    )
    assert ResolvedFigurePlan.from_payload(plan.to_payload()) == plan


def test_temperature_plan_honors_one_explicit_complete_sample_order() -> None:
    requested = ("S-PA", "SD-PA", "D-PA", "PA-2")

    plan = _resolve({"series_order": list(requested)})

    assert all(task.sample_order == requested for task in plan.tasks)
    assert all(
        tuple(sample for sample, _count in task.replicate_counts) == requested
        for task in plan.tasks
    )


def test_temperature_domain_parses_once_and_plan_reuses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_loader = temperature_domain._read_rheology_temperature_comparison_samples
    calls: list[Path] = []

    def counted_loader(source: Path):
        calls.append(source)
        return real_loader(source)

    monkeypatch.setattr(
        temperature_domain,
        "_read_rheology_temperature_comparison_samples",
        counted_loader,
    )

    source_resolution = resolve_rheology_temperature_domain(
        _fixture(),
        request={},
    )
    monkeypatch.setattr(
        temperature_resolution,
        "resolve_rheology_temperature_domain",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("FigurePlan reparsed the resolved temperature domain")
        ),
    )
    plan = resolve_temperature_plan(
        input_path=_fixture(),
        request={},
        source_resolution=source_resolution,
    )

    assert calls == [_fixture()]
    assert source_resolution.rule_id == RULE_ID
    assert source_resolution.source == _fixture()
    assert source_resolution.selected_sources == tuple(
        dict.fromkeys(sample.source.resolve() for sample in source_resolution.raw_samples)
    )
    assert source_resolution.facts.sample_order == EXPECTED_SAMPLE_ORDER
    assert plan.source_sha256 == source_resolution.source_sha256
    assert all(task.sample_order == EXPECTED_SAMPLE_ORDER for task in plan.tasks)


def test_temperature_resolution_rejects_source_drift_during_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stable_hash = source_tree_sha256(_fixture())
    assert stable_hash is not None
    fingerprints = iter((stable_hash, "b" * 64))
    monkeypatch.setattr(
        temperature_domain,
        "source_tree_sha256",
        lambda _source: next(fingerprints),
    )

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        _resolve()

    assert exc_info.value.reason_code == "temperature_source_changed_during_resolution"


def test_temperature_plan_rejects_missing_loss_factor(tmp_path: Path) -> None:
    source = tmp_path / "storage_only.tsv"
    source.write_text(
        "Temperature\tStorage Modulus\nC\tPa\n200\t1000\n190\t2000\n",
        encoding="utf-8",
    )

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_temperature_plan(input_path=source, request={})

    assert exc_info.value.reason_code == "temperature_metric_source_unavailable"


def test_temperature_plan_is_registered_in_global_resolution() -> None:
    assert RULE_ID in REQUIRED_FIGURE_PLAN_RULE_IDS

    plan = resolve_figure_plan(
        rule_id=RULE_ID,
        template=TEMPLATE,
        study_model={},
        input_path=_fixture(),
        request={"template": TEMPLATE},
    )

    assert plan == _resolve({"template": TEMPLATE})
