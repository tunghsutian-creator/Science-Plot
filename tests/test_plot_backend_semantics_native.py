"""Phase 2 real native round trips, reviewed once with unchanged scientific data."""

from collections import Counter
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.plot_backends import VeuszBackend
from sciplot_core.plot_document import apply_patch
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head
from sciplot_core.studio_core.annotation_operations import preview_document_operations
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.project_query import inspect_project


class CountingBackend(VeuszBackend):
    def __init__(self):
        super().__init__()
        self.calls = Counter()

    def preview(self, *args):
        self.calls["preview"] += 1
        return super().preview(*args)


def create_project(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    created = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
                              "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"],
                             capture_output=True, text=True, timeout=180, cwd=REPO_ROOT)
    assert created.returncode == 0, created.stdout + created.stderr
    return source, Path(json.loads(created.stdout)["project_dir"])


def change(target, prop, value):
    return {"op": "set", "target": [target], "property": prop, "value": value}


@pytest.mark.comprehensive
def test_reviewed_axes_legend_annotations_restart_and_rollback(tmp_path):
    source, project = create_project(tmp_path)
    source_bytes = source.read_bytes()
    initial = inspect_project(project, native=True)["selected_figure"]
    key = "/page1/graph1/key1"
    seed = [{"op": "add_annotation", "id": "note_axes", "parent_path": "/page1/graph1", "text": "Observed value",
             "position": {"mode": "axes", "x": 450, "y": 3.5, "x_unit": "nm", "y_unit": "a.u."},
             "arrow_to": {"mode": "axes", "x": 450, "y": 3, "x_unit": "nm", "y_unit": "a.u."}},
            {"op": "add_annotation", "id": "note_relative", "parent_path": "/page1/graph1", "text": "Fixed note",
             "position": {"mode": "relative", "x": 0.05, "y": 0.85}}]
    seed.extend({"op": "set_style", "object_path": key, "setting_path": key + "/" + name,
                 "expected_value": initial["objects"][key]["settings"][name], "value": value}
                for name, value in {"horzPosn": "right", "vertPosn": "top"}.items())
    review = preview_document_operations(project, seed, output_dir=tmp_path / "seed",
                                         expected_document_sha256=initial["document_sha256"])
    apply_document_edit(project, review)
    original = inspect_project(project, native=True, include_annotations=True)["selected_figure"]
    original_spec = json.loads(Path(original["spec"]).read_bytes())
    backend = CountingBackend()
    service = PlotService(backend)
    opened = service.open(project)
    root = Path(opened["plot"])
    document = load_head(root)["document"]
    assert document["presentation"]["objects"]["legend:key1"]["properties"]["legend.position"] is None
    native_bytes = Path(original["document"]).read_bytes()

    def request(key, changes):
        return {"plot_id": opened["plot_id"], "base_revision": load_head(root)["document"]["revision"],
                "idempotency_key": key, "intent_class": "presentation", "changes": changes}

    patch = request("phase2", [change("axis:x", "axis.limits", [390, 510]), change("axis:y", "axis.limits", [0, 5]),
        change("annotation:note_axes", "annotation.text", "Reviewed value"),
        change("annotation:note_axes", "annotation.position", [475, 3.8]),
        change("annotation:note_relative", "annotation.visible", False),
        change("legend:key1", "legend.position", [0.7, 0.5]), change("legend:key1", "legend.visible", False)])
    reviewed = service.patch(root, patch)
    assert reviewed["status"] == "needs_review", reviewed
    assert reviewed["effective_risk"] == "review" and reviewed["scientific_audit"]["status"] == "passed"
    assert Path(original["document"]).read_bytes() == native_bytes
    assert service.patch(root, patch)["status"] == "needs_review"
    assert backend.calls["preview"] == 1
    complete = PlotService(backend).decide(root, reviewed["next_step"]["request"])
    assert complete["status"] == "complete" and complete["ready_to_use"], complete
    saved = inspect_project(project, native=True, include_annotations=True)["selected_figure"]
    changed_spec = json.loads(Path(saved["spec"]).read_bytes())
    assert changed_spec["series"] == original_spec["series"]
    assert changed_spec["legend"]["show"] is False and saved["objects"][key]["settings"]["hide"] == 1
    assert changed_spec["native_annotations"]["items"][0]["position"] == {
        "mode": "axes", "x": 475, "y": 3.8, "x_unit": "nm", "y_unit": "a.u."}
    for name, bounds in (("x", [390, 510]), ("y", [0, 5])):
        settings = saved["objects"][f"/page1/graph1/{name}"]["settings"]
        assert [settings["min"], settings["max"]] == bounds
        assert settings["MajorTicks/manualTicks"] == original["objects"][f"/page1/graph1/{name}"]["settings"]["MajorTicks/manualTicks"]
        assert changed_spec["axes"][name]["ticks"] == original_spec["axes"][name]["ticks"]
        assert changed_spec["axis_data_visibility"]["axes"][name]["clipped_coordinate_count"] == 0
    edited = PlotService(backend).patch(root, request("hidden", [change("annotation:note_relative", "annotation.text", "Saved hidden note"),
        change("annotation:note_relative", "annotation.position", [0.25, 0.75])]))
    assert edited["status"] == "needs_review", edited
    assert PlotService(backend).decide(root, edited["next_step"]["request"])["status"] == "complete"
    shown = PlotService(backend).patch(root, request("show", [change("annotation:note_relative", "annotation.visible", True)]))
    assert shown["status"] == "needs_review", shown
    assert PlotService(backend).decide(root, shown["next_step"]["request"])["status"] == "complete"
    restored_note = inspect_project(project, native=True, include_annotations=True)["selected_figure"]["annotations"]
    assert next(item for item in restored_note if item["id"] == "note_relative")["text"] == "Saved hidden note"
    before_undo_calls = backend.calls["preview"]
    undone = PlotService(backend).rollback(root, {"base_revision": 3, "target_revision": 0, "idempotency_key": "undo"})
    assert undone["status"] == "needs_review", undone
    assert backend.calls["preview"] == before_undo_calls + 1
    final = PlotService(backend).decide(root, undone["next_step"]["request"])
    assert final["status"] == "complete" and final["revision"] == 4 and final["ready_to_use"], final
    final_head = load_head(root)["document"]
    assert final_head["presentation_hash"] == document["presentation_hash"]
    assert final_head["scientific_hash"] == document["scientific_hash"]
    restored = inspect_project(project, native=True, include_annotations=True)["selected_figure"]
    assert sorted(restored["annotations"], key=lambda item: item["id"]) == sorted(original["annotations"], key=lambda item: item["id"])
    for name in ("horzPosn", "vertPosn", "horzManual", "vertManual", "hide"):
        assert restored["objects"][key]["settings"][name] == original["objects"][key]["settings"][name]
    assert source.read_bytes() == source_bytes
    clipped = PlotService(backend).patch(root, request("clipping-rejected", [change("axis:x", "axis.limits", [425, 500])]))
    assert clipped["status"] == "blocked" and clipped["error"]["reason_code"] == "axis_clipping_not_authorized", clipped
    assert load_head(root)["document"]["revision"] == 4
    evidence = REPO_ROOT / ".tmp_verify/document_migration_20261007/phase2_native_acceptance.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"status": "passed", "scope": "phase2 axes, legend, ordinary managed annotations",
        "fixture": str(project), "one_preview_per_review": True, "review_count": before_undo_calls + 1,
        "native_spec_series_unchanged": True, "source_bytes_unchanged": True,
        "scientific_hash_unchanged": True, "rollback_restores_presentation_and_legend_preset": True,
        "clipping_reason_code": clipped["error"]["reason_code"], "warm_worker_starts": backend._worker.starts}, indent=2))
    backend.close()


