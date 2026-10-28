"""Public new-spectrum create/export proves real native text/frame/curve clearance."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.qa.audit_support import _run_veusz_audit
from sciplot_core.smoke.data_mapping import _write_synthetic_ftir
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.review_artifacts import _current_layout_issues
from sciplot_core.studio_render.direct_label_layout import DIRECT_LABEL_LAYOUT_KEY as KEY, DIRECT_LABEL_LAYOUT_VERSION as VERSION
from test_categorical_source_identity import snapshots


def _cli(*arguments):
    actual = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, arguments), "--json"],
        capture_output=True, text=True, timeout=120)
    assert actual.returncode == 0, (actual.stdout, actual.stderr)
    return json.loads(actual.stdout)


@pytest.mark.comprehensive
def test_public_default_spectrum_create_cold_export_has_clear_complete_inline_text(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    source = tmp_path / "ftir_runtime_smoke.csv"
    _write_synthetic_ftir(source)
    original = source.read_bytes()
    raw = list(csv.reader(original.decode().splitlines()))
    created = _cli("studio", source, "--rule", "ftir_spectrum")
    project = Path(created["project_dir"])
    selected = resolve_project_figure(project, None)
    document, spec_path = Path(selected["document"]), Path(selected["spec"])
    spec = json.loads(spec_path.read_text())
    assert spec["source_request"][KEY] == VERSION
    assert spec["size_mm"] == [120, 55]
    assert spec["style"]["font_size_pt"] == 7.
    assert spec["style"]["margins_mm"] == {"left": 14., "right": 4.5, "top": 5.5, "bottom": 11.}
    assert len(spec["direct_labels"]) == len(spec["series"]) == 1
    series = spec["series"][0]
    assert series["x_values"] == [float(row[0]) for row in raw]
    assert series["y_values"] == [float(row[1]) for row in raw]
    assert spec["render_options"]["baseline"] == "none"
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    native, error = _run_veusz_audit([document])
    assert error is None
    audited = native["documents"][0]
    geometry = audited["direct_label_geometry"]
    assert geometry["coverage_complete"] and not geometry["unsupported"]
    assert geometry["outside_plot_paths"] == []
    assert geometry["labels"][0]["minimum_curve_clearance_mm"] >= 2.
    assert not any(issue["severity"] == "critical" for issue in _current_layout_issues(spec, document_path=document, native_audit=audited))
    request_path = project / "plot_request.json"
    assert json.loads(request_path.read_text())[KEY] == VERSION
    assert geometry["labels"][0]["ink_bounds_mm"][3] > geometry["labels"][0]["bounds_mm"][3]
    before = {str(path): file_sha256(path) for path in (source, document, spec_path, request_path)}
    exported = _cli("studio", project, "--export", "pdf,tiff_300")
    assert exported["studio_run"]["ready_to_use"] is True, exported
    assert exported["studio_run"]["qa"]["studio_layout"]["status"] == "passed"
    assert before == {str(path): file_sha256(path) for path in (source, document, spec_path, request_path)}

    # The original counterexample's legacy anchor intersects the descending
    # segment. Only this owned native copy is changed; no source/golden is edited.
    from sciplot_core.veusz_worker.document_edit import loaded_native_document
    bad = tmp_path / "legacy_anchor_counterexample.vsz"
    with loaded_native_document(document) as loaded:
        from veusz.document import CommandInterface
        numeric_before = {key: value.data.tobytes() for key, value in loaded.data.items() if hasattr(value.data, "tobytes")}
        interface = CommandInterface(loaded)
        interface.Set("/page1/graph1/label_1/xPos", [3800.])
        interface.Set("/page1/graph1/label_1/yPos", [97.499794])
        interface.Save(str(bad))
        assert numeric_before == {key: value.data.tobytes() for key, value in loaded.data.items() if hasattr(value.data, "tobytes")}
    bad_audit, error = _run_veusz_audit([bad])
    assert error is None
    actual_bad = bad_audit["documents"][0]
    assert actual_bad["direct_label_geometry"]["labels"][0]["minimum_curve_clearance_mm"] == 0.
    assert any(issue["severity"] == "critical" for issue in _current_layout_issues(spec, document_path=bad, native_audit=actual_bad))
    legacy_spec = deepcopy(spec)
    legacy_spec["source_request"].pop(KEY)
    # New diagnostic data never turns old unversioned/native-authoritative
    # documents into a new publication refusal or a silent automatic rearrange.
    assert _current_layout_issues(legacy_spec, document_path=bad, native_audit=actual_bad) == legacy_spec["layout_issues"]
    assert source.read_bytes() == original
    assert before == {str(path): file_sha256(path) for path in (source, document, spec_path, request_path)}
    # Exercise actual glyph descenders, native font fallback, and literal
    # escaped markup on owned copies. These copies are geometry probes, not
    # new scientific figures or accepted source-bound label edits.
    from sciplot_core.studio_core.series_request import veusz_literal_text
    glyph_cases = []
    for index, text in enumerate(("gy_pq", "光谱_μ", r"\alpha_{g_p}"), 1):
        probe = tmp_path / f"glyph_probe_{index}.vsz"
        with loaded_native_document(document) as loaded:
            interface = CommandInterface(loaded)
            interface.Set("/page1/graph1/label_1/label", veusz_literal_text(text))
            interface.Save(str(probe))
        probe_audit, error = _run_veusz_audit([probe])
        assert error is None
        probe_geometry = probe_audit["documents"][0]["direct_label_geometry"]
        assert probe_geometry["coverage_complete"], probe_geometry
        assert not probe_geometry["outside_plot_paths"]
        record = probe_geometry["labels"][0]
        assert record["ink_bounds_mm"][3] > record["bounds_mm"][3]
        glyph_cases.append({"text": text, "document": str(probe), "document_sha256": file_sha256(probe),
                            "geometry": probe_geometry})
    # Unsupported explicit current-native typography is never reported as a
    # complete automatic glyph proof. The saved copies remain unmodified by QA.
    unsupported_cases = []
    for index, (setting, value) in enumerate((("angle", 15.), ("Text/underline", True)), 1):
        probe = tmp_path / f"unsupported_glyph_probe_{index}.vsz"
        with loaded_native_document(document) as loaded:
            interface = CommandInterface(loaded)
            interface.Set(f"/page1/graph1/label_1/{setting}", value)
            interface.Save(str(probe))
        before_probe = file_sha256(probe)
        probe_audit, error = _run_veusz_audit([probe])
        assert error is None
        native_probe = probe_audit["documents"][0]
        assert native_probe["direct_label_geometry"]["coverage_complete"] is False
        assert any(issue["severity"] == "critical" for issue in _current_layout_issues(spec, document_path=probe, native_audit=native_probe))
        assert file_sha256(probe) == before_probe
        unsupported_cases.append({"setting": setting, "value": value, "document": str(probe),
                                  "geometry": native_probe["direct_label_geometry"]})
    (tmp_path / "native-evidence.json").write_text(json.dumps({"project": str(project),
        "source": str(source), "source_sha256": file_sha256(source), "document": str(document),
        "spec": str(spec_path), "before_after_sha256": before, "created": created, "exported": exported,
        "geometry": geometry, "glyph_cases": glyph_cases, "unsupported_glyph_cases": unsupported_cases, "counterexample_document": str(bad), "counterexample_geometry": actual_bad["direct_label_geometry"],
        "raw_numeric_and_source_replay": "passed", "fixed_frame_and_typography": "passed",
        "claim": "public synthetic regression, not private scientific acceptance"}, indent=2)+"\n")
