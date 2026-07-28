import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.materials_rules import get_rule, resolve_rule_template
from sciplot_core.readiness import (
    render_request_contract_payload,
    rule_contract_payload,
)
from sciplot_core.semantic import read_impact_condition_payloads
from sciplot_core.studio import (
    IMPACT_POINT_LINE_MARKER_KIND,
    IMPACT_POINT_LINE_RAW_KIND,
    IMPACT_POINT_LINE_SUMMARY_KIND,
    _apply_domain_render_defaults,
    _categorical_plot_contract,
    _impact_condition_figure_request,
    _impact_condition_figure_queue,
    _impact_point_line_series_from_source,
    _read_studio_figure_set,
    _veusz_axis_label,
)
from sciplot_core import workflow
from sciplot_core.workflow import (
    _impact_condition_sources,
    _render_veusz_impact_bundle,
)


def test_impact_workbook_sheets_are_independent_figure_conditions(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "impact.xlsx"
    with pd.ExcelWriter(source) as writer:
        for thickness, samples in (
            ("2mm", ("E0", "E2")),
            ("4mm", ("E0", "E2")),
            ("6mm", ("E3", "E4")),
        ):
            pd.DataFrame(
                [
                    ["Re", "Re"],
                    ["kJ/m²", "kJ/m²"],
                    list(samples),
                    [1.0, 2.0],
                    [1.5, 2.5],
                ]
            ).to_excel(writer, sheet_name=thickness, header=False, index=False)

    payloads = read_impact_condition_payloads(source)
    queue = _impact_condition_figure_queue(
        {"rule_id": "impact_metric", "input": str(source_dir)},
        base_dir=tmp_path,
        project_dir=tmp_path / "project",
    )
    autoplot_sources = _impact_condition_sources(
        source_dir,
        request={"rule_id": "impact_metric"},
        output_dir=tmp_path / "autoplot",
    )

    assert [condition for condition, _payload in payloads] == ["2mm", "4mm", "6mm"]
    assert [item["id"] for item in queue] == ["impact_2mm", "impact_4mm", "impact_6mm"]
    assert [item["sample_order"] for item in queue] == [
        ["E0", "E2"],
        ["E0", "E2"],
        ["E3", "E4"],
    ]
    assert all(Path(item["condition_source"]).is_file() for item in queue)
    assert [item[0] for item in autoplot_sources] == [
        "impact_2mm",
        "impact_4mm",
        "impact_6mm",
    ]
    assert all(item[1].is_file() for item in autoplot_sources)


def test_impact_semantics_expose_an_independent_presentation_contract() -> None:
    rule = get_rule("impact_metric")

    assert rule.presentation_data_shape == "categorical_replicates"
    assert rule.template == "box_strip"
    assert rule.presentation_templates == ("bar", "box", "box_strip", "point_line")
    assert [
        resolve_rule_template(rule, item) for item in rule.presentation_templates
    ] == [
        "bar",
        "box",
        "box_strip",
        "point_line",
    ]
    with pytest.raises(ValueError, match="not supported"):
        resolve_rule_template(rule, "curve")


def test_impact_rule_certificate_allows_supported_explicit_presentations() -> None:
    rule = get_rule("impact_metric")
    certificate = rule_contract_payload(rule)
    policy = certificate["render_request_policy"]

    assert policy["template_policy"] == "explicit_supported_template_or_default"
    assert policy["default_template"] == "box_strip"
    assert policy["supported_templates"] == [
        "bar",
        "box",
        "box_strip",
        "point_line",
    ]
    assert (
        render_request_contract_payload(
            rule,
            {"recipe": "auto", "template": "bar"},
        )["effective_template"]
        == "bar"
    )
    with pytest.raises(ValueError, match="not supported"):
        render_request_contract_payload(
            rule,
            {"recipe": "auto", "template": "curve"},
        )


@pytest.mark.parametrize("template", ["bar", "box", "box_strip", "point_line"])
def test_impact_figure_request_preserves_supported_presentation_choice(
    template: str,
) -> None:
    figure = {
        "condition_source": "/tmp/impact.csv",
        "default_template": "box_strip",
        "sample_order": ["E0", "E2", "E3", "E4"],
    }

    request = _impact_condition_figure_request(
        {"rule_id": "impact_metric", "template": template},
        figure,
    )

    assert request["template"] == template
    assert request["series_order"] == ["E0", "E2", "E3", "E4"]


@pytest.mark.parametrize("template", ["bar", "box", "box_strip", "point_line"])
def test_impact_bundle_renders_the_same_semantic_source_with_selected_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
) -> None:
    metric_source = tmp_path / "impact_2mm.csv"
    metric_source.write_text("sample,E0,E2\nvalue,1,2\n", encoding="utf-8")
    rendered_templates: list[str] = []

    monkeypatch.setattr(
        workflow,
        "_impact_condition_sources",
        lambda *_args, **_kwargs: [
            ("impact_2mm", metric_source, {"series_order": ["E0", "E2"]})
        ],
    )

    def fake_render_to_dir(
        _source: Path,
        *,
        template: str,
        output_dir: Path,
        **_kwargs: object,
    ) -> dict[str, object]:
        rendered_templates.append(template)
        output_dir.mkdir(parents=True, exist_ok=True)
        return {
            "template": template,
            "outputs": [],
            "exports": [],
            "qa_reports": [],
            "veusz_documents": [],
            "veusz_specs": [],
            "terminal_render_requests": [],
        }

    monkeypatch.setattr(workflow, "render_to_dir", fake_render_to_dir)

    result = _render_veusz_impact_bundle(
        tmp_path,
        output_dir=tmp_path / "out",
        options={},
        export_formats=["pdf", "tiff_300"],
        request={"rule_id": "impact_metric", "template": template},
    )

    assert result is not None
    assert result["template"] == template
    assert rendered_templates == [template]


