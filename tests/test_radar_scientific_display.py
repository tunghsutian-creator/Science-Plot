"""Radar interpretation is presentation; declared science remains exact."""

from copy import deepcopy
import json
from pathlib import Path
import unicodedata
import subprocess
import sys

import pandas as pd
import pymupdf
import pytest

from sciplot_core.performance_comparison import (
    PerformanceComparisonError, build_performance_radar_payload,
    load_performance_comparison,
)
from sciplot_core.performance_veusz import build_performance_veusz_spec
from sciplot_core.qa.fixed_frame import _fixed_frame_report
from sciplot_core.source_coverage.spec_units import (
    _spec_render_data_units, render_data_unit_signature,
)

FIXTURE = Path(__file__).parent / "fixtures/performance_comparison/material_performance_long.csv"


def _payload(tmp_path: Path, frame: pd.DataFrame | None = None):
    frame = pd.read_csv(FIXTURE) if frame is None else frame
    source = tmp_path / "performance.csv"
    frame.to_csv(source, index=False)
    return build_performance_radar_payload(load_performance_comparison(source))


def _spec(payload, **request):
    return build_performance_veusz_spec(payload=payload, request=request)


def test_radar_notes_explain_dimensionless_radius_raw_units_and_both_formulas(tmp_path):
    payload = _payload(tmp_path)
    notes = payload["radar_display"]["notes"]
    assert notes == [
        "Radius r: 0–1 (dimensionless)",
        "↑: r = (v − min) / (max − min)",
        "↓: r = (max − v) / (max − min)",
        "Axis ranges: raw min–max; outward is better",
        "↑ higher / ↓ lower raw value is better",
        "Endpoints: raw values in axis units",
        "Polygon area is not an overall score",
    ]
    assert payload["axis_endpoint_labels"] == ["0.8", "120", "180", "120"]
    assert payload["axis_labels"][0] == "Density\n(g cm⁻³; 0.8–1.6) ↓"
    assert payload["axis_labels"][1].endswith("(kJ m⁻²; 0–120) ↑")
    spec = _spec(payload)
    assert [item["label"] for item in spec["performance_comparison"]["labels"]
            if item["name"].startswith("performance_radar_note_")] == notes


def test_missing_original_unit_is_not_invented_as_dimensionless(tmp_path):
    frame = pd.read_csv(FIXTURE)
    frame.loc[frame["Metric"] == "tensile_strength", "Unit"] = ""
    with pytest.raises(PerformanceComparisonError) as error:
        _payload(tmp_path, frame)
    assert error.value.reason_code == "performance_required_value_missing"


def test_radar_negative_cost_constant_observations_and_incomplete_reference_are_retained(tmp_path):
    frame = pd.read_csv(FIXTURE)
    density = frame["Metric"] == "density"
    frame.loc[density, ["ScaleMin", "ScaleMax", "Value"]] = [-10, 10, -5]
    # All observations being equal never becomes a new data-derived scale.
    frame = frame.loc[~((frame["Material"] == "PA6") & ~density)].copy()
    payload = _payload(tmp_path, frame)
    assert payload["angles_degrees"] == [90, 180, 270, 0]
    for series in payload["series"]:
        assert series["raw_values"][0] == -5
        assert series["radii"][0] == 0.75  # lower is better on declared [-10, 10]
    reference = next(item for item in payload["series"] if item["label"] == "PA6")
    assert reference["metric_ids"] == ["density"]
    assert reference["angles_degrees"] == [90]
    assert reference["filled_polygon"] is False
    assert payload["axis_endpoint_labels"][0] == "-10"
    assert payload["axis_labels"][0].endswith("(g cm⁻³; -10–10) ↓")


@pytest.mark.parametrize("bounds,value,reason", [
    ((-10, 10), -11, "performance_radar_value_outside_scale"),
    ((-5, -5), -5, "performance_radar_scale_invalid"),
])
def test_display_does_not_relax_outside_or_zero_width_declared_scale(tmp_path, bounds, value, reason):
    frame = pd.read_csv(FIXTURE)
    frame.loc[frame["Metric"] == "density", ["ScaleMin", "ScaleMax", "Value"]] = [*bounds, value]
    with pytest.raises(PerformanceComparisonError) as error:
        _payload(tmp_path, frame)
    assert error.value.reason_code == reason


