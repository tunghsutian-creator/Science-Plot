"""First-failure guidance reads the same guarded evidence without recovery writes."""

import json
from pathlib import Path

import pytest

from sciplot_core import rheology_tts_render, rheology_tts_render_creation as native
from sciplot_core.cli.value_io import _cli_runtime_error_payload
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_spec import compile_tts_spec
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.workflow import rheology_tts_creation as creation
from sciplot_core.workflow.rheology_tts_creation_repair import attach_creation_repair
from sciplot_core.workflow.rheology_tts_prepared import plot_prepared_suite
from test_rheology_tts_prepared import _request, _write_json
from test_rheology_tts_render_creation import _snapshot, scenario

native_scenario = scenario


@pytest.fixture
def prepared_case(tmp_path, monkeypatch, native_scenario):
    case = native_scenario
    case.request, request, plan = _request(tmp_path)
    case.request_value, case.plan = request, plan
    case.source = Path(plan["source_binding"]["sources"][0]["path"])
    case.prepared = Path(request["prepared_plan"])
    case.workspace, case.delivery = tmp_path / ".sciplot/Figures", tmp_path / "Figures"
    case.out = case.workspace / "initial_render"
    case.root = tmp_path
    case.error = OSError("original export or publication failure")
    case.error.reason_code = "fixture_original_failure"
    case.production_render = rheology_tts_render.render_tts_figures

    def render(spec, out, *, resume=False):
        case.out = out  # the actual admitted private renderer root
        return native.render_native_creation(compile_tts_spec(spec), out, resume=resume, export_figure=case.export)

    monkeypatch.setattr(rheology_tts_render, "render_tts_figures", render)
    def complete(compiled, out):
        case.out = out
        return native.render_native_creation(compiled, out, resume=True, export_only=True, export_figure=case.export)
    monkeypatch.setattr(rheology_tts_render, "complete_tts_creation_exports", complete)
    case.run = lambda **kwargs: plot_prepared_suite(case.request, **kwargs)
    return case


def _inject(monkeypatch, case, owner, name, *, after=False, predicate=lambda *a, **k: True, mutate=None):
    original = getattr(owner, name)
    active = [True]

    def fail_once(*args, **kwargs):
        if active[0] and predicate(*args, **kwargs):
            active[0] = False
            if after:
                original(*args, **kwargs)
            if mutate:
                mutate()
            case.before = _snapshot(case.root)
            case.calls = (case.saves[:], case.exports[:])
            raise case.error
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, fail_once)


def _assert_failure(case, action):
    with pytest.raises(type(case.error)) as caught:
        case.run()
    assert caught.value is case.error
    payload = _cli_runtime_error_payload(caught.value)
    assert payload["exception_type"] == type(case.error).__name__
    assert payload["message"] == str(case.error)
    assert payload["reason_code"] == "fixture_original_failure"
    repair = payload["repair"]
    assert repair["action"] == action
    assert repair["request"] == str(case.request)
    assert repair["workspace"] == str(case.workspace)
    assert repair["repository"] == str(case.workspace / ".sciplot_store")
    assert "checkpoint" not in repair  # one command owner, no invented v1 checkpoint
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.io import digest
    store = FileProjectStore(case.workspace, locations={"delivery": case.delivery})
    parent = next(record for record in store.commands() if record["metadata"]["kind"] == "native_create")
    allowed = str((case.workspace / ".sciplot_store/commands" / (digest(parent["command_id"]) + ".json")).relative_to(case.root))
    after = _snapshot(case.root)
    assert set(after) == set(case.before)
    assert all(after[name] == value for name, value in case.before.items() if name != allowed)
    if after[allowed] != case.before[allowed]:
        assert parent["phase"] == "unknown"
        assert parent["native_failures"][-1]["original_error"] == type(case.error).__name__ + ": " + str(case.error)
    assert (case.saves, case.exports) == case.calls
    if action == "resume_prepared_creation":
        assert repair["command"] == ["rheology", "plot", "--request", str(case.request), "--resume", "--json"]
    else:
        assert "command" not in repair
    case.after_failure = _snapshot(case.root)
    return repair


@pytest.mark.parametrize("stage", ["before_native", "saved_export", "completed_native", "csv", "manifest",
                                   "publication_ready", "renamed", "completed_checkpoint"])
