"""Prepared creation resumes only its bound private work and never replaces delivery."""

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.project_session import external_project_session, ProjectSessionBusy
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.workflow import rheology_tts_creation as creation
from sciplot_core.workflow.rheology_tts_prepared import plot_prepared_suite
from test_rheology_tts_prepared import _request, _write_json


@pytest.fixture
def native_stub(monkeypatch):
    """Isolate publication faults; real native continuation has its own acceptance."""
    from sciplot_core import rheology_tts_render, rheology_tts_render_creation
    from sciplot_core.rheology_tts_spec import compile_tts_spec

    state = {"saves": 0, "calls": [], "result": None}

    def render(spec, out, *, resume=False):
        state["calls"].append(resume)
        if state["result"] is not None:
            return verify(None, out)
        out.mkdir(parents=True, exist_ok=True)
        figures = []
        for figure in compile_tts_spec(spec)["figures"]:
            identifier = figure["id"]
            document, sidecar = out / f"{identifier}.vsz", out / f"{identifier}.spec.json"
            document.write_text("Native stand-in for workflow fault isolation: " + identifier)
            state["saves"] += 1
            _write_json(sidecar, {"figure": figure, "source_binding": spec["source_binding"]})
            exports = []
            for fmt, suffix in (("pdf", ".pdf"), ("tiff_300", "_300dpi.tiff"), ("png_300", "_300dpi.png")):
                path = out / (identifier + suffix)
                path.write_text(identifier + fmt)
                exports.append({"format": fmt, "path": str(path), "sha256": file_sha256(path), "exists": True})
            audit = {"status": "passed", "scope": "Workflow fault stub only", "document": str(document),
                     "document_sha256": file_sha256(document)}
            audit_path = out / f"{identifier}.native-audit.json"
            _write_json(audit_path, audit)
            figures.append({"id": identifier, "document": str(document), "document_sha256": file_sha256(document),
                "spec_path": str(sidecar), "spec_sha256": file_sha256(sidecar), "exports": exports,
                "native_audit_path": str(audit_path), "native_audit": audit, "export_dir": str(out)})
        state["result"] = {"kind": "sciplot_rheology_tts_render", "version": 1, "status": "completed", "figures": figures}
        state["inventory"] = file_inventory(out)
        return deepcopy(state["result"])

    def verify(_compiled, _out):
        if file_inventory(_out) != state["inventory"]:
            raise ValueError("Saved native evidence changed")
        for figure in state["result"]["figures"]:
            for key, digest in (("document", "document_sha256"), ("spec_path", "spec_sha256")):
                if file_sha256(Path(figure[key])) != figure[digest]:
                    raise ValueError("Saved native evidence changed")
            if json.loads(Path(figure["native_audit_path"]).read_text()) != figure["native_audit"]:
                raise ValueError("Native audit sidecar changed")
        return deepcopy(state["result"])

    monkeypatch.setattr(rheology_tts_render, "render_tts_figures", render)
    monkeypatch.setattr(rheology_tts_render_creation, "verify_native_creation", verify)
    monkeypatch.setattr(rheology_tts_render_creation, "check_native_continuation",
                        lambda compiled, out, **_: verify(compiled, out) if state["result"] is not None else None)
    return state


def _paths(tmp_path):
    return tmp_path / ".sciplot/Figures", tmp_path / "Figures"


def _interrupt(monkeypatch, owner, name, *, after=False, predicate=lambda *a, **k: True):
    original = getattr(owner, name)
    active = [True]

    def fail_once(*args, **kwargs):
        if active[0] and predicate(*args, **kwargs):
            active[0] = False
            if after:
                original(*args, **kwargs)
            raise OSError("injected creation interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, fail_once)


@pytest.mark.parametrize("stage", ["startup", "native_saved", "csv", "manifest", "installed_checkpoint"])
def test_prepared_resume_reuses_saved_native_after_each_creation_failure(tmp_path, monkeypatch, native_stub, stage):
    from sciplot_core import rheology_tts_render

    request_path, request, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    if stage in {"startup", "native_saved"}:
        _interrupt(monkeypatch, rheology_tts_render, "render_tts_figures", after=stage == "native_saved")
    elif stage == "csv":
        _interrupt(monkeypatch, creation, "write_plot_tables", after=True)
    elif stage == "manifest":
        _interrupt(monkeypatch, creation, "write_json", predicate=lambda path, _: path.name == "delivery_manifest.json")
    else:
        _interrupt(monkeypatch, creation, "atomic_write_json",
                   predicate=lambda path, value: path.name == creation.CHECKPOINT and value["phase"] == "completed")
    with pytest.raises(OSError, match="injected creation interruption"):
        plot_prepared_suite(request_path)
    saved = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in workspace.rglob("*.vsz")}
    assert delivery.exists() is (stage == "installed_checkpoint")
    with pytest.raises(creation.PreparedCreationBlocked) as error:
        plot_prepared_suite(request_path)
    assert error.value.repair["action"] == ("export_saved_suite" if delivery.exists() else "resume_prepared_creation")
    result = plot_prepared_suite(request_path, resume=True)
    assert result["status"] == "ready" and result["resumed"] is True
    assert native_stub["saves"] == 1
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == previous for p, previous in saved.items())
    manifest = json.loads((workspace / "suite.json").read_text())
    assert manifest == json.loads((delivery / "data/delivery_manifest.json").read_text())
    assert all(Path(d["path"]).is_relative_to(delivery) for d in manifest["documents"])
    assert str(delivery / "editable/Custom.vsz") in (delivery / "editable/Open_Custom.command").read_text()
    assert "publication_stages" not in (delivery / "Open_in_SciPlot.command").read_text()
    assert Path(request["prepared_plan"]).is_file()
    before = file_inventory(delivery)
    calls = len(native_stub["calls"])
    assert plot_prepared_suite(request_path, resume=True)["status"] == "ready"
    assert file_inventory(delivery) == before and len(native_stub["calls"]) == calls


