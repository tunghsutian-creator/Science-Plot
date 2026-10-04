"""AI-processed coordinates reach native exports without local scientific work."""

from __future__ import annotations

import csv
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_render import audit_tts_document
from sciplot_core.semantic_sources import rheology_tts
from sciplot_core.workflow import rheology_tts_figures
from sciplot_core.workflow.rheology_tts_prepared import plot_prepared_suite


@pytest.fixture(autouse=True)
def prohibit_scientific_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("Prepared plotting invoked a scientific analysis/selection owner.")

    monkeypatch.setattr(rheology_tts, "analyze_tts_request", forbidden)
    monkeypatch.setattr(rheology_tts_figures, "build_tts_figures", forbidden)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def _request(tmp_path: Path) -> tuple[Path, dict, dict]:
    # Unsorted, repeated x values and non-linear supplied predictions detect
    # sorting, deduplication, interpolation and an accidental local refit.
    x = [3.2500000000000004, 0.12345678901234566, 2.0000000000000004,
         0.12345678901234566]
    y = [1.2345678901234567, 8.765432109876543, -0.3456789012345679,
         4.000000000000001]
    supplied_prediction = [7.000000000000001, -0.012345678901234567,
                           3.141592653589793, 2.718281828459045]
    source = tmp_path / "original.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["x", "observation", "caller_prediction"])
        writer.writerows(zip(x, y, supplied_prediction, strict=True))
    plan = {
        "version": 1,
        "source_binding": {"sources": [{"path": str(source), "sha256": file_sha256(source)}]},
        "transform_ledger": {
            "owner": "External AI synthetic fixture",
            "operations": "Coordinates and predictions are supplied explicitly; no local calculation requested.",
            "units": {"x": "1000/K", "y": "dimensionless"},
        },
        "figures": [{
            "id": "Custom", "width_mm": 60, "height_mm": 55,
            "panels": [{
                "id": "a", "rect_mm": [0, 0, 60, 55], "standard_frame": True,
                "x_label": "1000/T (K^{-1})", "y_label": "ln a_T",
                "legend": False,
                "series": [
                    {"role": "observed_shift", "label": "Supplied shifts", "x": x,
                     "y": y, "color_index": 1},
                    {"role": "regression_fit", "label": "Supplied prediction", "x": x,
                     "y": supplied_prediction, "color_index": 1},
                ],
            }],
        }],
    }
    plan_path = tmp_path / "prepared.json"
    _write_json(plan_path, plan)
    request = {"version": 1, "prepared_plan": str(plan_path), "out": str(tmp_path / "Figures")}
    request_path = tmp_path / "request.json"
    _write_json(request_path, request)
    return request_path, request, plan


