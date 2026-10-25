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
    def saved(compiled, out):
        result = verify(compiled, out)
        return {"figures": [{"id": item["id"], "document_sha256": item["document_sha256"],
                              "spec_sha256": item["spec_sha256"]} for item in result["figures"]]}
    monkeypatch.setattr(rheology_tts_render_creation, "check_saved_native_creation", saved)
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
        from sciplot_core.project_commands import ProjectCommands
        _interrupt(monkeypatch, ProjectCommands, "decide", after=True,
                   predicate=lambda self, command, **kwargs: command.kind.value == "create")
    with pytest.raises(OSError, match="injected creation interruption"):
        plot_prepared_suite(request_path)
    saved = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in workspace.rglob("*.vsz")}
    assert (delivery / "editable/Custom.vsz").exists() is (stage == "installed_checkpoint")
    assert (workspace / "suite.json").exists() is (stage == "installed_checkpoint")
    assert not (workspace / creation.CHECKPOINT).exists()
    with pytest.raises(creation.PreparedCreationBlocked) as error:
        plot_prepared_suite(request_path)
    assert error.value.repair["action"] == ("export_saved_suite" if (workspace / "suite.json").exists() else "resume_prepared_creation")
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
    from sciplot_core.project_commands import ProjectCommands
    decide = ProjectCommands.decide
    changed = []

    def install_then_change(self, command, **kwargs):
        result = decide(self, command, **kwargs)
        if command.kind.value != "create":
            return result
        target = {"source": Path(plan["source_binding"]["sources"][0]["path"]),
                  "plan": Path(request["prepared_plan"]), "native": workspace / "initial_render/Custom.vsz",
                  "spec": workspace / "initial_render/Custom.spec.json",
                  "audit": workspace / "initial_render/Custom.native-audit.json",
                  "delivery": delivery / "editable/Custom.vsz"}[drift]
        target.write_bytes(target.read_bytes() + b" ")
        changed.append((target, target.read_bytes()))
        return result

    monkeypatch.setattr(ProjectCommands, "decide", install_then_change)
    with pytest.raises(ValueError):
        plot_prepared_suite(request_path)
    assert delivery.is_dir() and native_stub["saves"] == 1
    assert all(path.read_bytes() == content for path, content in changed)
    from sciplot_core.project_store import FileProjectStore
    store = FileProjectStore(workspace, locations={"delivery": delivery})
    publication = next(item for item in store.commands() if item["metadata"]["kind"] == "create")
    assert publication["phase"] == "complete"  # commit and returned readiness remain independent
    assert not (workspace / creation.CHECKPOINT).exists()


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
    assert native_stub["saves"] == 0 and not list(delivery.iterdir())
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
    from sciplot_core.project_store import state
    from sciplot_core.project_store.errors import ProjectRecoveryRequired
    swapped = []
    def race(name):
        if name == "before_head" and (workspace / "suite.json").exists() is False:
            # No nested store lock: the files-to-publish appear in the private
            # workspace only after native saving; earlier source seals skip.
            if not list((workspace / ".sciplot_store/native_work").glob("*/candidate/workspace/suite.json")):
                return
            if not swapped:
                original = delivery.with_name("original-empty-root")
                delivery.rename(original)
                delivery.mkdir()
                swapped.append(original)
    monkeypatch.setattr(state, "boundary", race)
    with pytest.raises(ProjectRecoveryRequired):
        plot_prepared_suite(request_path)
    assert delivery.is_dir() and not list(delivery.iterdir())
    assert swapped[0].is_dir() and not list(swapped[0].iterdir())
    assert list((workspace / ".sciplot_store/native_work").glob("*/candidate/workspace/initial_render/Custom.vsz"))
    monkeypatch.setattr(state, "boundary", lambda _name: None)
    with pytest.raises(ValueError):
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


def _seed_legacy_creation(request_path, workspace, delivery):
    """Construct historical v1 bytes explicitly, outside new-command admission."""
    from sciplot_core.rheology_tts_spec import compile_tts_spec
    from sciplot_core.rheology_tts_style import prepare_tts_presentation
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    request = json.loads(request_path.read_text())
    plan = Path(request["prepared_plan"])
    spec = prepare_tts_presentation(json.loads(plan.read_text()))
    spec["source_binding"]["prepared_plan"] = {"path": str(plan), "sha256": file_sha256(plan),
        "authority": "External AI processing; local plotting preserves the supplied numeric coordinates."}
    compiled = compile_tts_spec(spec)
    binding = creation._creation_binding(request, spec, compiled, delivery, workspace,
                                         rheology_capabilities()["contract_sha256"])
    from native_suite_legacy_creation_fixture import _create_locked
    return _create_locked(request_path, request, spec, compiled, delivery, workspace, binding, resume=False)


