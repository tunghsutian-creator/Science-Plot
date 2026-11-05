"""Actual shared application/store contracts; synthetic bytes, no scientific claim."""

from pathlib import Path
from contextlib import nullcontext
from collections import Counter
import json
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from sciplot_core.project_commands import (
    NativeAdoption, ProjectCommand, ProjectCommands, ProjectMutation, ProjectCommandError, ProjectCommandUnknown,
)
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store import commands, state
from sciplot_core.project_store.errors import ProjectRecoveryRequired, ProjectConflict
from sciplot_core.project_store.io import owned_io, sha


def prepared(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "A.vsz").write_bytes(b"old-A")
    (project / "B.vsz").write_bytes(b"old-B")
    store = FileProjectStore(project)
    original = store.snapshot(import_legacy=True)
    return project, store, original


def make_command(snapshot, key="edit-A", resource="A.vsz", **options):
    return ProjectCommand.create("document_edit", key, project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={resource: snapshot["files"][resource]["sha256"]},
        write_set=[resource], request={"resource": resource}, **options)


def storage_command(snapshot, mutation):
    return ProjectCommand.create("semantic_record", "prepared-A", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"],
        read_set={name: snapshot["files"].get(name, {}).get("sha256") for name in mutation.writes},
        write_set=sorted(mutation.writes), request={"prepared_digest": mutation.prepared_digest})


class LostAfterHead(BaseException):
    pass


@pytest.mark.parametrize("reader", ["query", "commands", "snapshot"], ids=["query", "list", "snapshot"])
def test_status_read_cannot_repair_active_native_bytes_after_interrupted_publication(tmp_path, monkeypatch, reader):
    project, store, original = prepared(tmp_path)
    def stop(point):
        if point == "after_head":
            raise LostAfterHead()
    monkeypatch.setattr(state, "boundary", stop)
    command = make_command(original)
    with pytest.raises(LostAfterHead):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"A.vsz": b"new-A"}, {}))
    before = {name: ((project / name).read_bytes(), (project / name).stat().st_mtime_ns)
              for name in ("A.vsz", "B.vsz")}
    try:
        getattr(store, reader)(command.key) if reader == "query" else getattr(store, reader)()
    except ProjectRecoveryRequired:
        pass
    assert {name: ((project / name).read_bytes(), (project / name).stat().st_mtime_ns)
            for name in before} == before
    store.recover()
    assert (project / "A.vsz").read_bytes() == b"new-A"
    assert store.query(command.key)["phase"] == "complete"


def test_exact_preview_artifacts_and_reply_loss_share_the_real_store_owner(tmp_path):
    _project, store, original = prepared(tmp_path)
    app = ProjectCommands(store)
    command = make_command(original)
    native_calls = []
    def preview():
        native_calls.append("native")
        return ProjectMutation({"A.vsz": b"new-A"}, {"export_status": "pending"},
                               review={"image": "preview.png"}, artifacts={"preview.png": b"sealed-pixels"})
    pending = app.preview(command, preview)
    assert Path(pending["artifact_paths"]["preview.png"]).read_bytes() == b"sealed-pixels"
    assert app.query_decision(pending["decision_id"])["metadata"] == command.to_payload()
    result = app.decide(command, decision_id=pending["decision_id"], accept=True)
    retry = app.execute(ProjectCommand.from_payload(result["metadata"]), preview)
    assert retry["phase"] == "complete"
    assert retry["result"]["export_status"] == "pending"
    assert native_calls == ["native"]
    assert Path(retry["artifact_paths"]["preview.png"]).read_bytes() == b"sealed-pixels"


def test_invalid_resume_and_decision_cannot_repair_a_pending_project(tmp_path, monkeypatch):
    project, store, original = prepared(tmp_path)
    def stop(point):
        if point == "after_head":
            raise LostAfterHead()
    monkeypatch.setattr(state, "boundary", stop)
    request = make_command(original)
    app = ProjectCommands(store)
    with pytest.raises(LostAfterHead):
        app.execute(request, lambda: ProjectMutation({"A.vsz": b"new-A"}, {}))
    with pytest.raises(ProjectCommandError, match="No saved"):
        app.resume(make_command(original, key="missing"))
    with pytest.raises(ProjectCommandError, match="different immutable command"):
        app.resume(make_command(original, expected_revision="wrong-base"))
    with pytest.raises(ProjectCommandError, match="wrong candidate"):
        app.decide(request, decision_id="invalid", accept=True)
    assert (project / "A.vsz").read_bytes() == b"old-A"
    assert app.resume(request)["phase"] == "complete"
    assert (project / "A.vsz").read_bytes() == b"new-A"


