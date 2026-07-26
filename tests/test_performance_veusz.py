from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core.performance_comparison import (
    build_performance_radar_payload,
    build_performance_scatter_payload,
    load_performance_comparison,
)
from sciplot_core.performance_veusz import build_performance_veusz_spec
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
        item["presentation_kind"].startswith("performance_")
        for item in spec["series"]
    )

    references = [
        item
        for item in spec["series"]
        if item["label"] in {"PA6", "ABS", "CFRP"}
    ]
    if template == "scatter":
        assert all(item["plot_line_hide"] is True for item in references)
    else:
        assert all(item["expected_mark_channels"] == ["marker"] for item in references)
        assert all(item["plot_line_hide"] is True for item in references)


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
    spec = json.loads(
        Path(result["veusz_specs"][0]).read_text(encoding="utf-8")
    )
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
    assert "Add('label', name='performance_legend_heading_sample'" in text


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
    assert json.loads(
        (manifest_path.parent / "transform_ledger.json").read_text(
            encoding="utf-8"
        )
    ) == ledger


def test_pending_performance_studio_review_requires_explicit_template(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="explicit rule plus template"):
        prepare_studio_document(
            FIXTURE,
            output_root=tmp_path / "projects",
            rule_id="performance_comparison",
        )
