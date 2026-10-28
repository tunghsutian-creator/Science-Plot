"""Known categorical native expectations are checked before effect admission."""

from copy import deepcopy
import json

import pytest

from test_categorical_display import categorical as categorical
from test_project_export_use_case import publication as publication

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectCommandUnknown
from sciplot_core.studio_core import document_edit, project_query
from sciplot_core.studio_core.annotation_batch import compile_annotation_operations
from sciplot_core.studio_core.annotation_operations import preview_document_operations
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.studio_core.project_export import export_project_document


@pytest.fixture
def admitted(publication, categorical, monkeypatch):
    project, exports, _published = publication
    document, spec = project / "studio/document.vsz", project / "studio/spec.json"
    original_sources = json.loads(spec.read_text())["series"][0]["source_artifacts"]
    for item in categorical["series"]:
        item["source_artifacts"] = original_sources
    # Legacy native legend settings, rather than this stale spec annotation,
    # are the presentation authority used by the existing context descriptor.
    categorical["legend"]["columns"] = 1
    spec.write_text(json.dumps(categorical))
    store = project_store(project, create_delivery=True, with_snapshot=True)
    initial = store.snapshot(import_legacy=True)
    current = {"columns": 3.0, "horzPosn": "manual", "vertPosn": "manual"}
    effects, inspections = [], []

    def inspect(path):
        assert path == document
        inspections.append(path)
        return {"kind": "sciplot_veusz_document_state", "version": 1, "status": "passed",
                "document": {"path": str(path), "sha256": file_sha256(path)},
                "widgets": {"/page1/graph1/key1": {"settings": dict(current)}}}

    def candidate(path, specification, _changes, output, *, operations, figure_id):
        effects.append(path)
        if any(operation.get("legend", {}).get("expected", current) != current for operation in operations):
            raise ValueError("Stale categorical legend reached the native effect")
        _, after, changes = compile_annotation_operations(json.loads(specification.read_text()), operations,
            document_sha256=file_sha256(path), figure_id=figure_id)
        saved, after_spec, image = output / "candidate.vsz", output / "candidate.spec.json", output / "candidate.png"
        saved.write_bytes(path.read_bytes() + b"\nreviewed categorical legend")
        after_spec.write_text(json.dumps(after))
        image.write_bytes(b"controlled categorical preview")
        return {"changes": changes, "candidate": {"path": str(saved), "sha256": file_sha256(saved)},
                "candidate_spec": {"path": str(after_spec), "sha256": file_sha256(after_spec)},
                "preview": {"path": str(image), "sha256": file_sha256(image), "width": 20, "height": 20},
                "scientific_audit": {"status": "passed"}}

    monkeypatch.setattr(project_query, "_inspect_document", inspect)
    monkeypatch.setattr(document_edit, "_candidate", candidate)
    monkeypatch.setattr(document_edit, "audit_edited_document", lambda *_args: {"status": "passed"})
    return project, document, spec, store, initial, current, effects, inspections, exports


def legend(current):
    return {"op": "set_categorical_display_style", "legend": {
        "position": "upper_right", "columns": 2, "expected": dict(current)}}


def preview(admitted, tmp_path, operation, name):
    project, document, *_rest = admitted
    return preview_document_operations(project, [operation], output_dir=tmp_path / name,
        expected_document_sha256=file_sha256(document))


@pytest.mark.parametrize("field,value", [("columns", 1), ("horzPosn", "left"), ("vertPosn", "top")])
def test_stale_native_legend_leaves_no_unknown_and_allows_review_then_cold_export(admitted, tmp_path, field, value):
    project, document, spec, store, initial, current, effects, inspections, exports = admitted
    original = {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                for path in (document, spec, project / "plot_request.json", project / "source/data.csv")}
    invalid = legend(current)
    invalid["legend"]["expected"][field] = value
    with pytest.raises(ValueError):
        preview(admitted, tmp_path, invalid, "invalid")
    assert effects == [] and not store.commands()
    assert store.snapshot()["generation"] == initial["generation"]
    assert {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns) for path in original} == original
    # A current native value of 3 remains valid although the spec says 1.
    review = preview(admitted, tmp_path, legend(current), "valid")
    assert len(effects) == 1 and len(inspections) == 2
    saved = document_edit.apply_document_edit(project, review)
    assert saved["result_is_current"] and len(effects) == 1
    result = export_project_document(project_dir=project, formats=["pdf"])
    assert result.ready_to_use and [call[0] for call in exports] == ["export", "publish"]
    assert [record["phase"] for record in store.commands()] == ["complete", "complete"]
    for path in (project / "plot_request.json", project / "source/data.csv"):
        assert (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns) == original[path]