def test_unrelated_figure_generation_does_not_invalidate_exact_A_readset(tmp_path):
    project, store, original = prepared(tmp_path)
    app = ProjectCommands(store)
    a = make_command(original)
    b = make_command(original, "edit-B", "B.vsz")
    app.execute(b, lambda: ProjectMutation({"B.vsz": b"new-B"}, {}))
    app.execute(a, lambda: ProjectMutation({"A.vsz": b"new-A"}, {}))
    assert (project / "A.vsz").read_bytes() == b"new-A"
    assert (project / "B.vsz").read_bytes() == b"new-B"


def test_two_applications_cannot_repeat_the_same_inflight_native_callback(tmp_path):
    _project, store, original = prepared(tmp_path)
    command = make_command(original)
    entered, release = Event(), Event()
    calls = []
    def native():
        calls.append("native")
        entered.set()
        assert release.wait(5)
        return ProjectMutation({"A.vsz": b"new-A"}, {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ProjectCommands(store).execute, command, native)
        assert entered.wait(5)
        second = pool.submit(ProjectCommands(FileProjectStore(store.root)).execute, command, native)
        try:
            with pytest.raises(ProjectCommandUnknown):
                second.result(timeout=5)
        finally:
            release.set()
        assert first.result(timeout=5)["phase"] == "complete"
    assert calls == ["native"]


def test_audited_legacy_adoption_keeps_native_bytes_and_history_without_force_write(tmp_path):
    project, store, original = prepared(tmp_path)
    (project / "A.vsz").write_bytes(b"manual-A")
    new_sha = state.digest("placeholder")  # Distinct test audit identity, not a scientific certificate.
    import hashlib
    observed = hashlib.sha256(b"manual-A").hexdigest()
    adoption = NativeAdoption("A.vsz", original["files"]["A.vsz"]["sha256"], observed, new_sha)
    command = ProjectCommand.create("native_import", "adopt-A", project_id=original["project_id"],
        expected_generation=original["generation"], read_set={"A.vsz": adoption.before_sha256},
        write_set=["A.vsz"], request={"observed_sha256": observed}, native_adoptions=[adoption])
    result = ProjectCommands(store).execute(command, lambda: ProjectMutation({"A.vsz": b"manual-A"}, {}))
    assert result["phase"] == "complete"
    assert store.read_bytes("A.vsz", generation=original["generation"]) == b"old-A"
    assert store.read_bytes("A.vsz") == b"manual-A"
    assert (project / "A.vsz").read_bytes() == b"manual-A"


@pytest.mark.parametrize("window", [False, True], ids=["admissions", "held-window"])
def test_prepared_publish_composes_the_existing_owner_without_intermediate_port_roundtrips(tmp_path, monkeypatch, window):
    observed = {}
    for route in ("prepared", "explicit-stage"):
        base = tmp_path / route
        base.mkdir()
        _project, store, original = prepared(base)
        mutation = ProjectMutation({"A.vsz": b"new-A"}, {"saved": True}, review={"origin": "frozen"},
                                   artifacts={"before.vsz": b"old-A"})
        command = storage_command(original, mutation)
        counts = Counter()
        head, public, publish = state._read_checked_head, commands.public, store.publish
        def read_head(*args, counts=counts, head=head, **kwargs):
            counts["head"] += 1
            return head(*args, **kwargs)
        def public_record(*args, counts=counts, public=public, **kwargs):
            counts["public"] += 1
            return public(*args, **kwargs)
        def publish_record(*args, counts=counts, publish=publish, **kwargs):
            counts["publish-port"] += 1
            return publish(*args, **kwargs)
        with monkeypatch.context() as scoped:
            scoped.setattr(state, "_read_checked_head", read_head)
            scoped.setattr(commands, "public", public_record)
            scoped.setattr(store, "publish", publish_record)
            with store._validation_window() if window else nullcontext():
                app = ProjectCommands(store)
                if route == "prepared":
                    record = app.publish_prepared(command, mutation)
                else:
                    staged = app.stage_prepared(command, mutation)
                    record = app.decide(command, decision_id=staged["decision_id"], accept=True)
        observed[route] = dict(counts)
        assert record["phase"] == "complete"
        assert record["review"] == {"publication": "prepared_storage", "prepared_digest": mutation.prepared_digest,
                                    "candidate_review": mutation.review}
        assert Path(record["artifact_paths"]["before.vsz"]).read_bytes() == b"old-A"
        assert store.read_bytes("A.vsz", generation=original["generation"]) == b"old-A"
        assert store.read_bytes("A.vsz") == b"new-A"
    assert observed["prepared"]["publish-port"] == 1
    assert observed["prepared"]["head"] <= observed["explicit-stage"]["head"]
    assert observed["prepared"]["public"] < observed["explicit-stage"]["public"]
    print(f"prepared_owner_counts(window={window})={observed}")


@pytest.mark.parametrize("phase", ["reserved", "needs_review", "accepted", "complete", "applying", "rejected"])
def test_prepared_publication_keeps_each_saved_phase_and_exact_review(tmp_path, monkeypatch, phase):
    project, store, original = prepared(tmp_path)
    mutation = ProjectMutation({"A.vsz": b"new-A"}, {"saved": True}, review={"origin": "frozen"})
    command = storage_command(original, mutation)
    app = ProjectCommands(store)
    if phase in {"reserved", "applying"}:
        app._admit(command)
        if phase == "applying":
            store.mark_applying(command.key, command.command_digest)
    else:
        record = app.stage_prepared(command, mutation)
        if phase in {"accepted", "rejected", "complete"}:
            store.decide(command.key, command.command_digest, decision_id=record["decision_id"], accept=phase != "rejected")
        if phase == "complete":
            store.publish_staged(command.key, command.command_digest)
    entered = []
    monkeypatch.setattr(store, "mark_applying", lambda *args: entered.append("native"))
    if phase in {"applying", "rejected"}:
        before = (project / ".sciplot_store/head.json").read_bytes()
        with pytest.raises(ProjectCommandUnknown):
            app.publish_prepared(command, mutation)
        assert (project / ".sciplot_store/head.json").read_bytes() == before
        assert (project / "A.vsz").read_bytes() == b"old-A"
    else:
        result = app.publish_prepared(command, mutation)
        assert result["phase"] == "complete"
        assert result["review"] == {"publication": "prepared_storage", "prepared_digest": mutation.prepared_digest,
                                    "candidate_review": mutation.review}
        assert store.snapshot()["sequence"] == original["sequence"] + 1
        assert (project / "A.vsz").read_bytes() == b"new-A"
        if phase == "complete":
            assert result["replayed"] is True
    assert entered == []


@pytest.mark.parametrize("drift", ["applying", "metadata"])
def test_prepared_publish_rechecks_the_record_under_its_actual_store_lease(tmp_path, monkeypatch, drift):
    project, store, original = prepared(tmp_path)
    mutation = ProjectMutation({"A.vsz": b"must-not-publish"}, {})
    command = storage_command(original, mutation)
    publish = store.publish
    entered = []
    def changed_record(*args, **kwargs):
        if drift == "applying":
            store.mark_applying(command.key, command.command_digest)
        else:
            path = project / ".sciplot_store" / state.command_path(command.key)
            value = json.loads(path.read_bytes())
            value["metadata"]["request"]["outside"] = "changed after application admission"
            path.write_text(json.dumps(value))
        return publish(*args, **kwargs)
    monkeypatch.setattr(store, "publish", changed_record)
    monkeypatch.setattr(commands, "stage", lambda *args, **kwargs: entered.append("stage"))
    before = (project / ".sciplot_store/head.json").read_bytes()
    expected = ProjectCommandUnknown if drift == "applying" else ProjectConflict
    with pytest.raises(expected):
        ProjectCommands(store).publish_prepared(command, mutation)
    assert entered == []
    assert (project / ".sciplot_store/head.json").read_bytes() == before
    assert (project / "A.vsz").read_bytes() == b"old-A"
    assert not (project / ".sciplot_store/drafts").exists()


@pytest.mark.parametrize("tamper", ["descriptor", "object", "view"])
def test_prepared_publish_rechecks_sealed_inputs_after_its_durable_decision_before_head(tmp_path, monkeypatch, tamper):
    project, store, original = prepared(tmp_path)
    mutation = ProjectMutation({"A.vsz": b"new-A"}, {})
    command = storage_command(original, mutation)
    decide = commands.decide
    def changed_candidate(io, record, *args):
        result = decide(io, record, *args)
        base = project / ".sciplot_store"
        if tamper == "descriptor":
            path = base / "drafts" / state.digest(command.key) / (record["decision_id"] + ".json")
        elif tamper == "object":
            entry = record["draft"]["writes"]["A.vsz"]
            path = base / "objects" / entry["sha256"][:2] / entry["sha256"]
        else:
            path = base / "drafts" / state.digest(command.key) / record["decision_id"] / "writes/A.vsz"
        if tamper == "descriptor":
            value = json.loads(path.read_bytes())
            path.write_text(json.dumps({**value, "outside": "candidate changed after decide"}))
        else:
            path.chmod(0o600)
            path.write_bytes(b"outside-candidate")
        return result
    monkeypatch.setattr(commands, "decide", changed_candidate)
    before = (project / ".sciplot_store/head.json").read_bytes()
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).publish_prepared(command, mutation)
    assert (project / ".sciplot_store/head.json").read_bytes() == before
    assert (project / "A.vsz").read_bytes() == b"old-A"


