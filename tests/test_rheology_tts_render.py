"""Source-faithful native composition, export and derivative-data preservation."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_render import (
    audit_tts_document,
    export_tts_document,
    export_tts_documents,
    render_tts_figures,
)
from sciplot_core.rheology_tts_spec import compile_tts_spec


def _spec() -> dict:
    panels = [
        {
            "id": "a",
            "title": "a  Synthetic frequency sweep",
            "rect_mm": [0, 0, 80, 80],
            "x_label": "Angular frequency, ω (rad s^{-1})",
            "y_label": "G′ (Pa)",
            "xscale": "log",
            "yscale": "log",
            "legend": "upper_left",
            "series": [
                {
                    "label": "Control",
                    "x": [0.1, 1.0, 10.0],
                    "y": [10.123456789012345, 200, 3000],
                    "color": "#222222",
                    "marker": "circle",
                    "marker_size": 2.1,
                    "marker_fill": "none",
                    "line_style": "dash",
                }
            ],
        },
        {
            "id": "b",
            "title": "b  Apparent activation energy",
            "rect_mm": [80, 0, 80, 80],
            "x_label": "Sample",
            "y_label": "E_{a,app} (kJ mol^{-1})",
            "legend": False,
            "x_ticks": [0, 1],
            "x_tick_labels": ["HDPE", "LDPE"],
            "series": [
                {
                    "label": "",
                    "x": [0],
                    "y": [46.123456789012345],
                    "color": "#222222",
                    "kind": "bar",
                    "bar_width": 0.6,
                },
                {
                    "label": "",
                    "x": [1],
                    "y": [77.987654321012345],
                    "color": "#336699",
                    "kind": "bar",
                    "bar_width": 0.6,
                },
            ],
            "reference_lines": [{"axis": "y", "value": 65, "style": "dash"}],
        },
    ]
    return {
        "version": 1,
        "source_binding": {"test": "synthetic, not measurement"},
        "figures": [
            {"id": "test_native", "width_mm": 160, "height_mm": 80, "panels": panels}
        ],
    }


@pytest.mark.parametrize(
    "case", ["ragged", "nonfinite", "log_zero", "outside", "duplicate"]
)
def test_invalid_native_data_rejected_before_document_creation(case: str) -> None:
    spec = _spec()
    figure, curve = spec["figures"][0], spec["figures"][0]["panels"][0]["series"][0]
    if case == "ragged":
        curve["y"].append(9.0)
    elif case == "nonfinite":
        curve["y"][0] = float("nan")
    elif case == "log_zero":
        curve["x"][0] = 0
    elif case == "outside":
        figure["panels"][0]["rect_mm"][0] = 100
    else:
        figure["panels"][1]["id"] = "a"
    with pytest.raises(ValueError):
        compile_tts_spec(spec)


def test_compiled_styles_and_bar_baseline_preserve_explicit_meaning() -> None:
    spec = compile_tts_spec(_spec())
    first, bars = spec["figures"][0]["panels"]
    encoding = first["series"][0]["encoding"]
    assert encoding["line"]["style"] == "dashed"
    assert encoding["marker"]["size_pt"] == 2.1
    assert encoding["marker"]["fill_visible"] is False
    assert bars["axes"]["y"]["min"] == 0
    assert bars["axes"]["x"]["min"] < -0.3
    assert bars["axes"]["x"]["max"] > 1.3


def test_native_suite_round_trip_and_exact_export(tmp_path: Path) -> None:
    result = render_tts_figures(_spec(), tmp_path)
    figure = result["figures"][0]
    doc = Path(figure["document"])
    compiled = json.loads(Path(figure["spec_path"]).read_text())["figure"]
    assert figure["native_audit"]["dataset_count"] == 6
    assert [p["point_count"] for p in figure["native_audit"]["panels"]] == [3, 2]
    assert {p["format"] for p in figure["exports"]} == {"pdf", "tiff_300", "png_300"}
    assert all(Path(p["path"]).is_file() for p in figure["exports"])
    before = file_sha256(doc)
    identity = (doc.stat().st_ino, doc.stat().st_mtime_ns)
    assert render_tts_figures(_spec(), tmp_path, resume=True) == result
    assert file_sha256(doc) == before
    assert (doc.stat().st_ino, doc.stat().st_mtime_ns) == identity
    exported = export_tts_document(doc, tmp_path / "reexport" / doc.stem, compiled)
    assert exported["document_sha256"] == before == file_sha256(doc)
    mismatched = deepcopy(compiled)
    mismatched["panels"][0]["series"][0]["y_values"][0] += 1
    with pytest.raises((RuntimeError, ValueError), match="Saved native data differs"):
        audit_tts_document(doc, mismatched)
    assert file_sha256(doc) == before


def test_standard_single_panel_keeps_program_frame_margins(tmp_path: Path) -> None:
    spec = _spec()
    fig = spec["figures"][0]
    fig.update(width_mm=60, height_mm=55)
    fig["panels"] = [fig["panels"][0]]
    fig["panels"][0].update(rect_mm=[0, 0, 60, 55], standard_frame=True)
    result = render_tts_figures(spec, tmp_path)
    frame = result["figures"][0]["native_audit"]["panels"][0]["frame_settings"]
    assert frame == {
        "leftMargin": "14mm",
        "rightMargin": "4.5mm",
        "topMargin": "5.5mm",
        "bottomMargin": "11mm",
    }


def _native_settings(path: Path, *, edits=(), reads=()):
    """Exercise native edits through Veusz, never by rewriting VSZ text."""
    import subprocess
    import sys
    from sciplot_core.veusz_runtime import veusz_worker_environment

    script = """
