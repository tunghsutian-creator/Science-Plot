from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends import VeuszBackend
from sciplot_core.plot_backends import veusz, veusz_import
from sciplot_core.plot_backends.veusz_compile import compile_diff
from sciplot_core.plot_document import DocumentError, apply_patch


@pytest.fixture
def imported(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n")
    native = project / "document.vsz"
    native.write_bytes(b"native current with custom styles and opaque content")
    specification = project / "spec.json"
    spec = {"series": [{"name": "series_1", "label": "E2", "line_width_pt": 1.2,
                        "x_values": [1], "y_values": [2]}], "unrecognized_evidence": {"keep": True}}
    specification.write_text(json.dumps(spec))
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": str(source)}))
    curve = "/page1/graph1/series_1"
    annotation = {"op": "add_annotation", "id": "spectrum_title", "parent_path": "/page1/graph1",
                  "text": "Measured spectrum", "position": {"mode": "relative", "x": 0.1, "y": 0.9}}
    query = {"project": str(project), "request_sha256": file_sha256(request),
             "source": {"status": "unknown", "current": None, "input": {}},
             "selected_figure": {"figure_id": "f", "spec": str(specification), "document": str(native),
                                 "spec_sha256": file_sha256(specification), "document_sha256": file_sha256(native),
                                 "annotations": [annotation], "objects": {
                    curve: {"type": "xy", "name": "series_1", "editable_fields": [
                        {"setting_path": curve + "/PlotLine/width", "current_value": "0.7pt"},
                        {"setting_path": curve + "/PlotLine/color", "current_value": "#123456"}]},
                    "/page1/graph1/sciplot_annotation_spectrum_title": {
                        "type": "label", "name": "sciplot_annotation_spectrum_title", "editable_fields": []}}}}
    monkeypatch.setattr(veusz_import, "inspect_project", lambda *a, **kw: deepcopy(query))
    monkeypatch.setattr(veusz_import, "_source_records", lambda spec: {source: file_sha256(source)})
    monkeypatch.setattr(veusz_import, "audit_edited_document", lambda *a: {"status": "passed"})
    document, binding = VeuszBackend().import_project(project, plot_id="plot1")
    return document, binding, query, source


def _patch(document, changes):
    return apply_patch(document, {"plot_id": document["plot_id"], "base_revision": document["revision"],
                                  "idempotency_key": "one", "intent_class": "presentation", "changes": changes})


def test_import_native_styles_and_opaque_baseline_without_claiming_full_conversion(imported):
    document, binding, _, _ = imported
    obj = document["presentation"]["objects"]["series:E2"]
    assert obj["properties"]["style.line.width"] == "0.7pt"
    assert obj["properties"]["style.line.color"] == "#123456"
    assert document["scientific"]["provenance"]["imported_specification"]["unrecognized_evidence"] == {"keep": True}
    assert document["coverage"]["mode"] == "legacy_shadow"
    assert document["scientific"]["guards"]["source_status_at_import"] == "unknown"
    assert "/page1/graph1" not in json.dumps(document["presentation"])
    assert binding["targets"]["series:E2"]["object_path"] == "/page1/graph1/series_1"


def test_duplicate_and_non_ascii_labels_have_valid_unambiguous_ids(imported):
    _, _, query, _ = imported
    selected = deepcopy(query["selected_figure"])
    widget = selected["objects"]["/page1/graph1/series_1"]
    selected["objects"]["/page1/graph1/series_2"] = {**deepcopy(widget), "name": "series_2"}
    for field in selected["objects"]["/page1/graph1/series_2"]["editable_fields"]:
        field["setting_path"] = field["setting_path"].replace("series_1", "series_2")
    objects, targets = veusz_import._presentation(selected, {"series": [
        {"name": "series_1", "label": "试样 A"}, {"name": "series_2", "label": "试样 A"}]})
    series = [key for key in objects if key.startswith("series:")]
    assert len(series) == 2 and len(set(series)) == 2
    assert [objects[key]["label"] for key in series] == ["试样 A", "试样 A"]
    assert targets[series[0]]["object_path"] != targets[series[1]]["object_path"]


def test_width_delta_uses_current_expected_value_and_no_annotation_rebuild(imported, monkeypatch, tmp_path):
    document, binding, _, _ = imported
    new, diff, _ = _patch(document, [{"op": "set", "target": ["series:E2"], "property": "style.line.width", "value": "0.8pt"}])
    calls = []
    monkeypatch.setattr(veusz, "preview_document_edit", lambda *a, **kw: calls.append((a, kw)) or {"status": "ready"})
    result = VeuszBackend().preview(document, binding, new, diff, tmp_path / "preview")
    changes = calls[0][0][1]
    assert changes[0]["expected_value"] == "0.7pt" and changes[0]["value"] == "0.8pt"
    assert calls[0][1]["operations"] is None
    assert result["_backend_updates"]["targets"]["series:E2"]["properties"]["style.line.width"]["current_value"] == "0.8pt"
    assert new["scientific_hash"] == document["scientific_hash"]


def test_title_hide_and_restore_compiles_same_annotation_record(imported):
    document, binding, _, _ = imported
    new, diff, _ = _patch(document, [{"op": "set", "target": ["title:spectrum_title"], "property": "title.visible", "value": False}])
    _, operations, updates = compile_diff(document, binding, new, diff)
    original = binding["targets"]["title:spectrum_title"]["annotation"]
    assert operations == [{"op": "remove_annotation", "id": "spectrum_title", "expected_annotation": original}]
    restored, inverse, _ = _patch(new, [{"op": "set", "target": ["title:spectrum_title"], "property": "title.visible", "value": True}])
    _, undo, _ = compile_diff(new, {**binding, **updates}, restored, inverse)
    assert undo == [original]


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_imported_title_advertises_native_text_limits_before_render(imported, text):
    document, _, _, _ = imported
    with pytest.raises(DocumentError) as failure:
        _patch(document, [{"op": "set", "target": ["title:spectrum_title"], "property": "title.text", "value": text}])
    assert failure.value.reason_code == "document_invalid_value"


def test_external_source_or_native_change_blocks_before_preview(imported, tmp_path, monkeypatch):
    document, binding, _, source = imported
    new, diff, _ = _patch(document, [{"op": "set", "target": ["series:E2"], "property": "style.line.width", "value": "1pt"}])
    monkeypatch.setattr(veusz, "preview_document_edit", lambda *a, **kw: pytest.fail("native preview must not start"))
    source.write_text("changed scientific source")
    with pytest.raises(DocumentError) as failure:
        VeuszBackend().preview(document, binding, new, diff, tmp_path / "unused")
    assert failure.value.reason_code == "backend_changed"
    assert failure.value.repair["action"] == "resolve_input_conflict"
    assert failure.value.issues[0]["changed_paths"] == [str(source)]
    assert not (tmp_path / "unused").exists()


def test_false_source_status_cannot_be_adopted_as_new_baseline(imported, monkeypatch):
    _, binding, query, _ = imported
    query["source"] = {"status": "stale", "current": False}
    monkeypatch.setattr(veusz_import, "inspect_project", lambda *a, **kw: query)
    monkeypatch.setattr(veusz_import, "audit_edited_document", lambda *a: pytest.fail("stale import audited"))
    with pytest.raises(ValueError) as failure:
        VeuszBackend().import_project(Path(binding["project"]))
    assert failure.value.reason_code == "source_changed"


def test_lost_apply_response_delegates_to_durable_native_recovery(imported, monkeypatch):
    _, binding, _, _ = imported
    Path(binding["document"]).write_bytes(b"already applied document")
    calls = []
    monkeypatch.setattr(veusz, "apply_document_edit", lambda project, review: calls.append(review) or {"status": "already_applied"})
    result = VeuszBackend().apply(binding, {"operation_id": "a" * 64, "_backend_updates": {"targets": {}}})
    assert result["status"] == "already_applied"
    assert calls == [{"operation_id": "a" * 64}]


def test_refresh_does_not_adopt_unrelated_source_drift(imported):
    _, binding, _, source = imported
    source.write_text("changed")
    with pytest.raises(DocumentError):
        VeuszBackend().refresh_binding(binding, {"status": "applied", "document_sha256": file_sha256(Path(binding["document"]))})


@pytest.mark.parametrize("field", ["document", "spec"])
def test_refresh_does_not_adopt_external_native_change_after_commit(imported, field):
    _, binding, _, _ = imported
    applied = {"status": "applied", "document_sha256": file_sha256(Path(binding["document"]))}
    Path(binding[field]).write_text("unrelated external replacement")
    with pytest.raises(DocumentError, match="changed after apply"):
        VeuszBackend().refresh_binding(binding, applied)


def test_native_label_name_alone_does_not_infer_a_title(imported):
    _, _, query, _ = imported
    selected = deepcopy(query["selected_figure"])
    selected["annotations"] = []
    objects, _ = veusz_import._presentation(selected, {"series": []})
    assert not any(obj["kind"] == "title" for obj in objects.values())


def test_export_rechecks_native_binding_after_acquiring_project_lease(imported, monkeypatch):
    _, binding, _, _ = imported

    @contextmanager
    def intervening_commit(project):
        Path(binding["document"]).write_text("a direct client committed before lease acquisition")
        yield

    monkeypatch.setattr(veusz, "external_project_session", intervening_commit)
    monkeypatch.setattr(veusz, "export_project_document", lambda **kw: pytest.fail("stale binding exported"))
    with pytest.raises(DocumentError) as failure:
        VeuszBackend().export(binding)
    assert failure.value.repair["action"] == "resolve_input_conflict"
