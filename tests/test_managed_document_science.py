from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_data import build_plot_data_exports
from sciplot_core.render import render_to_dir
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.source_coverage.managed_documents import (
    _verify_prepared_data,
    verify_managed_document_sources,
)
from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
from sciplot_core.source_coverage.verify import verify_rendered_mapping_source_coverage
from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.veusz_worker.spec_audit.scientific_geometry import (
    axis_matches_science,
    label_matches_science,
)


def test_scientific_axis_preserves_units_and_visible_source_values() -> None:
    axis = {"label": "Time (s)", "scale": "linear", "min": -1.0, "max": 4.0}
    bindings = {
        "label": "Time (s)",
        "direction": "horizontal",
        "mode": "numeric",
        "log": False,
        "Label/hide": False,
        "min": 0.0,
        "max": 3.0,
        "Label/size": "18pt",
        "Line/width": "2pt",
    }
    record = {"name": "x", "bindings": bindings}
    spec = {"series": [{"x_values": [0.0, 1.0, 2.0, 3.0]}]}
    assert axis_matches_science(record, axis, name="x", spec=spec)
    for change in (
        {"min": 1.0},
        {"label": "Time (ms)"},
        {"log": True},
        {"Label/hide": True},
    ):
        assert not axis_matches_science(
            {**record, "bindings": {**bindings, **change}}, axis, name="x", spec=spec
        )


def test_scientific_label_keeps_sample_identity_when_layout_changes() -> None:
    expected = {
        "path": "/page1/graph1/label_1",
        "name": "label_1",
        "literal_label": "Sample A",
        "x_axis": "x",
        "y_axis": "y",
    }
    record = {
        "path": expected["path"],
        "name": expected["name"],
        "bindings": {
            "label": "Sample A",
            "Text/hide": False,
            "xAxis": "x",
            "yAxis": "y",
            "xPos": [0.7],
            "Text/size": "8pt",
        },
    }
    assert label_matches_science(record, expected)
    record["bindings"]["label"] = "Sample B"
    assert not label_matches_science(record, expected)


def test_multifigure_csvs_keep_each_figures_values_and_units(tmp_path: Path) -> None:
    source = tmp_path / "primary.csv"
    source.write_text("Time,Force\ns,N\nSample A,Sample A\n1,2\n2,3\n")
    documents = [tmp_path / "document.vsz", tmp_path / "modulus.vsz"]
    for document, label, values in zip(
        documents, ("Force (N)", "Modulus (MPa)"), ([2, 3], [40, 60]), strict=True
    ):
        spec_path = (
            document.with_name("spec.json")
            if document.name == "document.vsz"
            else document.with_suffix(".spec.json")
        )
        spec_path.write_text(
            json.dumps(
                {
                    "axes": {"x": {"label": "Time (s)"}, "y": {"label": label}},
                    "series": [
                        {"label": "Sample A", "x_values": [1, 2], "y_values": values}
                    ],
                }
            )
        )
    records = build_plot_data_exports(
        {
            "result": {"processed_source": str(source)},
            "veusz_documents": [str(path) for path in documents],
            "semantic": {
                "axis_plan": {"y": {"canonical_label": "Force"}},
                "unit_plan": {"y": "N"},
            },
        },
        destination=tmp_path / "delivery",
    )
    assert len(records) == 2
    with Path(records[1]["path"]).open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [
        ["Time", "Modulus"],
        ["s", "MPa"],
        ["Sample A", "Sample A"],
        ["1", "40"],
        ["2", "60"],
    ]


def _edit_native(document: Path, statements: str) -> None:
    code = f"""
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_runtime_path()
ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document, dataimport, widgets
from veusz.document import CommandInterface
app = QtWidgets.QApplication([])
doc = document.Document()
doc.load({str(document)!r})
i = CommandInterface(doc)
{statements}
i.Save({str(document)!r})
"""
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=veusz_worker_environment(),
        timeout=60,
    )


def _render_curve(
    tmp_path: Path, *, template: str = "curve"
) -> tuple[dict, Path, dict]:
    source = tmp_path / "curve.csv"
    source.write_text(
        "Wavelength,Absorbance\nnm,a.u.\nA,A\n400,0.1\n450,0.2\n500,0.3\n"
    )
    result = render_to_dir(
        source,
        template=template,
        output_dir=tmp_path / "rendered",
        options={
            "size": "60x55",
            "series_label_mode": "inline",
            "show_single_series_label": True,
        },
        export_formats=("pdf",),
    )
    document = Path(result["veusz_documents"][0])
    spec = json.loads(Path(result["veusz_specs"][0]).read_text())
    result["data_snapshot_sources"] = [str(source)]
    return result, document, spec


