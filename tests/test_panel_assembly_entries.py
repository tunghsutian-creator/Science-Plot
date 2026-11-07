"""Public intents bind generated assets locally and keep layout work independent."""

import builtins
import json
import os
from pathlib import Path
import subprocess
import webbrowser

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


@pytest.mark.parametrize("target_kind", ["none", "saved", "missing", "symlink"])
@pytest.mark.parametrize("json_output", [False, True])
def test_retired_desktop_argv_uses_cli_errors_without_layout_io_or_gui(
    tmp_path, monkeypatch, capsys, target_kind, json_output,
):
    path = tmp_path / "saved layout.json"
    path.write_bytes(b"historical layout bytes; retirement must not parse them")
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    target = {"none": None, "saved": path, "missing": tmp_path / "missing.json", "symlink": alias}[target_kind]
    original_import = builtins.__import__

    def no_ui_import(name, *args, **kwargs):
        forbidden = ("PyQt6", "veusz", "sciplot_gui", "sciplot_core.panel_assembly.desktop",
                     "sciplot_core.studio_core.runtime")
        assert not any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
        return original_import(name, *args, **kwargs)

    def guarded(function):
        def call(value, *args, **kwargs):
            if isinstance(value, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(value))
                if candidate == tmp_path or tmp_path in candidate.parents:
                    pytest.fail("Retired compose open attempted layout IO")
            return function(value, *args, **kwargs)
        return call

    def no_launch(*_args, **_kwargs):
        pytest.fail("Retired compose open must not launch any process or browser")

    argv = ["compose", "open", *([str(target)] if target is not None else []),
            *(["--json"] if json_output else [])]
    with monkeypatch.context() as guard:
        guard.setattr(builtins, "__import__", no_ui_import)
        guard.setattr(subprocess, "Popen", no_launch)
        guard.setattr(webbrowser, "open", no_launch)
        for owner, names in ((Path, ("stat", "resolve", "open", "mkdir", "unlink", "rename", "replace")),
                             (os, ("open", "stat", "lstat")), (builtins, ("open",))):
            for name in names:
                guard.setattr(owner, name, guarded(getattr(owner, name)))
        assert main(argv) == 1
    captured = capsys.readouterr()
    if json_output:
        result = json.loads(captured.out)
        assert result["kind"] == "sciplot_cli_runtime_error"
        assert result["category"] == "expected_runtime_failure" and result["status"] == "failed"
        assert result["reason_code"] == "manual_composer_retired"
        message = result["message"]
        assert captured.err == ""
    else:
        assert captured.out == ""
        message = captured.err
    assert "manual_composer_retired" in message and "compose capabilities --json" in message
    assert "compose new/inspect/apply/export" in message
    assert path.read_bytes() == b"historical layout bytes; retirement must not parse them"
    assert alias.is_symlink() and not (tmp_path / "missing.json").exists()
    assert sorted(item.name for item in tmp_path.iterdir()) == ["alias.json", "saved layout.json"]


def test_public_entry_retains_the_layout_symlink_refusal(tmp_path):
    path = tmp_path / "layout.json"
    compose({"action": "new", "layout": str(path)})
    original = path.read_bytes()
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(AssemblyError, match="symbolic links"):
        compose({"action": "inspect", "layout": str(alias)})
    assert path.read_bytes() == original



def test_public_export_refuses_dangling_output_symlink_without_creating_its_target(tmp_path):
    layout = tmp_path / "layout.json"
    compose({"action": "new", "layout": str(layout)})
    compose({"action": "apply", "layout": str(layout), "expected_revision": 0,
             "operations": [add_panel(image_reference(tmp_path))]})
    target = tmp_path / "uncreated-package"
    alias = tmp_path / "selected-output"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(AssemblyError) as error:
        compose({"action": "export", "layout": str(layout), "out": str(alias)})
    assert error.value.code == "assembly_output_exists"
    assert alias.is_symlink() and not target.exists()


