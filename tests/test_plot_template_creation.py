"""Template bindings are source-bound and remain one durable semantic operation."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_engine import creation, template_creation
from sciplot_core.plot_engine.template_creation_binding import prepare


def template_request(source: Path, *, key: str = "template-create") -> dict[str, Any]:
    objects = {"slot:" + name: {"kind": "series", "label": "template " + name,
        "properties": {"style.line.width": "1.1pt", "style.line.color": color},
        "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"},
                         "style.line.color": {"type": "color", "risk": "presentation"}}}
        for name, color in (("E2", "#2878B5"), ("E4", "#C82423"))}
    template = {"kind": "sciplot_template", "schema_version": 1, "template_id": "paired-spectra",
                "presentation": {"objects": objects, "layout": {}, "theme": {}, "export_configuration": {}},
                "series_slots": list(objects)}
    binding = {"kind": "sciplot_binding", "schema_version": 1, "template_id": "paired-spectra",
        "data_sources": [{"source_id": "raw", "sha256": file_sha256(source), "path": str(source),
            "table_selection": {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2,
                                "data_start_row": 3, "data_end_row": 6}}],
        "slots": {"slot:" + name: {"series_id": "bound:" + name, "sample": name,
                    "x": {"source_id": "raw", "column": "Wavelength", "column_index": offset},
                    "y": {"source_id": "raw", "column": "Absorbance", "column_index": offset + 1},
                    "x_unit": "nm", "y_unit": "a.u."} for name, offset in (("E2", 0), ("E4", 2))},
        "transforms": [], "guards": {}, "provenance": {"scope": "original source cells"}}
    return {"idempotency_key": key, "mode": "legacy", "template_definition": template, "data_binding": binding,
            "rule_id": "uvvis_spectrum", "theme": {"kind": "sciplot_theme", "schema_version": 1,
                "theme_id": "thin-lines", "rules": [{"target": ["bound:E2", "bound:E4"],
                    "property": "style.line.width", "value": "0.7pt"}]}}


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "UVvis.csv"
    path.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                    "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    return path


def test_explicit_binding_compiles_to_existing_mapping_without_rewriting_source(source: Path) -> None:
    raw = source.read_bytes()
    request = template_request(source)
    path, task, desired = prepare(request)
    assert path == source and source.read_bytes() == raw
    assert task["mapping"] == {"source_sha256": file_sha256(source),
        "table_selection": request["data_binding"]["data_sources"][0]["table_selection"],
        "column_mapping": {"pairs": [{"x_column": 0, "y_column": 1}, {"x_column": 2, "y_column": 3}]}}
    assert desired["presentation"]["objects"]["bound:E2"]["properties"]["style.line.width"] == "0.7pt"
    assert not (source.parent / ".sciplot_documents").exists()


@pytest.mark.parametrize("change,reason", [
    ("sha", "template_source_changed"), ("unit", "template_metadata_conflict"),
    ("column", "template_metadata_conflict"), ("sample", "template_sample_conflict"),
    ("region", "template_table_selection_required"), ("index", "template_column_binding_required"),
    ("transform", "template_transform_executor_required"), ("layout", "template_unsupported_presentation"),
    ("guard", "template_guard_executor_required"),
])
def test_invalid_template_input_stops_before_creation(source: Path, change: str, reason: str) -> None:
    request = template_request(source)
    binding = request["data_binding"]
    if change == "sha":
        binding["data_sources"][0]["sha256"] = "0" * 64
    elif change == "unit":
        binding["slots"]["slot:E2"]["x_unit"] = "s"
    elif change == "column":
        binding["slots"]["slot:E2"]["x"]["column"] = "Frequency"
    elif change == "sample":
        binding["slots"]["slot:E2"]["sample"] = "Wrong sample"
    elif change == "region":
        del binding["data_sources"][0]["table_selection"]
    elif change == "index":
        del binding["slots"]["slot:E2"]["x"]["column_index"]
    elif change == "transform":
        binding["transforms"] = [{"operation": "smooth"}]
    elif change == "guard":
        binding["guards"] = {"custom": "not an implemented rule"}
    else:
        request["template_definition"]["presentation"]["layout"] = {"width_mm": 60}
    with pytest.raises(DocumentError) as error:
        prepare(request)
    assert error.value.reason_code == reason
    assert not (source.parent / ".sciplot_documents").exists()


def test_missing_numeric_cell_is_not_dropped_or_interpolated(source: Path) -> None:
    source.write_text(source.read_text().replace("450,2,450,3", "450,,450,3"))
    with pytest.raises(DocumentError) as error:
        prepare(template_request(source))
    assert error.value.reason_code == "template_column_rejected"
    assert ",," in source.read_text()


def test_invalid_row_bounds_return_source_field_before_allocating(source: Path) -> None:
    request = template_request(source)
    request["data_binding"]["data_sources"][0]["table_selection"]["data_end_row"] = 100
    with pytest.raises(DocumentError) as error:
        prepare(request)
    assert error.value.reason_code == "template_table_rejected"
    assert error.value.issues[0]["path"] == "/data_binding/data_sources/0/table_selection"
    assert not (source.parent / ".sciplot_documents").exists()


def test_committed_template_retry_reuses_frozen_patch_without_restarting_source_task(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = template_request(source)
    starts: list[dict[str, Any]] = []
    patches: list[dict[str, Any]] = []
    _, _, desired = prepare(request)

    class Service:
        def open(self, target: Path, figure_id: str | None = None) -> dict[str, Any]:
            pytest.fail("Template creation must adopt identities before its first commit")

        def open_created(self, target: Path, *, series_ids: dict[str, str], recipe: dict[str, Any], figure_id: str | None = None) -> dict[str, Any]:
            assert series_ids == {"E2": "bound:E2", "E4": "bound:E4"}
            assert recipe["data_binding"] == request["data_binding"]
            objects = deepcopy(desired["presentation"]["objects"])
            for obj in objects.values():
                obj["properties"]["style.line.width"] = "1pt"
            return {"status": "current", "plot": str(source.parent / "plot"), "plot_id": "new-plot", "revision": 0,
                    "coverage": {"mode": "legacy_shadow"}, "objects": objects}

        def describe(self, plot: Path) -> dict[str, Any]:
            pytest.fail("Retry should use the frozen patch, not recalculate a new one")

        def patch(self, plot: Path, patch: dict[str, Any]) -> dict[str, Any]:
            patches.append(deepcopy(patch))
            return {"status": "blocked" if len(patches) == 1 else "complete", "revision": 1,
                    "plot": str(plot), "commit_status": "committed", "ready_to_use": len(patches) > 1}

    def start(task: dict[str, Any], *, task_dir: Path, defer_creation_export: bool = False) -> dict[str, Any]:
        assert defer_creation_export is True
        starts.append(task)
        return {"status": "complete", "project": str(source.parent / "project"),
                "result": {"studio_run": {"ready_to_use": True}},
                "current_project": {key: {"current": True} for key in ("source", "qa", "delivery")}}

    monkeypatch.setattr(template_creation, "start_task", start)
    monkeypatch.setattr(template_creation, "inspect_task", lambda *_: pytest.fail("Source task restarted"))
    first = creation.create(Service(), request)
    second = creation.create(Service(), request)
    assert first["status"] == "blocked" and second["status"] == "complete"
    assert len(starts) == 1 and len(patches) == 2 and patches[0] == patches[1]
    assert patches[0]["base_revision"] == 0 and second["template_id"] == "paired-spectra"


@pytest.mark.parametrize("change_source", [False, True])
def test_existing_output_requires_bound_choice_without_overwriting_or_guessing(source, monkeypatch, change_source):
    from sciplot_core import task_execution

    request = template_request(source)
    occupied = source.parent / "Existing"
    occupied.mkdir()
    sentinel = occupied / "keep.txt"
    sentinel.write_text("existing user output")
    request["out"] = str(occupied)
    calls = []

    def create(_source, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("test stopped before native preparation")

    monkeypatch.setattr(task_execution, "create_project", create)
    service = object()  # No native service method may be reached before output selection/preparation.
    first = creation.create(service, request)
    assert first["status"] == "needs_input" and first["question"]["field"] == "out" and not calls
    response = {"response": {"out": str(source.parent / "New"), "expected_question_id": first["question"]["question_id"]}}
    if change_source:
        source.write_text(source.read_text().replace("450,2", "450,7"))
        with pytest.raises(DocumentError) as error:
            creation.decide_creation(service, Path(first["plot"]), response)
        assert error.value.reason_code == "template_source_changed" and not calls
    else:
        second = creation.decide_creation(service, Path(first["plot"]), response)
        assert second["status"] == "blocked" and len(calls) == 1
        assert calls[0]["output_dir"] == source.parent / "New" and calls[0]["publish"] is False
    assert sentinel.read_text() == "existing user output"