def test_first_failure_recommends_only_guarded_resume_and_preserves_exception(prepared_case, monkeypatch, stage):
    case = prepared_case
    if stage in {"before_native", "completed_native"}:
        _inject(monkeypatch, case, rheology_tts_render, "render_tts_figures", after=stage == "completed_native")
    elif stage == "saved_export":
        _inject(monkeypatch, case, case, "export")
    elif stage == "csv":
        _inject(monkeypatch, case, creation, "write_plot_tables", after=True)
    elif stage == "manifest":
        _inject(monkeypatch, case, creation, "write_json",
                predicate=lambda path, _: path.name == "delivery_manifest.json")
    elif stage == "publication_ready":
        from sciplot_core.project_commands import ProjectCommands
        _inject(monkeypatch, case, ProjectCommands, "decide", predicate=lambda self, command, **_: command.kind.value == "create")
    elif stage == "renamed":
        from sciplot_core.project_store import FileProjectStore
        _inject(monkeypatch, case, FileProjectStore, "publish_staged", after=True,
                predicate=lambda self, key, *_args, **_kwargs: key.endswith(":publish"))
    else:
        from sciplot_core.project_commands import ProjectCommands
        _inject(monkeypatch, case, ProjectCommands, "decide", after=True,
                predicate=lambda self, command, **_: command.kind.value == "create")
    _assert_failure(case, "resume_prepared_creation")
    assert case.run(resume=True)["status"] == "ready"
    assert case.saves == ["Custom"]


@pytest.mark.parametrize("uncertain", ["before_save", "after_save", "saved_checkpoint"])
def test_uncertain_save_first_failure_and_plain_retry_both_require_inspection(prepared_case, monkeypatch, uncertain):
    from sciplot_core import rheology_tts_native

    case = prepared_case
    if uncertain == "saved_checkpoint":
        _inject(monkeypatch, case, native, "atomic_write_json", predicate=lambda path, state: state.get("state") == "saved")
    else:
        _inject(monkeypatch, case, rheology_tts_native, "save_native_figure", after=uncertain == "after_save")
    _assert_failure(case, "inspect_creation_evidence")
    with pytest.raises(creation.PreparedCreationBlocked) as caught:
        case.run()
    assert caught.value.repair["action"] == "inspect_creation_evidence"
    assert "--resume" not in str(caught.value)
    assert _snapshot(case.root) == case.after_failure


@pytest.mark.parametrize("drift", ["source", "prepared", "request", "ledger", "contract", "native", "spec",
                                   "checkpoint", "unknown", "source_symlink", "visible"])
def test_first_failure_never_recommends_resume_after_drift(prepared_case, monkeypatch, drift):
    from sciplot_core.workflow import rheology_tts_contract

    case = prepared_case

    def mutate():
        if drift in {"source", "prepared"}:
            path = getattr(case, drift)
            path.write_bytes(path.read_bytes() + b"\n")
        elif drift == "request":
            _write_json(case.request, {**case.request_value, "out": str(case.root / "Other")})
        elif drift == "ledger":
            value = json.loads(case.prepared.read_text())
            value["transform_ledger"]["operations"] = "changed ledger"
            _write_json(case.prepared, value)
        elif drift == "contract":
            monkeypatch.setattr(rheology_tts_contract, "rheology_capabilities", lambda: {"contract_sha256": "changed"})
        elif drift in {"native", "spec"}:
            (case.out / ("Custom.vsz" if drift == "native" else "Custom.spec.json")).write_text("changed")
        elif drift == "checkpoint":
            (case.workspace / creation.CHECKPOINT).write_text("[]")
        elif drift == "unknown":
            (case.workspace / "personal.txt").write_text("preserve")
        elif drift == "source_symlink":
            copy = case.root / "source-copy.csv"
            copy.write_bytes(case.source.read_bytes())
            case.source.unlink()
            case.source.symlink_to(copy)
        else:
            case.delivery.rename(case.root / "original-empty-delivery")
            case.delivery.mkdir()

    _inject(monkeypatch, case, case, "export", mutate=mutate)
    _assert_failure(case, "inspect_creation_evidence")
    assert not case.delivery.exists() or not list(case.delivery.iterdir())


