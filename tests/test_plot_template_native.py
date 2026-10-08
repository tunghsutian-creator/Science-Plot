"""A reusable template and fresh cell bindings create real editable Veusz figures."""

from copy import deepcopy
from collections import Counter
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from time import perf_counter

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.storage import load_head
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_backends import VeuszBackend
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.studio_core.project_query import inspect_project
from test_plot_template_creation import template_request


@pytest.mark.comprehensive
def test_template_create_two_sources_through_one_public_command_each(tmp_path):
    sources = [tmp_path / name for name in ("First.csv", "Second.csv")]
    for index, source in enumerate(sources):
        source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nE2,E2,E4,E4\n"
                          f"400,{1 + index},400,{2 + index}\n450,{2 + index},450,{3 + index}\n500,{3 + index},500,{4 + index}\n")
    source_hashes = {str(source): file_sha256(source) for source in sources}
    requests = [template_request(source, key=f"template-create-{index}") for index, source in enumerate(sources)]
    assert requests[0]["template_definition"] == requests[1]["template_definition"]
    assert requests[0]["theme"] == requests[1]["theme"]
    results, measurements = [], []
    with tempfile.TemporaryDirectory(prefix="sptmpl-", dir="/tmp") as temporary:
        socket = Path(temporary) / "engine.sock"
        environment = {**os.environ, "SCIPLOT_ENGINE_SOCKET": str(socket)}
        pid = None
        try:
            for index, request in enumerate(requests):
                request_path = tmp_path / f"request-{index}.json"
                request_path.write_text(json.dumps(request))
                started = perf_counter()
                process = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "create", "--request", str(request_path), "--json"],
                                         capture_output=True, text=True, env=environment, cwd=REPO_ROOT, timeout=180)
                measurements.append({"case": f"template_new_source_{index + 1}", "seconds": round(perf_counter() - started, 6),
                                     "response_bytes": len(process.stdout.encode()), "public_calls": 1})
                assert process.returncode == 0, process.stdout + process.stderr
                result = json.loads(process.stdout)
                assert result["status"] == "complete" and result["ready_to_use"] is True, result
                pid = read_owner(socket)["pid"]
                head = load_head(Path(result["plot"]))
                doc = head["document"]
                assert doc["coverage"]["mode"] == "legacy_shadow"
                assert set(identifier for identifier, obj in doc["presentation"]["objects"].items() if obj["kind"] == "series") == {"bound:E2", "bound:E4"}
                for identifier in ("bound:E2", "bound:E4"):
                    assert doc["presentation"]["objects"][identifier]["properties"]["style.line.width"] == "0.7pt"
                assert doc["scientific"]["provenance"]["template_data_binding"] == request["data_binding"]
                state = json.loads(Path(result["creation_evidence"]).read_text())
                assert state["task_request"]["mapping"]["column_mapping"]["pairs"] == [{"x_column": 0, "y_column": 1}, {"x_column": 2, "y_column": 3}]
                assert state["template_result"]["scientific_hash_changed"] is False
                transaction = json.loads(Path(result["evidence"]).read_text())
                assert transaction["review"]["scientific_audit"]["status"] == "passed"
                spec = json.loads(Path(head["binding"]["spec"]).read_text())
                assert [(item["label"], item["x_values"], item["y_values"]) for item in spec["series"]] == [
                    ("E2", [400.0, 450.0, 500.0], [1.0 + index, 2.0 + index, 3.0 + index]),
                    ("E4", [400.0, 450.0, 500.0], [2.0 + index, 3.0 + index, 4.0 + index])]
                actual = inspect_project(Path(head["binding"]["project"]), native=True)["selected_figure"]["objects"]
                for identifier, color in (("bound:E2", "#2878B5"), ("bound:E4", "#C82423")):
                    target = head["binding"]["targets"][identifier]
                    fields = {item["setting_path"]: item["current_value"] for item in actual[target["object_path"]]["editable_fields"]}
                    assert fields[target["properties"]["style.line.width"]["setting_path"]] == "0.7pt"
                    assert fields[target["properties"]["style.line.color"]["setting_path"]] == color
                results.append(result)
            assert results[0]["plot_id"] != results[1]["plot_id"]
            assert results[0]["scientific_hash"] != results[1]["scientific_hash"]
            baseline = deepcopy(load_head(Path(results[0]["plot"])))
            request_path = tmp_path / "request-0.json"
            started = perf_counter()
            replay = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "create", "--request", str(request_path), "--json"],
                                    capture_output=True, text=True, env=environment, cwd=REPO_ROOT, timeout=180)
            measurements.append({"case": "template_idempotent_replay", "seconds": round(perf_counter() - started, 6),
                                 "response_bytes": len(replay.stdout.encode()), "public_calls": 1})
            assert replay.returncode == 0, replay.stdout + replay.stderr
            repeated = json.loads(replay.stdout)
            assert repeated["replayed"] is True and repeated["revision"] == results[0]["revision"]
            assert load_head(Path(results[0]["plot"])) == baseline
            assert {str(source): file_sha256(source) for source in sources} == source_hashes
            report = {"status": "passed", "scope": "Two original tables, explicit row/column/unit/sample bindings, identical template/theme, real Veusz backend",
                      "sources_unchanged": True, "exact_explicit_mapping": True, "native_scientific_audit": "passed",
                      "series_ids_preserved": True, "theme_widths_preserved": True, "coverage": "legacy_shadow",
                      "native_final_width_color_verified": True, "compiled_coordinates_match_original_cells": True,
                      "idempotent_replay": True, "plots": [item["plot"] for item in results], "measurements": measurements}
            output = REPO_ROOT / ".tmp_verify/document_migration_20261007/template_native_acceptance.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if pid is None and socket.exists():
                pid = read_owner(socket)["pid"]
            if pid is not None:
                os.kill(pid, signal.SIGTERM)


