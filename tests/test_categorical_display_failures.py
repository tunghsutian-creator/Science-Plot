"""Known native categorical conflicts stay closed, retryable and before export."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
import runpy
from types import SimpleNamespace

import pytest

from sciplot_core.studio_core.categorical_display import KEY
from sciplot_core.studio_core.categorical_display_errors import (
    CODE,
    CategoricalPresentationConflict,
    raise_categorical_worker_rejection,
)
from sciplot_core.studio_core import categorical_display_preflight as preflight
from sciplot_core.studio_core import project_export


def failure():
    return {
        "kind": "sciplot_worker_preparation_blocked",
        "version": 1,
        "reason_code": CODE,
        "message": "Native categorical colour differs from its explicit display overlay.",
    }


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "code",
        "kind",
        "extra",
        "version",
        "returncode",
        "empty",
        "crash",
        "prefix",
    ],
)
def test_only_specific_exact_worker_conflict_is_projected(fault):
    payload = failure()
    if fault == "code":
        payload["reason_code"] = "unrelated_error"
    elif fault == "kind":
        payload["kind"] = "arbitrary"
    elif fault == "extra":
        payload["extra"] = True
    elif fault == "version":
        payload["version"] = True
    elif fault == "empty":
        payload["message"] = ""
    stderr = json.dumps(payload)
    if fault == "crash":
        stderr = "Traceback: programming fault"
    elif fault == "prefix":
        stderr = "Traceback: unrelated failure\n" + stderr
    if fault is None:
        with pytest.raises(CategoricalPresentationConflict) as error:
            raise_categorical_worker_rejection(1, stderr)
        assert error.value.reason_code == CODE
    else:
        assert (
            raise_categorical_worker_rejection(
                2 if fault == "returncode" else 1, stderr
            )
            is None
        )


def test_cold_worker_emits_existing_closed_domain_envelope(monkeypatch, capsys):
    import sciplot_core.veusz_worker as worker
    import sys

    def reject():
        print("Generated native settings diagnostic", file=sys.stderr)
        raise CategoricalPresentationConflict(failure()["message"])

    monkeypatch.setattr(worker, "main", reject)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("sciplot_core.veusz_worker.__main__", run_name="__main__")
    captured = capsys.readouterr()
    assert exit_info.value.code == 1 and captured.out == ""
    assert json.loads(captured.err) == failure()


@pytest.mark.parametrize("known", [True, False])
def test_cold_frame_relays_success_and_unexpected_fault_output(known, capsys):
    import sys
    from sciplot_core.veusz_worker.categorical_rejection import (
        categorical_rejection_frame,
    )

    def execute():
        with categorical_rejection_frame():
            print("ordinary result")
            print("native diagnostic remains visible", file=sys.stderr)
            if not known:
                raise KeyError("programming failure")

    if known:
        execute()
    else:
        with pytest.raises(KeyError, match="programming failure"):
            execute()
    captured = capsys.readouterr()
    assert (
        captured.out == "ordinary result\n"
        and captured.err == "native diagnostic remains visible\n"
    )


@pytest.mark.parametrize("known", [True, False])
def test_persistent_worker_keeps_specific_conflict_separate_from_programming_fault(
    monkeypatch, known
):
    from sciplot_core.veusz_worker import persistent, cli
    from sciplot_core.native_process.protocol import encode

    captured = io.BytesIO()

    @contextmanager
    def capture():
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            yield output, error

    def reject(_):
        import sys

        print("Generated settings chatter", file=sys.stderr)
        if known:
            raise CategoricalPresentationConflict(failure()["message"])
        raise KeyError("programming failure remains a traceback")

    monkeypatch.setattr(persistent, "_capture", capture)
    monkeypatch.setattr(
        persistent, "_application", lambda: SimpleNamespace(quit=lambda: None)
    )
    monkeypatch.setattr(cli, "main", reject)
    monkeypatch.setattr(
        persistent.sys,
        "stdin",
        SimpleNamespace(
            buffer=io.BytesIO(encode({"id": "one", "argv": ["font-families"]}))
        ),
    )
    monkeypatch.setattr(persistent.sys, "stdout", SimpleNamespace(buffer=captured))
    assert persistent.serve() == 0
    response = json.loads(captured.getvalue())
    assert response["returncode"] == 1 and response["stdout"] == ""
    if known:
        assert json.loads(response["stderr"]) == failure()
    else:
        assert "KeyError" in response["stderr"]
        assert (
            raise_categorical_worker_rejection(
                response["returncode"], response["stderr"]
            )
            is None
        )


@pytest.mark.parametrize("known", [True, False])
def test_only_overlay_projects_receive_preflight_before_export_and_publication(
    tmp_path, monkeypatch, known
):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.project_store import FileProjectStore, state
    from sciplot_core.studio_core import native_export_adapter, publication_prepare

    project = tmp_path.resolve()
    studio = project / "studio"
    studio.mkdir()
    document, request = studio / "document.vsz", project / "plot_request.json"
    document.write_bytes(b"saved canonical native")
    source = project / "source.csv"
    source.write_bytes(b"x,y\n1,2\n")
    request.write_text(json.dumps({"input": str(source)}))
    spec = studio / "spec.json"
    payload = {"series": [{"source_artifacts": [{"path": str(source), "sha256": file_sha256(source)}]}]}
    payload.update({KEY: {}} if known else {"ordinary": "existing legacy path"})
    spec.write_text(json.dumps(payload))
    original = {path: path.read_bytes() for path in (document, request, spec, source)}
    digest = file_sha256(document)
    repository = FileProjectStore(project)
    baseline = repository.snapshot(import_legacy=True)
    calls, heads = [], []
    boundary = state.boundary

    def observe(name):
        if name == "after_head":
            heads.append(name)
        boundary(name)

    def audit(actual_document, actual_spec):
        assert (actual_document, actual_spec) == (document, spec)
        calls.append("audit")
        raise CategoricalPresentationConflict(failure()["message"])

    def export(actual_document, *, formats, output_dir, audit_spec_path):
        assert (actual_document, audit_spec_path, formats) == (document, spec, ["pdf"])
        assert {path: path.read_bytes() for path in original} == original
        calls.append("export")
        output_dir.mkdir()
        pdf = output_dir / "document.pdf"
        pdf.write_bytes(b"synthetic pure export")
        return {"document_sha256": digest, "exports": [{"format": "pdf", "path": str(pdf)}]}

    def prepare(**kwargs):
        assert (kwargs["project_dir"], kwargs["request_path"], kwargs["document_path"]) == (
            project, request, document)
        assert kwargs["export_document_sha256"] == digest
        assert [item["format"] for item in kwargs["exports"]] == ["pdf"]
        calls.append("publish")  # Private preparation; the actual Store publishes once below.
        (kwargs["output_dir"] / "manifest.json").write_text(json.dumps({"document_sha256": digest}))
        kwargs["delivery_dir"].mkdir()
        return {"document_sha256": digest, "exports": kwargs["exports"],
                "delivery_package": {"complete": True}, "ready_to_use": True}

    monkeypatch.setattr(state, "boundary", observe)
    monkeypatch.setattr(preflight, "audit_edited_document", audit)
    monkeypatch.setattr(native_export_adapter, "export_studio_document", export)
    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", prepare)
    if known:
        with pytest.raises(CategoricalPresentationConflict):
            project_export.export_project_document(project_dir=project, formats=["pdf"])
        assert calls == ["audit"]
        assert not heads and repository.commands() == ()
        assert repository.snapshot()["generation"] == baseline["generation"]
    else:
        result = project_export.export_project_document(project_dir=project, formats=["pdf"])
        assert result.ready_to_use
        assert calls == ["export", "publish"]
        assert heads == ["after_head"] and len(repository.commands()) == 1
        assert result.document_sha256 == digest
        assert result.run_payload["project_command"]["phase"] == "complete"
        assert result.exports == [{"format": "pdf", "path": str(studio / "exports/document.pdf")}]
        assert (studio / "exports/document.pdf").read_bytes() == b"synthetic pure export"
    assert {path: path.read_bytes() for path in original} == original


def _recover_frozen_display_edit(project, document, spec_path, second_review, monkeypatch):
    """Exercise the same single-Store frozen candidate boundaries for native cases."""
    from pathlib import Path
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.project_store import FileProjectStore, ProjectRecoveryRequired, state
    from sciplot_core.studio_core.document_edit import apply_document_edit
    from sciplot_core.studio_core.document_edit_state import edit_state

    # Before head publication the old pair stays authoritative; after a partial
    # materialization the new sealed pair owns recovery, never a mutable outcome.
    repository = FileProjectStore(Path(project))
    baseline_generation = repository.snapshot()["generation"]
    pair = document.read_bytes(), spec_path.read_bytes()
    boundary = state.boundary
    for failure_boundary in ("before_head", "after_projection"):
        def reject_publication(name, expected=failure_boundary):
            if name == expected:
                raise OSError("generated publication failure: " + expected)
            boundary(name)

        with monkeypatch.context() as fault:
            fault.setattr(state, "boundary", reject_publication)
            with pytest.raises(OSError, match="generated publication failure: " + failure_boundary):
                apply_document_edit(Path(project), second_review)
        record = repository.query(second_review["operation_id"])
        assert record["phase"] == "accepted"
        assert record["decision_id"] == second_review["decision_id"]
        assert record["draft"]["writes"]["studio/document.vsz"]["sha256"] == second_review["candidate"]["sha256"]
        assert record["draft"]["writes"]["studio/spec.json"]["sha256"] == second_review["candidate_spec"]["sha256"]
        if failure_boundary == "before_head":
            assert (document.read_bytes(), spec_path.read_bytes()) == pair
            assert repository.snapshot()["generation"] == baseline_generation
        else:
            with pytest.raises(ProjectRecoveryRequired):
                edit_state(Path(project))
            partial_pair = document.read_bytes(), spec_path.read_bytes()
            assert sum(a == b for a, b in zip(pair, partial_pair, strict=True)) == 1
            spec_path.write_bytes(b"foreign spec must survive pending recovery")
            with pytest.raises(ProjectRecoveryRequired, match="Outside bytes"):
                apply_document_edit(Path(project), second_review)
            assert document.read_bytes() == partial_pair[0]
            assert spec_path.read_bytes() == b"foreign spec must survive pending recovery"
            spec_path.write_bytes(partial_pair[1])  # Restore only this test's exact interrupted view.

    def must_not_prepare(*args, **kwargs):
        pytest.fail("Accepted native candidate recovery must not enter preparation again")

    with monkeypatch.context() as frozen:
        frozen.setattr(FileProjectStore, "mark_applying", must_not_prepare)
        result = apply_document_edit(Path(project), second_review)
        assert result["document_sha256"] == second_review["candidate"]["sha256"]
        assert file_sha256(spec_path) == second_review["candidate_spec"]["sha256"]
        assert repository.query(second_review["operation_id"])["phase"] == "complete"
    return repository