@pytest.mark.parametrize("conflict", ["empty", "populated", "edited_installed", "hidden_manifest"])
def test_publication_conflicts_are_inspect_on_first_failure_and_plain_retry(prepared_case, monkeypatch, conflict):
    case = prepared_case

    def mutate():
        if conflict in {"empty", "populated"}:
            case.delivery.rename(case.root / "original-empty-delivery")
            case.delivery.mkdir()
            if conflict == "populated":
                (case.delivery / "user.vsz").write_text("preserve user document")
        elif conflict == "edited_installed":
            (case.delivery / "editable/Custom.vsz").write_text("preserve later user edit")
        else:
            (case.workspace / "suite.json").write_text('{"unrelated": true}')

    from sciplot_core.project_commands import ProjectCommands
    _inject(monkeypatch, case, ProjectCommands, "decide", after=conflict == "edited_installed", mutate=mutate,
            predicate=lambda self, command, **_: command.kind.value == "create")
    _assert_failure(case, "inspect_creation_evidence")
    with pytest.raises(creation.PreparedCreationBlocked) as caught:
        case.run()
    assert caught.value.repair["action"] == "inspect_creation_evidence"
    assert _snapshot(case.root) == case.after_failure


def test_source_failure_before_creation_has_locations_without_allocating_workspace(prepared_case):
    case = prepared_case
    case.source.write_text("changed original bytes")
    before = _snapshot(case.root)
    with pytest.raises(ValueError) as caught:
        case.run()
    payload = _cli_runtime_error_payload(caught.value)
    assert payload["repair"]["action"] == "inspect_creation_evidence"
    assert payload["repair"]["workspace"] == str(case.workspace)
    assert not case.workspace.parent.exists() and _snapshot(case.root) == before


def test_lease_failure_has_inspection_only_without_native_or_projection_writes(prepared_case):
    case = prepared_case
    case.workspace.parent.mkdir()
    with external_project_session(case.workspace):
        before = _snapshot(case.root)
        with pytest.raises(ValueError) as caught:
            case.run()
    assert caught.value.reason_code == "project_busy"
    assert caught.value.repair["action"] == "inspect_creation_evidence"
    assert _snapshot(case.root) == before and not case.saves and not case.exports


def test_projection_failure_cannot_replace_original_error(prepared_case, monkeypatch):
    case = prepared_case
    _inject(monkeypatch, case, rheology_tts_render, "render_tts_figures")
    def inaccessible(*_args, **_kwargs):
        raise PermissionError("cannot inspect checkpoint")
    from sciplot_core.workflow import native_suite_creation_inspection
    monkeypatch.setattr(native_suite_creation_inspection, "inspect_creation_continuation", inaccessible)
    repair = _assert_failure(case, "inspect_creation_evidence")
    assert repair["blocked_by"] == "cannot inspect checkpoint"