@pytest.mark.comprehensive
def test_prepared_plot_preserves_order_values_and_native_roles_without_analysis(tmp_path: Path) -> None:
    request_path, request, input_plan = _request(tmp_path)
    original = Path(input_plan["source_binding"]["sources"][0]["path"])
    original_sha, plan_sha = file_sha256(original), file_sha256(Path(request["prepared_plan"]))

    result = plot_prepared_suite(request_path)

    assert result["status"] == "ready"
    assert result["figures"] == 1
    assert result["numerical_processing"] is False
    assert result["prepared_plan_sha256"] == plan_sha
    delivery = Path(result["delivery"])
    assert delivery == tmp_path / "Figures"
    manifest = json.loads((delivery / "data/delivery_manifest.json").read_text())
    document = manifest["documents"][0]
    assert document["id"] == "Custom"  # No fixed-50 UDC figure selection.
    assert {Path(path).suffix for path in document["exports"]} == {".pdf", ".tiff", ".png"}
    assert all(Path(path).is_file() and Path(path).stat().st_size > 0 for path in document["exports"])
    native_path = Path(document["path"])
    assert native_path == delivery / "editable/Custom.vsz"
    assert file_sha256(native_path) == document["sha256"]

    supplied = input_plan["figures"][0]["panels"][0]["series"]
    plotted = json.loads((delivery / "data/figure_plan.json").read_text())
    assert plotted["transform_ledger"] == input_plan["transform_ledger"]
    actual = plotted["figures"][0]["panels"][0]["series"]
    assert [(s["role"], s["x"], s["y"]) for s in actual] == [
        (s["role"], s["x"], s["y"]) for s in supplied
    ]
    with (delivery / "data/Custom.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == sum(len(s["x"]) for s in supplied)
    for index, series in enumerate(supplied):
        selected = [row for row in rows if int(row["curve"]) == index]
        assert [int(row["point_index"]) for row in selected] == list(range(len(series["x"])))
        assert [float(row["x"]) for row in selected] == series["x"]
        assert [float(row["y"]) for row in selected] == series["y"]

    receipt = result["native_result"]["figures"][0]
    compiled = json.loads(Path(receipt["spec_path"]).read_text())["figure"]
    native_audit = audit_tts_document(native_path, compiled, check_presentation=True)
    assert native_audit["status"] == "passed"
    assert native_audit["dataset_count"] == 4
    assert native_audit["presentation"]["template_match"] is True
    encodings = [s["encoding"] for s in compiled["panels"][0]["series"]]
    assert encodings[0]["marker"]["shape"] == "circle"
    assert encodings[0]["line"]["visible"] is False
    assert encodings[1]["marker"]["shape"] == "none"
    assert encodings[1]["line"]["visible"] is True
    assert file_sha256(original) == original_sha
    assert file_sha256(Path(request["prepared_plan"])) == plan_sha
    from sciplot_core.cli.dispatch.rheology import _compact_creation_result

    compact = _compact_creation_result(result)
    assert "native_result" not in compact
    assert compact["review"]["figures"][0]["document_sha256"] == file_sha256(native_path)
    assert Path(compact["review"]["figures"][0]["preview"]).is_file()
    assert json.loads(Path(compact["full_evidence_path"]).read_text())["native_result"] == result["native_result"]


@pytest.mark.parametrize("failure", ["stale_source", "missing_ledger", "missing_sources", "unknown_marker", "stale_contract"])
def test_prepared_rejects_invalid_provenance_or_request_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    from sciplot_core import rheology_tts_render

    request_path, request, plan = _request(tmp_path)
    if failure == "stale_source":
        plan["source_binding"]["sources"][0]["sha256"] = "0" * 64
    elif failure == "missing_ledger":
        plan.pop("transform_ledger")
    elif failure == "missing_sources":
        plan["source_binding"] = {"description": "Unbound AI output"}
    elif failure == "unknown_marker":
        request["marker"] = "none"
    else:
        request["expected_contract_sha256"] = "0" * 64
    _write_json(Path(request["prepared_plan"]), plan)
    _write_json(request_path, request)

    def unexpected_render(*_args, **_kwargs):
        pytest.fail("Invalid prepared request reached native creation.")

    monkeypatch.setattr(rheology_tts_render, "render_tts_figures", unexpected_render)
    with pytest.raises(ValueError):
        plot_prepared_suite(request_path)
    assert not Path(request["out"]).exists()
    assert not (tmp_path / ".sciplot").exists()


def _creation_result(tmp_path: Path) -> tuple[dict, Path]:
    """Distinct native and published paths detect accidental history-as-authority."""
    delivery = tmp_path / "Figures"
    workspace = tmp_path / ".sciplot" / "Figures"
    workspace.mkdir(parents=True)
    receipt = {
        "id": "Custom", "document": str(workspace / "initial_render/Custom.vsz"),
        "document_sha256": "a" * 64,
        "exports": [{"format": fmt, "path": str(workspace / f"Custom.{suffix}"),
                     "exists": True, "sha256": "b" * 64}
                    for fmt, suffix in (("pdf", "pdf"), ("png_300", "png"), ("tiff_300", "tiff"))],
        "native_audit": {"status": "passed", "scope": "Numeric fidelity; visual review is separate.",
                         "presentation": {"status": "matched", "template_match": True,
                                          "differences": [], "series": [{"matches": True}]}},
    }
    result = {"status": "ready", "delivery": str(delivery), "workspace": str(workspace),
              "figures": 1, "manual_edit": str(delivery / "Open_in_SciPlot.command"),
              "scientific_scope": "External coordinates; no scientific certification.",
              "numerical_processing": False, "prepared_plan_sha256": "c" * 64,
              "native_result": {"kind": "sciplot_rheology_tts_render", "version": 1,
                                "status": "completed", "figures": [receipt]}}
    manifest_path = workspace / "suite.json"
    _write_json(manifest_path, {"delivery": result["delivery"], "workspace": result["workspace"],
        "native_result": result["native_result"], "documents": [{"id": "Custom",
            "path": str(delivery / "editable/Custom.vsz"), "sha256": "a" * 64,
            "exports": [str(delivery / f"panels/Custom.{suffix}") for suffix in ("pdf", "png", "tiff")]}]})
    return result, manifest_path


def test_compact_creation_preserves_review_bindings_scope_and_full_evidence(tmp_path: Path) -> None:
    from sciplot_core.cli.dispatch.rheology import _compact_creation_result

    result, manifest_path = _creation_result(tmp_path)
    before = deepcopy(result)
    manifest_bytes = manifest_path.read_bytes()
    compact = _compact_creation_result(result)

    assert "native_result" not in compact
    assert compact["full_evidence_path"] == str(manifest_path)
    assert compact["native_audit"] == {"status": "passed", "scopes": [
        "Numeric fidelity; visual review is separate."]}
    assert compact["native_status"] == "completed"
    for key in set(result) - {"native_result"}:
        assert compact[key] == result[key]
    document = json.loads(manifest_bytes)["documents"][0]
    assert compact["review"]["figures"] == [{
        "id": "Custom", "document": document["path"], "document_sha256": document["sha256"],
        "preview": document["exports"][1], "tiff": document["exports"][2], "native_audit_status": "passed"}]
    assert "fresh style-preview" in compact["review"]["scope"]
    assert "index" not in compact["review"]
    assert result == before
    assert manifest_path.read_bytes() == manifest_bytes

    # Audit volume may grow without increasing the successful CLI receipt.
    result["native_result"]["figures"][0]["native_audit"]["presentation"]["series"] *= 1000
    manifest = json.loads(manifest_bytes)
    manifest["native_result"] = result["native_result"]
    _write_json(manifest_path, manifest)
    assert _compact_creation_result(result) == compact

    index = Path(result["delivery"]) / "index.html"
    index.parent.mkdir()
    index.write_text("<h1>Delivered figures</h1>", encoding="utf-8")
    assert _compact_creation_result(result)["review"]["index"] == str(index)


@pytest.mark.parametrize("diagnostic", ["failed", "unknown_status", "warning", "differs", "missing_export"])
def test_compact_creation_never_hides_native_failure_or_uncertainty(tmp_path: Path, diagnostic: str) -> None:
    from sciplot_core.cli.dispatch.rheology import _compact_creation_result

    result, _ = _creation_result(tmp_path)
    native = result["native_result"]["figures"][0]
    if diagnostic == "failed":
        native["native_audit"].update(status="failed", errors=[{"reason": "numeric mismatch"}])
    elif diagnostic == "unknown_status":
        native["native_audit"]["status"] = "not_checked"
    elif diagnostic == "warning":
        native["cleanup_warnings"] = ["Export backup cleanup failed."]
    elif diagnostic == "differs":
        native["native_audit"]["presentation"].update(status="differs", template_match=False,
            differences=[{"field": "marker", "matches": False}])
    else:
        native["exports"][0]["exists"] = False
    assert _compact_creation_result(result) == result


@pytest.mark.parametrize("change", ["missing", "invalid_json", "stale_native", "stale_document", "missing_preview"])
def test_compact_creation_fallback_keeps_success_and_complete_original_result(tmp_path: Path, change: str) -> None:
    from sciplot_core.cli.dispatch.rheology import _compact_creation_result

    result, path = _creation_result(tmp_path)
    manifest = json.loads(path.read_text())
    if change == "missing":
        path.unlink()
    elif change == "invalid_json":
        path.write_text("{", encoding="utf-8")
    else:
        if change == "stale_native":
            manifest["native_result"]["version"] = 2
        elif change == "stale_document":
            manifest["documents"][0]["sha256"] = "d" * 64
        else:
            manifest["documents"][0]["exports"].pop(1)
        _write_json(path, manifest)
    projected = _compact_creation_result(result)
    assert projected.pop("compact_unavailable")
    assert projected == result
    assert projected["status"] == "ready"


@pytest.mark.parametrize("command", ["plot", "tts"])
@pytest.mark.parametrize("full", [False, True])
def test_rheology_creation_cli_defaults_compact_and_full_keeps_previous_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, command: str, full: bool,
) -> None:
    from sciplot_core.cli.dispatch.rheology import _compact_creation_result, dispatch_rheology
    from sciplot_core.cli.parsers import build_parser
    from sciplot_core.workflow import rheology_tts_prepared, rheology_tts_suite

    result, _ = _creation_result(tmp_path)
    owner, name = ((rheology_tts_prepared, "plot_prepared_suite") if command == "plot"
                   else (rheology_tts_suite, "create_suite"))
    calls = []

    def create(request):
        calls.append(request)
        return result

    monkeypatch.setattr(owner, name, create)
    request = tmp_path / "request.json"
    args = build_parser().parse_args(["rheology", command, "--request", str(request), "--json",
                                     *(["--full"] if full else [])])
    assert dispatch_rheology(args) == 0
    assert json.loads(capsys.readouterr().out) == (result if full else _compact_creation_result(result))
    assert calls == [request]


