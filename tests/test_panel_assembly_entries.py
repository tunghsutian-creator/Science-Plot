"""Public intents bind generated assets locally and keep layout work independent."""

import json
from pathlib import Path

import anyio
from jsonschema import Draft202012Validator
from PIL import Image
import pytest

from sciplot_core.cli import main
from sciplot_core.cli.parsers import build_parser
from sciplot_core.mcp_server.server import Adapter
from sciplot_core.panel_assembly.errors import AssemblyError
from sciplot_core.panel_assembly.service import compose, composition_capabilities, composition_request_schema


def image_reference(tmp_path):
    path = tmp_path / "generated microscopy.png"
    Image.new("RGB", (80, 60), "#859da5").save(path)
    return {"kind": "image", "path": str(path)}


def add_panel(reference):
    return {"op": "add_panel", "panel": {"id": "panel:a", "source": reference, "row": 0, "column": 0}}


def test_compact_entry_captures_source_and_keeps_spacing_free_of_source_calls(tmp_path, monkeypatch):
    from sciplot_core.panel_assembly import sources
    from sciplot_core.panel_assembly.model import load_document

    path = tmp_path / "selected.assembly.json"
    created = compose({"action": "new", "layout": str(path), "rows": 2, "columns": 2})
    assert created["revision"] == 0 and created["panels"] == []
    first = compose({"action": "apply", "layout": str(path), "expected_revision": 0,
                     "operations": [add_panel(image_reference(tmp_path))]})
    frozen = load_document(path)["panels"][0]["source"]
    assert frozen["binding"] and first["revision"] == 1
    assert "binding" not in json.dumps(first)
    monkeypatch.setattr(sources, "capture_source", lambda *_: pytest.fail("spacing recaptured sources"))
    monkeypatch.setattr(sources, "assert_source_current", lambda *_: pytest.fail("spacing rechecked native sources"))
    result = compose({"action": "apply", "layout": str(path), "expected_revision": 1,
                      "operations": [{"op": "set_spacing", "gap_x_mm": 7, "gap_y_mm": 9}]})
    assert result["revision"] == 2 and result["layout"]["gap_x_mm"] == 7
    assert result["source_validation"] == "deferred_until_export"
    assert load_document(path)["panels"][0]["source"] == frozen


def test_old_revision_and_invalid_atomic_batch_leave_saved_bytes_unchanged(tmp_path):
    path = tmp_path / "layout.json"
    compose({"action": "new", "layout": str(path)})
    original = path.read_bytes()
    with pytest.raises(AssemblyError, match="revision"):
        compose({"action": "apply", "layout": str(path), "expected_revision": 8,
                 "operations": [{"op": "set_spacing", "gap_x_mm": 6, "gap_y_mm": 6}]})
    assert path.read_bytes() == original
    with pytest.raises(AssemblyError):
        compose({"action": "apply", "layout": str(path), "expected_revision": 0,
                 "operations": [{"op": "set_spacing", "gap_x_mm": 6, "gap_y_mm": 6},
                                {"op": "set_grid", "rows": 0, "columns": 2}]})
    assert path.read_bytes() == original


def test_cli_and_mcp_share_saved_layout_and_explicit_version_conflicts(tmp_path, capsys):
    path = tmp_path / "layout with spaces.json"
    assert main(["compose", "new", str(path), "--rows", "1", "--columns", "2", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 0

    async def scenario():
        adapter = Adapter()
        result = await adapter.call("sciplot_compose", {"request": {"action": "apply", "layout": str(path),
            "expected_revision": 0, "operations": [add_panel(image_reference(tmp_path))]}})
        assert not result.is_error and result.structured_content["revision"] == 1
        stale = await adapter.call("sciplot_compose", {"request": {"action": "apply", "layout": str(path),
            "expected_revision": 0, "operations": [{"op": "set_label", "id": "panel:a", "label": "SEM"}]}})
        assert stale.is_error
        assert stale.structured_content["error"]["code"] == "assembly_revision_conflict"

    anyio.run(scenario)
    assert main(["compose", "inspect", str(path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["panels"][0]["source_kind"] == "image" and result["revision"] == 1


def test_source_drift_is_visible_without_rebinding_or_layout_mutation(tmp_path):
    path = tmp_path / "layout.json"
    reference = image_reference(tmp_path)
    compose({"action": "new", "layout": str(path)})
    compose({"action": "apply", "layout": str(path), "expected_revision": 0,
             "operations": [add_panel(reference)]})
    before = path.read_bytes()
    Image.new("RGB", (80, 60), "#a58989").save(reference["path"])
    assert compose({"action": "inspect", "layout": str(path)})["source_validation"] == "deferred_until_export"
    with pytest.raises(AssemblyError):
        compose({"action": "inspect", "layout": str(path), "check_sources": True})
    assert path.read_bytes() == before
    refreshed = compose({"action": "apply", "layout": str(path), "expected_revision": 1,
                         "operations": [{"op": "replace_panel", "id": "panel:a", "source": reference}]})
    assert refreshed["revision"] == 2
    assert compose({"action": "inspect", "layout": str(path), "check_sources": True})["source_validation"] == "current"


@pytest.mark.parametrize("operation", [
    {"op": "set_scientific_values", "values": [1, 2]},
    {"op": "set_spacing", "gap_x_mm": 3, "gap_y_mm": 4, "execute": "code"},
    {"op": "move_panel", "id": "panel:a", "row": -1, "column": 0},
])
def test_advertised_intent_schema_rejects_unknown_or_out_of_grid_fields(operation):
    request = {"action": "apply", "layout": "/layout.json", "expected_revision": 0, "operations": [operation]}
    assert not Draft202012Validator(composition_request_schema()).is_valid(request)


def test_capabilities_and_parser_keep_compact_sources_and_explicit_export_scope():
    caps = composition_capabilities()
    validator = Draft202012Validator(caps["request_schema"])
    assert validator.is_valid({"action": "apply", "layout": "/layout.json", "expected_revision": 0,
                               "operations": [add_panel({"kind": "project", "project": "/existing", "figure_id": "curve"})]})
    assert not validator.is_valid({"action": "export", "layout": "/layout.json", "out": "/out", "dpi": 30})
    args = build_parser().parse_args(["compose", "export", "/layout.json", "--out", "/out", "--dpi", "600", "--json"])
    assert args.layout == Path("/layout.json") and args.dpi == 600
    assert caps["authority"]["legacy"] == "exact saved VSZ"


def test_desktop_entry_bootstraps_qt_before_opening_the_window(monkeypatch):
    from sciplot_core.cli.dispatch.composition import dispatch_composition
    from sciplot_core.studio_core import runtime

    class ReexecRequested(Exception):
        pass

    def reexec(argv):
        assert argv == ["compose", "open", "/saved layout.json"]
        raise ReexecRequested

    monkeypatch.setattr(runtime, "maybe_reexec_with_qt_runtime", reexec)
    args = build_parser().parse_args(["compose", "open", "/saved layout.json"])
    with pytest.raises(ReexecRequested):
        dispatch_composition(args)


def test_public_entry_retains_the_layout_symlink_refusal(tmp_path):
    path = tmp_path / "layout.json"
    compose({"action": "new", "layout": str(path)})
    original = path.read_bytes()
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(AssemblyError, match="symbolic links"):
        compose({"action": "inspect", "layout": str(alias)})
    assert path.read_bytes() == original