def test_long_mixed_language_labels_keep_every_character_and_6pt_size(tmp_path):
    frame = pd.read_csv(FIXTURE)
    frame.loc[frame["Metric"] == "specific_impact_strength", "DisplayLabel"] = (
        "低温抗冲击能力 / Specific impact strength"
    )
    payload = _payload(tmp_path, frame)
    spec = _spec(payload)
    labels = [item for item in spec["performance_comparison"]["labels"]
              if item["name"].startswith("performance_radar_axis_label_2_line_")]
    assert len(labels) > 2
    assert "".join(item["label"] for item in labels).replace(" ", "") == (
        payload["axis_labels"][1].replace("\n", "").replace(" ", "")
    )
    assert all(item["text_size_pt"] == 6 for item in labels)
    assert spec["frame_alignment"]["plot_panel_size_mm"] == [60, 55]
    assert spec["frame_alignment"]["plot_region_mm"] == [41.5, 38.5]


def test_impossible_label_and_explicit_size_conflicts_fail_without_shrinking(tmp_path):
    payload = _payload(tmp_path)
    with pytest.raises(PerformanceComparisonError) as error:
        _spec(payload, render_options={"size": "60x55"})
    assert error.value.reason_code == "performance_radar_presentation_size_conflict"
    assert _spec(payload, render_options={"size": "120.0X55.0"})["size_mm"] == [120, 55]
    payload["axis_labels"][0] = "非常长的指标" * 100
    with pytest.raises(PerformanceComparisonError) as error:
        _spec(payload)
    assert error.value.reason_code == "performance_radar_label_space_insufficient"


def test_studio_consumer_checks_explicit_size_before_overwriting_defaults(tmp_path):
    from sciplot_core.studio_core.series_request import _series_from_request
    from sciplot_core.studio_render.models import StudioPreparationBlocked

    request = {"input": str(FIXTURE.resolve()), "rule_id": "performance_comparison",
               "template": "polar_curve", "render_options": {"size": "60x55"},
               "explicit_render_option_keys": ["size"]}
    original = deepcopy(request)
    with pytest.raises(StudioPreparationBlocked) as error:
        _series_from_request(request, base_dir=tmp_path)
    assert error.value.reason_code == "performance_radar_presentation_size_conflict"
    assert request == original
    assert list(tmp_path.iterdir()) == []
    request["render_options"]["size"] = "120x55"
    assert _series_from_request(request, base_dir=tmp_path)[1]["performance_comparison"]["layout"]["page_size_mm"] == [120, 55]
    # An inferred legacy default can be replaced, unlike the explicit constraint.
    request["render_options"]["size"] = "60x55"
    request["explicit_render_option_keys"] = []
    assert _series_from_request(request, base_dir=tmp_path)[1]["performance_comparison"]["layout"]["page_size_mm"] == [120, 55]
    request["template"] = "scatter"
    request["explicit_render_option_keys"] = ["size"]
    assert _series_from_request(request, base_dir=tmp_path)[1]["performance_comparison"]["template"] == "scatter"


def test_display_and_reserved_panel_cannot_change_existing_data_signatures(tmp_path):
    frame = pd.read_csv(FIXTURE)
    frame = frame.loc[frame["Role"] == "sample"].copy()
    current = _payload(tmp_path, frame)
    historical = deepcopy(current)
    historical.pop("radar_display")
    historical["axis_labels"] = [item["display_label"] for item in historical["metrics"]]
    layout = historical["layout"]
    layout.update(page_size_mm=[60, 55], legend_panel_size_mm=None,
                  legend_column_count=0, legend_uses_reserved_panel=False)
    layout["graph_margins_mm"]["right"] = 10.5
    new_spec, old_spec = _spec(current), _spec(historical)
    assert new_spec["size_mm"] == [120, 55] and old_spec["size_mm"] == [60, 55]
    inventory = {current["source"]: current["source_sha256"]}
    def signatures(spec):
        return [render_data_unit_signature(item) for item in
                _spec_render_data_units(spec, artifact_inventory=inventory)]
    assert signatures(new_spec) == signatures(old_spec)
    for key in ["metrics", "normalization", "angles_degrees", "series", "source_sha256"]:
        assert current[key] == historical[key]