@pytest.mark.comprehensive
def test_current_audit_allows_presentation_edits_but_keeps_generated_gate(
    tmp_path: Path,
) -> None:
    result, document, spec = _render_curve(tmp_path, template="stacked_curve")
    assert verify_managed_document_sources(result)["status"] == "passed"
    _edit_native(
        document,
        """i.To('/page1/graph1/x')
i.Set('Label/size', '8pt')
i.Set('Line/width', '0.9pt')
i.To('/page1/graph1/series_1')
i.Set('PlotLine/color', '#006699')
i.Set('PlotLine/width', '1.5pt')
i.To('/page1/graph1/label_1')
i.Set('xPos', [0.6])
i.Set('Text/size', '8pt')""",
    )
    assert verify_managed_document_sources(result)["status"] == "passed"
    with pytest.raises(ValueError, match="axis labels|direct-label"):
        _audit_exact_document_data(
            document_path=document, spec_path=Path(result["veusz_specs"][0])
        )
    mapping = {
        "proposal_id": "confirmed",
        "mapped_outputs": spec["series"][0]["source_artifacts"],
    }
    assert (
        verify_managed_document_sources(result, mapping_application=mapping)[
            "mapping_source_coverage"
        ]["status"]
        == "passed"
    )
    # Studio publication reconstructs terminal requests from the source request;
    # direct-render transport receipts are not part of its result envelope.
    result.pop("terminal_render_requests", None)
    assert (
        verify_rendered_mapping_source_coverage(
            result,
            mapping_application=mapping,
            request=spec["source_request"],
            check_presentation=False,
        )["status"]
        == "passed"
    )


@pytest.mark.comprehensive
def test_managed_mapping_checks_every_figure_and_confirmed_source(
    tmp_path: Path,
) -> None:
    results = []
    records = []
    for label in ("first", "second"):
        folder = tmp_path / label
        folder.mkdir()
        result, _document, spec = _render_curve(folder)
        results.append(result)
        records.extend(spec["series"][0]["source_artifacts"])
    combined = {
        "template": "curve",
        "veusz_documents": [item["veusz_documents"][0] for item in results],
        "data_snapshot_sources": [item["data_snapshot_sources"][0] for item in results],
    }
    mapping = {"proposal_id": "two_confirmed_tables", "mapped_outputs": records}
    verified = verify_managed_document_sources(combined, mapping_application=mapping)
    assert verified["document_count"] == 2
    assert verified["mapping_source_coverage"]["coverage_mode"] == "exact_per_output"
    combined["veusz_documents"].pop()
    with pytest.raises(
        ValueError, match="do not consume every confirmed mapped output"
    ):
        verify_managed_document_sources(combined, mapping_application=mapping)


@pytest.mark.comprehensive
@pytest.mark.parametrize(
    "change, message",
    [
        ("i.SetData('y_1_1', [0.3, 0.2, 0.1])", "dataset.*differs"),
        (
            "i.SetData('replacement', [0.1, 0.2, 0.3])\ni.To('/page1/graph1/series_1')\ni.Set('yData', 'replacement')",
            "bound xy widget",
        ),
        (
            "i.To('/page1/graph1/series_1')\ni.Set('key', 'Other sample')",
            "bound xy widget",
        ),
        ("i.To('/page1/graph1/series_1')\ni.Set('hide', True)", "bound xy widget"),
        ("i.To('/page1/graph1/series_1')\ni.Set('xAxis', 'missing')", "axis bindings"),
        ("i.To('/page1/graph1/series_1')\ni.Set('yAxis', 'missing')", "axis bindings"),
        ("i.To('/page1/graph1/x')\ni.Set('label', 'Wavelength (um)')", "axis labels"),
        ("i.To('/page1/graph1/x')\ni.Set('min', 450.0)", "axis labels"),
    ],
)
def test_current_audit_rejects_scientific_changes(
    tmp_path: Path, change: str, message: str
) -> None:
    result, document, _spec = _render_curve(tmp_path)
    _edit_native(document, change)
    with pytest.raises(ValueError, match=message):
        verify_managed_document_sources(result)


@pytest.mark.comprehensive
def test_current_audit_rederives_spec_from_prepared_csv(tmp_path: Path) -> None:
    result, document, spec = _render_curve(tmp_path)
    spec["series"][0]["y_values"] = [0.3, 0.2, 0.1]
    Path(result["veusz_specs"][0]).write_text(json.dumps(spec))
    _edit_native(document, "i.SetData('y_1_1', [0.3, 0.2, 0.1])")
    with pytest.raises(ValueError, match="do not reproduce"):
        verify_managed_document_sources(result)


