from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from public_multitask_inputs import mechanical_source
import sciplot_core.workflow as workflow_facade
import sciplot_core.workflow.auto_split as auto_split
import sciplot_core.workflow.impact_bundle as impact_bundle
from sciplot_core.materials_rules import get_rule
from sciplot_core.policy import DEFAULT_EXPORT_FORMATS_POLICY
from sciplot_core.semantic_sources.scientific_source import (
    ResolvedScientificSource,
    resolve_scientific_source,
)


_BUNDLE_ATTRIBUTES = {
    "performance": "_render_veusz_performance_bundle",
    "impact": "_render_veusz_impact_bundle",
    "mechanical": "_render_veusz_mechanical_bundle",
    "dma_temperature": "_render_veusz_dma_temperature_bundle",
    "rheology": "_render_veusz_sweep_bundle",
}


def _install_render_spies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bundle_results: dict[str, dict[str, Any] | None] | None = None,
    mechanical_snapshot: ResolvedScientificSource | None = None,
) -> list[tuple[str, Path]]:
    calls: list[tuple[str, Path]] = []
    effective_results = (
        bundle_results
        if bundle_results is not None
        else {
            family: {"family": family, "qa_reports": []}
            for family in _BUNDLE_ATTRIBUTES
        }
    )

    for family, attribute in _BUNDLE_ATTRIBUTES.items():

        def fake_bundle(
            input_path: Path,
            *_args: object,
            _family: str = family,
            **_kwargs: object,
        ) -> dict[str, Any] | None:
            if _family == "mechanical":
                assert _kwargs["resolved_scientific_source"] is mechanical_snapshot
            calls.append((_family, input_path))
            return effective_results.get(_family)

        monkeypatch.setattr(auto_split, attribute, fake_bundle)

    def fake_generic(
        input_path: Path,
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, Any]:
        calls.append(("generic", input_path))
        return {"family": "generic", "qa_reports": []}

    monkeypatch.setattr(auto_split, "render_to_dir", fake_generic)
    return calls


def _mechanical_snapshot(tmp_path: Path) -> ResolvedScientificSource:
    source = mechanical_source(tmp_path / "mechanical", "tensile_curve")
    resolved = resolve_scientific_source(
        source, rule_id="tensile_curve", template="curve", request={},
    )
    assert resolved is not None and resolved.figure_plan is not None
    return resolved


@pytest.mark.parametrize(
    ("rule_id", "expected_family"),
    [
        ("performance_comparison", "performance"),
        ("impact_metric", "impact"),
        ("tensile_curve", "mechanical"),
        ("compression_curve", "mechanical"),
        ("flexural_curve", "mechanical"),
        ("dsc_curve", "generic"),
        ("rheology_frequency_sweep", "rheology"),
        ("rheology_temperature_sweep", "rheology"),
        ("ftir_spectrum", "generic"),
        ("rheology_stress_relaxation", "generic"),
        ("rheology_strain_sweep", "generic"),
        ("rheology_stress_sweep", "generic"),
        ("rheology_time_sweep", "generic"),
        ("dma_frequency_sweep", "generic"),
        ("dma_temperature_sweep", "dma_temperature"),
        ("rheology_creep", "generic"),
        ("dtg_curve", "generic"),
        ("uvvis_spectrum", "generic"),
        ("tga_curve", "generic"),
        ("torque_curve", "generic"),
        ("xrd_pattern", "generic"),
        ("saxs_profile", "generic"),
        ("gpc_sec_chromatogram", "generic"),
        ("swelling_curve", "generic"),
        (None, "generic"),
        ("", "generic"),
        ("   ", "generic"),
    ],
)
def test_rule_id_resolves_one_workflow_render_family(
    rule_id: object,
    expected_family: str,
) -> None:
    assert auto_split._resolve_workflow_render_family(rule_id) == expected_family


@pytest.mark.parametrize("rule_id", [True, 1, [], {}, " tensile_curve "])
def test_render_family_rejects_noncanonical_rule_id(rule_id: object) -> None:
    with pytest.raises(ValueError, match="Workflow render `rule_id`"):
        auto_split._resolve_workflow_render_family(rule_id)


def test_render_family_is_read_from_the_semantic_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = get_rule("tga_curve")
    monkeypatch.setattr(
        auto_split,
        "get_rule",
        lambda _rule_id: replace(base, render_adapter="performance"),
    )

    assert auto_split._resolve_workflow_render_family("tga_curve") == "performance"


