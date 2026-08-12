from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from sciplot_core.figure_plan import REQUIRED_FIGURE_PLAN_RULE_IDS
from sciplot_core.figure_plan import resolution as figure_plan_resolution
from sciplot_core.materials_rules import get_rule
from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources import scientific_source


def test_swelling_rule_uses_the_shared_single_curve_spine() -> None:
    rule = get_rule("swelling_curve")

    assert rule.scientific_source_adapter == "swelling"
    assert rule.figure_plan_adapter == "registered_single_curve"
    assert rule.render_adapter == "generic"
    assert rule.rule_id in REQUIRED_FIGURE_PLAN_RULE_IDS


def test_single_curve_source_dispatch_is_plan_owned_not_an_adapter_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule("swelling_curve")
    expected = object()
    calls: list[tuple[Path, str, dict[str, object], str]] = []

    def resolve_shared(
        source: Path,
        *,
        rule: SemanticRule,
        request: dict[str, object],
        template: str,
    ) -> object:
        calls.append((source, rule.rule_id, request, template))
        return expected

    from sciplot_core.semantic_sources import scientific_source_single_curve

    monkeypatch.setattr(
        scientific_source_single_curve,
        "resolve_single_curve_scientific_source",
        resolve_shared,
    )
    source = tmp_path / "unknown-future-adapter.dat"
    rerouted_rule = replace(
        rule,
        scientific_source_adapter=cast(Any, "future_adapter"),
    )
    monkeypatch.setattr(
        scientific_source,
        "get_rule",
        lambda _rule_id: rerouted_rule,
    )

    resolved = scientific_source.resolve_scientific_source(
        source,
        rule_id=rule.rule_id,
        request={},
        template=rule.template,
    )

    assert resolved is expected
    assert calls == [(source.resolve(), rule.rule_id, {}, rule.template)]


def test_swelling_plan_dispatches_through_the_shared_scientific_source_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "arbitrary-swelling.xlsx"
    expected_plan = object()
    calls: list[dict[str, object]] = []

    def resolve_shared_source(
        input_path: Path,
        *,
        rule_id: str,
        request: dict[str, object],
        template: str,
        study_model: dict[str, object],
    ) -> SimpleNamespace:
        calls.append(
            {
                "input_path": input_path,
                "rule_id": rule_id,
                "request": request,
                "template": template,
                "study_model": study_model,
            }
        )
        return SimpleNamespace(figure_plan=expected_plan)

    monkeypatch.setattr(
        scientific_source,
        "resolve_scientific_source",
        resolve_shared_source,
    )

    result = figure_plan_resolution.resolve_figure_plan(
        rule_id="swelling_curve",
        template="point_line",
        study_model={"figure_queue": []},
        input_path=source,
        request={"series_order": ["sample-b", "sample-a"]},
    )

    assert result is expected_plan
    assert calls == [
        {
            "input_path": source,
            "rule_id": "swelling_curve",
            "request": {"series_order": ["sample-b", "sample-a"]},
            "template": "point_line",
            "study_model": {"figure_queue": []},
        }
    ]


def test_swelling_adapter_binds_the_same_transform_snapshot_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sciplot_core.semantic_sources import (
        scientific_source_single_curve,
        swelling_transform,
    )

    source = tmp_path / "swelling.xlsx"
    source.write_text("source", encoding="utf-8")
    from sciplot_core.figure_plan.source_binding import source_tree_sha256

    expected_source_sha256 = source_tree_sha256(source)
    assert expected_source_sha256 is not None
    snapshot = object()
    expected = object()
    calls: list[tuple[str, object]] = []

    def resolve_transform(
        selected: Path,
        *,
        series_order: object = None,
    ) -> object:
        calls.append(("transform", (selected, series_order)))
        return snapshot

    def bind_source(
        selected: Path,
        *,
        rule: SemanticRule,
        request: dict[str, object],
        template: str,
        transform: object,
        source_sha256_before: str,
    ) -> object:
        calls.append(
            (
                "bind",
                (
                    selected,
                    rule.rule_id,
                    request,
                    template,
                    transform,
                    source_sha256_before,
                ),
            )
        )
        return expected

    monkeypatch.setattr(
        swelling_transform,
        "resolve_swelling_scientific_transform",
        resolve_transform,
    )
    monkeypatch.setattr(
        scientific_source_single_curve,
        "bind_single_curve_scientific_source",
        bind_source,
    )

    request = {"series_order": ["sample-b", "sample-a"]}
    resolved = scientific_source.resolve_scientific_source(
        source,
        rule_id="swelling_curve",
        request=request,
        template="point_line",
    )

    assert resolved is expected
    assert calls == [
        ("transform", (source.resolve(), request["series_order"])),
        (
            "bind",
            (
                source.resolve(),
                "swelling_curve",
                request,
                "point_line",
                snapshot,
                expected_source_sha256,
            ),
        ),
    ]


def test_swelling_adapter_keeps_shared_rule_scoped_error_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sciplot_core.figure_plan import source_binding
    from sciplot_core.semantic_sources import swelling_transform
    from sciplot_core.semantic_sources.scientific_source import (
        ScientificSourceResolutionError,
    )

    source = tmp_path / "swelling.xlsx"
    source.write_text("source", encoding="utf-8")
    monkeypatch.setattr(
        swelling_transform,
        "resolve_swelling_scientific_transform",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("ambiguous source")
        ),
    )

    with pytest.raises(ScientificSourceResolutionError) as transform_error:
        scientific_source.resolve_scientific_source(
            source,
            rule_id="swelling_curve",
            request={},
            template="point_line",
        )

    assert transform_error.value.reason_code == "swelling_curve_transform_invalid"

    snapshot = object()
    monkeypatch.setattr(
        swelling_transform,
        "resolve_swelling_scientific_transform",
        lambda *_args, **_kwargs: snapshot,
    )
    monkeypatch.setattr(source_binding, "source_tree_sha256", lambda _source: None)

    with pytest.raises(ScientificSourceResolutionError) as source_error:
        scientific_source.resolve_scientific_source(
            source,
            rule_id="swelling_curve",
            request={},
            template="point_line",
        )

    assert source_error.value.reason_code == "swelling_curve_source_unavailable"


def test_single_curve_snapshot_rejects_source_drift_between_parse_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sciplot_core.figure_plan import single_curve_resolution, source_binding
    from sciplot_core.semantic_sources import swelling_transform
    from sciplot_core.semantic_sources.scientific_source import (
        ScientificSourceResolutionError,
    )

    source = tmp_path / "swelling.xlsx"
    source.write_text("source", encoding="utf-8")
    hashes = iter(("before", "after"))
    hash_calls: list[Path] = []

    def changed_hash(selected: Path) -> str:
        hash_calls.append(selected)
        return next(hashes)

    monkeypatch.setattr(source_binding, "source_tree_sha256", changed_hash)
    monkeypatch.setattr(
        swelling_transform,
        "resolve_swelling_scientific_transform",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        single_curve_resolution,
        "resolve_registered_single_curve_plan",
        lambda **_kwargs: pytest.fail("drifted source reached FigurePlan binding"),
    )

    with pytest.raises(ScientificSourceResolutionError) as exc_info:
        scientific_source.resolve_scientific_source(
            source,
            rule_id="swelling_curve",
            request={},
            template="point_line",
        )

    assert exc_info.value.reason_code == (
        "swelling_curve_source_changed_during_resolution"
    )
    assert hash_calls == [source.resolve(), source.resolve()]