@pytest.mark.parametrize("command,status", [("capabilities", "ready"), ("export", "ready"),
                                          ("style-preview", "preview_ready"), ("style-apply", "no_change")])
def test_other_rheology_commands_keep_full_results_and_preview_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, command: str, status: str,
) -> None:
    from sciplot_core.cli.dispatch.rheology import dispatch_rheology
    from sciplot_core.cli.parsers import build_parser
    from sciplot_core.workflow import rheology_tts_contract, rheology_tts_style_update, rheology_tts_suite

    owner, name = {"capabilities": (rheology_tts_contract, "rheology_capabilities"),
                   "export": (rheology_tts_suite, "export_suite"),
                   "style-preview": (rheology_tts_style_update, "preview_suite_style"),
                   "style-apply": (rheology_tts_style_update, "apply_suite_style")}[command]
    result = {"status": status, "preview": str(tmp_path / "preview.json"),
              "preview_id": "bound-preview", "figures": [{"id": "Custom", "document_sha256": "a" * 64}],
              "source_binding": {"sha256": "b" * 64}, "diagnostic_details": ["keep"]}
    monkeypatch.setattr(owner, name, lambda *args, **kwargs: result)
    argv = ["rheology", command, "--json"]
    if command != "capabilities":
        argv.append(str(tmp_path))
    if command == "style-apply":
        argv.extend(["--preview", str(tmp_path / "preview.json")])
    assert dispatch_rheology(build_parser().parse_args(argv)) == 0
    assert json.loads(capsys.readouterr().out) == result