def test_cli_and_mcp_keep_actionable_physical_style_details(tmp_path, monkeypatch, capsys):
    from sciplot_core.panel_assembly import export

    layout = tmp_path / "layout.json"
    compose({"action": "new", "layout": str(layout)})
    original = layout.read_bytes()
    issue = {"code": "assembly_relative_physical_style", "panel_id": "panel:a", "panel_label": "a",
             "setting_path": "/page/graph/x/Label/size", "value": "3%",
             "repair": "Set a fixed size in pt in the original plot, Save, then use the current source version and retry export."}
    message = "Panel a (panel:a): /page/graph/x/Label/size uses 3%. " + issue["repair"]

    def refuse(*_args, **_kwargs):
        raise AssemblyError(issue["code"], message, issues=[issue])

    monkeypatch.setattr(export, "export_document", refuse)
    assert main(["compose", "export", str(layout), "--out", str(tmp_path / "cli-package"), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["reason_code"] == issue["code"]
    assert result["message"] == message and result["issues"] == [issue]

    async def scenario():
        reply = await Adapter().call("sciplot_compose", {"request": {"action": "export", "layout": str(layout),
                                                                     "out": str(tmp_path / "mcp-package")}})
        assert reply.is_error and reply.structured_content["error"]["code"] == issue["code"]
        assert reply.structured_content["error"]["message"] == message
        assert reply.structured_content["issues"] == [issue]

    anyio.run(scenario)
    assert layout.read_bytes() == original
    assert not (tmp_path / "cli-package").exists() and not (tmp_path / "mcp-package").exists()


def test_saved_layout_labels_crop_and_source_replacement_survive_without_a_window(tmp_path):
    from sciplot_core.panel_assembly.model import load_document

    layout = tmp_path / "saved layout.json"
    original = image_reference(tmp_path)
    source = Path(original["path"])
    source_bytes = source.read_bytes()
    compose({"action": "new", "layout": str(layout)})
    result = compose({"action": "apply", "layout": str(layout), "expected_revision": 0,
                      "operations": [add_panel(original)]})
    assert "compose open" not in result["next_step"]
    assert "compose apply" in result["next_step"] and "expected_revision" in result["next_step"]
    for label in ("", "B", None):
        result = compose({"action": "apply", "layout": str(layout), "expected_revision": result["revision"],
                          "operations": [{"op": "set_label", "id": "panel:a", "label": label},
                                         {"op": "set_span", "id": "panel:a", "row_span": 2, "column_span": 1}]})
        resolved = result["resolved_layout"]["panels"][0]
        assert resolved["label"] == ("a" if label is None else label)
        assert (resolved["label_mm"] is None) is (label == "")
        assert load_document(layout)["panels"][0]["label"] == label
    result = compose({"action": "apply", "layout": str(layout), "expected_revision": result["revision"],
                      "operations": [{"op": "set_crop", "id": "panel:a", "crop": [.15, .2, .8, .9]}]})
    assert load_document(layout)["panels"][0]["crop"] == [.15, .2, .8, .9]
    result = compose({"action": "apply", "layout": str(layout), "expected_revision": result["revision"],
                      "operations": [{"op": "set_crop", "id": "panel:a", "crop": None}]})
    assert load_document(layout)["panels"][0]["crop"] is None
    assert source.read_bytes() == source_bytes
    result = compose({"action": "apply", "layout": str(layout), "expected_revision": result["revision"],
                      "operations": [{"op": "set_crop", "id": "panel:a", "crop": [.15, .2, .8, .9]}]})
    before = load_document(layout)["panels"][0]
    replacement = tmp_path / "replacement.png"
    Image.new("RGB", (80, 60), "#dba37b").save(replacement)
    result = compose({"action": "apply", "layout": str(layout), "expected_revision": result["revision"],
                      "operations": [{"op": "replace_panel", "id": "panel:a",
                                      "source": {"kind": "image", "path": str(replacement)}}]})
    after = load_document(layout)["panels"][0]
    assert {key: after[key] for key in ("id", "row", "column", "row_span", "column_span", "label", "crop")} == {
        key: before[key] for key in ("id", "row", "column", "row_span", "column_span", "label", "crop")}
    assert after["source"]["path"] == str(replacement)
    saved, modified = layout.read_bytes(), layout.stat().st_mtime_ns
    assert compose({"action": "inspect", "layout": str(layout)})["revision"] == result["revision"]
    assert layout.read_bytes() == saved and layout.stat().st_mtime_ns == modified
    assert source.read_bytes() == source_bytes


def test_retired_desktop_modules_are_absent_while_core_assembly_remains():
    root = Path(__file__).resolve().parents[1] / "src/sciplot_core/panel_assembly"
    assert not list(root.glob("desktop*.py"))
    assert all((root / name).is_file() for name in (
        "model.py", "history.py", "storage.py", "service.py", "preview.py", "native.py", "export.py", "sources.py"))


@pytest.mark.comprehensive
def test_program_intents_mix_saved_projects_managed_and_image_with_scientific_qa(tmp_path):
    import pymupdf
    from test_panel_assembly_export import managed_source, clipped_legacy_label
    from test_task_papers_native import _projects
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.panel_assembly.sources import project_references
    from sciplot_core.plot_engine.storage import load_head

    raw, projects = _projects(tmp_path)
    clipped_legacy_label(projects[1], sources=raw)
    managed, _bound = managed_source(tmp_path)
    image = image_reference(tmp_path)
    protected = [*raw, Path(image["path"]), *(project / "studio/document.vsz" for project in projects),
                 *(project / "studio/spec.json" for project in projects)]
    originals = {path: file_sha256(path) for path in protected}
    canonical = load_head(managed)
    references = [project_references(project)[0][1] for project in projects]
    references += [{"kind": "managed", "project": str(managed), "plot_id": canonical["document"]["plot_id"]}, image]
    layout, out = tmp_path / "saved-layout.json", tmp_path / "native-package"
    compose({"action": "new", "layout": str(layout), "width_mm": 230, "height_mm": 200})
    operations = [{"op": "add_panel", "panel": {"id": f"panel:{index}", "source": source,
        "row": index // 2, "column": index % 2, **({"crop": [.1, .1, .9, .9]} if source["kind"] == "image" else {})}}
        for index, source in enumerate(references)]
    added = compose({"action": "apply", "layout": str(layout), "expected_revision": 0, "operations": operations})
    assert [panel["source_kind"] for panel in added["panels"]] == ["project", "project", "managed", "image"]
    before_refusal = layout.read_bytes()
    with pytest.raises(AssemblyError) as rejected:
        compose({"action": "export", "layout": str(layout), "out": str(out)})
    assert rejected.value.code == "assembly_native_qa_failed"
    assert "annotation_outside_view" in str(rejected.value)
    assert not out.exists() and layout.read_bytes() == before_refusal
    compose({"action": "apply", "layout": str(layout), "expected_revision": added["revision"],
             "operations": [{"op": "remove_panel", "id": "panel:1"}]})
    result = compose({"action": "export", "layout": str(layout), "out": str(out)})
    assert result["status"] == "complete" and result["source_currentness"] == "passed"
    assert all(Path(result[key]).is_file() for key in ("pdf", "tiff", "layout", "manifest"))
    scientific = [panel for panel in result["panels"] if panel["evidence"]["authority"] != "image_bytes"]
    assert len(scientific) == 2
    for panel in scientific:
        assert panel["evidence"]["physical_size"]["scale"] == 1
        assert panel["evidence"]["publication_qa"]["native_text_checked"]
        assert panel["evidence"]["publication_qa"]["status"] == "passed"
    assert load_head(managed) == canonical
    assert not Path(canonical["binding"]["document"]).exists()
    assert {path: file_sha256(path) for path in protected} == originals
    with pymupdf.open(result["pdf"]) as pdf:
        assert pdf[0].rect.width * 25.4 / 72 == pytest.approx(230, abs=.001)
        assert pdf[0].rect.height * 25.4 / 72 == pytest.approx(200, abs=.001)
        assert "Wavelength" in pdf[0].get_text()
