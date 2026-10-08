"""A–G acceptance through durable semantic execution and a real Veusz backend."""

from collections import Counter
import json
from pathlib import Path
import subprocess
from time import perf_counter

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.plot_backends import VeuszBackend
from sciplot_core.plot_backends import veusz, veusz_identity
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, read, transaction_path
from sciplot_core.studio_core.annotation_operations import preview_document_operations
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.project_query import inspect_project


class MeasuredBackend(VeuszBackend):
    def __init__(self):
        self.calls = Counter()
        self.faults = {}

    def _count(self, name):
        self.calls[name] += 1
        fault = self.faults.pop(name, None)
        if fault:
            raise fault

    def fingerprint(self, binding):
        self._count("fingerprint")
        return super().fingerprint(binding)

    def preview(self, document, binding, new_document, diff, output):
        self._count("preview")
        return super().preview(document, binding, new_document, diff, output)

    def apply(self, binding, review):
        self._count("apply")
        result = super().apply(binding, review)
        self.calls["native_" + result["status"]] += 1
        fault = self.faults.pop("after_apply", None)
        if fault:
            raise fault
        return result

    def export(self, binding):
        self._count("export")
        return super().export(binding)


@pytest.mark.comprehensive
def test_native_semantic_engine_cases_a_to_g(tmp_path, monkeypatch):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    original_source = source.read_bytes()
    created = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
                              "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"],
                             capture_output=True, text=True, timeout=180, cwd=REPO_ROOT)
    assert created.returncode == 0, created.stdout + created.stderr
    project = Path(json.loads(created.stdout)["project_dir"])
    initial = inspect_project(project, native=True)["selected_figure"]
    preview = preview_document_operations(project, [
        {"op": "add_annotation", "id": "spectrum_title", "parent_path": "/page1/graph1",
         "text": "Measured spectra", "position": {"mode": "relative", "x": 0.05, "y": 0.96}},
        {"op": "set_sample_style", "samples": ["E2", "E4"], "style": {"width": "0.9pt"}},
    ], output_dir=tmp_path / "seed", expected_document_sha256=initial["document_sha256"])
    apply_document_edit(project, preview)
    backend = MeasuredBackend()
    service = PlotService(backend)
    opened = service.open(project)
    root = Path(opened["plot"])
    start_document = load_head(root)["document"]
    native_processes = Counter()
    state_checks = []
    actual_fingerprint = veusz_identity.fingerprint

    def measured_fingerprint(binding):
        state_checks.append(True)
        return actual_fingerprint(binding)

    monkeypatch.setattr(veusz_identity, "fingerprint", measured_fingerprint)
    monkeypatch.setattr(veusz, "fingerprint", measured_fingerprint)
    actual_run = subprocess.run

    def measured_run(args, *a, **kw):
        values = list(map(str, args))
        if "sciplot_core.veusz_worker" in values:
            position = values.index("sciplot_core.veusz_worker") + 1
            native_processes[values[position]] += 1
        return actual_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", measured_run)
    from sciplot_core.studio_core import prepare_generated, studio_prepare
    preparation_calls = []

    def forbid_preparation(*a, **kw):
        preparation_calls.append(True)
        pytest.fail("Presentation edits must not prepare scientific data")

    monkeypatch.setattr(prepare_generated, "generate_studio_document", forbid_preparation)
    monkeypatch.setattr(studio_prepare, "prepare_studio_document", forbid_preparation)
    measurements = []

    def request(key, revision, prop, value, targets=None):
        return {"plot_id": opened["plot_id"], "base_revision": revision, "idempotency_key": key,
                "intent_class": "presentation", "changes": [{"op": "set", "target": targets or ["series:E2", "series:E4"],
                                                               "property": prop, "value": value}]}

    def execute(label, patch):
        before, processes = backend.calls.copy(), native_processes.copy()
        previous_checks = len(state_checks)
        started = perf_counter()
        result = PlotService(backend).patch(root, patch)
        measurements.append({"case": label, "seconds": round(perf_counter() - started, 6),
                             "public_calls": 1, "response_bytes": len(json.dumps(result, ensure_ascii=False).encode()),
                             "backend_calls": dict(backend.calls - before), "native_processes": dict(native_processes - processes),
                             "saved_input_fingerprint_checks": len(state_checks) - previous_checks,
                             "native_candidate_render_count": sum((native_processes - processes)[name]
                                                                  for name in ("edit-document", "edit-annotations", "preview-document")),
                             "data_preparations": len(preparation_calls), "status": result["status"],
                             "revision": result["revision"]})
        return result

    a = execute("A_title_hide", request("A", 0, "title.visible", False, ["title:spectrum_title"]))
    assert a["status"] == "complete" and a["revision"] == 1 and a["ready_to_use"]
    b_request = request("B", 1, "style.line.width", "0.7pt")
    b = execute("B_width", b_request)
    assert b["status"] == "complete" and b["revision"] == 2
    assert b["scientific_hash"] == a["scientific_hash"] == start_document["scientific_hash"]
    transaction = read(transaction_path(root, "B"))
    assert [{k: item[k] for k in ("target", "property", "before", "after")} for item in transaction["diff"]] == [
        {"target": target, "property": "style.line.width", "before": "0.9pt", "after": "0.7pt"}
        for target in ("series:E2", "series:E4")]
    replay = execute("E_identical_replay", b_request)
    assert replay["replayed"] and replay["revision"] == 2
    assert measurements[-1]["native_processes"] == {}
    assert not any(measurements[-1]["backend_calls"].get(key) for key in ("preview", "apply", "export"))
    native_before_rejection = Path(load_head(root)["binding"]["document"]).read_bytes()
    with pytest.raises(DocumentError) as scientific:
        service.patch(root, request("C", 2, "mapping.x", "old_y"))
    assert scientific.value.reason_code == "document_scientific_edit_unsupported"
    with pytest.raises(DocumentError) as stale:
        service.patch(root, request("F", 1, "style.line.width", "0.8pt"))
    assert stale.value.reason_code == "document_revision_conflict"
    assert Path(load_head(root)["binding"]["document"]).read_bytes() == native_before_rejection
    assert not transaction_path(root, "C").exists() and not transaction_path(root, "F").exists()
    backend.faults["preview"] = subprocess.TimeoutExpired("native preview", 120)
    g_preview = execute("G_preview_timeout", request("G-preview", 2, "style.line.width", "0.8pt"))
    assert g_preview["status"] == "complete" and g_preview["revision"] == 3
    assert measurements[-1]["backend_calls"]["preview"] == 2
    backend.faults["export"] = subprocess.TimeoutExpired("native export", 120)
    g_export = execute("G_export_timeout", request("G-export", 3, "style.line.width", "0.6pt"))
    assert g_export["status"] == "complete" and g_export["revision"] == 4
    assert measurements[-1]["backend_calls"]["export"] == 2 and measurements[-1]["backend_calls"]["apply"] == 1
    backend.faults["export"] = OSError("simulated interrupted export")
    pending_request = request("G-pending", 4, "style.line.width", "0.5pt")
    pending = execute("G_export_pending", pending_request)
    assert pending["commit_status"] == "committed" and pending["export_status"] == "pending"
    assert load_head(root)["document"]["revision"] == 5
    completed = execute("G_export_only_resume", pending_request)
    assert completed["status"] == "complete" and completed["revision"] == 5
    assert measurements[-1]["backend_calls"].get("apply", 0) == 0
    backend.faults["after_apply"] = RuntimeError("simulated process response lost after native commit")
    lost_request = request("G-lost-apply", 5, "style.line.width", "0.4pt")
    lost = execute("G_apply_response_lost", lost_request)
    assert lost["status"] == "blocked" and load_head(root)["document"]["revision"] == 5
    recovered = execute("G_apply_durable_recovery", lost_request)
    assert recovered["status"] == "complete" and recovered["revision"] == 6
    assert measurements[-1]["backend_calls"].get("native_already_applied") == 1
    assert len(list((root / "revisions").glob("*.json"))) == 7
    rolled_back = service.rollback(root, {"base_revision": 6, "target_revision": 0, "idempotency_key": "restore"})
    assert rolled_back["status"] == "complete" and rolled_back["revision"] == 7
    assert load_head(root)["document"]["presentation_hash"] == start_document["presentation_hash"]
    noop = execute("cache_same_style_noop", request("noop", 7, "style.line.width", "0.9pt"))
    assert noop["status"] == "complete" and noop["changed"] is False and noop["revision"] == 7
    assert measurements[-1]["native_processes"] == {}
    assert source.read_bytes() == original_source
    final_head = load_head(root)
    recorded_source = Path(final_head["document"]["scientific"]["data_sources"][0]["path"])
    recorded_source.write_bytes(recorded_source.read_bytes() + b"\n")
    dirty = service.describe(root)
    assert dirty["status"] == "stale" and str(recorded_source) in dirty["changed_inputs"]
    assert {"compile", "render", "export"} <= set(dirty["dependencies"]["invalidated"])
    with pytest.raises(ValueError) as drift:
        service.patch(root, request("D", 7, "style.line.width", "0.8pt"))
    assert drift.value.reason_code == "document_inputs_changed"
    assert load_head(root)["document"]["revision"] == 7
    evidence = REPO_ROOT / ".tmp_verify/document_migration_20261007"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "engine_native_acceptance.json").write_text(json.dumps({
        "cases": {letter: "passed" for letter in "ABCDEFG"}, "measurements": measurements,
        "scientific_preparations": len(preparation_calls), "native_processes_total": dict(native_processes),
        "recorded_source_scope": "managed source paths; unrecorded original external files cannot be inferred",
        "persisted_document": str(root), "final_revision": 7,
        "faults": "Known preview/export timeout once; export OSError; lost native apply response. All injected synchronously, not an OS kill.",
    }, ensure_ascii=False, indent=2))