def _stop_at_phase(tmp_path, monkeypatch, phase):
    from sciplot_core import rheology_tts_render

    request_path, _, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    import native_suite_legacy_creation_fixture as legacy
    seams = {"initialized": (rheology_tts_render, "render_tts_figures"),
             "native_complete": (legacy, "write_plot_tables"),
             "publication_ready": (legacy, "_install_delivery")}
    if phase == "completed":
        _seed_legacy_creation(request_path, workspace, delivery)
    else:
        _interrupt(monkeypatch, *seams[phase])
        with pytest.raises(OSError, match="injected creation interruption"):
            _seed_legacy_creation(request_path, workspace, delivery)
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
        _seed_legacy_creation(request_path, workspace, delivery)
    (workspace / missing).unlink()
    before = file_inventory(workspace)
    with pytest.raises(ValueError, match="input evidence is missing"):
        plot_prepared_suite(request_path, resume=True)
    assert file_inventory(workspace) == before and not delivery.exists() and native_stub["saves"] == 1


@pytest.mark.parametrize("closure", ["missing", "unclosed"])
def test_unknown_native_creation_requires_recorded_child_closure(tmp_path, monkeypatch, native_stub, closure):
    from sciplot_core import rheology_tts_render
    from sciplot_core.project_commands.errors import ProjectCommandUnknown
    from sciplot_core.project_store import FileProjectStore
    request_path, _, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    append = FileProjectStore.append_native_failure
    def preserve_unknown(self, *args, **kwargs):
        if closure == "unclosed":
            return append(self, *args, **{**kwargs, "owned_invocation_closed": False})
        return None  # synthetic abrupt parent loss before failure-fact persistence
    monkeypatch.setattr(FileProjectStore, "append_native_failure", preserve_unknown)
    _interrupt(monkeypatch, rheology_tts_render, "render_tts_figures", after=True)
    with pytest.raises(OSError, match="injected creation interruption"):
        plot_prepared_suite(request_path)
    store = FileProjectStore(workspace, locations={"delivery": delivery})
    parent = next(item for item in store.commands() if item["metadata"]["kind"] == "native_create")
    assert parent["phase"] == "unknown" and native_stub["saves"] == 1
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(parent["native_workspace_path"]).rglob("*") if p.is_file()}
    calls = len(native_stub["calls"])
    with pytest.raises(ProjectCommandUnknown):
        plot_prepared_suite(request_path, resume=True)
    assert len(native_stub["calls"]) == calls and native_stub["saves"] == 1
    assert not list(delivery.iterdir()) and store.query(parent["command_id"])["phase"] == "unknown"
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in before.items())


@pytest.mark.parametrize("drift", ["native", "spec", "audit", "unknown"])
def test_known_native_creation_recovery_rejects_changed_receipt_without_save(tmp_path, monkeypatch, native_stub, drift):
    from sciplot_core import rheology_tts_render
    from sciplot_core.project_store import FileProjectStore
    request_path, _, _ = _request(tmp_path)
    workspace, delivery = _paths(tmp_path)
    _interrupt(monkeypatch, rheology_tts_render, "render_tts_figures", after=True)
    with pytest.raises(OSError):
        plot_prepared_suite(request_path)
    store = FileProjectStore(workspace, locations={"delivery": delivery})
    parent = next(item for item in store.commands() if item["metadata"]["kind"] == "native_create")
    out = Path(parent["native_workspace_path"]) / "workspace/initial_render"
    target = out / {"native": "Custom.vsz", "spec": "Custom.spec.json", "audit": "Custom.native-audit.json", "unknown": "foreign.txt"}[drift]
    target.write_bytes(target.read_bytes() + b" " if target.exists() else b"unknown owner")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in out.rglob("*") if p.is_file()}
    calls = len(native_stub["calls"])
    with pytest.raises(ValueError):
        plot_prepared_suite(request_path, resume=True)
    assert native_stub["saves"] == 1 and len(native_stub["calls"]) == calls
    assert not list(delivery.iterdir()) and store.query(parent["command_id"])["phase"] == "unknown"
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in before.items())


