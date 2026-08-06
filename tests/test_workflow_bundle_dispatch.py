from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sciplot_core.workflow.auto_split as auto_split
import sciplot_core.workflow.impact_bundle as impact_bundle


_BUNDLE_ATTRIBUTES = {
    "performance": "_render_veusz_performance_bundle",
    "impact": "_render_veusz_impact_bundle",
    "mechanical": "_render_veusz_mechanical_bundle",
    "dsc": "_render_veusz_dsc_bundle",
    "rheology": "_render_veusz_sweep_bundle",
}


def _install_render_spies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bundle_results: dict[str, dict[str, Any] | None] | None = None,
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


@pytest.mark.parametrize(
    ("rule_id", "expected_family"),
    [
        ("performance_comparison", "performance"),
        ("impact_metric", "impact"),
        ("tensile_curve", "mechanical"),
        ("compression_curve", "mechanical"),
        ("flexural_curve", "mechanical"),
        ("dsc_curve", "dsc"),
        ("rheology_frequency_sweep", "rheology"),
        ("rheology_temperature_sweep", "rheology"),
        ("ftir_spectrum", "generic"),
        ("rheology_stress_relaxation", "generic"),
        ("rheology_strain_sweep", "generic"),
        ("rheology_stress_sweep", "generic"),
        ("rheology_time_sweep", "generic"),
        ("dma_frequency_sweep", "generic"),
        ("dma_temperature_sweep", "generic"),
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


@pytest.mark.parametrize(
    ("rule_id", "template", "expected_family", "uses_raw_source"),
    [
        ("performance_comparison", "scatter", "performance", True),
        ("impact_metric", "box_strip", "impact", True),
        ("tensile_curve", "curve", "mechanical", False),
        ("dsc_curve", "curve", "dsc", False),
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
    calls = _install_render_spies(monkeypatch)
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
    )

    assert result["family"] == expected_family
    assert calls == [
        (
            expected_family,
            raw if uses_raw_source else prepared,
        )
    ]
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
        request={"rule_id": "tensile_curve"},
    )

    assert result["family"] == "generic"
    assert calls == [
        ("mechanical", prepared),
        ("generic", prepared),
    ]
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
            export_formats=["pdf"],
            request={
                "rule_id": "tensile_curve",
                "template": "curve",
            },
        )
        is None
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