@pytest.mark.parametrize("fault", ["missing_key", "missing_field", "wrong_document", "wrong_hash"])
def test_native_precondition_requires_complete_exact_selected_descriptor(admitted, tmp_path, monkeypatch, fault):
    project, document, _spec, store, initial, current, effects, _inspections, _exports = admitted
    inspect = project_query._inspect_document

    def malformed(path):
        result = inspect(path)
        if fault == "missing_key":
            result["widgets"].clear()
        elif fault == "missing_field":
            result["widgets"]["/page1/graph1/key1"]["settings"].pop("columns")
        elif fault == "wrong_document":
            result["document"]["path"] = str(project / "foreign.vsz")
        else:
            result["document"]["sha256"] = "a" * 64
        return result

    monkeypatch.setattr(project_query, "_inspect_document", malformed)
    with pytest.raises(ValueError):
        preview(admitted, tmp_path, legend(current), "invalid-descriptor")
    assert not effects and not store.commands()
    assert store.snapshot()["generation"] == initial["generation"]


def test_unknown_native_effect_still_blocks_export_and_never_reexecutes(admitted, tmp_path, monkeypatch):
    project, document, _spec, store, initial, current, effects, _inspections, exports = admitted

    def uncertain(_document, _specification, _changes, output, **_kwargs):
        effects.append("private native effect")
        (output / "partial.vsz").write_bytes(b"private candidate written before lost reply")
        raise RuntimeError("lost native reply after private effect")

    monkeypatch.setattr(document_edit, "_candidate", uncertain)
    with pytest.raises(RuntimeError, match="lost native reply"):
        preview(admitted, tmp_path, legend(current), "uncertain")
    record, = store.commands()
    assert record["phase"] == "unknown" and "draft" not in record
    with pytest.raises(ProjectCommandUnknown):
        ProjectCommands(store).resume(ProjectCommand.from_payload(record["metadata"]))
    with pytest.raises(ProjectCommandUnknown):
        export_project_document(project_dir=project, formats=["pdf"])
    assert effects == ["private native effect"] and exports == []
    assert store.snapshot()["generation"] == initial["generation"]
    assert file_sha256(document) == initial["files"]["studio/document.vsz"]["sha256"]


def test_late_native_legend_rejection_remains_unknown_without_publication(admitted, tmp_path, monkeypatch):
    project, document, spec, store, initial, current, effects, _inspections, exports = admitted
    original = {path: path.read_bytes() for path in (document, spec, project / "source/data.csv")}
    candidate = document_edit._candidate

    def late_change(*args, **kwargs):
        # The worker's final native comparison is still required even after
        # a successful read-only preflight. No generic exception is terminalized.
        current["columns"] = 4.0
        return candidate(*args, **kwargs)

    monkeypatch.setattr(document_edit, "_candidate", late_change)
    with pytest.raises(ValueError, match="reached the native effect"):
        preview(admitted, tmp_path, legend(current), "late-rejection")
    record, = store.commands()
    assert record["phase"] == "unknown" and len(effects) == 1
    with pytest.raises(ProjectCommandUnknown):
        export_project_document(project_dir=project, formats=["pdf"])
    assert not exports and store.snapshot()["generation"] == initial["generation"]
    assert {path: path.read_bytes() for path in original} == original


@pytest.mark.parametrize("kind", ["category", "series"])
def test_other_categorical_expected_values_still_reject_before_native_effect(admitted, tmp_path, kind):
    _project, document, spec, store, _initial, _current, effects, inspections, _exports = admitted
    if kind == "category":
        operation = {"op": "set_category_display_labels", "changes": [
            {"category_id": "P", "expected_label": "stale", "label": "Control"}]}
    else:
        from sciplot_core.studio_core.categorical_display import context

        target = context(json.loads(spec.read_text()))["style_targets"][0]
        expected = {**deepcopy(target["current_style"]), "color": "#aabbcc"}
        operation = {"op": "set_categorical_display_style", "changes": [
            {"series_id": target["series_id"], "expected_style": expected, "style": {"color": "#112233"}}]}
    with pytest.raises(ValueError):
        preview(admitted, tmp_path, operation, "invalid-original")
    assert not effects and inspections == [document] and not store.commands()
