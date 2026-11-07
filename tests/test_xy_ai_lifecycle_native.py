"""One real source-bound XY lifecycle through the public typed application API.

This simulates client-submitted commands, not model inference or RPC transport.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import sys
from time import perf_counter, time_ns

import pytest

from managed_plot_helpers import patch, request_for_source
from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core import plot_ir
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, read, transaction_path
from sciplot_core.project_lifecycle.contracts import NormalizedCommand, RevisionToken
from sciplot_core.project_lifecycle.repository import FileProjectRepository


@pytest.mark.comprehensive
def test_real_xy_typed_review_save_cold_export_and_reply_loss(tmp_path, monkeypatch):
    source_request = request_for_source(tmp_path)
    source = Path(source_request["data_binding"]["data_sources"][0]["path"])
    original_source = source.read_bytes()
    calls = []
    phases = []
    phase = "setup"
    flow_completed = False
    started = perf_counter()
    evidence = {"status": "incomplete", "started_utc": datetime.now(timezone.utc).isoformat(),
                "source_sha256": file_sha256(source), "source_request": source_request,
                "test_sha256": file_sha256(Path(__file__)),
                "runtime": {"executable": sys.executable, "version": sys.version},
                "source_files": {name: file_sha256(REPO_ROOT / "src/sciplot_core" / name) for name in
                    ("plot_engine/managed_state.py", "plot_engine/managed_backend.py",
                     "project_lifecycle/managed_creation.py", "plot_ir/compiler.py")},
                "scope": "Generated CSV; public service/typed command; real Veusz native; no model, RPC daemon or portable/offline proof."}

    def instrument(owner, name, operation):
        original = getattr(owner, name)

        @wraps(original)
        def observed(*args, **kwargs):
            begin = perf_counter()
            event = {"phase": phase, "operation": operation}
            if operation == "native.command":
                event["command"] = args[1][0]
            try:
                result = original(*args, **kwargs)
                if operation == "content_snapshot":
                    event.update(path=str(args[1]), bytes=len(result["bytes"]))
                return result
            except BaseException as exc:
                event.update(error_type=type(exc).__name__, error=str(exc))
                raise
            finally:
                event["seconds"] = perf_counter() - begin
                calls.append(event)

        monkeypatch.setattr(owner, name, observed)

    for name in ("compile_ir", "render_ir", "inspect_ir", "export_ir"):
        instrument(ManagedVeuszCompiler, name, "compiler." + name)
    instrument(ManagedVeuszCompiler, "_run", "native.command")
    instrument(plot_ir, "compile_document", "compile_document")
    instrument(FileProjectRepository, "content_snapshot", "content_snapshot")

    def run(name, operation):
        nonlocal phase
        phase = name
        begin = perf_counter()
        try:
            return operation()
        finally:
            phases.append({"phase": name, "seconds": perf_counter() - begin})

    def close(service):
        compiler = service.backend.managed.compiler
        worker = compiler._worker
        process = worker._process if worker is not None else None
        service.close()
        if worker is not None:
            assert worker._closed and worker._process is None
        if process is not None:
            assert process.poll() is not None
        return {"had_live_worker": process is not None,
                "pid": process.pid if process is not None else None, "closed": True}

    service = PlotService()
    services = [service]
    try:
        created = run("create", lambda: service.create(source_request))
        assert created["ready_to_use"] and created["revision"] == 0, created
        root = Path(created["plot"])
        initial = load_head(root)
        native = Path(initial["binding"]["document"])
        native_before = native.read_bytes()
        evidence["initial_native_state_hash"] = read(native.parent / "build.json")["native_state_hash"]
        summary = run("summary", lambda: service.describe(root, description={"scope": "summary"}))
        assert summary["status"] == "current"
        assert "legend.position" in summary["edit_targets"]["legend:main"]["properties"]
        edit = run("edit_contract", lambda: service.describe(root, description={
            "scope": "edit", "target": "legend:main", "property": "legend.position"}))
        assert edit["current_value"] == initial["document"]["presentation"]["objects"]["legend:main"]["properties"]["legend.position"]

        # A valid early change cannot escape an invalid later semantic target.
        invalid = patch(summary, "xy-late-invalid", "style.line.width", "1.3pt", "series:A")
        invalid["changes"].append({"op": "set", "target": ["series:missing"],
                                   "property": "style.line.width", "value": "1.1pt"})
        invalid_command = NormalizedCommand.create("patch", invalid,
            expected_revision=RevisionToken.of(initial["document"]))
        before_invalid = len(calls)
        with pytest.raises(DocumentError) as failure:
            run("late_invalid", lambda: service.execute(root, invalid_command))
        assert failure.value.reason_code == "document_unknown_target"
        assert load_head(root) == initial and native.read_bytes() == native_before
        assert not transaction_path(root, "xy-late-invalid").exists()
        assert not any(event["operation"].startswith("compiler.") for event in calls[before_invalid:])

        requested_position = [.62, .78]
        wire = patch(summary, "xy-legend", "legend.position", requested_position, "legend:main")
        command = NormalizedCommand.create("patch", wire,
            expected_revision=RevisionToken.of(initial["document"]))
        review = run("typed_preview", lambda: service.execute(root, command))
        assert review["status"] == "needs_review" and review["scientific_audit"]["status"] == "passed", review
        assert Path(review["preview"]["path"]).is_file()
        assert load_head(root) == initial and native.read_bytes() == native_before
        preview_calls = len(calls)
        replay_preview = run("preview_reply_replay", lambda: service.execute(root, command))
        assert replay_preview["decision_id"] == review["decision_id"]
        assert replay_preview["status"] == "needs_review"
        assert not any(event["operation"].startswith("compiler.") for event in calls[preview_calls:])

        # Model lost delivery of a successful response at the caller boundary:
        # the real decision completes, but recovery uses the same saved command.
        completed = run("decide_save", lambda: service.decide(root, review["next_step"]["request"]))
        assert completed["ready_to_use"] and completed["revision"] == 1, completed
        saved = load_head(root)
        assert saved["document"]["scientific"] == initial["document"]["scientific"]
        assert saved["document"]["scientific_hash"] == initial["document"]["scientific_hash"]
        expected_presentation = deepcopy(initial["document"]["presentation"])
        expected_presentation["objects"]["legend:main"]["properties"]["legend.position"] = requested_position
        assert saved["document"]["presentation"] == expected_presentation
        history = {path.name: file_sha256(path) for path in (root / "revisions").glob("*.json")}
        assert len(history) == 2
        evidence["first_service"] = run("close_first", lambda: close(service))
        services.remove(service)

        service = PlotService()
        services.append(service)
        before_replay = len(calls)
        replay = run("saved_reply_replay", lambda: service.execute(root, command))
        assert replay["ready_to_use"] and replay["revision"] == 1, replay
        assert not any(event["operation"].startswith("compiler.") for event in calls[before_replay:])
        assert load_head(root) == saved
        opened = run("cold_open", lambda: service.open(root, description={"scope": "summary"}))
        assert opened["status"] == "current" and opened["revision"] == 1
        removed = []
        for item in completed["exports"]:
            if item["format"] in {"pdf", "tiff_300"}:
                path = Path(item["path"])
                assert path.is_relative_to(tmp_path)
                removed.append({"path": str(path), "sha256": file_sha256(path)})
                path.unlink()
        assert len(removed) == 2
        evidence["owned_disposable_exports_removed_to_require_fresh_export"] = removed
        cold_calls = len(calls)
        exported = run("cold_export", lambda: service.export(root))
        assert exported["ready_to_use"] and exported["revision"] == 1, exported
        assert sum(event["operation"] == "compiler.export_ir" for event in calls[cold_calls:]) == 1
        assert exported["scientific_hash"] == created["scientific_hash"]
        assert {path.name: file_sha256(path) for path in (root / "revisions").glob("*.json")} == history
        assert load_head(root) == saved and source.read_bytes() == original_source
        formats = {item["format"] for item in exported["exports"]}
        assert {"pdf", "tiff_300", "vsz"} <= formats
        for item in exported["exports"]:
            path = Path(item["path"])
            assert path.is_file() and path.stat().st_size > 0
            assert file_sha256(path) == item["sha256"]
        final_ir = read(Path(saved["binding"]["ir_path"]))
        final_native = Path(saved["binding"]["document"])
        assert final_ir["legend"]["position"] == requested_position
        assert final_ir["series"][0]["x"] == [0, 1, 2]
        assert final_ir["series"][0]["y"] == [.25, .5, 1]
        evidence.update(plot=str(root), created=created, review=review,
                        completed=completed, replay=replay, exported=exported,
                        original_source_unchanged=True, science_unchanged=True,
                        unrelated_presentation_unchanged=True, history=history,
                        revision_document_hashes={path.name: canonical_json_sha256(read(path)["document"], allow_nan=False)
                            for path in (root / "revisions").glob("*.json")},
                        final_document_hash=canonical_json_sha256(saved["document"], allow_nan=False),
                        ir_file_sha256=file_sha256(Path(saved["binding"]["ir_path"])),
                        final_native_sha256=file_sha256(final_native),
                        final_native_state_hash=read(final_native.parent / "build.json")["native_state_hash"],
                        ir_hash=saved["binding"]["ir_hash"])
        flow_completed = True
    finally:
        try:
            evidence["remaining_services"] = [run("close_final", lambda current=current: close(current))
                                               for current in services]
            if flow_completed:
                evidence["status"] = "passed"
        except BaseException as exc:
            evidence.update(status="failed", cleanup_error={"type": type(exc).__name__, "message": str(exc)})
            raise
        finally:
            counts = Counter(event["operation"] for event in calls)
            measured = ["compile_document", "content_snapshot", "native.command",
                        "compiler.compile_ir", "compiler.render_ir", "compiler.inspect_ir", "compiler.export_ir"]
            evidence.update(total_seconds=perf_counter() - started, phases=phases, calls=calls,
                            counts={operation: counts[operation] for operation in measured},
                            timing_contract="Nested method times overlap; total is wall time of this generated-data flow, no model/transport latency.")
            destination = Path(os.environ.get("SCIPLOT_XY_EVIDENCE_DIR", str(REPO_ROOT / ".tmp_verify/xy-ai-lifecycle")))
            destination.mkdir(parents=True, exist_ok=True)
            phase_name = os.environ.get("SCIPLOT_XY_PROOF_PHASE", "run")
            report = destination / f"{phase_name}-{time_ns()}.json"
            report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