def test_prepared_candidate_view_creation_refusal_stays_before_decision_and_head(tmp_path, monkeypatch):
    project, store, original = prepared(tmp_path)
    mutation = ProjectMutation({"A.vsz": b"new-A"}, {})
    command = storage_command(original, mutation)
    install = commands.install
    decisions = []
    def denied_view(fd, name, *args, **kwargs):
        if name == "A.vsz":
            raise PermissionError("candidate view denied")
        return install(fd, name, *args, **kwargs)
    monkeypatch.setattr(commands, "install", denied_view)
    monkeypatch.setattr(commands, "decide", lambda *args: decisions.append("decide"))
    before = (project / ".sciplot_store/head.json").read_bytes()
    with pytest.raises(PermissionError, match="candidate view denied"):
        ProjectCommands(store).publish_prepared(command, mutation)
    assert decisions == []
    assert store.query(command.key)["phase"] == "needs_review"
    assert "accepted" not in store.query(command.key)
    assert (project / ".sciplot_store/head.json").read_bytes() == before
    assert (project / "A.vsz").read_bytes() == b"old-A"


@pytest.mark.parametrize("point", ["before_storage", "after_generation", "before_head", "after_head",
                                   "before_projection", "after_projection", "before_reply"])
def test_prepared_immediate_owner_retains_every_publication_fault_and_exact_replay(tmp_path, monkeypatch, point):
    project, store, original = prepared(tmp_path)
    mutation = ProjectMutation({"A.vsz": b"new-A"}, {"saved": True}, review={"origin": "frozen"})
    command = storage_command(original, mutation)
    def interrupted(name):
        if name == point:
            raise LostAfterHead()
    with monkeypatch.context() as scoped:
        scoped.setattr(state, "boundary", interrupted)
        with pytest.raises(LostAfterHead):
            ProjectCommands(store).publish_prepared(command, mutation)
    if point in {"before_storage", "after_generation", "before_head"}:
        assert store.snapshot()["generation"] == original["generation"]
        assert (project / "A.vsz").read_bytes() == b"old-A"
    result = ProjectCommands(FileProjectStore(project)).publish_prepared(command, mutation)
    assert result["phase"] == "complete"
    assert result["review"] == {"publication": "prepared_storage", "prepared_digest": mutation.prepared_digest,
                                "candidate_review": mutation.review}
    assert store.snapshot()["sequence"] == original["sequence"] + 1
    assert (project / "A.vsz").read_bytes() == b"new-A"
    assert store.read_bytes("A.vsz", generation=original["generation"]) == b"old-A"


