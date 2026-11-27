"""Public same-figure append: one exact selection, one saved revision."""
from contextlib import closing

import pytest
from openpyxl import Workbook

from sciplot_core.cli import main
from sciplot_core.mcp_server.schemas import tool_definitions
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_protocol.rpc import invoke
from sciplot_core.project_lifecycle.errors import EngineError
from test_project_file_append import ordinary_archive  # noqa: F401


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
    with project_file_figure(archive, plot_id) as (_, owner, current):
        with repository_scope(owner), owner.query_scope(owner.attachment.root):
            content = resolve_document_content(owner.attachment.root, current)
            layers = figure_spec(content)["views"][0]["layers"]
            arrays = [{axis: content["scientific"]["provenance"]["datasets"][layer["dataset_id"]]
                      ["columns"][layer["mappings"][axis]]["values"] for axis in ("x", "y")} for layer in layers]
        assert arrays == [{"x": [66., 61., 61., 53.], "y": [-.023, .008, None, -.016]},
                          {"x": [50., 51., 53., 56.], "y": [-.9, .2, None, .4]}]