import json,sys
from sciplot_core.studio_core.runtime import _ensure_veusz_on_path
_ensure_veusz_on_path()
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat,ensure_veusz_qsettings_compat
ensure_veusz_qsettings_compat();ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document,dataimport,widgets
from veusz.document import CommandInterface
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
path,edits,reads=json.loads(sys.argv[1])
doc=document.Document();doc.load(path);doc._sciplot_write_full_precision=True
interface=CommandInterface(doc)
for setting,value in edits:interface.Set(setting,value)
if edits:interface.Save(path)
print(json.dumps({setting:interface.Get(setting) for setting in reads}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps([str(path), edits, reads])],
        env=veusz_worker_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_strict_presentation_rejects_invisible_or_misstyled_series_with_identical_data(
    tmp_path,
):
    import shutil

    result = render_tts_figures(_spec(), tmp_path / "generated")["figures"][0]
    source = Path(result["document"])
    compiled = json.loads(Path(result["spec_path"]).read_text())["figure"]
    assert (
        result["native_audit"]["presentation"]["mode"] == "resolved_creation_contract"
    )
    assert result["native_audit"]["presentation"]["template_match"] is True
    settings = [
        ("marker", "none"),
        ("MarkerLine/hide", True),
        ("PlotLine/hide", True),
        ("markerSize", "0.2pt"),
        ("PlotLine/width", "4pt"),
        ("MarkerLine/transparency", 100),
        ("hide", True),
        ("thinfactor", 20),
    ]
    for index, (setting, value) in enumerate(settings):
        target = tmp_path / f"changed_{index}.vsz"
        shutil.copyfile(source, target)
        _native_settings(target, edits=[(f"/page1/a/series_1/{setting}", value)])
        numeric = audit_tts_document(target, compiled)
        assert numeric["status"] == "passed"
        assert numeric["presentation"]["template_match"] is False
        with pytest.raises((ValueError, RuntimeError), match="presentation differs"):
            audit_tts_document(target, compiled, check_presentation=True)
    target = tmp_path / "hidden_bar.vsz"
    shutil.copyfile(source, target)
    _native_settings(target, edits=[("/page1/b/series_1/hide", True)])
    with pytest.raises((ValueError, RuntimeError), match="presentation differs"):
        audit_tts_document(target, compiled, check_presentation=True)


def test_native_presentation_edits_survive_ordinary_exact_reexport(tmp_path):
    result = render_tts_figures(_spec(), tmp_path / "generated")["figures"][0]
    path = Path(result["document"])
    compiled = json.loads(Path(result["spec_path"]).read_text())["figure"]
    _native_settings(
        path,
        edits=[
            ("/page1/a/series_1/marker", "diamond"),
            ("/page1/a/series_1/PlotLine/width", "4pt"),
        ],
    )
    before = file_sha256(path)
    exported = export_tts_document(path, tmp_path / "reexport" / path.stem, compiled)
    assert exported["document_sha256"] == before == file_sha256(path)
    presentation = exported["native_audit"]["presentation"]
    assert presentation["mode"] == "saved_native_authority"
    assert presentation["template_match"] is False
    assert {"marker", "PlotLine/width"} <= {
        difference["field"] for difference in presentation["differences"]
    }


def test_restyle_candidate_preserves_unrelated_native_settings_and_original_bytes(
    tmp_path,
):
    from sciplot_core.rheology_tts_render import restyle_tts_document

    result = render_tts_figures(_spec(), tmp_path / "generated")["figures"][0]
    path = Path(result["document"])
    old = json.loads(Path(result["spec_path"]).read_text())["figure"]
    new = deepcopy(old)
    new["panels"][0]["series"][0]["encoding"]["marker"]["shape"] = "square"
    new["panels"][0]["series"][0]["encoding"]["marker"]["size_pt"] = 3.5
    edits = [
        ("/page1/a/x/label", "Manual axis label"),
        ("/page1/a/series_1/PlotLine/color", "#ff00ff"),
    ]
    _native_settings(path, edits=edits)
    before = file_sha256(path)
    candidate = tmp_path / "candidate.vsz"
    result = restyle_tts_document(path, candidate, old, new, before)
    assert file_sha256(path) == before
    assert result["source_document_sha256"] == before
    assert result["document_sha256"] == file_sha256(candidate)
    assert {change["field"] for change in result["changes"]} == {"marker", "markerSize"}
    values = _native_settings(
        candidate,
        reads=[setting for setting, _ in edits] + ["/page1/a/series_1/marker"],
    )
    assert values["/page1/a/x/label"] == "Manual axis label"
    assert values["/page1/a/series_1/PlotLine/color"] == "#ff00ff"
    assert values["/page1/a/series_1/marker"] == "square"
    assert result["candidate_audit"]["changed_presentation"]["status"] == "passed"
    assert result["candidate_audit"]["presentation"]["template_match"] is False
    assert all(
        d["field"] == "PlotLine/color"
        for d in result["candidate_audit"]["presentation"]["differences"]
    )


def test_restyle_rejects_stale_revision_target_conflicts_and_changed_arrays(tmp_path):
    from sciplot_core.rheology_tts_render import restyle_tts_document

    result = render_tts_figures(_spec(), tmp_path / "generated")["figures"][0]
    path = Path(result["document"])
    old = json.loads(Path(result["spec_path"]).read_text())["figure"]
    new = deepcopy(old)
    new["panels"][0]["series"][0]["encoding"]["marker"]["shape"] = "square"
    candidate = tmp_path / "candidate.vsz"
    before = file_sha256(path)
    with pytest.raises((ValueError, RuntimeError), match="stale"):
        restyle_tts_document(path, candidate, old, new, "0" * 64)
    assert not candidate.exists()
    altered_data = deepcopy(new)
    altered_data["panels"][0]["series"][0]["x_values"][0] += 0.01
    with pytest.raises((ValueError, RuntimeError), match="numeric coordinates"):
        restyle_tts_document(path, candidate, old, altered_data, before)
    assert not candidate.exists()
    _native_settings(path, edits=[("/page1/a/series_1/marker", "diamond")])
    edited_sha = file_sha256(path)
    with pytest.raises((ValueError, RuntimeError), match="Native style conflict"):
        restyle_tts_document(path, candidate, old, new, edited_sha)
    assert not candidate.exists()
    assert file_sha256(path) == edited_sha


def test_restyle_bar_color_preserves_unrelated_native_group_spacing(tmp_path):
    from sciplot_core.rheology_tts_render import restyle_tts_document

    result = render_tts_figures(_spec(), tmp_path / "generated")["figures"][0]
    path = Path(result["document"])
    old = json.loads(Path(result["spec_path"]).read_text())["figure"]
    new = deepcopy(old)
    new["panels"][1]["series"][0]["color"] = "#cc3344"
    _native_settings(path, edits=[("/page1/b/series_1/groupfill", 0.55)])
    source_sha = file_sha256(path)
    candidate = tmp_path / "bar_candidate.vsz"
    result = restyle_tts_document(path, candidate, old, new, source_sha)
    values = _native_settings(
        candidate,
        reads=[
            "/page1/b/series_1/groupfill",
            "/page1/b/series_1/BarFill/fills",
            "/page1/b/series_1/BarLine/lines",
        ],
    )
    assert values["/page1/b/series_1/groupfill"] == 0.55
    assert values["/page1/b/series_1/BarFill/fills"][0][1] == "#cc3344"
    assert values["/page1/b/series_1/BarLine/lines"][0][2] == "#cc3344"
    assert file_sha256(path) == source_sha
    assert {change["field"] for change in result["changes"]} == {
        "BarFill/fills[0][1]",
        "BarLine/lines[0][2]",
    }


def _batch_entries(tmp_path):
    entries = []
    for identifier in ("Alpha", "Beta"):
        path = tmp_path / f"{identifier}.vsz"
        path.write_bytes(f"test placeholder {identifier}".encode())
        entries.append((path, tmp_path / "exports" / identifier,
                        {"id": identifier, "panels": [{}]}))
    return entries


def test_batch_export_dispatches_once_with_complete_ordered_receipts(tmp_path, monkeypatch):
    from sciplot_core import rheology_tts_render as render

    entries = _batch_entries(tmp_path)[::-1]
    results = [{"document": str(path), "cleanup_warnings": ["keep complete warning"]}
               for path, _, _ in entries]
    calls = []

    def dispatch(request):
        calls.append(request)
        return {"status": "completed", "results": results}

    monkeypatch.setattr(render, "_dispatch", dispatch)
    assert export_tts_documents(entries) == results
    assert len(calls) == 1 and calls[0]["action"] == "export_batch"
    assert [record["path"] for record in calls[0]["documents"]] == [str(entry[0]) for entry in entries]


@pytest.mark.parametrize("case", ["empty", "extra_key", "extra_entry_key", "relative", "missing",
                                 "duplicate", "case_collision", "wrong_figure", "alias", "audit_symlink",
                                 "audit_hardlink", "audit_hardlink_collision"])
def test_invalid_batch_request_rejected_before_native_side_effects(tmp_path, monkeypatch, case):
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.studio_core import runtime

    entries = _batch_entries(tmp_path)
    request = {"action": "export_batch", "documents": [
        {"path": str(path), "out_base": str(out_base), "figure": figure} for path, out_base, figure in entries]}
    last = request["documents"][-1]
    if case == "empty":
        request["documents"] = []
    elif case == "extra_key":
        request["unchecked"] = True
    elif case == "extra_entry_key":
        last["unchecked"] = True
    elif case == "relative":
        last["path"] = "Beta.vsz"
    elif case == "missing":
        entries[-1][0].unlink()
    elif case == "duplicate":
        request["documents"][-1] = request["documents"][0]
    elif case == "case_collision":
        alternate = tmp_path / "other" / "aLPHA.vsz"
        alternate.parent.mkdir()
        alternate.write_bytes(b"distinct document")
        last.update(path=str(alternate), out_base=str(tmp_path / "exports/aLPHA"),
                    figure={"id": "aLPHA", "panels": [{}]})
    elif case == "wrong_figure":
        last["figure"]["id"] = "Unbound"
    elif case == "alias":
        alias = tmp_path / "Alias.vsz"
        alias.symlink_to(entries[-1][0])
        last.update(path=str(alias), out_base=str(tmp_path / "exports/Alias"),
                    figure={"id": "Alias", "panels": [{}]})
    elif case == "audit_symlink":
        target = tmp_path / "exports/Beta.native-audit.json"
        target.parent.mkdir()
        target.symlink_to(entries[0][0])
    elif case == "audit_hardlink":
        target = tmp_path / "exports/Beta.native-audit.json"
        target.parent.mkdir()
        target.hardlink_to(entries[0][0])
    else:
        first = tmp_path / "exports/Alpha.native-audit.json"
        first.parent.mkdir()
        first.write_bytes(b"existing audit")
        (first.parent / "Beta.native-audit.json").hardlink_to(first)

    def forbidden():
        pytest.fail("Invalid batch request reached the native runtime.")

    monkeypatch.setattr(runtime, "_ensure_veusz_on_path", forbidden)
    with pytest.raises(ValueError):
        render._run_native(request)
    assert not list(tmp_path.rglob("*.pdf"))
    assert entries[0][0].read_bytes() == b"test placeholder Alpha"


@pytest.mark.parametrize("failure", ["later_audit", "audit_drift", "export_drift", "receipt_drift"])
def test_batch_preaudits_all_and_rejects_cross_document_drift(tmp_path, monkeypatch, failure):
    from sciplot_core import rheology_tts_native, rheology_tts_render as render

    entries = _batch_entries(tmp_path)
    documents = [(path, base.parent, figure) for path, base, figure in entries]
    before = {path: path.read_bytes() for path, _, _ in entries}
    calls = []

    def audit(path, figure, *, check_presentation):
        assert check_presentation is False
        calls.append(("audit", path))
        if path == entries[-1][0]:
            if failure == "later_audit":
                raise ValueError("invalid later document")
            if failure == "audit_drift":
                entries[0][0].write_bytes(b"external change during later audit")

    def export(path, out, figure):
        calls.append(("export", path))
        if failure == "export_drift" and path == entries[-1][0]:
            entries[0][0].write_bytes(b"external change during later export")
        return {"document_sha256": "incorrect" if failure == "receipt_drift" else file_sha256(path)}

    monkeypatch.setattr(rheology_tts_native, "audit_native_figure", audit)
    monkeypatch.setattr(render, "_export", export)
    with pytest.raises(ValueError, match="invalid later|changed"):
        render._export_batch(documents)
    assert calls[:2] == [("audit", entry[0]) for entry in entries]
    if failure in {"later_audit", "audit_drift"}:
        assert len(calls) == 2
    assert entries[-1][0].read_bytes() == before[entries[-1][0]]
    if failure == "later_audit":
        assert all(path.read_bytes() == value for path, value in before.items())


def test_native_batch_matches_separate_exact_exports_and_keeps_saved_edits(tmp_path, monkeypatch):
    from PIL import Image
    from sciplot_core import rheology_tts_render as render

    spec = _spec()
    second = deepcopy(spec["figures"][0])
    second["id"] = "second_native"
    second["panels"][0]["series"][0]["y"][0] = 32.987654321012345
    spec["figures"].append(second)
    native = render_tts_figures(spec, tmp_path / "native")["figures"][::-1]
    entries = [(Path(item["document"]), tmp_path / "batch" / item["id"],
                json.loads(Path(item["spec_path"]).read_text())["figure"]) for item in native]
    _native_settings(entries[0][0], edits=[("/page1/a/series_1/marker", "diamond")])
    before = {path: file_sha256(path) for path, _, _ in entries}
    references = [export_tts_document(path, tmp_path / "reference" / path.stem, figure)
                  for path, _, figure in entries]
    dispatched = []
    original_dispatch = render._dispatch

    def dispatch(request):
        dispatched.append(request["action"])
        return original_dispatch(request)

    monkeypatch.setattr(render, "_dispatch", dispatch)
    results = export_tts_documents(entries)
    assert dispatched == ["export_batch"]
    assert [item["document"] for item in results] == [str(path) for path, _, _ in entries]
    for (path, _, _), actual, reference in zip(entries, results, references, strict=True):
        assert before[path] == file_sha256(path) == actual["document_sha256"] == reference["document_sha256"]
        assert actual["native_audit"] == reference["native_audit"]
        for image_format in ("png_300", "tiff_300"):
            actual_path = next(item["path"] for item in actual["exports"] if item["format"] == image_format)
            reference_path = next(item["path"] for item in reference["exports"] if item["format"] == image_format)
            with Image.open(actual_path) as actual_image, Image.open(reference_path) as reference_image:
                assert actual_image.size == reference_image.size
                assert actual_image.mode == reference_image.mode
                assert actual_image.tobytes() == reference_image.tobytes()
    assert results[0]["native_audit"]["presentation"]["template_match"] is False

    invalid = deepcopy(entries)
    invalid[-1][2]["panels"][0]["series"][0]["y_values"][0] += 1
    invalid = [(path, tmp_path / "rejected" / path.stem, figure) for path, _, figure in invalid]
    with pytest.raises((RuntimeError, ValueError), match="Saved native data differs"):
        export_tts_documents(invalid)
    assert not (tmp_path / "rejected").exists()
    assert all(file_sha256(path) == digest for path, digest in before.items())
