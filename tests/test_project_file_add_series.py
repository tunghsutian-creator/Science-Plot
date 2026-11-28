"""Public same-figure append: one exact selection, one saved revision."""
from contextlib import closing
from pathlib import Path

import pytest
from openpyxl import Workbook

from sciplot_core.cli import main
from sciplot_core.mcp_server.schemas import tool_definitions
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_protocol.rpc import invoke
from sciplot_core.project_lifecycle.errors import EngineError
import test_project_file_append

ordinary_archive = test_project_file_append.ordinary_archive


def _source(folder):
    book = Workbook()
    a = book.active
    a.title = "Decoy"
    b = book.create_sheet("Measured")
    for sheet, base in ((a, 400), (b, 50)):
        for row in (("Temperature", "Heat Flow", "Heat Flow"), ("C", "W/g", "W/g"),
                    ("Run B", "Run B", "Run B"), (base, 88, -.9), (base + 1, 89, .2),
                    (base + 3, 90, None), (base + 6, 91, .4)):
            sheet.append(row)
    path = folder / "incoming work.xlsx"
    book.save(path)
    return path


def _request(opened, source, **extra):
    return {"plot_id": opened["plot_id"], "base_revision": opened["revision"],
            "expected_generation": opened["generation"], "source": str(source), "mode": "plan",
            "x_column": 0, "y_column": 2, "sample": "Run B", **extra}


def test_public_add_series_plans_exact_original_and_never_writes_on_stale_or_cancel(ordinary_archive, capsys):
    import json

    archive, plot_id, _, _ = ordinary_archive
    source = _source(archive.parent)
    before = archive.read_bytes()
    with closing(PlotService()) as service:
        opened = service.open(archive, plot_id)
        request = _request(opened, source)
        with pytest.raises(EngineError, match="exact worksheet"):
            invoke(service, "project.file-add-series", {"target": str(archive), "request": request})
        assert before == archive.read_bytes()
        assert main(["plot", "add-series", str(archive), str(source), "--plot-id", plot_id,
                     "--revision", str(opened["revision"]), "--expected-generation", opened["generation"],
                     "--x-column", "0", "--y-column", "2", "--sample", "Run B", "--sheet", "Measured",
                     "--direct", "--json"]) == 0
        plan = json.loads(capsys.readouterr().out)
        assert plan["status"] == "ready" and not plan["saved"]
        assert plan["selection"]["source"]["table_selection"]["sheet"] == "Measured"
        assert plan["selection"]["curves"][0]["y_column_index"] == 2
        assert before == archive.read_bytes()  # Declining the opt-in apply has no commit.
        apply = plan["apply_request"]
        with pytest.raises(EngineError, match="exact figure"):
            invoke(service, "project.file-add-series", {"target": str(archive), "request": {**apply, "y_column": 1}})
        with pytest.raises(EngineError, match="current revision"):
            invoke(service, "project.file-add-series", {"target": str(archive), "request": {**request, "base_revision": 0}})
        source.write_bytes(source.read_bytes() + b"changed")
        with pytest.raises(EngineError, match="changed after"):
            invoke(service, "project.file-add-series", {"target": str(archive), "request": apply})
        assert before == archive.read_bytes()
    names = {tool.name for tool in tool_definitions("daily")}
    assert "sciplot_project_file_add_series" in names


@pytest.mark.comprehensive
def test_native_add_series_preserves_selected_plot_identity_and_independent_raw_grids(ordinary_archive):
    from sciplot_core.plot_engine.content_store import resolve_document_content
    from sciplot_core.plot_ir.figure_document import figure_spec
    from sciplot_core.project_lifecycle.context import repository_scope
    from sciplot_core.project_lifecycle.project_file_summary import project_file_figure

    archive, plot_id, incoming, request = ordinary_archive
    source = _source(archive.parent)
    with closing(PlotService()) as service:
        first = service.open(archive, plot_id)
        sibling = service.append_project_file_xy(archive, request, expected_generation=first["generation"])
        opened = service.open(archive, plot_id)
        plan = invoke(service, "project.file-add-series", {"target": str(archive),
                      "request": _request(opened, source, sheet="Measured")})
        args = {"target": str(archive), "request": plan["apply_request"]}
        try:
            done = invoke(service, "project.file-add-series", args)
        except EngineError as exc:
            pytest.fail(str(exc) + " " + repr(exc.repair))
        assert done["saved"] and done["status"] == "saved"
        assert done["plot_id"] == plot_id and done["revision"] == opened["revision"] + 1
        assert done["scientific_hash"] != opened["scientific_hash"]
        source.unlink()
        incoming.unlink()
        committed = archive.read_bytes()
        assert invoke(service, "project.file-add-series", args)["status"] == "already_saved"
        assert archive.read_bytes() == committed
        after_sibling = service.open(archive, sibling["plot_id"])
        for key in ("plot_id", "revision", "scientific_hash", "presentation_hash"):
            assert after_sibling[key] == sibling[key]
        output = archive.parent / "selected-TIFF"
        result = service.export(archive, handoff={"plot_id": plot_id, "revision": done["revision"],
                                                  "output_dir": str(output), "formats": ["tiff_300"]})
        assert result["scientific_hash"] == done["scientific_hash"]
        [rendered] = result["exports"]
        from PIL import Image

        with Image.open(rendered["path"]) as image:
            image.load()
            assert image.format == "TIFF" and image.info["dpi"] == pytest.approx((300., 300.))
        assert [path.name for path in output.iterdir()] == [Path(rendered["path"]).name]
        assert archive.read_bytes() == committed
    with project_file_figure(archive, plot_id) as (_, owner, current):
        with repository_scope(owner), owner.query_scope(owner.attachment.root):
            content = resolve_document_content(owner.attachment.root, current)
            layers = figure_spec(content)["views"][0]["layers"]
            arrays = [{axis: content["scientific"]["provenance"]["datasets"][layer["dataset_id"]]
                      ["columns"][layer["mappings"][axis]]["values"] for axis in ("x", "y")} for layer in layers]
        assert arrays == [{"x": [66., 61., 61., 53.], "y": [-.023, .008, None, -.016]},
                          {"x": [50., 51., 53., 56.], "y": [-.9, .2, None, .4]}]