@pytest.mark.parametrize("point", ["stage-mapping", "before-head"])
def test_prepared_publication_cannot_discard_an_independent_reentrant_generation(tmp_path, monkeypatch, point):
    project, store, original = prepared(tmp_path)
    entered = []
    committed_b = []
    def publish_b():
        entered.append("B")
        command = make_command(original, "independent-B", "B.vsz")
        committed_b.append(ProjectCommands(store).execute(command, lambda: ProjectMutation({"B.vsz": b"new-B"}, {"independent": "B"})))
    # Candidate declarations are now detached before Store admission. Inject
    # the same nested writer at the actual held-lease byte staging boundary,
    # rather than rely on a retired user-mapping callback surviving detachment.
    original_import = state.import_writes
    def import_with_nested_writer(io, writes):
        if point == "stage-mapping" and not entered and set(writes) == {"A.vsz"} and owned_io(project) is not None:
            publish_b()
        return original_import(io, writes)
    monkeypatch.setattr(state, "import_writes", import_with_nested_writer)
    mutation = ProjectMutation({"A.vsz": b"new-A"}, {})
    command = storage_command(original, mutation)
    if point == "before-head":
        def boundary(name):
            if name == "before_head" and not entered:
                publish_b()
        monkeypatch.setattr(state, "boundary", boundary)
    if point == "stage-mapping":
        assert ProjectCommands(store).publish_prepared(command, mutation)["phase"] == "complete"
    else:
        with pytest.raises(ProjectConflict, match="head changed"):
            ProjectCommands(store).publish_prepared(command, mutation)
        assert (project / "A.vsz").read_bytes() == b"old-A"
    assert entered == ["B"]
    current = store.snapshot()
    assert current["files"]["B.vsz"]["sha256"] == sha(b"new-B")
    assert current["commands"]["independent-B"]["phase"] == "complete"
    assert current["commands"]["independent-B"]["result"] == {"independent": "B"}
    saved_b = store.query("independent-B")
    assert saved_b["phase"] == "complete" and saved_b["generation"] == committed_b[0]["generation"]
    assert current["parent" if point == "stage-mapping" else "generation"] == saved_b["generation"]
    assert current["sequence"] == original["sequence"] + (2 if point == "stage-mapping" else 1)
    assert store.read_bytes("B.vsz") == b"new-B"
    assert store.read_bytes("B.vsz", generation=saved_b["generation"]) == b"new-B"
    assert store.read_bytes("B.vsz", generation=original["generation"]) == b"old-B"
    if point == "before-head":
        resumed = ProjectCommands(FileProjectStore(project)).publish_prepared(command, mutation)
        assert resumed["phase"] == "complete"
        final = store.snapshot()
        assert final["sequence"] == original["sequence"] + 2 and final["parent"] == saved_b["generation"]
        assert final["commands"]["independent-B"] == current["commands"]["independent-B"]
        assert store.query("independent-B")["generation"] == saved_b["generation"]
        assert store.read_bytes("A.vsz") == b"new-A" and store.read_bytes("B.vsz") == b"new-B"
        assert store.read_bytes("B.vsz", generation=saved_b["generation"]) == b"new-B"


def test_initial_import_requires_actual_head_absence_at_its_final_publication(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "A.vsz").write_bytes(b"old-A")
    store = FileProjectStore(project)
    admitted = []
    def boundary(name):
        if name == "before_head" and not admitted:
            admitted.append("importing")
            admitted.append(store.snapshot(import_legacy=True))
    monkeypatch.setattr(state, "boundary", boundary)
    with pytest.raises(ProjectConflict, match="head changed"):
        store.snapshot(import_legacy=True)
    assert len(admitted) == 2
    current = store.snapshot()
    assert current["project_id"] == admitted[1]["project_id"]
    assert current["generation"] == admitted[1]["generation"]
    assert current["sequence"] == 0 and current["projection_status"] == "current"
    assert (project / "A.vsz").read_bytes() == b"old-A"