@pytest.mark.comprehensive
def test_native_radar_long_mixed_units_and_incomplete_negative_reference(tmp_path):
    from sciplot_core.render import render_to_dir
    from sciplot_core.source_coverage.document_audit import _run_audit_worker

    frame = pd.read_csv(FIXTURE)
    density = frame["Metric"] == "density"
    frame.loc[density, ["ScaleMin", "ScaleMax", "Value"]] = [-10, 10, -5]
    frame.loc[frame["Metric"] == "specific_impact_strength", "DisplayLabel"] = (
        "低温抗冲击能力 / Specific impact strength"
    )
    frame = frame.loc[~((frame["Material"] == "PA6") & ~density)].copy()
    payload = _payload(tmp_path, frame)
    result = render_to_dir(payload["source"], template="polar_curve", output_dir=tmp_path / "native",
                           export_formats=("pdf", "tiff_300"),
                           request_context={"rule_id": "performance_comparison"})
    assert result["qa_reports"][0]["issues"] == []
    document_path, spec_path = map(Path, (result["veusz_documents"][0], result["veusz_specs"][0]))
    spec = json.loads(spec_path.read_text())
    pdf = next(Path(item) for item in result["outputs"] if str(item).endswith(".pdf"))
    with pymupdf.open(pdf) as native_pdf:
        page = native_pdf[0]
        text = page.get_text()
        # PDF CJK fonts can encode a compatibility radical for the same glyph.
        assert "低温抗冲击能力" in unicodedata.normalize("NFKC", text).replace("\n", "").replace(" ", "")
        assert "dimensionless" in text and "overall score" in text
        spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block
                 for line in block["lines"] for span in line["spans"]]
        assert all(span["size"] >= 5.99 for span in spans)
        assert all(pymupdf.Rect(span["bbox"]).x0 >= -0.1 and
                   pymupdf.Rect(span["bbox"]).x1 <= page.rect.width + 0.1 and
                   pymupdf.Rect(span["bbox"]).y0 >= -0.1 and
                   pymupdf.Rect(span["bbox"]).y1 <= page.rect.height + 0.1 for span in spans)
    assert _run_audit_worker(document_path, spec_path, True)["status"] == "passed"
    # Missing units/direction and reversed meaning must be detected by the
    # exact-current native label inventory, not accepted as a visual restyle.
    for mutation in ["unit", "direction", "formula", "endpoint"]:
        forged = deepcopy(spec)
        labels = forged["performance_comparison"]["labels"]
        target = next(item for item in labels if item["name"] == (
            "performance_radar_note_2" if mutation == "formula" else
            "performance_radar_axis_endpoint_label_1" if mutation == "endpoint" else
            "performance_radar_axis_label_1_line_2"))
        target["label"] = {"unit": "Density", "direction": "(g cm⁻³; -10–10) ↑",
                           "formula": "↑: r = v / max", "endpoint": "10"}[mutation]
        candidate = tmp_path / f"forged_{mutation}.json"
        candidate.write_text(json.dumps(forged))
        with pytest.raises(ValueError, match="direct-label"):
            _run_audit_worker(document_path, candidate, True)


def test_radar_frame_contract_is_exact_and_cartesian_contract_stays_strict():
    audit = {"documents": [{"path": "radar.vsz", "pages": [
        {"page": 1, "size_mm": [120, 55], "bounds_mm": [0, 0, 120, 55]}],
        "graphs": [{"path": "/page1/graph1", "page": 1, "parent_type": "page",
                    "slot_bounds_mm": [0, 0, 120, 55], "role": "performance_plot",
                    "performance_template": "polar_curve",
                    "margins_mm": {"left": 8, "right": 70.5, "bottom": 9.5, "top": 7}}]}]}
    assert _fixed_frame_report(audit, {})["passed"]
    for margin in ["left", "right", "bottom", "top"]:
        candidate = deepcopy(audit)
        candidate["documents"][0]["graphs"][0]["margins_mm"][margin] += 1
        assert not _fixed_frame_report(candidate, {})["passed"]
    candidate = deepcopy(audit)
    graph = candidate["documents"][0]["graphs"][0]
    graph["performance_template"] = "scatter"
    assert not _fixed_frame_report(candidate, {})["passed"]
    graph["margins_mm"] = {"left": 14, "right": 64.5, "bottom": 11, "top": 5.5}
    assert _fixed_frame_report(candidate, {})["passed"]