@pytest.mark.comprehensive
def test_reversed_native_axis_limits_preserve_direction_ticks_and_rollback(tmp_path):
    source, project = create_project(tmp_path)
    source_bytes = source.read_bytes()
    from sciplot_core.studio_core.studio_prepare import prepare_studio_document

    request_path = project / "plot_request.json"
    request = json.loads(request_path.read_bytes())
    request.setdefault("render_options", {})["reverse_x"] = True
    request_path.write_text(json.dumps(request))
    prepare_studio_document(project, regenerate_generated=True)
    backend = VeuszBackend()
    document, binding = backend.import_project(project, plot_id="reversed")
    original = inspect_project(project, native=True)["selected_figure"]
    original_spec = json.loads(Path(original["spec"]).read_bytes())
    obj = document["presentation"]["objects"]["axis:x"]
    limits = obj["properties"]["axis.limits"]
    assert limits[0] > limits[1] and obj["capabilities"]["axis.limits"]["direction"] == "descending"
    request = {"plot_id": document["plot_id"], "base_revision": 0, "idempotency_key": "expand", "intent_class": "review",
               "changes": [change("axis:x", "axis.limits", [limits[0] + 10, limits[1] - 10])]}
    new, diff, risk = apply_patch(document, request)
    review = backend.preview(document, binding, new, diff, tmp_path / "reverse-expand")
    assert risk == "review" and review["scientific_audit"]["status"] == "passed"
    binding = backend.refresh_binding(binding, backend.apply(binding, review))
    expanded = inspect_project(project, native=True)["selected_figure"]
    settings = expanded["objects"]["/page1/graph1/x"]["settings"]
    assert [settings["min"], settings["max"]] == [limits[0] + 10, limits[1] - 10]
    request["changes"] = [change("axis:x", "axis.limits", limits)]
    restored, diff, _ = apply_patch(new, request)
    review = backend.preview(new, binding, restored, diff, tmp_path / "reverse-undo")
    binding = backend.refresh_binding(binding, backend.apply(binding, review))
    final = inspect_project(project, native=True)["selected_figure"]
    for name in ("min", "max", "MajorTicks/manualTicks", "label", "direction", "mode"):
        assert final["objects"]["/page1/graph1/x"]["settings"][name] == original["objects"]["/page1/graph1/x"]["settings"][name]
    assert json.loads(Path(final["spec"]).read_bytes())["series"] == original_spec["series"]
    assert source.read_bytes() == source_bytes
    evidence = REPO_ROOT / ".tmp_verify/document_migration_20261007/phase2_native_reversed_acceptance.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"status": "passed", "fixture": str(project), "native_initial_bounds": limits,
        "native_expanded_bounds": [settings["min"], settings["max"]], "source_bytes_unchanged": True,
        "series_unchanged": True, "direction_units_ticks_restored": True,
        "warm_worker_starts": backend._worker.starts}, indent=2))
    backend.close()
