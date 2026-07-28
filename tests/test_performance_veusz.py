from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from sciplot_core.performance_comparison import (
    build_performance_radar_payload,
    build_performance_scatter_payload,
    load_performance_comparison,
)
from sciplot_core.performance_veusz import build_performance_veusz_spec
from sciplot_core.policy import (
    PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
    PERFORMANCE_RADAR_GUIDE_COLOR,
    PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT,
    PERFORMANCE_RADAR_RING_TRANSPARENCY,
    PERFORMANCE_RADAR_SPOKE_TRANSPARENCY,
)
from sciplot_core.qa import _normalized_label
from sciplot_core.render import render_to_dir
from sciplot_core.studio import (
    export_studio_document,
    prepare_studio_document,
    publish_studio_export_run,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)
DENSE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_dense_16.csv"
)


def test_publication_label_normalization_unescapes_literal_square_brackets() -> None:
    assert _normalized_label(r"PA66 composites \[ref x\]") == (
        _normalized_label("PA66 composites [ref x]")
    )


@pytest.mark.parametrize(
    ("template", "payload_builder", "native_widget"),
    [
        ("scatter", build_performance_scatter_payload, "performance_envelope_1"),
        ("polar_curve", build_performance_radar_payload, "performance_radar_ring_1"),
    ],
)
def test_performance_spec_uses_native_editable_veusz_contract(
    template: str,
    payload_builder,
    native_widget: str,
) -> None:
    payload = payload_builder(load_performance_comparison(FIXTURE))
    spec = build_performance_veusz_spec(
        payload=payload,
        request={
            "input": str(FIXTURE),
            "rule_id": "performance_comparison",
            "template": template,
        },
        transform_steps=[],
    )

    assert spec["template"] == template
    assert spec["size_mm"] == [120.0, 55.0]
    assert spec["frame_alignment"]["plot_panel_size_mm"] == [60.0, 55.0]
    assert spec["frame_alignment"]["reference_panel_size_mm"] == [60.0, 55.0]
    assert spec["frame_alignment"]["plot_region_mm"] == [41.5, 38.5]
    assert spec["legend"]["mode"] == "reserved_reference_panel"
    assert spec["legend"]["outside_legend"] is False
    performance = spec["performance_comparison"]
    assert any(item["name"] == native_widget for item in performance["polygons"])
    assert all(item["parent"] in {"page", "graph"} for item in performance["polygons"])
    assert all(
        item["presentation_kind"].startswith("performance_") for item in spec["series"]
    )

    references = [
        item for item in spec["series"] if item["label"] in {"PA6", "ABS", "CFRP"}
    ]
    if template == "scatter":
        assert all(item["plot_line_hide"] is True for item in references)
    else:
        assert all(item["expected_mark_channels"] == ["marker"] for item in references)
        assert all(item["plot_line_hide"] is True for item in references)
        rings = [
            item
            for item in performance["polygons"]
            if item["role"] == "radar_grid_ring"
        ]
        assert len(rings) == 4
        assert all(item["line_style"] == "dashed" for item in rings)
        assert all(
            len(item["xPos"]) == len(payload["angles_degrees"]) + 1
            and len(item["yPos"]) == len(payload["angles_degrees"]) + 1
            and item["xPos"][0] == pytest.approx(item["xPos"][-1])
            and item["yPos"][0] == pytest.approx(item["yPos"][-1])
            for item in rings
        )
        assert all(
            item["line_color"] == PERFORMANCE_RADAR_GUIDE_COLOR
            and item["line_width_pt"] == PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT
            and item["line_transparency"] == PERFORMANCE_RADAR_RING_TRANSPARENCY
            for item in rings
        )
        assert all(
            item["line_color"] == PERFORMANCE_RADAR_GUIDE_COLOR
            and item["line_width_pt"] == PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT
            and item["line_transparency"] == PERFORMANCE_RADAR_SPOKE_TRANSPARENCY
            for item in performance["lines"]
        )
        labels = {
            int(str(item["name"]).rsplit("_", 1)[1]): item
            for item in performance["labels"]
            if str(item["name"]).startswith("performance_radar_axis_label_")
        }
        endpoint_labels = {
            int(str(item["name"]).rsplit("_", 1)[1]): item
            for item in performance["labels"]
            if str(item["name"]).startswith("performance_radar_axis_endpoint_label_")
        }
        assert all(
            item["text_size_pt"] == PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT
            for item in labels.values()
        )
        assert [
            endpoint_labels[index]["label"] for index in sorted(endpoint_labels)
        ] == payload["axis_endpoint_labels"]
        x_scale = float(payload["layout"]["plot_region_mm"][1]) / float(
            payload["layout"]["plot_region_mm"][0]
        )
        for index, angle in enumerate(payload["angles_degrees"], start=1):
            radians = math.radians(float(angle))
            cosine = math.cos(radians)
            sine = math.sin(radians)
            horizontal_radius = (
                1.06 if cosine > 0.25 else 0.78 if cosine < -0.25 else 1.0
            )
            assert labels[index]["x"] == pytest.approx(
                cosine * x_scale * horizontal_radius
            )
            assert labels[index]["y"] == pytest.approx(sine * 1.15)
            assert endpoint_labels[index]["x"] == pytest.approx(cosine * x_scale * 1.06)
            assert endpoint_labels[index]["y"] == pytest.approx(sine * 1.06)