def test_impact_point_line_compares_compatible_conditions_and_preserves_raw_points(
    tmp_path: Path,
) -> None:
    source = tmp_path / "impact.xlsx"
    with pd.ExcelWriter(source) as writer:
        for thickness, samples in (
            ("2mm", ("E0", "E2", "E3", "E4")),
            ("4mm", ("E0", "E2", "E3", "E4")),
            ("6mm", ("E3", "E4")),
        ):
            rows: list[list[object]] = [
                ["Re"] * len(samples),
                ["kJ/m²"] * len(samples),
                list(samples),
            ]
            rows.extend(
                [
                    [10.0 + row + column for column in range(len(samples))]
                    for row in range(5)
                ]
            )
            pd.DataFrame(rows).to_excel(
                writer,
                sheet_name=thickness,
                header=False,
                index=False,
            )

    request = {
        "rule_id": "impact_metric",
        "template": "point_line",
        "condition_label_mapping": {
            "2mm": "33% weight reduction",
            "4mm": "50% weight reduction",
        },
    }
    series, axis_info, steps = _impact_point_line_series_from_source(
        source,
        request=request,
    )
    summaries = [
        item
        for item in series
        if item.presentation_kind == IMPACT_POINT_LINE_SUMMARY_KIND
    ]
    markers = [
        item
        for item in series
        if item.presentation_kind == IMPACT_POINT_LINE_MARKER_KIND
    ]
    raw = [
        item for item in series if item.presentation_kind == IMPACT_POINT_LINE_RAW_KIND
    ]

    assert [item.label for item in summaries] == [
        "33% weight reduction",
        "50% weight reduction",
    ]
    assert [item.color for item in summaries] == ["#222222", "#3568C0"]
    assert summaries[0].error_values == pytest.approx((10.0**0.5 / 2.0,) * 4)
    assert summaries[0].x_values == pytest.approx((0.95, 1.95, 2.95, 3.95))
    assert summaries[1].x_values == pytest.approx((1.05, 2.05, 3.05, 4.05))
    assert axis_info["category_labels"] == ["E0", "E2", "E3", "E4"]
    assert axis_info["condition_labels"] == [
        "33% weight reduction",
        "50% weight reduction",
    ]
    assert len(markers) == 8
    assert [item.marker for item in markers[:4]] == [
        "circle",
        "square",
        "diamond",
        "triangle",
    ]
    assert markers[0].x_values == pytest.approx((0.95,))
    assert markers[4].x_values == pytest.approx((1.05,))
    assert all(item.marker_line_color == "#FFFFFF" for item in markers)
    assert all(item.marker_line_width == pytest.approx(0.70) for item in markers)
    assert sum(len(item.y_values) for item in raw) == 40
    assert raw[0].category_position == pytest.approx(0.95)
    assert raw[4].category_position == pytest.approx(1.05)
    assert all(item.marker_size == pytest.approx(1.75) for item in raw)
    assert all(item.marker_alpha == pytest.approx(0.50) for item in raw)
    assert all(
        min(item.x_values) < float(item.category_position) < max(item.x_values)
        for item in raw
    )
    assert all(
        sum(x_value < float(item.category_position) for x_value in item.x_values) == 2
        for item in raw
    )
    categorical = _categorical_plot_contract(
        series,
        template_id="point_line",
        render_options={},
    )
    assert categorical is not None
    assert categorical["error_bar_statistic"] == "sample_sd"
    assert len(categorical["error_bars"]) == 8
    assert categorical["condition_offsets"] == pytest.approx([-0.05, 0.05])
    assert categorical["visual_style"]["raw_point_condition_offset"] is True
    assert categorical["visual_style"]["raw_point_alpha"] == pytest.approx(0.50)
    assert categorical["visual_style"]["raw_marker_scale"] == pytest.approx(0.875)
    render_options = _apply_domain_render_defaults(
        {},
        request=request,
        axis_info=axis_info,
    )
    assert render_options["size"] == "60x55"
    assert steps[0]["parameters"]["selected_conditions"] == ["2mm", "4mm"]
    assert steps[0]["parameters"]["raw_values_preserved"] is True
    assert steps[0]["parameters"]["error_bar_statistic"] == "sample_sd_n_minus_1"
    assert steps[0]["parameters"]["condition_offsets"] == pytest.approx([-0.05, 0.05])


