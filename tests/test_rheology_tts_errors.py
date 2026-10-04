"""Prepared symmetric errors survive native bars, points and exact export."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_render import (
    audit_tts_document,
    export_tts_document,
    render_tts_figures,
    restyle_tts_document,
)
from sciplot_core.rheology_tts_spec import compile_tts_spec
from sciplot_core.rheology_tts_style import prepare_tts_presentation
from sciplot_core.veusz_runtime import veusz_worker_environment
from test_rheology_tts_render import _native_settings, _spec


def _errors_spec():
    spec = _spec()
    panels = spec["figures"][0]["panels"]
    panels[0]["series"][0]["error_values"] = [0, 10.123456789012345, 1234.5678901234567]
    panels[1]["series"][0].update(
        x=[-0.2, 0.8],
        y=[40.12345678901234, 50.98765432109876],
        error_values=[4.234567890123456, 20.234567890123456],
        bar_width=0.3,
    )
    panels[1]["series"][1].update(
        x=[0.2, 1.2],
        y=[20.987654321012345, 35.123456789012345],
        error_values=[1.23456789012345, 0],
        bar_width=0.3,
    )
    spec["transform_ledger"] = {
        "error_values": "Supplied linear-fit SE; no calculation by plotter."
    }
    return spec


@pytest.mark.parametrize(
    "errors",
    [[], [1], [1, -1, 1], [1, float("nan"), 1], [1, float("inf"), 1], [True, 1, 1]],
)
def test_invalid_supplied_errors_rejected(errors):
    spec = _errors_spec()
    spec["figures"][0]["panels"][0]["series"][0]["error_values"] = errors
    with pytest.raises(ValueError, match="error_values"):
        compile_tts_spec(spec)


def test_error_endpoints_define_auto_bounds_without_extra_plotted_points():
    spec = _errors_spec()
    compiled = compile_tts_spec(spec)
    panels = compiled["figures"][0]["panels"]
    assert panels[0]["axes"]["y"]["max"] >= 4234.567890123457
    assert [s["x_values"] for s in panels[1]["series"]] == [[-0.2, 0.8], [0.2, 1.2]]
    assert panels[1]["axes"]["y"]["max"] >= 71.22222221122222
    assert compiled["transform_ledger"] == spec["transform_ledger"]
    spec["figures"][0]["panels"][0]["series"][0]["error_values"][0] = 100
    with pytest.raises(ValueError, match="nonpositive"):
        compile_tts_spec(spec)


@pytest.mark.parametrize(
    "role,kind", [("measured_curve", "curve"), ("summary_bar", "bar")]
)
def test_governed_prepared_roles_retain_errors(role, kind):
    errors = [0, 1.2345678901234567]
    prepared = prepare_tts_presentation(
        {
            "version": 1,
            "source_binding": {"test": "supplied synthetic uncertainty"},
            "figures": [
                {
                    "id": "errors",
                    "panels": [
                        {
                            "id": "graph1",
                            "x_label": "Group",
                            "y_label": "Estimate",
                            "series": [
                                {
                                    "role": role,
                                    "kind": kind,
                                    "label": "Estimate",
                                    "x": [0, 1],
                                    "y": [20, 30],
                                    "error_values": errors,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    compiled = compile_tts_spec(prepared)
    assert compiled["figures"][0]["panels"][0]["series"][0]["error_values"] == errors


def _dataset(path, name, *, update=None):
    script = """
import json,sys
from sciplot_core.rheology_tts_render import _run_native
from sciplot_core.studio_core.runtime import _ensure_veusz_on_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat,ensure_veusz_qsettings_compat
_ensure_veusz_on_path();ensure_veusz_qsettings_compat();ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document,dataimport,widgets
from veusz.document import CommandInterface
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
path,name,update=json.loads(sys.argv[1]);doc=document.Document();doc.load(path)
doc._sciplot_write_full_precision=True;interface=CommandInterface(doc)
if update is not None:
    data=doc.data[name].data.copy();interface.SetData(name,data,**update);interface.Save(path)