def test_five_axis_radar_uses_aligned_physical_label_slots() -> None:
    payload = build_performance_radar_payload(load_performance_comparison(FIXTURE))
    payload["angles_degrees"] = [90.0, 162.0, 234.0, 306.0, 18.0]
    payload["axis_labels"] = [
        "Density\n(g cm⁻³)",
        "Specific tensile\ntoughness\n(kJ kg⁻¹)",
        "Specific tensile\nstrength\n(MPa cm³ g⁻¹)",
        "Specific flexural\nstrength\n(MPa cm³ g⁻¹)",
        "Specific impact\nstrength\n(kJ m⁻² cm³ g⁻¹)",
    ]
    payload["axis_endpoint_labels"] = ["0.5", "12", "60", "140", "120"]
    for item in payload["legend_items"]:
        if item["legend_group"] == "This work":
            item["legend_items_per_row"] = 2

    spec = build_performance_veusz_spec(
        payload=payload,
        request={
            "input": str(FIXTURE),
            "rule_id": "performance_comparison",
            "template": "polar_curve",
        },
        transform_steps=[],
    )
    labels = spec["performance_comparison"]["labels"]
    page_width, page_height = spec["size_mm"]
    expected_x_mm = [28.75, 9.0, 13.8, 46.2, 51.9]
    expected_line_centres_y_mm = [
        [1.6, 4.2],
        [10.8, 13.4, 16.0],
        [45.8, 48.4, 51.0],
        [45.8, 48.4, 51.0],
        [10.8, 13.4, 16.0],
    ]
    for axis_index, (x_mm, y_centres_mm) in enumerate(
        zip(
            expected_x_mm,
            expected_line_centres_y_mm,
            strict=True,
        ),
        start=1,
    ):
        axis_lines = [
            item
            for item in labels
            if str(item["name"]).startswith(
                f"performance_radar_axis_label_{axis_index}_line_"
            )
        ]
        assert len(axis_lines) == len(y_centres_mm)
        assert all(item["parent"] == "page" for item in axis_lines)
        assert all(item["align"] == "centre" for item in axis_lines)
        assert all(
            float(item["x"]) * page_width == pytest.approx(x_mm) for item in axis_lines
        )
        assert [
            (1.0 - float(item["y"])) * page_height for item in axis_lines
        ] == pytest.approx(y_centres_mm)

    endpoint_labels = [
        item
        for item in labels
        if str(item["name"]).startswith("performance_radar_axis_endpoint_label_")
    ]
    assert [item["label"] for item in endpoint_labels] == [
        "0.5",
        "12",
        "60",
        "140",
        "120",
    ]
    assert all(item["parent"] == "page" for item in endpoint_labels)
    assert all(item["align"] == "centre" for item in endpoint_labels)

    own_a = next(item for item in labels if item["name"] == "performance_legend_text_1")
    own_b = next(item for item in labels if item["name"] == "performance_legend_text_2")
    assert (float(own_b["x"]) - float(own_a["x"])) * page_width == (pytest.approx(22.0))