@pytest.mark.comprehensive
@pytest.mark.parametrize(
    "template",
    [
        "point_line",
        "bar",
        "grouped_bar",
        "box_strip",
        "heatmap",
        "scatter",
        "polar_curve",
    ],
)
def test_current_audit_preserves_supported_chart_families(
    tmp_path: Path, template: str
) -> None:
    source = tmp_path / "source.csv"
    context = {}
    options = {"size": "60x55"}
    if template in {"scatter", "polar_curve"}:
        source = Path(
            "tests/fixtures/performance_comparison/material_performance_long.csv"
        ).resolve()
        context = {"rule_id": "performance_comparison"}
    elif template == "heatmap":
        source.write_text("x,y,z\n0,0,1\n1,0,2\n0,1,3\n1,1,4\n")
        options.update(
            {"data_variables": {"x": "x", "y": "y", "z": "z"}, "show_colorbar": True}
        )
    elif template == "grouped_bar":
        source.write_text(
            "Sample,Condition,Strength (MPa)\n"
            "A,thin,1\nA,thin,2\nA,thick,3\nA,thick,4\n"
            "B,thin,5\nB,thin,6\nB,thick,7\nB,thick,8\n"
        )
    elif template in {"bar", "box_strip"}:
        source.write_text(
            "Impact strength,Impact strength\nkJ/m2,kJ/m2\nA,B\n1,2\n2,3\n3,4\n"
        )
    else:
        source.write_text("x,A,B\n1,2,3\n2,3,4\n3,4,5\n")
    result = render_to_dir(
        source,
        template="bar" if template == "grouped_bar" else template,
        output_dir=tmp_path / "rendered",
        options=options,
        request_context=context,
        export_formats=("pdf",),
    )
    result["data_snapshot_sources"] = [str(source)]
    document = Path(result["veusz_documents"][0])
    assert verify_managed_document_sources(result)["status"] == "passed"
    _edit_native(document, "i.To('/page1/graph1/x')\ni.Set('Label/size', '8pt')")
    assert verify_managed_document_sources(result)["status"] == "passed"
    if template == "bar":
        spec = json.loads(Path(result["veusz_specs"][0]).read_text())
        spec["categorical"]["groups"][0]["bar_mean"] += 1.0
        with pytest.raises(ValueError, match="do not reproduce"):
            _verify_prepared_data(
                spec, [_stable_file_snapshot(source, label="test source")]
            )


def _studio_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "skill/scripts/sciplot",
            "studio",
            *arguments,
            "--export",
            "pdf,tiff_300",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.comprehensive
def test_current_audit_rejects_thinned_replicate_markers(tmp_path: Path) -> None:
    source = tmp_path / "replicates.csv"
    source.write_text(
        "Impact strength,Impact strength\nkJ/m2,kJ/m2\nA,B\n1,2\n2,3\n3,4\n"
    )
    result = render_to_dir(
        source, template="box_strip", output_dir=tmp_path / "rendered",
        options={"size": "60x55"}, export_formats=("pdf",),
    )
    result["data_snapshot_sources"] = [str(source)]
    assert verify_managed_document_sources(result)["status"] == "passed"
    _edit_native(
        Path(result["veusz_documents"][0]),
        "i.To('/page1/graph1/series_1')\ni.Set('thinfactor', 2)",
    )
    with pytest.raises(ValueError, match="every raw-point marker"):
        verify_managed_document_sources(result)


@pytest.mark.comprehensive
def test_uvvis_managed_cli_keeps_styles_and_rejects_changed_measurements(
    tmp_path: Path,
) -> None:
    source = tmp_path / "uvvis.csv"
    source.write_text(
        "Wavelength (nm),Absorbance (a.u.)\n400,0.1\n450,0.2\n500,0.3\n550,0.4\n600,0.5\n"
    )
    initial = _studio_cli(str(source), "--rule", "uvvis_spectrum")
    assert initial.returncode == 0, initial.stderr
    payload = json.loads(initial.stdout)
    assert payload["studio_run"]["ready_to_use"] is True
    document = Path(payload["document"])
    _edit_native(document, "i.To('/page1/graph1/x')\ni.Set('Label/size', '8pt')")
    styled = _studio_cli(payload["project_dir"])
    assert styled.returncode == 0, styled.stderr
    styled_payload = json.loads(styled.stdout)
    assert styled_payload["studio_run"]["ready_to_use"] is True
    run_manifest = json.loads(
        Path(styled_payload["studio_run"]["manifest"]).read_text()
    )
    assert run_manifest["result"]["scientific_data_verification"]["status"] == "passed"
    package = styled_payload["studio_run"]["delivery_package"]
    csv = Path(package["data_csvs"][0]["path"])
    before = file_sha256(csv)
    _edit_native(document, "i.SetData('y_1_1', [0.5, 0.4, 0.3, 0.2, 0.1])")
    changed = _studio_cli(payload["project_dir"])
    assert changed.returncode != 0
    assert "differs from the rendered specification" in changed.stderr + changed.stdout
    assert file_sha256(csv) == before