def test_failed_rheology_creation_cli_keeps_error_and_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    from sciplot_core.cli.dispatch.rheology import dispatch_rheology
    from sciplot_core.cli.parsers import build_parser
    from sciplot_core.workflow import rheology_tts_prepared

    result = {"status": "failed", "native_result": {"status": "failed", "errors": ["mismatch"]}}
    monkeypatch.setattr(rheology_tts_prepared, "plot_prepared_suite", lambda request: result)
    args = build_parser().parse_args(["rheology", "plot", "--request", str(tmp_path / "request.json"), "--json"])
    assert dispatch_rheology(args) == 1
    assert json.loads(capsys.readouterr().out) == result


@pytest.fixture
def prohibit_prepared_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    from sciplot_core import rheology_tts_render
    from sciplot_core.workflow import rheology_tts_creation

    def forbidden(*_args, **_kwargs):
        pytest.fail("Invalid prepared structure reached workspace allocation or native rendering.")

    monkeypatch.setattr(rheology_tts_creation, "create_prepared_suite", forbidden)
    monkeypatch.setattr(rheology_tts_render, "render_tts_figures", forbidden)


@pytest.mark.parametrize("field,value,location", [
    *[("plan", value, "prepared_plan") for value in (None, [], "text", False, 1)],
    *[("binding", value, "source_binding") for value in (None, [], "text", False, 1)],
    *[("sources", value, "source_binding.sources") for value in (None, [], {}, "text", False, 1)],
    *[("source", value, "source_binding.sources[0]") for value in (None, [], "text", False, 1)],
    ("source", {"path": "/original"}, "source_binding.sources[0]"),
    ("source", {"sha256": "a" * 64}, "source_binding.sources[0]"),
    ("source", {"path": "/original", "sha256": "a" * 64, "extra": True}, "source_binding.sources[0]"),
    ("later_source", None, "source_binding.sources[1]"),
    *[(field, value, f"source_binding.sources[0].{field}")
      for field in ("path", "sha256") for value in (None, [], {}, False, 1, "")],
    ("path", "relative.csv", "source_binding.sources[0].path"),
])
def test_prepared_structure_errors_are_field_bound_before_side_effects(
    tmp_path: Path, field: str, value: object, location: str, prohibit_prepared_creation: None,
) -> None:
    request_path, request, plan = _request(tmp_path)
    if field == "plan":
        payload = value
    else:
        payload = plan
        if field == "binding":
            plan["source_binding"] = value
        elif field == "sources":
            plan["source_binding"]["sources"] = value
        elif field == "source":
            plan["source_binding"]["sources"][0] = value
        elif field == "later_source":
            plan["source_binding"]["sources"].append(value)
        else:
            plan["source_binding"]["sources"][0][field] = value
    _write_json(Path(request["prepared_plan"]), payload)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in tmp_path.iterdir()}
    with pytest.raises(ValueError) as error:
        plot_prepared_suite(request_path)
    assert str(error.value).startswith(f"Invalid prepared plan at {location}:")
    assert set(tmp_path.iterdir()) == set(before)
    assert all((p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) == previous for p, previous in before.items())
    assert not Path(request["out"]).exists() and not (tmp_path / ".sciplot").exists()