@pytest.mark.parametrize(
    ("template", "native_widget"),
    [
        ("scatter", "performance_envelope_1"),
        ("polar_curve", "performance_radar_sample_fill_1"),
    ],
)
def test_performance_direct_render_passes_exact_native_qa(
    tmp_path: Path,
    template: str,
    native_widget: str,
) -> None:
    result = render_to_dir(
        FIXTURE,
        template=template,
        output_dir=tmp_path / template,
        export_formats=("pdf",),
        request_context={"rule_id": "performance_comparison"},
    )
    spec = json.loads(Path(result["veusz_specs"][0]).read_text(encoding="utf-8"))
    document = Path(result["veusz_documents"][0])
    text = document.read_text(encoding="utf-8")

    assert result["qa_reports"][0]["issues"] == []
    assert Path(result["outputs"][0]).is_file()
    assert document.is_file()
    assert spec["frame_alignment"]["status"] == "locked"
    assert spec["frame_alignment"]["plot_region_mm"] == [41.5, 38.5]
    assert "performance_comparison_preparation" in {
        step["id"] for step in result["transform_steps"]
    }
    assert f"Add('polygon', name='{native_widget}'" in text
    assert "Add('xy', name='series_1'" in text
    assert "Add('label', name='performance_legend_heading_1_" in text
    assert "performance_legend_title" not in text


def test_dense_performance_direct_render_supports_sixteen_native_markers(
    tmp_path: Path,
) -> None:
    result = render_to_dir(
        DENSE_FIXTURE,
        template="scatter",
        output_dir=tmp_path / "dense_scatter",
        export_formats=("pdf",),
        request_context={"rule_id": "performance_comparison"},
    )
    spec = json.loads(Path(result["veusz_specs"][0]).read_text(encoding="utf-8"))
    markers = [item["marker"] for item in spec["series"]]

    assert result["qa_reports"][0]["issues"] == []
    assert Path(result["outputs"][0]).is_file()
    assert len(markers) == 16
    assert len(set(markers)) == 16
    assert (
        len(
            [
                item
                for item in spec["performance_comparison"]["labels"]
                if str(item["name"]).startswith("performance_legend_text_")
            ]
        )
        == 16
    )


def test_explicit_pending_performance_studio_review_preserves_lineage(
    tmp_path: Path,
) -> None:
    prepared = prepare_studio_document(
        FIXTURE,
        output_root=tmp_path / "projects",
        delivery_root=tmp_path / "delivery",
        rule_id="performance_comparison",
        template="scatter",
    )
    request_path = Path(prepared["request"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    document = Path(prepared["document"])
    exported = export_studio_document(
        document,
        formats=["pdf", "tiff_300"],
    )
    studio_run = publish_studio_export_run(
        project_dir=Path(prepared["project_dir"]),
        request_path=request_path,
        document_path=document,
        exports=exported["exports"],
        export_document_sha256=str(exported["document_sha256"]),
    )
    manifest_path = Path(studio_run["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert prepared["pending_rule_review"] is True
    assert prepared["autonomous_rule_ready"] is False
    assert request["pending_rule_review"] is True
    assert studio_run["ready_to_use"] is True
    assert studio_run["pending_rule_review"] is True
    assert studio_run["autonomous_rule_ready"] is False
    assert manifest["semantic"]["rule_id"] == "performance_comparison"
    assert manifest["semantic"]["rule_readiness"] == "pending"
    assert manifest["result"]["template"] == "scatter"
    assert manifest["publication_qa"]["status"] == "passed"
    assert manifest["qa"]["status"] == "passed"
    assert manifest["pending_rule_review"] is True
    assert manifest["autonomous_rule_ready"] is False
    ledger = manifest["transform_ledger"]
    by_id = {step["id"]: step for step in ledger["steps"]}
    assert "performance_comparison_preparation" in by_id
    preparation = by_id["performance_comparison_preparation"]
    assert preparation["parameters"]["template"] == "scatter"
    assert preparation["parameters"]["legend_panel_reserved"] is True
    assert preparation["parameters"]["plot_region_mm"] == [41.5, 38.5]
    assert preparation["parameters"]["scientific_values_modified"] is False
    assert (
        json.loads(
            (manifest_path.parent / "transform_ledger.json").read_text(encoding="utf-8")
        )
        == ledger
    )


def test_pending_performance_studio_review_requires_explicit_template(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="explicit rule plus template"):
        prepare_studio_document(
            FIXTURE,
            output_root=tmp_path / "projects",
            rule_id="performance_comparison",
        )
