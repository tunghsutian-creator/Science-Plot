"""No-refit template restoration is revision-bound, reversible and native-faithful."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_render import render_tts_figures
from sciplot_core.workflow.rheology_tts_style_storage import publish_files, snapshot
from sciplot_core.workflow.rheology_tts_style_update import apply_suite_style, preview_suite_style
from sciplot_core.workflow.rheology_tts_suite import _compiled_figures, _publish, export_suite
from sciplot_core.workflow.rheology_tts_tables import write_json


def _saved_legacy_style(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("original evidence\n")
    sources = [{"path": str(source), "sha256": file_sha256(source)}]
    workspace, delivery = tmp_path / ".sciplot/Test", tmp_path / "Test"
    series = [{"label": label, "x": [10, 1, .1], "y": [1000 + i, 100 + i, 10 + i],
               "color": color, "marker": "none"}
              for i, (label, color) in enumerate(zip(["Control", "2 wt% UDC", "4 wt% UDC", "6 wt% UDC"],
                  ["#222222", "#3568C0", "#C83E4D", "#2A9D8F"], strict=True))]
    spec = {"version": 1, "figure_layout": "separate_polymer_modulus", "source_binding": {"sources": sources},
        "transform_ledger": {"processing": "synthetic fixture; no analysis"}, "figures": [{
            "id": "FS_HDPE_Gprime_210C", "polymer": "HDPE", "quantity": "storage_modulus_Pa",
            "data_basis": "original_210C_acquisition", "width_mm": 60, "height_mm": 55,
            "panels": [{"id": "graph1", "title": "HDPE", "rect_mm": [0, 0, 60, 55],
                "standard_frame": True, "x_label": "ω", "y_label": "G′", "xscale": "log", "yscale": "log",
                "x_min": .08, "x_max": 15, "y_min": 5, "y_max": 2000, "series": series}]}]}
    native = render_tts_figures(spec, workspace / "initial_render")
    for item in native["figures"]:
        item["spec_sha256"] = file_sha256(Path(item["spec_path"]))
    documents = _publish(workspace / "initial_render", delivery, spec, native)
    manifest = {"kind": "sciplot_rheology_tts_suite", "version": 1, "sources": sources,
        "workspace": str(workspace), "delivery": str(delivery), "figure_layout": "separate_polymer_modulus",
        "native_result": native, "documents": documents}
    for base in [workspace, delivery / "data"]:
        write_json(base / "figure_plan.json", spec)
        write_json(base / "analysis.json", {"must_remain": "exact processed analysis"})
    write_json(workspace / "suite.json", manifest)
    write_json(delivery / "data/delivery_manifest.json", manifest)
    return workspace, delivery, source, manifest


def test_preview_preserves_delivery_apply_updates_only_styles_and_retries_once(tmp_path):
    workspace, delivery, source, manifest = _saved_legacy_style(tmp_path)
    original = snapshot([source, delivery / "data/analysis.json", workspace / "analysis.json"])
    native = Path(manifest["documents"][0]["path"])
    before = file_sha256(native)
    preview = preview_suite_style(workspace)
    assert preview["changed_figures"] == 1
    assert file_sha256(native) == before
    receipt = json.loads(Path(preview["preview"]).read_text())
    assert {c["field"] for c in receipt["candidates"][0]["edit"]["changes"]} >= {"marker", "MarkerFill/hide", "MarkerLine/hide"}
    result = apply_suite_style(workspace, Path(preview["preview"]))
    assert result["status"] == "ready" and result["numerical_refit"] is False
    assert file_sha256(native) != before
    assert snapshot([Path(p) for p in original]) == original
    updated = json.loads((workspace / "suite.json").read_text())
    figure = _compiled_figures(updated)["FS_HDPE_Gprime_210C"]
    assert [s["encoding"]["marker"]["shape"] for s in figure["panels"][0]["series"]] == ["circle", "square", "diamond", "triangle"]
    after = file_sha256(native)
    assert apply_suite_style(workspace, Path(preview["preview"]))["already_applied"] is True
    assert file_sha256(native) == after
    assert preview_suite_style(workspace)["status"] == "no_change"
    assert export_suite(workspace)["exact_saved_export"] is True
    assert file_sha256(native) == after
    assert snapshot([Path(p) for p in original]) == original


@pytest.mark.parametrize("target", ["source", "candidate", "receipt", "hidden_analysis", "visible_analysis"])
def test_stale_or_modified_preview_is_rejected_without_delivery_changes(tmp_path, target):
    workspace, delivery, source, manifest = _saved_legacy_style(tmp_path)
    preview = preview_suite_style(workspace)
    before = snapshot([Path(d["path"]) for d in manifest["documents"]])
    path = Path(preview["preview"])
    receipt = json.loads(path.read_text())
    if target == "source":
        source.write_text("changed source\n")
    elif target == "candidate":
        candidate = Path(receipt["candidates"][0]["export"]["exports"][0]["path"])
        candidate.write_bytes(b"changed export")
    elif target in {"hidden_analysis", "visible_analysis"}:
        analysis = workspace / "analysis.json" if target == "hidden_analysis" else delivery / "data/analysis.json"
        analysis.write_text("changed analysis\n")
    else:
        changed = deepcopy(receipt)
        changed["baseline"] = {}
        write_json(path, changed)
    with pytest.raises(ValueError, match="changed|Stale"):
        apply_suite_style(workspace, path)
    assert snapshot([Path(p) for p in before]) == before
    assert not (path.parent / "applied.json").exists()


def test_partial_publication_rolls_back_all_applied_files(tmp_path, monkeypatch):
    from sciplot_core.workflow import rheology_tts_style_storage as storage

    old = [tmp_path / "one", tmp_path / "two"]
    new = [tmp_path / "new_one", tmp_path / "new_two"]
    for index, (a, b) in enumerate(zip(old, new, strict=True)):
        a.write_text(f"old {index}")
        b.write_text(f"new {index}")
    baseline = snapshot(old)
    replace = storage.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publication failure")
        return replace(source, target)

    monkeypatch.setattr(storage.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated"):
        publish_files(list(zip(new, old, strict=True)), tmp_path / "backup", expected=baseline,
                      candidates=snapshot(new), allowed_roots=(tmp_path,))
    assert snapshot(old) == baseline


def test_candidate_change_during_staging_cannot_publish_unreviewed_bytes(tmp_path, monkeypatch):
    from sciplot_core.workflow import rheology_tts_style_storage as storage

    source, target = tmp_path / "candidate", tmp_path / "visible"
    source.write_text("reviewed candidate")
    target.write_text("original")
    before, reviewed = snapshot([target]), snapshot([source])
    copy = storage.shutil.copy2

    def change_candidate(a, b, **kwargs):
        if Path(a) == source:
            source.write_text("unreviewed mutation")
        return copy(a, b, **kwargs)

    monkeypatch.setattr(storage.shutil, "copy2", change_candidate)
    with pytest.raises(ValueError, match="changed during staging"):
        publish_files([(source, target)], tmp_path / "backup", expected=before,
                      candidates=reviewed, allowed_roots=(tmp_path,))
    assert snapshot([target]) == before


def test_caller_supplies_display_labels_without_changing_numeric_science(tmp_path):
    from sciplot_core.rheology_tts_render import audit_tts_document
    from sciplot_core.rheology_tts_style import upgrade_tts_presentation

    workspace, delivery, source, manifest = _saved_legacy_style(tmp_path)
    plan = upgrade_tts_presentation(json.loads((workspace / "figure_plan.json").read_text()))
    plan["figures"][0]["panels"][0]["series"][0]["label"] = "Control · 210 °C"
    supplied = tmp_path / "presentation.json"
    write_json(supplied, plan)
    protected = snapshot([source, delivery / "data/analysis.json"])
    preview = preview_suite_style(workspace, presentation_plan=supplied)
    receipt = json.loads(Path(preview["preview"]).read_text())
    changes = receipt["candidates"][0]["edit"]["changes"]
    assert any(c["field"] == "key" and c["after_expected"] == "Control · 210 °C" for c in changes)
    assert apply_suite_style(workspace, Path(preview["preview"]))["status"] == "ready"
    current = json.loads((workspace / "suite.json").read_text())
    compiled = _compiled_figures(current)["FS_HDPE_Gprime_210C"]
    audit_tts_document(Path(manifest["documents"][0]["path"]), compiled, check_presentation=True)
    assert compiled["panels"][0]["series"][0]["legend_key"] == "Control · 210 °C"
    assert snapshot([Path(p) for p in protected]) == protected


def test_prepared_suite_display_update_without_analysis_preserves_science(tmp_path, monkeypatch):
    from sciplot_core.rheology_tts_render import audit_tts_document
    from sciplot_core.semantic_sources import rheology_tts
    from sciplot_core.workflow.rheology_tts_prepared import plot_prepared_suite

    def forbid_analysis(*_args, **_kwargs):
        pytest.fail("Prepared presentation updates must not calculate scientific analysis.")

    monkeypatch.setattr(rheology_tts, "analyze_tts_request", forbid_analysis)
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n3,10\n1,7\n1,9\n", encoding="utf-8")
    plan = {"version": 1, "figure_layout": "separate_polymer_modulus",
        "source_binding": {"sources": [{"path": str(source), "sha256": file_sha256(source)}]},
        "transform_ledger": {"processing": "Caller-supplied values; no fitting", "units": {"x": "rad/s", "y": "Pa"}},
        "figures": [{"id": "Prepared", "panels": [{"id": "graph1", "x_label": "ω (rad/s)",
            "y_label": "G′ (Pa)", "series": [{"role": "measured_curve", "label": "219.8 °C",
                "x": [3, 1, 1], "y": [10, 7, 9]}]}]}]}
    prepared = tmp_path / "prepared.json"
    request = tmp_path / "request.json"
    write_json(prepared, plan)
    write_json(request, {"version": 1, "prepared_plan": str(prepared), "out": str(tmp_path / "Figures")})
    result = plot_prepared_suite(request)
    workspace, delivery = Path(result["workspace"]), Path(result["delivery"])
    analysis_paths = [workspace / "analysis.json", delivery / "data/analysis.json"]
    assert not any(path.exists() for path in analysis_paths)
    protected = snapshot([source, prepared])
    before_plan = json.loads((workspace / "figure_plan.json").read_text())
    supplied = deepcopy(before_plan)
    supplied["figures"][0]["panels"][0]["series"][0]["label"] = "220 °C"
    supplied["figures"][0]["panels"][0]["legend"] = "upper_right"
    presentation = tmp_path / "presentation.json"
    write_json(presentation, supplied)

    preview = preview_suite_style(workspace, presentation_plan=presentation)

    receipt = json.loads(Path(preview["preview"]).read_text())
    assert preview["changed_figures"] == 1
    assert not any(str(path) in receipt["baseline"] for path in analysis_paths)
    applied = apply_suite_style(workspace, Path(preview["preview"]))
    assert applied["status"] == "ready" and applied["numerical_refit"] is False
    assert not any(path.exists() for path in analysis_paths)
    assert snapshot([source, prepared]) == protected
    after_plan = json.loads((workspace / "figure_plan.json").read_text())
    assert after_plan == supplied
    before_series = before_plan["figures"][0]["panels"][0]["series"][0]
    after_series = after_plan["figures"][0]["panels"][0]["series"][0]
    assert (after_series["x"], after_series["y"]) == (before_series["x"], before_series["y"])
    manifest = json.loads((workspace / "suite.json").read_text())
    native = Path(manifest["documents"][0]["path"])
    audit = audit_tts_document(native, _compiled_figures(manifest)["Prepared"], check_presentation=True)
    assert audit["status"] == "passed"
    assert apply_suite_style(workspace, Path(preview["preview"]))["already_applied"] is True

    # Optional scientific evidence, when actually supplied, remains a stale gate.
    write_json(analysis_paths[0], {"caller_evidence": "must remain bound"})
    supplied["figures"][0]["panels"][0]["series"][0]["label"] = "Reference sample"
    write_json(presentation, supplied)
    second = preview_suite_style(workspace, presentation_plan=presentation)
    second_receipt = json.loads(Path(second["preview"]).read_text())
    assert second_receipt["baseline"][str(analysis_paths[0])] == file_sha256(analysis_paths[0])
    delivered = snapshot([native, *(Path(p) for p in manifest["documents"][0]["exports"])])
    analysis_paths[0].unlink()
    with pytest.raises(ValueError, match="Stale presentation baseline"):
        apply_suite_style(workspace, Path(second["preview"]))
    assert snapshot([Path(path) for path in delivered]) == delivered


@pytest.mark.parametrize("change", ["coordinates", "ledger", "stale_plan"])
def test_presentation_plan_cannot_change_science_or_drift_after_preview(tmp_path, change):
    from sciplot_core.rheology_tts_style import upgrade_tts_presentation

    workspace, delivery, _, manifest = _saved_legacy_style(tmp_path)
    plan = upgrade_tts_presentation(json.loads((workspace / "figure_plan.json").read_text()))
    supplied = tmp_path / "presentation.json"
    if change == "coordinates":
        plan["figures"][0]["panels"][0]["series"][0]["y"][0] += 1
    elif change == "ledger":
        plan["transform_ledger"] = {"processing": "different analysis"}
    write_json(supplied, plan)
    before = snapshot([Path(d["path"]) for d in manifest["documents"]])
    if change == "stale_plan":
        preview = preview_suite_style(workspace, presentation_plan=supplied)
        supplied.write_text(supplied.read_text() + "\n")
        with pytest.raises(ValueError, match="Stale|changed"):
            apply_suite_style(workspace, Path(preview["preview"]))
    else:
        with pytest.raises(ValueError):
            preview_suite_style(workspace, presentation_plan=supplied)
    assert snapshot([Path(p) for p in before]) == before
