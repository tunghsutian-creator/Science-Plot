"""Native failures retain actionable streams and immutable attempt history."""

import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_lifecycle.execution import _attempt, _failure
from sciplot_core.project_lifecycle.receipts import receipt
from sciplot_core.project_lifecycle.recovery import project_recovery


def transaction():
    doc = {"plot_id": "diagnostic-plot", "revision": 0, "plot_type": "ManagedPlot",
           "scientific_hash": "a" * 64, "presentation_hash": "b" * 64}
    return {"id": "tx", "request": {"idempotency_key": "create", "base_revision": 0, "action": "export"},
            "document": doc, "before": doc, "binding": {}, "phase": "export_pending",
            "diff": [], "risk": "presentation",
            "request_hash": canonical_json_sha256({"idempotency_key": "create", "base_revision": 0, "action": "export"}, allow_nan=False)}


def record(root, tx, exc):
    try:
        raise exc
    except Exception as caught:
        _failure(root, tx, caught, "export")
    return Path(tx["error"]["diagnostic"])


def test_process_failure_streams_survive_and_previous_attempt_is_immutable(tmp_path):
    tx = transaction()
    first = record(tmp_path, tx, subprocess.CalledProcessError(
        23, ["python", "-m", "sciplot_core.veusz_worker", "compile-plot-ir", "input file.json"],
        output='{"candidate":"incomplete"}\n', stderr="真实 traceback: axis_label_clipping\n"))
    original = first.read_bytes()
    second = record(tmp_path, tx, subprocess.CalledProcessError(24, ["python", "retry"],
                                                               output="retry stdout", stderr="retry stderr"))
    assert second != first
    assert first.read_bytes() == original
    detail = json.loads(original)
    assert detail["process"] == {"cmd": ["python", "-m", "sciplot_core.veusz_worker", "compile-plot-ir", "input file.json"],
                                  "returncode": 23, "stdout": '{"candidate":"incomplete"}\n',
                                  "stderr": "真实 traceback: axis_label_clipping\n"}
    assert [item["diagnostic"] for item in tx["failure_attempts"]] == [str(first), str(second)]
    assert tx["error"]["process"]["returncode"] == 24
    assert "stdout" not in tx["error"]["process"]


def test_wrapped_timeout_preserves_partial_raw_bytes_without_inventing_exit(tmp_path):
    timeout = subprocess.TimeoutExpired(["native", "slow"], 0.02, output=b"partial\xff", stderr=b"stderr")
    wrapper = RuntimeError("native rendering failed")
    wrapper.__cause__ = timeout
    detail = json.loads(record(tmp_path, transaction(), wrapper).read_text())
    assert detail["process"]["returncode"] is None
    assert detail["process"]["timeout_seconds"] == 0.02
    assert detail["process"]["stdout_bytes_base64"] == "cGFydGlhbP8="
    assert detail["process"]["stderr"] == "stderr"


def test_transient_failure_keeps_its_diagnostic_even_when_retry_succeeds(tmp_path):
    tx = transaction()
    calls = []

    def operation():
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(["native", "export"], 1, stderr="first timeout")
        return {"status": "exported"}

    assert _attempt(tmp_path, tx, "export", operation) == {"status": "exported"}
    assert len(tx["failure_attempts"]) == 1
    assert json.loads(Path(tx["failure_attempts"][0]["diagnostic"]).read_text())["process"]["stderr"] == "first timeout"
    assert tx["retry_counts"] == {"export": 1}


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, ["native"], stderr="deterministic failure"),
                                  subprocess.TimeoutExpired(["native"], 1, stderr="timed out")])
def test_initial_failure_and_summary_recovery_share_continuation(tmp_path, error):
    tx = transaction()
    record(tmp_path, tx, error)
    initial = receipt(tmp_path, tx)
    summary = {"revision": 0, "status": "current", "pending": {"phase": "export_pending"}}
    project_recovery(summary, tmp_path, tx)
    assert initial["ready_to_use"] is False
    assert initial["next_step"] == summary["recovery"]["next_step"]
    assert initial["commit_status"] == "committed"
    assert initial["export_status"] == "pending"


def test_doctor_does_not_claim_a_request_was_natively_verified():
    from sciplot_core.doctor import doctor_payload

    report = doctor_payload()
    scope = report["readiness_scope"]
    assert scope["installation"] == report["status"]
    assert scope["native_launch"] == "not_run"
    assert scope["requested_figure"] == "not_run"
    assert scope["delivery_verified"] is False
    assert report["execution_identity"]["native_execution_verified"] is False