@pytest.mark.parametrize("drift", ["source", "plan", "native", "spec", "audit", "delivery"])
def test_creation_rechecks_bound_evidence_after_atomic_install(tmp_path, monkeypatch, native_stub, drift):
    request_path, request, plan = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    install = creation._install_delivery
    changed = []

    def install_then_change(candidate, destination):
        install(candidate, destination)
        target = {"source": Path(plan["source_binding"]["sources"][0]["path"]),
                  "plan": Path(request["prepared_plan"]), "native": workspace / "initial_render/Custom.vsz",
                  "spec": workspace / "initial_render/Custom.spec.json",
                  "audit": workspace / "initial_render/Custom.native-audit.json",
                  "delivery": delivery / "editable/Custom.vsz"}[drift]
        target.write_bytes(target.read_bytes() + b" ")
        changed.append((target, target.read_bytes()))

    monkeypatch.setattr(creation, "_install_delivery", install_then_change)
    with pytest.raises(ValueError):
        plot_prepared_suite(request_path)
    assert delivery.is_dir() and native_stub["saves"] == 1
    assert all(path.read_bytes() == content for path, content in changed)
    assert json.loads((workspace / creation.CHECKPOINT).read_text())["phase"] == "publication_ready"


@pytest.mark.parametrize("drift", ["prepared_bytes", "source", "contract", "unknown_file", "symlink", "request_out", "checkpoint"])
def test_resume_refuses_changed_or_unknown_bindings_without_native_writes(tmp_path, monkeypatch, native_stub, drift):
    from sciplot_core import rheology_tts_render
    from sciplot_core.workflow import rheology_tts_prepared

    request_path, request, plan = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    _interrupt(monkeypatch, rheology_tts_render, "render_tts_figures")
    with pytest.raises(OSError):
        plot_prepared_suite(request_path)
    if drift == "prepared_bytes":
        path = Path(request["prepared_plan"])
        path.write_bytes(path.read_bytes() + b"\n")
    elif drift == "source":
        Path(plan["source_binding"]["sources"][0]["path"]).write_text("changed raw evidence")
    elif drift == "contract":
        monkeypatch.setattr(rheology_tts_prepared, "rheology_capabilities", lambda: {"contract_sha256": "changed"})
    elif drift == "unknown_file":
        (workspace / "personal-note.txt").write_text("preserve")
    elif drift == "symlink":
        (workspace / "unrecognized").symlink_to(Path(request["prepared_plan"]))
    elif drift == "request_out":
        request["out"] = str(tmp_path / "Other")
        _write_json(request_path, request)
    else:
        (workspace / creation.CHECKPOINT).write_text("[]")
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, creation.PreparedCreationBlocked)):
        plot_prepared_suite(request_path, resume=True)
    assert native_stub["saves"] == 0 and not delivery.exists()
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("resume", [False, True])
def test_existing_unknown_partial_is_never_adopted(tmp_path, native_stub, resume):
    request_path, _, _ = _request(tmp_path)
    workspace, _ = _paths(tmp_path)
    workspace.mkdir(parents=True)
    unknown = workspace / "old.vsz"
    unknown.write_text("earlier uncertain native work")
    with pytest.raises(creation.PreparedCreationBlocked) as error:
        plot_prepared_suite(request_path, resume=resume)
    assert error.value.reason_code == "prepared_creation_unknown_partial"
    assert unknown.read_text() == "earlier uncertain native work" and native_stub["saves"] == 0