@pytest.mark.comprehensive
@pytest.mark.parametrize("style_change", [True, False])
def test_template_creation_has_exactly_one_native_export_and_no_repeated_preparation(tmp_path, monkeypatch, style_change):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nE2,E2,E4,E4\n"
                      "400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    request = template_request(source)
    if not style_change:
        request.pop("theme")
        for obj in request["template_definition"]["presentation"]["objects"].values():
            obj["properties"] = {}
            obj["capabilities"] = {}
    workers = Counter()
    actual_run = subprocess.run

    def measured_run(args, *a, **kw):
        values = list(map(str, args))
        if "sciplot_core.veusz_worker" in values:
            workers[values[values.index("sciplot_core.veusz_worker") + 1]] += 1
        return actual_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", measured_run)
    service = PlotService(VeuszBackend(warm=False))
    first = service.create(request)
    assert first["status"] == "complete" and first["ready_to_use"] is True, first
    assert workers["export-document"] == 1, workers
    assert sum(workers[name] for name in ("edit-document", "edit-annotations", "preview-document")) == (2 if style_change else 0), workers
    original_workers = workers.copy()
    repeated = service.create(request)
    assert repeated["status"] == "complete" and repeated["revision"] == first["revision"]
    assert workers == original_workers, (original_workers, workers)
    state = json.loads(Path(first["creation_evidence"]).read_text())
    prepared = json.loads((Path(first["creation_evidence"]).parent / "task/task.json").read_text())
    assert prepared["phase"] == "prepared" and prepared["result"]["ready_to_use"] is False
    assert prepared["result"]["export_performed"] is False
    assert bool(state.get("template_export_only")) is not style_change
    report = {"status": "passed", "style_change": style_change, "native_workers": dict(workers),
              "baseline_export_performed": False, "replay_native_calls": 0,
              "source_sha256": file_sha256(source), "plot": first["plot"]}
    output = REPO_ROOT / f".tmp_verify/document_migration_20261007/template_export_count_{'style' if style_change else 'unchanged'}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
