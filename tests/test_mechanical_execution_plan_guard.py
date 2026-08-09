from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.mechanical_task_sources import require_mechanical_execution_plan
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from tests.test_mechanical_workflow_bundle import _facts, _plan, _write_prepared


def test_execution_plan_rejects_pair_count_or_unit_mismatch(tmp_path: Path) -> None:
    facts, raw = _facts(tmp_path)
    plan = _plan(facts, "representative")
    prepared = tmp_path / "prepared.csv"
    _write_prepared(prepared, facts.representative_curve_series)
    attestation = PreparationSourceAttestation.capture(
        rule_id=facts.rule_id,
        source_root=raw,
        source_tree_sha256_before=facts.source_sha256,
        selected_sources=facts.selected_sources,
        prepared_source=prepared,
    )
    forged_task = replace(plan.tasks[1], replicate_counts=(("Sample", 1),))
    forged = ResolvedFigurePlan.planned(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=(plan.tasks[0], forged_task, *plan.tasks[2:]),
        source_sha256=plan.source_sha256,
    )
    with pytest.raises(ValueError, match="mechanical_figure_plan_mismatch"):
        require_mechanical_execution_plan(
            forged,
            facts=facts,
            prepared_source=prepared,
            source_attestation=attestation,
        )
    bad_units = replace(
        facts,
        metric_units=tuple(
            (metric, "J") if metric == "toughness_MJ_m3" else (metric, unit)
            for metric, unit in facts.metric_units
        ),
    )
    with pytest.raises(ValueError, match="mechanical_terminal_source_binding_mismatch"):
        require_mechanical_execution_plan(
            plan,
            facts=bad_units,
            prepared_source=prepared,
            source_attestation=attestation,
        )