data=doc.data[name]
print(json.dumps({key:None if getattr(data,key) is None else getattr(data,key).tolist() for key in ('data','serr','nerr','perr')}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps([str(path), name, update])],
        env=veusz_worker_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture
def native_errors(tmp_path):
    result = render_tts_figures(_errors_spec(), tmp_path / "original")["figures"][0]
    return Path(result["document"]), json.loads(Path(result["spec_path"]).read_text())[
        "figure"
    ]


def test_curve_and_grouped_bars_retain_exact_supplied_errors(native_errors, tmp_path):
    path, figure = native_errors
    for panel in figure["panels"]:
        for item in panel["series"]:
            assert _dataset(path, item["y_name"]) == {
                "data": item["y_values"],
                "serr": item["error_values"],
                "nerr": None,
                "perr": None,
            }
    assert (
        audit_tts_document(path, figure, check_presentation=True)["panels"][1][
            "error_point_count"
        ]
        == 4
    )
    before = file_sha256(path)
    no_error_contract = deepcopy(figure)
    no_error_contract["panels"][0]["series"][0]["error_values"] = []
    with pytest.raises((ValueError, RuntimeError), match="native uncertainty differs"):
        audit_tts_document(path, no_error_contract)
    exported = export_tts_document(path, tmp_path / "reexport" / path.stem, figure)
    assert exported["document_sha256"] == before == file_sha256(path)
    for panel in figure["panels"]:
        for item in panel["series"]:
            changed = deepcopy(figure)
            target = changed["panels"][figure["panels"].index(panel)]["series"][
                panel["series"].index(item)
            ]
            target["error_values"][0] += 1
            with pytest.raises(
                (ValueError, RuntimeError), match="uncertainty coordinates"
            ):
                restyle_tts_document(
                    path, tmp_path / "rejected.vsz", figure, changed, before
                )


@pytest.mark.parametrize(
    "name,update",
    [
        ("a_s0_y", {"symerr": [0, 10, 1234]}),
        ("b_s0_y", {}),
        ("a_s0_x", {"symerr": [1, 1, 1]}),
        ("b_s1_y", {"symerr": [1.23456789012345, 0], "poserr": [1, 1]}),
    ],
)
def test_native_error_channel_tampering_rejected(native_errors, name, update):
    path, figure = native_errors
    _dataset(path, name, update=update)
    with pytest.raises((ValueError, RuntimeError), match="native uncertainty differs"):
        audit_tts_document(path, figure)


def test_hidden_native_errors_fail_strict_audit_but_saved_reexport_preserves_edit(
    native_errors, tmp_path
):
    path, figure = native_errors
    _native_settings(
        path,
        edits=[
            ("/page1/b/series_1/ErrorBarLine/hide", True),
            ("/page1/a/series_1/errorStyle", "none"),
        ],
    )
    before = file_sha256(path)
    with pytest.raises((ValueError, RuntimeError), match="presentation differs"):
        audit_tts_document(path, figure, check_presentation=True)
    result = export_tts_document(path, tmp_path / "export" / path.stem, figure)
    assert file_sha256(path) == before == result["document_sha256"]
    assert result["native_audit"]["presentation"]["template_match"] is False


def test_plot_csv_preserves_supplied_uncertainties_and_no_error_schema(tmp_path):
    import csv
    from sciplot_core.workflow.rheology_tts_tables import write_plot_tables

    curve = {"label": "Estimated Ea", "x": [1, 2], "y": [60.9, 92.2],
             "error_values": [3.7660235142725353, 0.0]}
    panel = {"id": "graph1", "x_label": "Sample", "y_label": "Ea", "series": [curve]}
    spec = {"figures": [{"id": "Summary", "panels": [panel]}]}
    write_plot_tables(spec, tmp_path)
    with (tmp_path / "Summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [float(r["y_error"]) for r in rows] == curve["error_values"]
    curve["error_values"] = []
    write_plot_tables(spec, tmp_path)
    with (tmp_path / "Summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert "y_error" not in next(csv.reader(stream))