def test_atomic_install_never_replaces_empty_directory_created_concurrently(tmp_path, monkeypatch, native_stub):
    request_path, _, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    install = creation._install_delivery

    def race(candidate, destination):
        destination.mkdir()
        install(candidate, destination)

    monkeypatch.setattr(creation, "_install_delivery", race)
    with pytest.raises(FileExistsError):
        plot_prepared_suite(request_path)
    assert delivery.is_dir() and not list(delivery.iterdir())
    assert list((workspace / "publication_stages").glob("*/delivery/editable/Custom.vsz"))
    with pytest.raises(ValueError, match="Visible delivery already exists"):
        plot_prepared_suite(request_path, resume=True)
    assert not list(delivery.iterdir()) and native_stub["saves"] == 1


def test_creation_obeys_existing_workspace_session_lease(tmp_path, native_stub):
    request_path, _, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    workspace.parent.mkdir()
    with external_project_session(workspace):
        with pytest.raises(ProjectSessionBusy):
            plot_prepared_suite(request_path)
    assert native_stub["saves"] == 0 and not workspace.exists() and not delivery.exists()


def test_cli_resume_is_explicit_and_preserves_compact_default(tmp_path, monkeypatch, capsys):
    from sciplot_core.cli.dispatch.rheology import dispatch_rheology
    from sciplot_core.cli.parsers import build_parser
    from sciplot_core.workflow import rheology_tts_prepared

    calls = []
    monkeypatch.setattr(rheology_tts_prepared, "plot_prepared_suite",
                        lambda request, *, resume: calls.append((request, resume)) or {"status": "ready", "resumed": True})
    path = tmp_path / "request.json"
    args = build_parser().parse_args(["rheology", "plot", "--request", str(path), "--resume", "--json"])
    assert dispatch_rheology(args) == 0
    assert calls == [(path, True)] and json.loads(capsys.readouterr().out)["resumed"] is True


def _stop_at_phase(tmp_path, monkeypatch, phase):
    from sciplot_core import rheology_tts_render

    request_path, _, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    seams = {"initialized": (rheology_tts_render, "render_tts_figures"),
             "native_complete": (creation, "write_plot_tables"),
             "publication_ready": (creation, "_install_delivery")}
    if phase == "completed":
        plot_prepared_suite(request_path)
    else:
        _interrupt(monkeypatch, *seams[phase])
        with pytest.raises(OSError, match="injected creation interruption"):
            plot_prepared_suite(request_path)
    assert json.loads((workspace / creation.CHECKPOINT).read_text())["phase"] == phase
    return request_path, workspace, delivery


@pytest.mark.parametrize("phase,field", [
    (phase, field) for phase in ("initialized", "native_complete", "publication_ready", "completed")
    for field in ("attempts", "binding", "phase", "kind", "version")
] + [(phase, "native_result") for phase in ("native_complete", "publication_ready", "completed")]
  + [(phase, "publication") for phase in ("publication_ready", "completed")])
def test_incomplete_checkpoint_stops_before_any_recovery_writes(tmp_path, monkeypatch, native_stub, phase, field):
    request_path, workspace, _ = _stop_at_phase(tmp_path, monkeypatch, phase)
    path = workspace / creation.CHECKPOINT
    checkpoint = json.loads(path.read_text())
    checkpoint.pop(field)
    _write_json(path, checkpoint)
    before = file_inventory(workspace)
    calls = len(native_stub["calls"])
    with pytest.raises((ValueError, creation.PreparedCreationBlocked)):
        plot_prepared_suite(request_path, resume=True)
    assert file_inventory(workspace) == before and len(native_stub["calls"]) == calls


@pytest.mark.parametrize("corruption", ["unknown", "boolean_version", "nonstring_phase", "attempts_type",
    "duplicate_attempts", "native_type", "native_digest", "publication_type", "publication_missing",
    "publication_extra", "unknown_attempt", "files_type", "files_missing", "files_unknown", "bad_sha"])