def test_impact_point_line_uses_one_combined_document(tmp_path: Path) -> None:
    assert (
        _impact_condition_figure_queue(
            {
                "rule_id": "impact_metric",
                "template": "point_line",
                "input": str(tmp_path / "impact.xlsx"),
            },
            base_dir=tmp_path,
            project_dir=tmp_path / "project",
        )
        == []
    )


@pytest.mark.comprehensive
def test_impact_point_line_terminal_render_keeps_semantic_overlay_context(
    tmp_path: Path,
) -> None:
    source = tmp_path / "impact.xlsx"
    with pd.ExcelWriter(source) as writer:
        for thickness, offset in (("2mm", 0.0), ("4mm", 10.0)):
            rows: list[list[object]] = [
                ["Re"] * 4,
                ["kJ/m²"] * 4,
                ["E0", "E2", "E3", "E4"],
            ]
            rows.extend(
                [[offset + row + column for column in range(4)] for row in range(5)]
            )
            pd.DataFrame(rows).to_excel(
                writer,
                sheet_name=thickness,
                header=False,
                index=False,
            )

    result = _render_veusz_impact_bundle(
        source,
        output_dir=tmp_path / "out",
        options={"size": "60x55"},
        export_formats=["pdf"],
        request={
            "rule_id": "impact_metric",
            "template": "point_line",
            "condition_order": ["4mm", "2mm"],
            "condition_label_mapping": {
                "4mm": "4 mm specimen",
                "2mm": "2 mm specimen",
            },
        },
    )

    assert result is not None
    assert result["terminal_render_requests"] == [
        {
            "template": "point_line",
            "render_options": {"size": "60x55"},
            "rule_id": "impact_metric",
            "explicit_render_option_keys": [],
            "condition_order": ["4mm", "2mm"],
            "condition_label_mapping": {
                "4mm": "4 mm specimen",
                "2mm": "2 mm specimen",
            },
        }
    ]
    spec = json.loads(Path(result["veusz_specs"][0]).read_text(encoding="utf-8"))
    categorical = spec["categorical"]
    assert categorical["presentation_kind"] == "point_line_raw_overlay"
    assert categorical["condition_labels"] == [
        "4 mm specimen",
        "2 mm specimen",
    ]
    assert categorical["raw_replicate_count"] == 40
    assert len(categorical["error_bars"]) == 8
    assert categorical["condition_offsets"] == pytest.approx([-0.05, 0.05])
    raw_specs = [
        item
        for item in spec["series"]
        if item["presentation_kind"] == IMPACT_POINT_LINE_RAW_KIND
    ]
    mean_specs = [
        item
        for item in spec["series"]
        if item["presentation_kind"] == IMPACT_POINT_LINE_MARKER_KIND
    ]
    assert all(item["marker_size_pt"] == pytest.approx(1.75) for item in raw_specs)
    assert all(item["marker_alpha"] == pytest.approx(0.50) for item in raw_specs)
    assert all(item["marker_line_color"] == "#FFFFFF" for item in mean_specs)
    assert all(
        item["marker_line_width_pt"] == pytest.approx(0.70) for item in mean_specs
    )
    assert spec["layout_issues"] == []
    assert [step["id"] for step in result["transform_steps"]] == [
        "impact_condition_point_line_overlay"
    ]
    assert result["transform_steps"][0]["parameters"]["selected_conditions"] == [
        "4mm",
        "2mm",
    ]