@pytest.mark.parametrize(
    ("rule_id", "template", "expected_family", "uses_raw_source"),
    [
        ("performance_comparison", "scatter", "performance", True),
        ("impact_metric", "box_strip", "impact", True),
        ("tensile_curve", "curve", "mechanical", False),
        ("dsc_curve", "curve", "generic", False),
        ("dma_temperature_sweep", "point_line", "dma_temperature", False),
        ("rheology_frequency_sweep", "point_line", "rheology", False),
        ("tga_curve", "curve", "generic", False),
        (None, "curve", "generic", False),
    ],
)
def test_render_dispatch_calls_only_the_resolved_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: object,
    template: str,
    expected_family: str,
    uses_raw_source: bool,
) -> None:
    resolved = _mechanical_snapshot(tmp_path) if expected_family == "mechanical" else None
    calls = _install_render_spies(monkeypatch, mechanical_snapshot=resolved)
    prepared = tmp_path / "prepared.csv"
    raw = tmp_path / "raw.xlsx"

    result = auto_split._render_with_auto_split(
        prepared,
        source_input=raw,
        template=template,
        output_dir=tmp_path / "out",
        options={},
        export_formats=["pdf"],
        request={"rule_id": rule_id},
        _resolved_scientific_source=resolved,
        _resolved_figure_plan=resolved.figure_plan if resolved is not None else None,
    )

    assert result["family"] == expected_family
    assert calls == [
        (
            expected_family,
            raw if uses_raw_source else prepared,
        )
    ]
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("rule_id", "requested", "expected"),
    [
        ("tga_curve", None, DEFAULT_EXPORT_FORMATS_POLICY),
        ("tga_curve", [], DEFAULT_EXPORT_FORMATS_POLICY),
        ("tga_curve", "pdf", DEFAULT_EXPORT_FORMATS_POLICY),
        ("performance_comparison", None, DEFAULT_EXPORT_FORMATS_POLICY),
        ("performance_comparison", [], DEFAULT_EXPORT_FORMATS_POLICY),
        ("performance_comparison", "pdf", DEFAULT_EXPORT_FORMATS_POLICY),
        ("tga_curve", ["tiff", "pdf"], ("tiff_300", "pdf")),
        (
            "performance_comparison",
            ["png", "tif_300"],
            ("png_300", "tiff_300"),
        ),
    ],
)
def test_dispatch_normalizes_export_formats_once_before_selected_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: str,
    requested: object,
    expected: tuple[str, ...],
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def render_performance(
        *_args: object,
        export_formats: tuple[str, ...],
        **_kwargs: object,
    ) -> dict[str, Any]:
        calls.append(("performance", export_formats))
        return {"family": "performance"}

    def render_generic(
        *_args: object,
        export_formats: tuple[str, ...],
        **_kwargs: object,
    ) -> dict[str, Any]:
        calls.append(("generic", export_formats))
        return {"family": "generic"}

    monkeypatch.setattr(
        auto_split,
        "_render_veusz_performance_bundle",
        render_performance,
    )
    monkeypatch.setattr(auto_split, "render_to_dir", render_generic)

    result = auto_split._render_with_auto_split(
        tmp_path / "prepared.csv",
        template="curve",
        output_dir=tmp_path / "out",
        options={},
        export_formats=requested,
        request={"rule_id": rule_id},
    )

    expected_family = (
        "performance" if rule_id == "performance_comparison" else "generic"
    )
    assert result == {"family": expected_family}
    assert calls == [(expected_family, expected)]


@pytest.mark.parametrize(
    ("requested", "message"),
    [
        (["gif"], "Unsupported export format"),
        (["tiff", "tiff_300"], "same output artifact"),
    ],
)
@pytest.mark.parametrize("rule_id", ["tga_curve", "performance_comparison"])
def test_invalid_export_formats_fail_before_adapter_or_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: str,
    requested: list[str],
    message: str,
) -> None:
    calls = _install_render_spies(monkeypatch)

    with pytest.raises(ValueError, match=message):
        auto_split._render_with_auto_split(
            tmp_path / "prepared.csv",
            template="curve",
            output_dir=tmp_path / "out",
            options={},
            export_formats=requested,
            request={"rule_id": rule_id},
        )

    assert calls == []
    assert not (tmp_path / "out").exists()


def test_selected_bundle_can_fall_back_only_to_generic_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_render_spies(
        monkeypatch,
        bundle_results={family: None for family in _BUNDLE_ATTRIBUTES},
    )
    prepared = tmp_path / "prepared.csv"

    result = auto_split._render_with_auto_split(
        prepared,
        source_input=tmp_path / "raw.csv",
        template="curve",
        output_dir=tmp_path / "out",
        options={},
        export_formats=["pdf"],
        # An unplanned adapter may decline. A mechanical source always owns a
        # selected plan, whose refusal must not downgrade to generic rendering.
        request={"rule_id": "performance_comparison"},
    )

    assert result["family"] == "generic"
    assert calls == [
        ("performance", tmp_path / "raw.csv"),
        ("generic", prepared),
    ]
    assert not (tmp_path / "out").exists()


def test_mechanical_dispatch_requires_its_resolved_source_before_any_adapter(
    tmp_path, monkeypatch,
):
    calls = _install_render_spies(monkeypatch)
    with pytest.raises(ValueError, match="requires its resolved scientific source"):
        auto_split._render_with_auto_split(
            tmp_path / "prepared.csv", template="curve", output_dir=tmp_path / "out",
            options={}, export_formats=["pdf"], request={"rule_id": "tensile_curve"},
        )
    assert calls == []
    assert not (tmp_path / "out").exists()


