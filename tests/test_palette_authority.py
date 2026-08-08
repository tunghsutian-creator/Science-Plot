from __future__ import annotations

import pytest

from sciplot_core.contract import load_plot_contract
from sciplot_core.doctor import doctor_payload
from sciplot_core.policy import (
    CONTROL_FIRST_BRIGHT_COLORS,
    DEFAULT_PALETTE_PRESET,
    resolve_palette_authority,
)
from sciplot_core.publication import build_publication_intent
from sciplot_core.studio_render.models import StudioSeries
from sciplot_core.studio_render.series_domain import (
    _resolved_domain_render_options,
)
from sciplot_core.style_contract import audit_style_template_contract


def _series() -> list[StudioSeries]:
    return [
        StudioSeries(
            label="control",
            x_name="x",
            y_name="y",
            x_values=(0.0, 1.0),
            y_values=(1.0, 2.0),
            color="#FFFFFF",
        )
    ]


def test_serialized_and_python_palette_defaults_are_one_contract() -> None:
    contract = load_plot_contract()

    assert contract.version == 4
    assert contract.defaults.palette_preset == DEFAULT_PALETTE_PRESET
    assert contract.palettes[DEFAULT_PALETTE_PRESET].categorical == (
        CONTROL_FIRST_BRIGHT_COLORS
    )
    assert all(
        template.default_options["palette_preset"] == DEFAULT_PALETTE_PRESET
        and DEFAULT_PALETTE_PRESET in template.available_palettes
        for template in contract.templates.values()
    )
    assert all(
        style.recommended_palette_preset == DEFAULT_PALETTE_PRESET
        for style in contract.styles.values()
    )
    audit = audit_style_template_contract()
    assert audit["status"] == "passed"
    assert audit["ordinary_palette_contract"]["palette_id"] == (DEFAULT_PALETTE_PRESET)


def test_palette_authority_distinguishes_explicit_direct_and_inherited() -> None:
    inherited = resolve_palette_authority(
        {
            "template": "point_line",
            "render_options": {"palette_preset": "jama_editorial"},
            "explicit_render_option_keys": [],
        },
        template_id="point_line",
    )
    explicit = resolve_palette_authority(
        {
            "template": "point_line",
            "render_options": {"palette_preset": "jama_editorial"},
            "explicit_render_option_keys": ["palette_preset"],
        },
        template_id="point_line",
    )
    direct = resolve_palette_authority(
        {
            "template": "point_line",
            "render_options": {"palette_preset": "jama_editorial"},
        },
        template_id="point_line",
    )

    assert inherited.palette_id == DEFAULT_PALETTE_PRESET
    assert inherited.source == "shared_project_default"
    assert inherited.ignored_non_authoritative_palette_id == "jama_editorial"
    assert explicit.palette_id == "jama_editorial"
    assert explicit.source == "explicit_render_option"
    assert direct.palette_id == "jama_editorial"
    assert direct.source == "direct_render_option"


def test_custom_colors_have_an_explicit_audit_source() -> None:
    inherited_name_with_explicit_colors = resolve_palette_authority(
        {
            "render_options": {
                "palette_preset": "jama_editorial",
                "palette_colors": ["#101010", "#202020"],
            },
            "explicit_render_option_keys": ["palette_colors"],
        }
    )
    direct = resolve_palette_authority(
        {"render_options": {"palette_colors": ["#101010", "#202020"]}}
    )

    assert inherited_name_with_explicit_colors.palette_id == DEFAULT_PALETTE_PRESET
    assert inherited_name_with_explicit_colors.colors == ("#101010", "#202020")
    assert inherited_name_with_explicit_colors.source == "explicit_render_option"
    assert inherited_name_with_explicit_colors.explicit is True
    assert (
        inherited_name_with_explicit_colors.ignored_non_authoritative_palette_id
        == "jama_editorial"
    )
    assert direct.source == "direct_render_option"
    assert direct.custom_colors is True


def test_missing_point_line_palette_cannot_reactivate_template_history() -> None:
    resolved = _resolved_domain_render_options(
        {
            "template": "point_line",
            "render_options": {"size": "60x55"},
        },
        axis_info={"x_label": "x", "y_label": "y"},
        series=_series(),
    )

    assert resolved["palette_preset"] == DEFAULT_PALETTE_PRESET


def test_publication_intent_records_the_same_palette_resolution() -> None:
    inherited = build_publication_intent(
        {},
        request={
            "template": "point_line",
            "render_options": {"palette_preset": "jama_editorial"},
            "explicit_render_option_keys": [],
        },
    )
    explicit = build_publication_intent(
        {},
        request={
            "template": "point_line",
            "render_options": {"palette_preset": "jama_editorial"},
            "explicit_render_option_keys": ["palette_preset"],
        },
    )

    inherited_policy = inherited["palette_policy"]
    explicit_policy = explicit["palette_policy"]
    assert inherited_policy["palette_id"] == DEFAULT_PALETTE_PRESET
    assert inherited_policy["resolution"]["source"] == "shared_project_default"
    assert explicit_policy["palette_id"] == "jama_editorial"
    assert explicit_policy["resolution"]["source"] == "explicit_render_option"


def test_unknown_explicit_palette_fails_before_rendering() -> None:
    with pytest.raises(ValueError, match="Unknown palette_preset"):
        resolve_palette_authority(
            {"render_options": {"palette_preset": "not_a_palette"}}
        )


def test_doctor_exposes_machine_readable_palette_authority() -> None:
    payload = doctor_payload()
    palette = payload["style_template_contract"]["ordinary_palette_contract"]

    # Overall readiness also depends on acceptance-registry freshness; this test
    # owns only the independently audited, machine-readable palette contract.
    assert payload["style_template_contract"]["status"] == "passed"
    assert palette["palette_id"] == DEFAULT_PALETTE_PRESET
    assert palette["colors"] == list(CONTROL_FIRST_BRIGHT_COLORS)
    assert palette["authority_order"] == [
        "explicit_render_option",
        "direct_render_option",
        "shared_project_default",
    ]