@pytest.mark.comprehensive
def test_native_radar_scaffold_and_each_margin_are_independently_discriminated(tmp_path):
    from sciplot_core.render import render_to_dir
    from sciplot_core.qa.audit_support import _run_veusz_audit
    from sciplot_core.veusz_runtime import veusz_worker_environment

    radar = render_to_dir(FIXTURE, template="polar_curve", output_dir=tmp_path / "radar",
                          export_formats=("pdf",), request_context={"rule_id": "performance_comparison"})
    scatter = render_to_dir(FIXTURE, template="scatter", output_dir=tmp_path / "scatter",
                            export_formats=("pdf",), request_context={"rule_id": "performance_comparison"})
    radar_path, scatter_path = Path(radar["veusz_documents"][0]), Path(scatter["veusz_documents"][0])
    audit, error = _run_veusz_audit([radar_path, scatter_path])
    assert error is None and _fixed_frame_report(audit, {})["passed"]
    assert [item["graphs"][0]["performance_template"] for item in audit["documents"]] == ["polar_curve", "scatter"]
    # Historical specs are rendered through the native adapter without the new
    # display contract, then classified solely from their actual scaffold.
    historical = _payload(tmp_path)
    historical.pop("radar_display")
    historical["axis_labels"] = [item["display_label"] for item in historical["metrics"]]
    old_spec = tmp_path / "historical.json"
    old_spec.write_text(json.dumps(_spec(historical)))
    old_path = tmp_path / "historical.vsz"
    completed = subprocess.run([sys.executable, "-m", "sciplot_core.veusz_worker", "save-spec",
                                str(old_path), str(old_spec)], env=veusz_worker_environment(),
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    audit, error = _run_veusz_audit([old_path])
    assert error is None and _fixed_frame_report(audit, {})["passed"]
    mutations = {name: (radar_path, [("set", f"/page1/graph1/{name}Margin", "0.9cm")])
                 for name in ("left", "right", "bottom", "top")}
    mutations.update({
        "missing_ring": (radar_path, [("remove", "/page1/graph1/performance_radar_ring_1", None)]),
        "missing_spoke": (radar_path, [("remove", "/page1/graph1/performance_radar_spoke_1", None)]),
        "visible_axis": (radar_path, [("set", "/page1/graph1/x/Line/hide", False)]),
        "cartesian_radar_margins": (scatter_path, [("set", f"/page1/graph1/{name}Margin", value)
            for name, value in {"left": "0.8cm", "right": "7.05cm", "bottom": "0.95cm", "top": "0.7cm"}.items()]),
        "label_spoof": (scatter_path, [("label", "performance_radar_fake", None),
            ("set", "/page1/graph1/leftMargin", "0.8cm")]),
    })
    script = tmp_path / "native_mutations.py"
    script.write_text('''import json, sys
from pathlib import Path
from sciplot_core.veusz_worker.document_edit import loaded_native_document
for record in json.loads(Path(sys.argv[1]).read_text()):
    with loaded_native_document(Path(record['source'])) as doc:
        from veusz.document import CommandInterface
        interface = CommandInterface(doc)
        for operation, path, value in record['operations']:
            if operation == 'set': interface.Set(path, value)
            elif operation == 'remove': interface.Remove(path)
            else:
                interface.To('/page1/graph1')
                interface.Add('label', name=path, autoadd=False)
        interface.Save(record['target'])
''')
    records = [{"source": str(source), "target": str(tmp_path / f"{name}.vsz"), "operations": operations}
               for name, (source, operations) in mutations.items()]
    inputs = tmp_path / "mutations.json"
    inputs.write_text(json.dumps(records))
    completed = subprocess.run([sys.executable, str(script), str(inputs)], env=veusz_worker_environment(),
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    audit, error = _run_veusz_audit([Path(record["target"]) for record in records])
    assert error is None
    for document in audit["documents"]:
        assert not _fixed_frame_report({"documents": [document]}, {})["passed"], document["path"]