def test_structured_worker_rejection_retains_subprocess_cause(tmp_path, monkeypatch):
    from sciplot_core.plot_backends import managed
    from sciplot_core.plot_document import DocumentError

    issues = [{"code": "axis_label_clipping", "semantic_id": "axis:right", "bounds_mm": [58, 2, 6, 3]}]
    payload = {"kind": "sciplot_worker_failure", "version": 1, "reason_code": "publication_qa_failed",
               "message": "Native publication text exceeds the available canvas.", "issues": issues,
               "repair": {"action": "correct_layout", "issues": issues}}
    cause = subprocess.CalledProcessError(1, ["native", "compile"], output="", stderr="Traceback detail\n" + json.dumps(payload) + "\n")

    def reject(*args, **kwargs):
        raise cause

    monkeypatch.setattr(managed, "run_worker", reject)
    with pytest.raises(DocumentError) as failure:
        managed.ManagedVeuszCompiler(warm=False)._run(["compile-plot-ir", "a", "b", "--preview", "c"])
    assert failure.value.reason_code == "publication_qa_failed"
    assert failure.value.issues == issues
    assert failure.value.repair["action"] == "correct_layout"
    detail = json.loads(record(tmp_path, transaction(), failure.value).read_text())
    assert detail["process"]["stderr"] == cause.stderr
    assert detail["issues"] == issues


def test_worker_cli_emits_structured_domain_failure_with_traceback(monkeypatch, capsys):
    from sciplot_core.plot_document import DocumentError
    from sciplot_core.veusz_worker import cli, managed

    def reject(*args):
        error = DocumentError("publication_qa_failed", "Right axis clips.", issues=[{"code": "axis_label_clipping"}])
        error.repair = {"action": "correct_layout"}
        raise error

    monkeypatch.setattr(managed, "compile_plot_ir", reject)
    assert cli.main(["compile-plot-ir", "ir.json", "document.vsz", "--preview", "preview.png"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "Traceback" in err
    payload = json.loads(err.splitlines()[-1])
    assert payload["kind"] == "sciplot_worker_failure"
    assert payload["issues"] == [{"code": "axis_label_clipping"}]
    assert payload["repair"] == {"action": "correct_layout"}


@pytest.mark.comprehensive
def test_real_managed_native_failure_retries_original_transaction_without_scientific_reexecution(tmp_path, monkeypatch):
    from managed_plot_helpers import request_for_source
    from sciplot_core.project_lifecycle import managed_creation
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head

    request = request_for_source(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    raw = source.read_bytes()
    counts = {"science": 0, "failed_compile": 0}
    original_resolve = managed_creation.resolve_science

    def resolve(*args, **kwargs):
        counts["science"] += 1
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(managed_creation, "resolve_science", resolve)
    service = PlotService()
    compiler = service.backend.managed.compiler
    run = compiler._run

    def fail_command(arguments):
        counts["failed_compile"] += 1
        raise subprocess.CalledProcessError(31, ["native", *arguments], output="worker stdout", stderr="injected worker traceback")

    monkeypatch.setattr(compiler, "_run", fail_command)
    try:
        failed = service.create(request)
        assert failed["status"] == "blocked" and failed["ready_to_use"] is False
        assert failed["commit_status"] == "committed" and failed["export_status"] == "pending"
        assert counts == {"science": 1, "failed_compile": 1}  # Unknown failures are never automatically retried.
        diagnostic = Path(failed["error"]["diagnostic"])
        original_diagnostic = diagnostic.read_bytes()
        process = json.loads(original_diagnostic)["process"]
        assert process["returncode"] == 31 and process["stdout"] == "worker stdout"
        assert process["stderr"] == "injected worker traceback" and process["cmd"][1] == "compile-plot-ir"
        root = Path(failed["plot"])
        before = load_head(root)
        monkeypatch.setattr(compiler, "_run", run)
        recovered = service.create(request)
        assert recovered["ready_to_use"] is True and recovered["revision"] == 0
        assert counts["science"] == 1 and load_head(root)["document"] == before["document"]
        assert len(list((root / "revisions").glob("*.json"))) == 1
        assert diagnostic.read_bytes() == original_diagnostic and source.read_bytes() == raw
        assert all(Path(item["path"]).stat().st_size > 0 for item in recovered["exports"])
    finally:
        service.close()
