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
    studio = tmp_path / "studio"
    studio.mkdir()
    spec = studio / "spec.json"
    spec.write_text(
        json.dumps({KEY: {}} if known else {"ordinary": "existing legacy path"})
    )
    calls = []

    def audit(*args):
        calls.append("audit")
        raise CategoricalPresentationConflict(failure()["message"])

    def export(*args, **kwargs):
        calls.append("export")
        return {"document_sha256": "a" * 64, "exports": []}

    monkeypatch.setattr(preflight, "audit_edited_document", audit)
    monkeypatch.setattr(project_export, "export_studio_document", export)
    monkeypatch.setattr(
        project_export,
        "publish_studio_export_run",
        lambda **kwargs: calls.append("publish") or {"ready_to_use": True},
    )
    if known:
        with pytest.raises(CategoricalPresentationConflict):
            project_export.export_project_document(
                project_dir=tmp_path, formats=["pdf"]
            )
        assert calls == ["audit"]
    else:
        assert project_export.export_project_document(
            project_dir=tmp_path, formats=["pdf"]
        ).ready_to_use
        assert calls == ["export", "publish"]