def test_pending_creation_cold_resume_uses_registered_original_request_and_native_fact(tmp_path, monkeypatch, native_stub):
    from sciplot_core import rheology_tts_render_creation
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    original = tmp_path / "original"
    original.mkdir()
    request_path, _, _ = _request(original)
    workspace, delivery = _paths(original)
    _interrupt(monkeypatch, creation, "write_plot_tables", after=True)
    with pytest.raises(OSError):
        plot_prepared_suite(request_path)
    store = FileProjectStore(workspace, locations={"delivery": delivery})
    parent = next(item for item in store.commands() if item["metadata"]["kind"] == "native_create")
    assert parent["phase"] == "unknown" and store.query(parent["command_id"] + ":native-fact")["phase"] == "complete"
    bundle = store.export_bundle(tmp_path / "bundle")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "relocated")
    original.rename(tmp_path / "offline-original")
    source = parent["metadata"]["request"]["request_file"]
    local_request = moved.resolve_path(source["path"], expected_sha256=source["sha256"])
    assert not request_path.exists() and local_request.is_relative_to(moved.root)
    expected_native = deepcopy(native_stub["result"])
    expected_spec = parent["metadata"]["request"]["binding"]["compiled_sha256"]
    def read_only_complete(compiled, out, *, completed=False):
        assert completed and canonical_json_sha256(compiled) == expected_spec
        assert file_inventory(out) == native_stub["inventory"]
        return deepcopy(expected_native)
    # The workflow fixture's original paths are deliberately offline. Validate
    # exact imported bytes at the actual directory; this is a synthetic renderer
    # proof, not evidence of native kernel/runtime execution.
    monkeypatch.setattr(rheology_tts_render_creation, "check_native_continuation", read_only_complete)
    calls = len(native_stub["calls"])
    result = plot_prepared_suite(local_request, resume=True)
    assert result["status"] == "ready" and native_stub["saves"] == 1 and len(native_stub["calls"]) == calls
    assert (moved.locations["delivery"] / "editable/Custom.vsz").is_file()
    assert moved.query(parent["command_id"])["phase"] == "unknown"
    manifest = json.loads(moved.read_bytes("suite.json"))
    assert manifest["sources"] == parent["metadata"]["request"]["binding"]["sources"]
    assert json.loads(moved.read_bytes("initial_render/Custom.spec.json"))["source_binding"] == json.loads(
        Path(moved.query(parent["command_id"] + ":native-fact")["artifact_paths"]["Custom.spec.json"]).read_bytes())["source_binding"]


def test_legacy_analysis_creation_resume_does_not_repeat_analysis_or_native_save(tmp_path, monkeypatch, native_stub):
    from sciplot_core.semantic_sources import rheology_tts as analysis_owner
    from sciplot_core.workflow import rheology_tts_figures as figures, rheology_tts_suite as suite
    from sciplot_core.rheology_tts_style import prepare_tts_presentation
    _, _, plan = _request(tmp_path)
    spec = prepare_tts_presentation(plan)
    source = plan["source_binding"]["sources"][0]["path"]
    request = {"version": 1, "frequency_source": source, "reference_temperature_C": 210,
        "frequency_temperature_C": 210, "out": str(tmp_path / "Figures"),
        "samples": [{"sample_id": "fixture", "polymer": "HDPE", "udc_wt_percent": 0,
                     "frequency_test": "explicit synthetic fixture"}]}
    request_path = tmp_path / "analysis-request.json"
    _write_json(request_path, request)
    analyses = []
    def analyze(value):
        analyses.append(deepcopy(value))
        return {"fixture": "Fixed analysis result; not a scientific runtime test"}
    monkeypatch.setattr(analysis_owner, "analyze_tts_request", analyze)
    monkeypatch.setattr(figures, "build_tts_figures", lambda *_a, **_k: deepcopy(spec))
    monkeypatch.setattr(figures, "write_analysis_tables", lambda _value, root: (root / "analysis.csv").write_text("fixed fixture"))
    monkeypatch.setattr(suite, "write_methods", lambda path, _value: path.write_text("fixed methods"))
    _interrupt(monkeypatch, suite, "write_plot_tables", after=True)
    with pytest.raises(OSError):
        suite.create_suite(request_path)
    workspace, delivery = _paths(tmp_path)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in workspace.rglob("*.vsz")}
    calls = len(native_stub["calls"])
    result = suite.create_suite(request_path, resume=True)
    assert result["status"] == "ready" and (delivery / "editable/Custom.vsz").is_file()
    assert len(analyses) == 1 and native_stub["saves"] == 1 and len(native_stub["calls"]) == calls
    assert all((path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items())
    assert suite.create_suite(request_path, resume=True)["status"] == "ready"
    assert len(analyses) == 1 and native_stub["saves"] == 1 and len(native_stub["calls"]) == calls


def test_legacy_tts_resume_cli_is_explicit(tmp_path, monkeypatch, capsys):
    from sciplot_core.cli.dispatch.rheology import dispatch_rheology
    from sciplot_core.cli.parsers import build_parser
    from sciplot_core.workflow import rheology_tts_suite as suite
    calls = []
    monkeypatch.setattr(suite, "create_suite", lambda request, *, resume: calls.append((request, resume)) or {"status": "ready"})
    request = tmp_path / "same-request.json"
    args = build_parser().parse_args(["rheology", "tts", "--request", str(request), "--resume", "--json"])
    assert dispatch_rheology(args) == 0 and calls == [(request, True)]
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