def test_mechanical_selected_plan_cannot_fall_back_to_generic_renderer(
    tmp_path, monkeypatch,
):
    resolved = _mechanical_snapshot(tmp_path)
    calls = _install_render_spies(
        monkeypatch, mechanical_snapshot=resolved,
        bundle_results={family: None for family in _BUNDLE_ATTRIBUTES},
    )
    prepared = tmp_path / "prepared.csv"
    with pytest.raises(ValueError, match="workflow_planned_bundle_unavailable"):
        auto_split._render_with_auto_split(
            prepared, source_input=resolved.source, template="curve",
            output_dir=tmp_path / "out", options={}, export_formats=["pdf"],
            request={"rule_id": "tensile_curve"},
            _resolved_scientific_source=resolved, _resolved_figure_plan=resolved.figure_plan,
        )
    assert calls == [("mechanical", prepared)]
    assert not (tmp_path / "out").exists()


def test_unknown_rule_fails_before_any_bundle_or_renderer_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_render_spies(monkeypatch)

    with pytest.raises(ValueError, match="Unknown material rule"):
        auto_split._render_with_auto_split(
            tmp_path / "prepared.csv",
            template="curve",
            output_dir=tmp_path / "out",
            options={},
            export_formats=["pdf"],
            request={"rule_id": "not_a_registered_rule"},
        )

    assert calls == []
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("rule_id", [True, 1])
def test_malformed_rule_fails_before_any_bundle_or_renderer_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: object,
) -> None:
    calls = _install_render_spies(monkeypatch)

    with pytest.raises(ValueError, match="Workflow render `rule_id`"):
        auto_split._render_with_auto_split(
            tmp_path / "prepared.csv",
            template="curve",
            output_dir=tmp_path / "out",
            options={},
            export_formats=["pdf"],
            request={"rule_id": rule_id},
        )

    assert calls == []
    assert not (tmp_path / "out").exists()


def test_tensile_curve_does_not_enter_impact_template_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    resolved = _mechanical_snapshot(tmp_path)
    monkeypatch.setattr(
        auto_split,
        "_render_veusz_performance_bundle",
        lambda *_args, **_kwargs: calls.append("performance") or None,
    )
    monkeypatch.setattr(
        auto_split,
        "_render_veusz_mechanical_bundle",
        lambda *_args, **_kwargs: (
            calls.append("mechanical") or {"family": "mechanical"}
        ),
    )

    result = auto_split._render_with_auto_split(
        tmp_path / "prepared.csv",
        template="curve",
        output_dir=tmp_path / "out",
        options={},
        export_formats=["pdf"],
        request={
            "rule_id": "tensile_curve",
            "template": "curve",
        },
        _resolved_scientific_source=resolved,
        _resolved_figure_plan=resolved.figure_plan,
    )

    assert result == {"family": "mechanical"}
    assert calls == ["mechanical"]
    assert not (tmp_path / "out").exists()


def test_impact_bundle_checks_rule_before_resolving_impact_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        impact_bundle,
        "resolve_rule_template",
        lambda *_args, **_kwargs: pytest.fail(
            "foreign rule reached impact template resolution"
        ),
    )

    assert (
        impact_bundle._render_veusz_impact_bundle(
            tmp_path / "prepared.csv",
            output_dir=tmp_path / "out",
            options={},
            export_formats=["gif"],
            request={
                "rule_id": "tensile_curve",
                "template": "curve",
            },
        )
        is None
    )
    assert not (tmp_path / "out").exists()


def test_impact_facade_checks_persisted_plan_before_export_formats(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="ResolvedFigurePlan payload"):
        workflow_facade._render_veusz_impact_bundle(
            tmp_path / "prepared.csv",
            output_dir=tmp_path / "out",
            options={},
            export_formats=["gif"],
            request={
                "rule_id": "impact_metric",
                "template": "box_strip",
                "resolved_figure_plan": {},
            },
        )

    assert not (tmp_path / "out").exists()


@pytest.mark.comprehensive
@pytest.mark.parametrize(
    ("rule_id", "template", "source_text"),
    [
        (
            "tga_curve",
            "curve",
            (
                "Temperature,Mass\n"
                "°C,%\n"
                "Synthetic TGA,Synthetic TGA\n"
                "25,100\n"
                "100,98\n"
                "200,90\n"
            ),
        ),
        (
            "rheology_strain_sweep",
            "point_line",
            (
                "Strain,Storage Modulus\n"
                "%,Pa\n"
                "Synthetic sweep,Synthetic sweep\n"
                "0.1,1000\n"
                "1,900\n"
                "10,500\n"
            ),
        ),
    ],
)
def test_known_generic_rule_reaches_real_generic_renderer(
    tmp_path: Path,
    rule_id: str,
    template: str,
    source_text: str,
) -> None:
    source = tmp_path / f"{rule_id}.csv"
    source.write_text(source_text, encoding="utf-8")

    result = auto_split._render_with_auto_split(
        source,
        template=template,
        output_dir=tmp_path / "out",
        options={"size": "60x55"},
        export_formats=["pdf"],
        request={
            "rule_id": rule_id,
            "template": template,
        },
    )

    assert result["template"] == template
    assert all(Path(path).is_file() for path in result["outputs"])
    assert result["terminal_render_requests"][0]["rule_id"] == rule_id