def test_invalid_checkpoint_stops_before_any_recovery_writes(tmp_path, monkeypatch, native_stub, corruption):
    request_path, workspace, _ = _stop_at_phase(tmp_path, monkeypatch, "publication_ready")
    path = workspace / creation.CHECKPOINT
    checkpoint = json.loads(path.read_text())
    if corruption == "unknown":
        checkpoint["unrecognized"] = "preserve"
    elif corruption == "boolean_version":
        checkpoint["version"] = True
    elif corruption == "nonstring_phase":
        checkpoint["phase"] = []
    elif corruption == "attempts_type":
        checkpoint["attempts"] = None
    elif corruption == "duplicate_attempts":
        checkpoint["attempts"] *= 2
    elif corruption == "native_type":
        checkpoint["native_result"] = []
    elif corruption == "native_digest":
        checkpoint["native_result"]["figures"][0]["document_sha256"] = "a" * 64
    elif corruption == "publication_type":
        checkpoint["publication"] = []
    elif corruption == "publication_missing":
        checkpoint["publication"].pop("files")
    elif corruption == "publication_extra":
        checkpoint["publication"]["unknown"] = True
    elif corruption == "unknown_attempt":
        checkpoint["publication"]["attempt"] = "a" * 32
    elif corruption == "files_type":
        checkpoint["publication"]["files"] = []
    elif corruption == "files_missing":
        checkpoint["publication"]["files"].pop("index.html")
    elif corruption == "files_unknown":
        checkpoint["publication"]["files"]["../other"] = "a" * 64
    else:
        checkpoint["publication"]["manifest_sha256"] = "bad"
    _write_json(path, checkpoint)
    before = file_inventory(workspace)
    calls = len(native_stub["calls"])
    with pytest.raises((ValueError, creation.PreparedCreationBlocked)):
        plot_prepared_suite(request_path, resume=True)
    assert file_inventory(workspace) == before and len(native_stub["calls"]) == calls


def test_native_complete_resume_verifies_original_receipt_without_rebinding(tmp_path, monkeypatch, native_stub):
    request_path, workspace, _ = _stop_at_phase(tmp_path, monkeypatch, "native_complete")
    path = workspace / creation.CHECKPOINT
    checkpoint = json.loads(path.read_text())
    checkpoint["native_result"]["figures"][0]["document_sha256"] = "a" * 64
    _write_json(path, checkpoint)
    before = file_inventory(workspace)
    calls = len(native_stub["calls"])
    with pytest.raises(ValueError, match="Sealed native creation receipts changed"):
        plot_prepared_suite(request_path, resume=True)
    assert file_inventory(workspace) == before and len(native_stub["calls"]) == calls


@pytest.mark.parametrize("missing", ["request.json", "figure_plan.json", "suite.json"])
def test_completed_resume_never_recreates_missing_historical_evidence(tmp_path, monkeypatch, native_stub, missing):
    request_path, workspace, delivery = _stop_at_phase(tmp_path, monkeypatch, "completed")
    (workspace / missing).unlink()
    before, visible = file_inventory(workspace), file_inventory(delivery)
    with pytest.raises(ValueError, match="missing"):
        plot_prepared_suite(request_path, resume=True)
    assert not (workspace / missing).exists()
    assert file_inventory(workspace) == before and file_inventory(delivery) == visible


@pytest.mark.parametrize("change", ["hidden_hardlink", "visible_hardlink", "empty_directory", "launcher_mode"])
def test_resume_rejects_aliased_or_unrecognized_delivery_evidence(tmp_path, monkeypatch, native_stub, change):
    request_path, workspace, delivery = _stop_at_phase(tmp_path, monkeypatch, "completed")
    if change in {"hidden_hardlink", "visible_hardlink"}:
        target = workspace / "request.json" if change == "hidden_hardlink" else delivery / "editable/Custom.vsz"
        os.link(target, tmp_path / "external-alias")
    elif change == "empty_directory":
        (delivery / "personal").mkdir()
    else:
        (delivery / "Open_in_SciPlot.command").chmod(0o644)
    before, visible = file_inventory(workspace), file_inventory(delivery)
    with pytest.raises(ValueError):
        plot_prepared_suite(request_path, resume=True)
    assert file_inventory(workspace) == before and file_inventory(delivery) == visible


@pytest.mark.parametrize("target", ["initial_render", "logs", "publication_stages", ".sciplot_session_locks"])
def test_resume_rejects_workspace_directories_replaced_by_files(tmp_path, monkeypatch, native_stub, target):
    request_path, workspace, delivery = _stop_at_phase(tmp_path, monkeypatch, "initialized")
    (workspace / target).write_text("unrelated content; preserve")
    before = file_inventory(workspace)
    with pytest.raises(ValueError, match="path types changed"):
        plot_prepared_suite(request_path, resume=True)
    assert file_inventory(workspace) == before and not delivery.exists() and native_stub["saves"] == 0


@pytest.mark.parametrize("missing", ["request.json", "figure_plan.json"])
def test_initialized_with_native_work_requires_original_input_evidence(tmp_path, monkeypatch, native_stub, missing):
    from sciplot_core import rheology_tts_render

    request_path, _, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    _interrupt(monkeypatch, rheology_tts_render, "render_tts_figures", after=True)
    with pytest.raises(OSError):
        plot_prepared_suite(request_path)
    (workspace / missing).unlink()
    before = file_inventory(workspace)
    with pytest.raises(ValueError, match="input evidence is missing"):
        plot_prepared_suite(request_path, resume=True)
    assert file_inventory(workspace) == before and not delivery.exists() and native_stub["saves"] == 1
