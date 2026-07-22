from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.policy import (
    UNIFIED_HARD_OPTION_KEYS,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_RIGHT_MARGIN_MM,
)
from sciplot_core.render import render_to_dir
from sciplot_recipes.contracts import get_recipe_spec
from sciplot_core.style_contract import (
    VEUSZ_IMPLEMENTED_TEMPLATE_IDS,
    VEUSZ_TEMPLATE_COLOR_OPTIONS,
    audit_style_template_contract,
    validate_veusz_template_id,
)
from sciplot_core.studio import _request_template
from sciplot_core.request_contract import (
    apply_request_patch,
    normalize_render_options,
)


def test_style_and_template_contract_audit_passes_current_registry() -> None:
    payload = audit_style_template_contract()

    assert payload["status"] == "passed"
    assert payload["issues"] == []
    assert set(payload["implemented_veusz_templates"]) == (
        VEUSZ_IMPLEMENTED_TEMPLATE_IDS
    )
    assert set(payload["template_color_options"]["heatmap"]) == (
        VEUSZ_TEMPLATE_COLOR_OPTIONS["heatmap"]
    )
    assert (
        VEUSZ_TEMPLATE_COLOR_OPTIONS["heatmap"] & UNIFIED_HARD_OPTION_KEYS
    ) == frozenset()


def test_contract_audit_reports_private_style_and_rule_template_drift() -> None:
    payload = audit_style_template_contract(
        ready_rule_templates=("curve", "bar"),
        render_defaults={"font_size_pt": 12.0},
    )

    assert payload["status"] == "failed"
    assert {issue["code"] for issue in payload["issues"]} >= {
        "render_default_style_drift",
        "ready_rule_uses_unimplemented_template",
    }


@pytest.mark.parametrize("template", sorted(VEUSZ_IMPLEMENTED_TEMPLATE_IDS))
def test_request_contract_accepts_only_implemented_veusz_templates(
    template: str,
) -> None:
    assert normalize_render_options({}, template=template) == {}


def test_request_contract_rejects_reference_only_vendor_template() -> None:
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        normalize_render_options({}, template="bar")


def test_heatmap_request_contract_accepts_the_runtime_scalar_contract() -> None:
    options = {
        "data_variables": {"x": "x", "y": "y", "z": "z"},
        "z_min": 1.0,
        "z_max": 4.0,
        "colormap_name": "sciplot_cividis",
        "colormap_colors": ["#00204C", "#FFEA46"],
        "color_invert": False,
        "contour_levels": [2.0, 3.0],
        "highlight_contour_levels": [2.5],
        "colorbar_foreground_color": "#223344",
        "colorbar_background_color": "#F7F7F7",
    }

    assert normalize_render_options(options, template="heatmap") == options


def test_request_template_is_validated_even_without_an_explicit_template_argument() -> None:
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        apply_request_patch({"template": "scatter"})


def test_direct_render_and_studio_generation_share_the_fail_closed_allowlist(
    tmp_path,
) -> None:
    assert validate_veusz_template_id("curve") == "curve"
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        _request_template({"template": "bar"})
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        render_to_dir(
            tmp_path / "unused.csv",
            template="bar",
            output_dir=tmp_path / "out",
        )


def test_recipe_ids_resolve_to_supported_templates() -> None:
    assert _request_template({"recipe": "tensile"}) == "curve"
    assert _request_template({"recipe": "metrics_swelling"}) == "box_strip"
    assert get_recipe_spec("metrics_swelling").default_template == "box_strip"


def test_named_profiles_use_the_global_horizontal_frame() -> None:
    payload = audit_style_template_contract()
    assert payload["hard_style_values"]["global_frame"]["left_margin_mm"] == (
        UNIFIED_LEFT_MARGIN_MM
    )
    assert payload["hard_style_values"]["global_frame"]["right_margin_mm"] == (
        UNIFIED_RIGHT_MARGIN_MM
    )


@pytest.mark.parametrize(
    ("template", "expected_widget"),
    [
        ("curve", "Add('xy'"),
        ("point_line", "Add('xy'"),
        ("stacked_curve", "Add('xy'"),
        ("box", "Add('boxplot'"),
        ("box_strip", "Add('boxplot'"),
        ("heatmap", "Add('image'"),
    ],
)
def test_each_production_template_materializes_its_declared_veusz_semantics(
    tmp_path,
    template: str,
    expected_widget: str,
) -> None:
    source = tmp_path / f"{template}.csv"
    options: dict[str, object] = {"size": "60x55"}
    if template == "heatmap":
        pd.DataFrame(
            {
                "x": [0.0, 1.0, 0.0, 1.0],
                "y": [0.0, 0.0, 1.0, 1.0],
                "z": [1.0, 2.0, 2.0, 3.0],
            }
        ).to_csv(source, index=False)
        options.update(
            {
                "data_variables": {"x": "x", "y": "y", "z": "z"},
                "z_min": 1.0,
                "z_max": 3.0,
            }
        )
    elif template in {"box", "box_strip"}:
        pd.DataFrame(
            {
                "Sample": ["A", "A", "A", "B", "B", "B"],
                "Impact strength": [10.0, 11.0, 12.0, 20.0, 21.0, 22.0],
            }
        ).to_csv(source, index=False)
        options["summary_statistic"] = "median_iqr"
    else:
        pd.DataFrame(
            {
                "x": [0.0, 1.0, 2.0],
                "sample_a": [1.0, 2.0, 3.0],
                "sample_b": [1.5, 2.5, 3.5],
            }
        ).to_csv(source, index=False)

    result = render_to_dir(
        source,
        template=template,
        output_dir=tmp_path / f"rendered_{template}",
        options=options,
        export_formats=("pdf",),
    )
    document = Path(result["veusz_documents"][0])
    spec = json.loads(
        Path(result["veusz_specs"][0]).read_text(encoding="utf-8")
    )

    assert spec["template"] == template
    assert expected_widget in document.read_text(encoding="utf-8")