@pytest.mark.parametrize("phase", ["native_complete", "publication_ready"])
def test_projection_does_not_acquire_lease_or_invoke_any_write_owner(prepared_case, monkeypatch, phase):
    from sciplot_core import rheology_tts_native

    case, attempts = prepared_case, []
    def forbid(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("Error guidance attempted an operation instead of reading its evidence")
    from sciplot_core.workflow import rheology_tts_creation_repair as repair_owner
    from sciplot_core.project_commands import ProjectCommands
    from sciplot_core.project_store import FileProjectStore
    original_attach = repair_owner.attach_creation_repair
    def read_only_projection(*args, **kwargs):
        with monkeypatch.context() as guarded:
            for owner, names in ((ProjectCommands, ("execute", "preview", "decide", "resume", "publish_prepared")),
                                 (FileProjectStore, ("reserve", "mark_applying", "publish", "publish_staged", "stage", "recover")),
                                 (native, ("external_project_session", "atomic_write_json", "_stage_exports")),
                                 (rheology_tts_native, ("save_native_figure",))):
                for name in names:
                    guarded.setattr(owner, name, forbid)
            return original_attach(*args, **kwargs)
    monkeypatch.setattr(repair_owner, "attach_creation_repair", read_only_projection)
    if phase == "native_complete":
        _inject(monkeypatch, case, creation, "write_plot_tables")
    else:
        _inject(monkeypatch, case, ProjectCommands, "decide", predicate=lambda self, command, **_: command.kind.value == "create")
    _assert_failure(case, "resume_prepared_creation")
    assert attempts == []


def test_projection_preserves_existing_repair_and_immutable_exception(tmp_path):
    error = ValueError("original")
    error.repair = {"action": "existing_domain_action"}
    attach_creation_repair(error, tmp_path / "request.json", tmp_path / "workspace")
    assert error.repair == {"action": "existing_domain_action"}

    class ImmutableFailure(Exception):
        def __setattr__(self, _name, _value):
            raise RuntimeError("no attributes allowed")

    immutable = ImmutableFailure("keep this original")
    attach_creation_repair(immutable, tmp_path / "request.json", tmp_path / "workspace")
    assert str(immutable) == "keep this original"


@pytest.mark.parametrize("fault,action", [("export", "resume_prepared_creation"),
    ("uncertain_save", "inspect_creation_evidence"), ("source", "inspect_creation_evidence")])
def test_first_public_cli_json_failure_exposes_the_verified_next_step(prepared_case, monkeypatch, capsys, fault, action):
    from sciplot_core import cli, rheology_tts_native

    case = prepared_case
    if fault == "export":
        _inject(monkeypatch, case, case, "export")
    elif fault == "uncertain_save":
        _inject(monkeypatch, case, rheology_tts_native, "save_native_figure")
    else:
        case.source.write_text("changed original bytes")
    assert cli.main(["rheology", "plot", "--request", str(case.request), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed" and payload["repair"]["action"] == action
    assert payload["repair"]["request"] == str(case.request)
    assert payload["repair"]["workspace"] == str(case.workspace)
    if fault != "source":
        assert payload["exception_type"] == "OSError" and payload["message"] == str(case.error)
        assert payload["reason_code"] == "fixture_original_failure"


@pytest.mark.parametrize("worker", [False, True])
def test_direct_and_child_native_busy_both_require_inspection(prepared_case, monkeypatch, worker):
    from sciplot_core.studio_core.project_session import ProjectSessionBusy

    case = prepared_case
    def render_with_busy_native(spec, out, *, resume=False):
        case.out = out
        with external_project_session(out):
            if worker:
                return case.production_render(spec, out, resume=resume)
            return native.render_native_creation(compile_tts_spec(spec), out, resume=resume, export_figure=case.export)
    monkeypatch.setattr(rheology_tts_render, "render_tts_figures", render_with_busy_native)
    monkeypatch.setattr(rheology_tts_render, "needs_veusz_worker_process", lambda: True)
    with pytest.raises(RuntimeError if worker else ProjectSessionBusy) as caught:
        case.run()
    assert caught.value.repair["action"] == "inspect_creation_evidence"
    if worker:
        assert type(caught.value) is RuntimeError
        assert caught.value.native_reason_code == "project_busy"
        message = str(caught.value)
        assert message.startswith("Native TTS figure operation failed:\n")
        assert "\nTraceback (most recent call last):\n" in message
        assert message.rstrip().splitlines()[-1].startswith(
            f"{ProjectSessionBusy.__module__}.{ProjectSessionBusy.__name__}: "
        )
    else:
        assert caught.value.reason_code == "project_busy"
    assert not case.out.exists() and not case.saves and not case.exports


@pytest.mark.parametrize("boundary", ["needs_review", "accepted", "after_head"])
def test_sealed_renderer_fact_failure_resumes_storage_without_native_reexecution(prepared_case, monkeypatch, boundary):
    from sciplot_core.project_commands import ProjectCommands
    from sciplot_core.project_store import FileProjectStore, state
    case = prepared_case
    if boundary == "needs_review":
        _inject(monkeypatch, case, ProjectCommands, "stage_prepared", after=True,
                predicate=lambda self, command, *_a, **_k:
                command.to_payload()["request"].get("adapter") == "native_suite_renderer_fact")
    else:
        name = "before_storage" if boundary == "accepted" else "after_head"
        _inject(monkeypatch, case, state, "boundary", predicate=lambda value: value == name and case.saves == ["Custom"])
    _assert_failure(case, "resume_prepared_creation")
    before = {path: (file_sha256(path), path.stat().st_mtime_ns) for path in case.out.glob("*.vsz")}
    exports = case.exports[:]
    assert case.run(resume=True)["status"] == "ready"
    assert case.saves == ["Custom"] and case.exports == exports
    assert all((file_sha256(path), path.stat().st_mtime_ns) == value for path, value in before.items())
    store = FileProjectStore(case.workspace, locations={"delivery": case.delivery})
    parent = next(record for record in store.commands() if record["metadata"]["kind"] == "native_create")
    assert parent["phase"] == "unknown"  # original execution outcome is preserved
    assert store.query(parent["command_id"] + ":native-fact")["phase"] == "complete"