@pytest.mark.comprehensive
def test_impact_point_line_autoplot_ledger_includes_terminal_selection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "impact.xlsx"
    with pd.ExcelWriter(source) as writer:
        for thickness, samples, offset in (
            ("2mm", ("E0", "E2", "E3", "E4"), 0.0),
            ("4mm", ("E0", "E2", "E3", "E4"), 10.0),
            ("6mm", ("E3", "E4"), 20.0),
        ):
            rows: list[list[object]] = [
                ["Re"] * len(samples),
                ["kJ/m²"] * len(samples),
                list(samples),
            ]
            rows.extend(
                [
                    [offset + row + column for column in range(len(samples))]
                    for row in range(5)
                ]
            )
            pd.DataFrame(rows).to_excel(
                writer,
                sheet_name=thickness,
                header=False,
                index=False,
            )
    output_dir = tmp_path / "run"
    request_path = tmp_path / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "rule_id": "impact_metric",
                "template": "point_line",
                "input": str(source),
                "output": str(output_dir),
                "exports": ["pdf", "tiff_300"],
                "condition_order": ["4mm", "2mm"],
                "condition_label_mapping": {
                    "4mm": "4 mm specimen",
                    "2mm": "2 mm specimen",
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = workflow.run_request(request_path)

    ledger = manifest["transform_ledger"]
    by_id = {step["id"]: step for step in ledger["steps"]}
    assert set(by_id) == {
        "semantic_preparation",
        "impact_condition_point_line_overlay",
    }
    terminal = by_id["impact_condition_point_line_overlay"]
    assert terminal["parameters"]["selected_conditions"] == ["4mm", "2mm"]
    assert terminal["parameters"]["raw_replicate_count"] == 40
    assert terminal["parameters"]["condition_selection_policy"] == (
        "explicit_condition_order"
    )
    assert (
        json.loads((output_dir / "transform_ledger.json").read_text(encoding="utf-8"))
        == ledger
    )


def test_impact_point_line_ignores_stale_default_figure_set(
    tmp_path: Path,
) -> None:
    (tmp_path / "studio").mkdir()
    (tmp_path / "plot_request.json").write_text(
        '{"rule_id":"impact_metric","template":"point_line"}',
        encoding="utf-8",
    )
    (tmp_path / "studio" / "figure_set.json").write_text(
        '{"kind":"sciplot_studio_figure_set","primary_figure_id":"impact_2mm",'
        '"figures":[{"figure_id":"impact_2mm"}]}',
        encoding="utf-8",
    )

    assert _read_studio_figure_set(tmp_path) is None


def test_veusz_axis_label_closes_unit_superscript_before_parenthesis() -> None:
    assert _veusz_axis_label("Wavenumber (cm$^{-1}$)") == "Wavenumber (cm⁻¹)"
    assert (
        _veusz_axis_label("Scattering vector (nm$^{-1}$)") == "Scattering vector (nm⁻¹)"
    )
