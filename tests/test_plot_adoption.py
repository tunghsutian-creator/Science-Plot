"""Template identities are adopted once, before any public revision exists."""

from copy import deepcopy
from pathlib import Path

import pytest

from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.adoption import adopt, require_adoption
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head


def fixture():
    objects = {"series:" + name: {"kind": "series", "label": name,
        "properties": {"style.line.width": "1pt"},
        "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"}}}
        for name in ("E2", "E4")}
    objects["axis:x"] = {"kind": "axis", "label": "x", "properties": {"font.size": "7pt"},
                          "capabilities": {"font.size": {"type": "physical_size", "risk": "presentation"}}}
    doc = seal_document({"kind": "sciplot_document", "schema_version": 1, "plot_id": "created", "revision": 0,
        "scientific": {"data_sources": [], "transforms": [], "mappings": {"x": "nm", "y": "a.u."},
                       "guards": {}, "provenance": {}},
        "presentation": {"objects": objects, "layout": {}, "theme": {}, "export_configuration": {}},
        "coverage": {"mode": "legacy_shadow", "limitations": ["Test backend"]}})
    binding = {"targets": {name: {"object_path": "/native/" + name} for name in objects},
               "fingerprint": {"files": {}}}
    ids = {"E2": "series:control", "E4": "series:treated"}
    recipe = {"template_definition": {"template_id": "journal"}, "data_binding": {"source": "explicit"}}
    return doc, binding, ids, recipe


def test_adoption_moves_stable_ids_and_native_bindings_without_changing_coordinates():
    doc, binding, ids, recipe = fixture()
    originals = deepcopy((doc, binding))
    actual, native = adopt(doc, binding, series_ids=ids, recipe=recipe)
    assert set(actual["presentation"]["objects"]) == {"series:control", "series:treated", "axis:x"}
    assert native["targets"]["series:control"] == binding["targets"]["series:E2"]
    assert actual["scientific"]["mappings"] == doc["scientific"]["mappings"]
    assert actual["scientific"]["provenance"]["template_data_binding"] == recipe["data_binding"]
    assert (doc, binding) == originals
    require_adoption(native, ids, recipe)
    with pytest.raises(EngineError, match="different"):
        require_adoption(native, ids, {**recipe, "theme": {"theme_id": "other"}})


@pytest.mark.parametrize("ids", [{"E2": "series:control"}, {"E2": "axis:x", "E4": "series:t"},
                                 {"E2": "series:same", "E4": "series:same"}])
def test_adoption_rejects_missing_samples_and_identity_collisions(ids):
    doc, binding, _, recipe = fixture()
    with pytest.raises(EngineError):
        adopt(doc, binding, series_ids=ids, recipe=recipe)
    assert "template_adoption" not in binding


def test_adoption_does_not_rename_an_existing_revision():
    doc, binding, ids, recipe = fixture()
    doc["revision"] = 1
    with pytest.raises(EngineError, match="initial import"):
        adopt(doc, binding, series_ids=ids, recipe=recipe)


def test_open_created_persists_identity_and_reuses_exact_adoption(monkeypatch, tmp_path):
    doc, binding, ids, recipe = fixture()

    class Backend:
        calls = 0

        def import_project(self, project, figure_id=None, plot_id=None):
            self.calls += 1
            return deepcopy(doc), deepcopy(binding)

        def fingerprint(self, current):
            return deepcopy(current["fingerprint"])

    from sciplot_core.plot_engine import service

    monkeypatch.setattr(service, "resolve_project_figure", lambda *_: {"project": str(tmp_path / "project"), "figure_id": "primary"})
    backend = Backend()
    engine = PlotService(backend)
    first = engine.open_created(tmp_path / "project", series_ids=ids, recipe=recipe)
    root = Path(first["plot"])
    head = (root / "head.json").read_bytes()
    second = engine.open_created(tmp_path / "project", series_ids=ids, recipe=recipe)
    assert first == second and backend.calls == 1
    assert (root / "head.json").read_bytes() == head
    assert load_head(root)["document"]["revision"] == 0
    with pytest.raises(EngineError, match="different"):
        engine.open_created(tmp_path / "project", series_ids=ids, recipe={**recipe, "rule_id": "different"})
    assert (root / "head.json").read_bytes() == head
