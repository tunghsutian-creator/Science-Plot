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
    _impact_condition_figure_request,
    _impact_condition_figure_queue,
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
    assert rule.presentation_templates == ("bar", "box", "box_strip")
    assert [resolve_rule_template(rule, item) for item in rule.presentation_templates] == [
        "bar",
        "box",
        "box_strip",
    ]
    with pytest.raises(ValueError, match="not supported"):
        resolve_rule_template(rule, "curve")


def test_impact_rule_certificate_allows_supported_explicit_presentations() -> None:
    rule = get_rule("impact_metric")
    certificate = rule_contract_payload(rule)
    policy = certificate["render_request_policy"]

    assert policy["template_policy"] == "explicit_supported_template_or_default"
    assert policy["default_template"] == "box_strip"
    assert policy["supported_templates"] == ["bar", "box", "box_strip"]
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


@pytest.mark.parametrize("template", ["bar", "box", "box_strip"])
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


@pytest.mark.parametrize("template", ["bar", "box", "box_strip"])
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


def test_veusz_axis_label_closes_unit_superscript_before_parenthesis() -> None:
    assert _veusz_axis_label("Wavenumber (cm$^{-1}$)") == "Wavenumber (cm⁻¹)"
    assert _veusz_axis_label("Scattering vector (nm$^{-1}$)") == "Scattering vector (nm⁻¹)"