def _stable_layer(opened):
    return next(key for key, item in opened["edit_targets"].items() if item["kind"] == "layer")


def _replacement(folder):
    new = folder / "revised.csv"
    new.write_text("Temperature,Heat Flow\nC,W/g\nSample Z,Sample Z\n62,-0.025\n60,0.08\n59,\n54,0.016\n")
    return new


def _replacement_request(opened, path):
    return {"plot_id": opened["plot_id"], "base_revision": opened["revision"],
            "expected_generation": opened["generation"], "source": str(path), "mode": "plan",
            "x_column": 0, "y_column": 1, "replace_layer": _stable_layer(opened)}


def test_public_replace_series_plans_one_original_and_refuses_metadata_change(ordinary_archive, capsys):
    import json

    archive, plot_id, _, _ = ordinary_archive
    source = _replacement(archive.parent)
    baseline = archive.read_bytes()
    with closing(PlotService()) as service:
        opened = service.open(archive, plot_id)
        request = _replacement_request(opened, source)
        method = "project.file-replace-series-source"
        wrong = {**request, "replace_layer": "not:the:layer"}
        with pytest.raises(EngineError, match="exact current curve ID"):
            invoke(service, method, {"target": str(archive), "request": wrong})
        assert main(["plot", "replace-series-source", str(archive), str(source), "--plot-id", plot_id,
                     "--revision", str(opened["revision"]), "--expected-generation", opened["generation"],
                     "--x-column", "0", "--y-column", "1", "--layer-id", request["replace_layer"],
                     "--direct", "--json"]) == 0
        plan = json.loads(capsys.readouterr().out)
        assert plan["status"] == "ready" and not plan["saved"] and plan["scientific_hash"] == opened["scientific_hash"]
        assert plan["selection"]["replacement_path"] == str(source)
        assert plan["apply_request"]["replace_layer"] == request["replace_layer"]
        source.write_text(source.read_text().replace("W/g", "J/g"))
        with pytest.raises(EngineError, match="changed after"):
            invoke(service, method, {"target": str(archive), "request": plan["apply_request"]})
        with pytest.raises(EngineError, match="column metadata differs"):
            invoke(service, method, {"target": str(archive), "request": request})
        assert archive.read_bytes() == baseline


def _two_curve_archive(tmp_path, *, shared=False):
    from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
    from sciplot_core.project_lifecycle.project_file_append import project_file_create_xy
    from sciplot_core.task_semantic_contract import validate_intent
    from sciplot_core.task_semantic_creation import build_managed_request, prepare_plan

    folder = tmp_path.resolve()
    source_a = folder / "original A.xlsx"
    source_b = folder / "original B.csv"
    revised = folder / "revised workbook.xlsx"
    for source, offset in ((source_a, 0), (revised, 5)):
        book = Workbook()
        book.active.title = "Decoy"
        exact = book.create_sheet("Measured")
        rows = (("Temperature", "Heat Flow", "Heat Flow"), ("C", "W/g", "W/g"),
                ("Sample Z", "Sample Z", "Sample Z"), (55 + offset, 19., .1 + offset),
                (57 + offset, 18., None), (58 + offset, 17., .3 + offset))
        for row in rows:
            exact.append(row)
            book.active.append(tuple(20 * item if isinstance(item, (float, int)) else item for item in row))
        book.save(source)
    source_b.write_text("Temperature,Heat Flow,Heat Flow\nC,W/g,W/g\nSample Y,Sample Y,Sample Y\n40,17,0.4\n46,19,-0.1\n55,23,0.2\n")
    intent = validate_intent({"rule_id": "ordinary_xy",
        "x": {"quantity": "temperature", "column_id": "column:0"},
        "y": {"quantity": "heat_flow", "column_id": "column:2"}})
    plan = prepare_plan([source_a, source_b], intent)
    assert [decision["field"] for decision in plan["decisions"]] == ["tables"]
    choice = {"tables": {"source:0": "table:1"}}
    request = build_managed_request({"request": {"intent": intent}, "semantic_plan": plan,
                                    "semantic_choices": choice, "task_dir": str(folder), "intent_revision": 1})
    if shared:
        from copy import deepcopy

        binding = request["data_binding"]
        template = request["template_definition"]["figure_spec"]
        layer = template["views"][0]["layers"][0]
        another = template["views"][0]["layers"][1]
        # Direct fixture: two display curves intentionally consume the same
        # physical source. Updating that source must not masquerade as one edit.
        for name in ("dataset_id", "mappings", "mapping_semantics"):
            another[name] = deepcopy(layer[name])
        slots = binding["slots"]
        old = next(slot for slot in slots.values() if slot["series_id"] == layer["id"])
        other = next(slot for slot in slots.values() if slot["series_id"] == another["id"])
        other.update({axis: deepcopy(old[axis]) for axis in ("x", "y")})
        other["sample"] = old["sample"]
        needed = {old[axis]["source_id"] for axis in ("x", "y")}
        retained = []
        for node in reversed(binding["transforms"]):
            if node["output"] in needed:
                needed.update(node["inputs"])
                retained.append(node)
        binding["transforms"] = list(reversed(retained))
        binding["data_sources"] = [source for source in binding["data_sources"] if source["source_id"] in needed]
    archive = folder / "original.sciplot"
    result = project_file_create_xy(archive, request, capabilities=COMPATIBILITY_CAPABILITIES)
    return archive, result, source_a, source_b, revised


def test_public_replace_series_rejects_a_source_used_by_another_curve(tmp_path):
    archive, first, _, _, source = _two_curve_archive(tmp_path, shared=True)
    before = archive.read_bytes()
    with closing(PlotService()) as service:
        opened = service.open(archive, first["plot_id"])
        request = {**_replacement_request(opened, source), "sheet": "Measured", "y_column": 2}
        with pytest.raises(EngineError, match="not exclusive"):
            invoke(service, "project.file-replace-series-source", {"target": str(archive), "request": request})
    assert archive.read_bytes() == before


@pytest.mark.comprehensive
def test_native_replace_series_preserves_other_layers_and_sealed_originals(tmp_path):
    from sciplot_core.plot_engine.content_store import resolve_document_content
    from sciplot_core.plot_ir.figure_document import figure_spec
    from sciplot_core.project_lifecycle.context import repository_scope
    from sciplot_core.project_lifecycle.project_file_summary import project_file_figure
    from test_project_file_append import _ordinary_request

    archive, first, source_a, source_b, revised = _two_curve_archive(tmp_path)
    sibling_source = archive.parent / "sibling.csv"
    sibling_source.write_text("Temperature,Heat Flow\nC,W/g\nSample S,Sample S\n40,0.4\n46,-0.1\n55,0.2\n")
    with closing(PlotService()) as service:
        sibling = service.append_project_file_xy(archive, _ordinary_request(sibling_source), expected_generation=first["generation"])
        opened = service.open(archive, first["plot_id"])
        request = {**_replacement_request(opened, revised), "sheet": "Measured", "y_column": 2}
        method = "project.file-replace-series-source"
        # The already sealed old source must not be reread from the filesystem.
        source_a.unlink()
        plan = invoke(service, method, {"target": str(archive), "request": request})
        assert plan["selection"]["table_selection"]["sheet"] == "Measured"
        assert plan["selection"]["layer_id"] == request["replace_layer"]
        apply = {"target": str(archive), "request": plan["apply_request"]}
        try:
            done = invoke(service, method, apply)
        except EngineError as exc:
            pytest.fail(str(exc) + " " + repr(exc.repair))
        assert done["plot_id"] == opened["plot_id"] and done["revision"] == opened["revision"] + 1
        assert done["scientific_hash"] != opened["scientific_hash"]
        source_b.unlink()
        revised.unlink()
        after = archive.read_bytes()
        assert invoke(service, method, apply)["status"] == "already_saved"
        assert archive.read_bytes() == after
        for key in ("plot_id", "revision", "scientific_hash"):
            assert service.open(archive, sibling["plot_id"])[key] == sibling[key]
    with project_file_figure(archive, first["plot_id"]) as (_, owner, current):
        with repository_scope(owner), owner.query_scope(owner.attachment.root):
            root = owner.attachment.root
            old = owner.load_revision(root, 0)["document"]
            new = resolve_document_content(root, current)
            assert new["scientific"]["data_sources"][0]["path"] == str(revised)
            assert old["scientific"]["data_sources"][0]["path"] == str(source_a)
            layers, old_layers = (figure_spec(item)["views"][0]["layers"] for item in (new, old))
            assert [item["id"] for item in layers] == [item["id"] for item in old_layers]
            assert layers[1] == old_layers[1]
            arrays = [{axis: new["scientific"]["provenance"]["datasets"][layer["dataset_id"]]
                      ["columns"][layer["mappings"][axis]]["values"] for axis in ("x", "y")} for layer in layers]
        assert arrays == [{"x": [60., 62., 63.], "y": [5.1, None, 5.3]},
                          {"x": [40., 46., 55.], "y": [.4, -.1, .2]}]
