"""Discriminating admission/reply-loss tests for the shared application boundary."""

from copy import deepcopy
from threading import Event, Lock
from concurrent.futures import ThreadPoolExecutor

import pytest

from sciplot_core.project_commands import (
    CommandKind, MembershipRead, NativeAdoption, PreparedFile, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation,
    ProjectCommandError, ProjectCommandUnknown, ProjectionRead,
    SourceAdoption,
)


class MemoryPort:
    """A deliberately small port double; no filesystem/native implementation."""

    def __init__(self):
        self.record = None
        self.lock = Lock()
        self.calls = []

    def snapshot(self, **_options):
        return {"project_id": "project-a", "generation": "generation-a"}

    def query(self, _key):
        return deepcopy(self.record)

    def commands(self):
        return (deepcopy(self.record),) if self.record is not None else ()

    def reserve(self, key, digest, **options):
        self.calls.append("reserve")
        self.record = {"command_id": key, "command_digest": digest, "project_id": "project-a",
                       "phase": "reserved", "metadata": deepcopy(options["metadata"])}
        return deepcopy(self.record)

    def mark_applying(self, _key, _digest):
        with self.lock:
            if self.record["phase"] != "reserved":
                raise ProjectCommandUnknown()
            self.record["phase"] = "applying"
            self.calls.append("begin")
            return deepcopy(self.record)

    def publish(self, _key, _digest, *, writes, result, sources, artifacts=None):
        self.calls.append("publish")
        self.record.update(phase="complete", result=deepcopy(result), writes=deepcopy(writes), sources=sources,
                           artifacts=deepcopy(artifacts))
        return deepcopy(self.record)

    def stage(self, _key, _digest, *, writes, result, review, artifacts, sources=None):
        self.calls.append("stage")
        self.record.update(phase="needs_review", decision_id="exact-candidate", writes=deepcopy(writes),
                           result=deepcopy(result), review=deepcopy(review), artifacts=deepcopy(artifacts), sources=sources)
        return deepcopy(self.record)

    def decide(self, _key, _digest, *, decision_id, accept):
        if decision_id != self.record["decision_id"]:
            raise ValueError("wrong candidate")
        if "accepted" in self.record and self.record["accepted"] != accept:
            raise ValueError("conflicting decision")
        self.record["accepted"] = accept
        if self.record["phase"] != "complete":
            self.record["phase"] = "accepted" if accept else "rejected"
        self.calls.append("decide")
        return deepcopy(self.record)

    def publish_staged(self, _key, _digest):
        assert self.record["phase"] == "accepted"
        self.calls.append("publish_staged")
        self.record["phase"] = "complete"
        return deepcopy(self.record)

    def recover(self):
        self.calls.append("recover")
        return {"status": "ready"}


def command(**changes):
    values = dict(project_id="project-a", expected_generation="generation-a",
                  read_set={"studio/A.vsz": "a" * 64}, write_set=["studio/A.vsz"],
                  request={"idempotency_key": "edit-a", "width": 2}, expected_revision="native-a")
    values.update(changes)
    return ProjectCommand.create(CommandKind.DOCUMENT_EDIT, "edit-a", **values)


def candidate():
    return ProjectMutation({"studio/A.vsz": b"new native"}, {"status": "complete"})


def test_reply_loss_replays_outcome_without_preparing_or_publishing_again():
    port = MemoryPort()
    app = ProjectCommands(port)
    calls = []
    def prepare():
        calls.append("native")
        return candidate()
    first = app.execute(command(), prepare)
    again = app.execute(command(), prepare)
    assert first["phase"] == again["phase"] == "complete"
    assert again["replayed"] is True
    assert calls == ["native"]
    assert port.calls == ["reserve", "begin", "publish"]


def test_failed_preparation_never_reexecutes_on_request_or_resume():
    port = MemoryPort()
    app = ProjectCommands(port)
    calls = []
    def fail():
        calls.append("native-started")
        raise RuntimeError("lost worker reply")
    with pytest.raises(RuntimeError, match="lost worker reply"):
        app.execute(command(), fail)
    with pytest.raises(ProjectCommandUnknown):
        app.execute(command(), fail)
    with pytest.raises(ProjectCommandUnknown):
        app.resume(command())
    assert calls == ["native-started"]
    assert port.record["phase"] == "applying"
    assert "publish" not in port.calls


def test_immediate_commit_keeps_native_before_after_artifacts_in_same_owner():
    port = MemoryPort()
    saved = ProjectCommands(port).execute(command(), lambda: ProjectMutation(
        {"studio/A.vsz": b"new"}, {"status": "complete"},
        artifacts={"before.vsz": b"old", "after.vsz": b"new"}))
    assert saved["artifacts"] == {"before.vsz": b"old", "after.vsz": b"new"}
    assert port.calls == ["reserve", "begin", "publish"]


def prepared_command(mutation):
    return ProjectCommand.create("semantic_record", "store-a", project_id="project-a",
        expected_generation="generation-a", read_set={"head.json": None}, write_set=["head.json"],
        request={"prepared_digest": mutation.prepared_digest})


def test_prepared_storage_publication_never_enters_native_execution():
    port = MemoryPort()
    mutation = ProjectMutation({"head.json": b"fixed-json"}, {})
    result = ProjectCommands(port).publish_prepared(prepared_command(mutation), mutation)
    assert result["phase"] == "complete"
    assert "begin" not in port.calls
    assert port.calls == ["reserve", "recover", "stage", "decide", "publish_staged"]


def test_namespace_storage_cannot_accept_without_the_domain_fence_decision():
    from sciplot_core.project_commands import NamespaceMember, NamespaceTransfer

    transfer = NamespaceTransfer("old/plot", "old/history", "a" * 32,
        "1" * 64, "2" * 64, "3" * 64, "4" * 64,
        (NamespaceMember("head.json", "1" * 64, 10, 0o600),))
    reads = {"old/plot/head.json": "1" * 64, "old/plot/.sciplot_semantic_owner.json": None,
             "old/history/.sciplot_semantic_owner.json": None}
    mutation = ProjectMutation({name: b"frozen" for name in reads}, {})
    command = ProjectCommand.create("attachment_import", "transfer", project_id="project-a",
        expected_generation="generation-a", read_set=reads, write_set=list(reads),
        request={"prepared_digest": mutation.prepared_digest}, namespace_transfers=[transfer],
        read_memberships=[MembershipRead.capture(reads, "old/plot"), MembershipRead.capture({}, "old/history")])
    port = MemoryPort()
    app = ProjectCommands(port)
    with pytest.raises(ProjectCommandError, match="explicitly decide"):
        app.publish_prepared(command, mutation)
    assert port.calls == []
    assert app.stage_prepared(command, mutation)["phase"] == "needs_review"
    assert app.resume(command)["phase"] == "needs_review"
    assert "decide" not in port.calls
    assert "publish_staged" not in port.calls


def test_prepared_source_bytes_and_original_alias_are_bound_without_path_io():
    import hashlib
    source = PreparedSource("a" * 32, "/original/raw.csv", hashlib.sha256(b"raw").hexdigest(), b"raw", ("A",))
    port = MemoryPort()
    mutation = ProjectMutation({"head.json": b"fixed-json"}, {}, review={"origin": "unchanged"},
                               prepared_sources=(source,))
    saved = ProjectCommands(port).publish_prepared(prepared_command(mutation), mutation)
    assert saved["sources"][0]["data"] == b"raw"
    assert saved["sources"][0]["aliases"] == ["A"]
    assert saved["sources"][0]["source_id"] == "a" * 32
    assert saved["review"]["candidate_review"] == {"origin": "unchanged"}
    with pytest.raises(ValueError, match="exact captured bytes"):
        PreparedSource("a" * 32, "/original/raw.csv", "b" * 64, b"different", ("A",))


def test_produced_source_binds_an_exact_logical_output_without_changing_default_sources():
    from dataclasses import replace
    import hashlib

    original = PreparedSource("a" * 32, "/original/derived.csv", hashlib.sha256(b"derived").hexdigest(), b"derived")
    assert "produced_resource" not in original.descriptor()
    produced = replace(original, produced_resource="generated/derived.csv")
    assert produced.to_storage_payload() == {**original.to_storage_payload(), "produced_resource": "generated/derived.csv"}
    assert ProjectMutation({}, {}, prepared_sources=(produced,)).prepared_digest != ProjectMutation(
        {}, {}, prepared_sources=(original,)).prepared_digest
    with pytest.raises(ValueError, match="canonical relative"):
        replace(original, produced_resource="../raw.csv")


def test_captured_launcher_permissions_are_part_of_prepared_publication_identity():
    launcher = PreparedFile(b"#!/bin/sh\n", 0o755)
    executable = ProjectMutation({"head.json": launcher}, {})
    plain = ProjectMutation({"head.json": PreparedFile(launcher.data, 0o600)}, {})
    assert executable.prepared_digest != plain.prepared_digest
    saved = ProjectCommands(MemoryPort()).publish_prepared(prepared_command(executable), executable)
    assert saved["writes"]["head.json"].mode == 0o755
    with pytest.raises(ValueError, match="ordinary permission bits"):
        PreparedFile(b"code", 0o4755)


def test_raw_refresh_is_an_input_observation_and_never_a_writeback():
    import hashlib
    fresh = PreparedSource("a" * 32, "/original/raw.csv", hashlib.sha256(b"new-raw").hexdigest(), b"new-raw", ("A",))
    observed = SourceAdoption("raw.csv", fresh.source_id, "b" * 64, fresh.version)
    request = ProjectCommand.create("source_update", "refresh-a", project_id="project-a",
        expected_generation="generation-a", read_set={"raw.csv": observed.before_sha256, "A.vsz": "c" * 64},
        write_set=["A.vsz"], request={}, source_adoptions=[observed])
    ProjectMutation({"A.vsz": b"derived"}, {}, prepared_sources=(fresh,)).validate_for(request)
    assert ProjectCommand.from_payload(request.to_payload()).source_adoptions == (observed,)
    with pytest.raises(ValueError, match="declared source version"):
        ProjectMutation({"A.vsz": b"derived"}, {}).validate_for(request)
    with pytest.raises(ValueError, match="cannot become output writes"):
        ProjectCommand.create("source_update", "bad", project_id="project-a", expected_generation="generation-a",
            read_set={"raw.csv": observed.before_sha256}, write_set=["raw.csv"], request={}, source_adoptions=[observed])


def test_membership_witness_binds_additions_without_confusing_member_content_hashes():
    files = {"studio/A.vsz": {"sha256": "a" * 64}, "@delivery/A.pdf": {"sha256": "b" * 64}}
    original = MembershipRead.capture(files, "studio")
    assert MembershipRead.capture({**files, "studio/B.vsz": {}}, "studio") != original
    assert MembershipRead.capture({**files, "studio/A.vsz": {"sha256": "c" * 64}}, "studio") == original
    assert MembershipRead.capture({**files, "@delivery/B.pdf": {}}, "") == MembershipRead.capture(files, "")
    assert MembershipRead.capture(files, "@delivery") != MembershipRead.capture({"@delivery/B.pdf": {}}, "@delivery")
    admitted = command(read_memberships=[original])
    assert ProjectCommand.from_payload(admitted.to_payload()).read_memberships == (original,)


def test_prepared_storage_resumes_exact_staged_bytes_after_lost_stage_reply():
    class LostStageReplyPort(MemoryPort):
        def stage(self, *args, **kwargs):
            result = super().stage(*args, **kwargs)
            if self.calls.count("stage") == 1:
                raise RuntimeError("lost stage reply")
            return result
    port = LostStageReplyPort()
    mutation = ProjectMutation({"head.json": b"fixed-json"}, {})
    request = prepared_command(mutation)
    with pytest.raises(RuntimeError, match="lost stage reply"):
        ProjectCommands(port).publish_prepared(request, mutation)
    assert ProjectCommands(port).resume(request)["phase"] == "needs_review"
    assert ProjectCommands(port).publish_prepared(request, mutation)["phase"] == "complete"
    assert port.calls.count("stage") == 1
    assert "begin" not in port.calls
    with pytest.raises(ProjectCommandError, match="exact storage command"):
        ProjectCommands(port).publish_prepared(request, ProjectMutation({"head.json": b"different"}, {}))


def test_staged_transfer_cannot_publish_before_its_explicit_acceptance():
    port = MemoryPort()
    mutation = ProjectMutation({"head.json": b"fixed-json"}, {})
    request = prepared_command(mutation)
    app = ProjectCommands(port)
    staged = app.stage_prepared(request, mutation)
    assert staged["phase"] == "needs_review"
    assert app.resume(request)["phase"] == "needs_review"
    assert "decide" not in port.calls and "publish_staged" not in port.calls
    # A real attachment owner inserts its old-writer fence before this decision.
    assert app.decide(request, decision_id=staged["decision_id"], accept=True)["phase"] == "complete"


def test_prepared_storage_cannot_accept_an_interactive_preview_or_read_a_path():
    port = MemoryPort()
    mutation = ProjectMutation({"head.json": b"fixed-json"}, {})
    request = prepared_command(mutation)
    ProjectCommands(port).preview(request, lambda: mutation)
    with pytest.raises(ProjectCommandError, match="interactive"):
        ProjectCommands(port).publish_prepared(request, mutation)
    from pathlib import Path
    with pytest.raises(ValueError, match="byte values"):
        _ = ProjectMutation({"head.json": Path("never-open")}, {}).prepared_digest


def test_preview_decision_reuses_frozen_candidate_without_native_callback():
    port = MemoryPort()
    app = ProjectCommands(port)
    calls = []
    def prepare():
        calls.append("preview")
        return ProjectMutation({"studio/A.vsz": b"frozen"}, {"status": "complete"},
                               review={"artifact": "image"}, artifacts={"image": b"pixels"})
    reviewed = app.preview(command(), prepare)
    assert reviewed["phase"] == "needs_review"
    assert "publish" not in port.calls
    assert app.query_decision("exact-candidate")["metadata"] == command().to_payload()
    assert app.query_decision("missing") is None
    with pytest.raises(ValueError, match="wrong candidate"):
        app.decide(command(), decision_id="different", accept=True)
    result = app.decide(command(), decision_id="exact-candidate", accept=True)
    assert result["phase"] == "complete"
    assert result["writes"]["studio/A.vsz"] == b"frozen"
    assert calls == ["preview"]
    with pytest.raises(ValueError, match="conflicting decision"):
        app.decide(command(), decision_id="exact-candidate", accept=False)


def test_readonly_decision_lookup_refuses_nonunique_owner_records():
    class AmbiguousPort(MemoryPort):
        def commands(self):
            return ({"decision_id": "same"}, {"decision_id": "same"})
    port = AmbiguousPort()
    with pytest.raises(ProjectCommandError, match="uniquely bound"):
        ProjectCommands(port).query_decision("same")
    assert port.record is None
    assert port.calls == []


@pytest.mark.parametrize("operation", ["resume", "decide"], ids=["unknown-resume", "unknown-decision"])
def test_unknown_query_controls_do_not_reserve_a_new_command(operation):
    port = MemoryPort()
    app = ProjectCommands(port)
    with pytest.raises(ProjectCommandError, match="No saved"):
        if operation == "resume":
            app.resume(command())
        else:
            app.decide(command(), decision_id="none", accept=True)
    assert port.record is None
    assert "reserve" not in port.calls
    assert "recover" not in port.calls


def test_same_key_cannot_change_kind_native_revision_scope_or_request():
    port = MemoryPort()
    app = ProjectCommands(port)
    app.execute(command(), candidate)
    for changed in [command(expected_revision="other-native"), command(expected_generation="other-generation"),
                    command(request={"width": 3}),
                    command(read_set={"studio/A.vsz": "b" * 64})]:
        with pytest.raises(ProjectCommandError, match="different immutable command"):
            app.execute(changed, candidate)
    assert port.calls.count("begin") == port.calls.count("publish") == 1


def test_callback_cannot_add_or_omit_writes_after_admission():
    port = MemoryPort()
    app = ProjectCommands(port)
    with pytest.raises(ValueError, match="exactly its admitted"):
        app.execute(command(), lambda: ProjectMutation({"studio/B.vsz": b"wrong"}, {}))
    assert "publish" not in port.calls
    assert port.record["phase"] == "applying"


def test_concurrent_same_command_enters_native_preparation_once():
    port = MemoryPort()
    app = ProjectCommands(port)
    entered, release = Event(), Event()
    calls = []
    def prepare():
        calls.append("native")
        entered.set()
        assert release.wait(5)
        return candidate()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(app.execute, command(), prepare)
        assert entered.wait(5)
        second = pool.submit(app.execute, command(), prepare)
        try:
            with pytest.raises(ProjectCommandUnknown):
                second.result(timeout=5)
        finally:
            release.set()
        assert first.result(timeout=5)["phase"] == "complete"
    assert calls == ["native"]


def test_command_owns_a_canonical_copy_and_preserves_legacy_key_strings():
    original = {"nested": {"width": 2}}
    admitted = ProjectCommand.create("save", "old key / with spaces", project_id="project-a",
                                     expected_generation=None, read_set={}, write_set=[], request=original)
    digest = admitted.command_digest
    original["nested"]["width"] = 100
    assert admitted.command_digest == digest
    assert admitted.to_payload()["request"]["nested"]["width"] == 2


def test_saved_command_roundtrip_keeps_original_base_after_unrelated_head_change():
    original = command()
    resumed = ProjectCommand.from_payload(original.to_payload())
    assert resumed == original
    assert resumed.expected_generation == "generation-a"
    assert resumed.command_digest == original.command_digest


@pytest.mark.parametrize("change", ["version", "extra", "missing", "selector"],
                         ids=["boolean-version", "unknown-field", "missing-request", "unknown-selector-field"])
def test_saved_command_corruption_is_not_accepted_as_current_metadata(change):
    saved = command().to_payload()
    if change == "version":
        saved["version"] = True
    elif change == "extra":
        saved["permissions"] = ["all"]
    elif change == "missing":
        del saved["request"]
    else:
        saved["projected_reads"] = [{"resource": "a", "kind": "studio_figure_v1", "key": "A",
                                     "sha256": "a" * 64, "allow_any": True}]
    with pytest.raises(ValueError):
        ProjectCommand.from_payload(saved)


def test_projected_write_must_bind_its_exact_selected_read_and_declared_resource():
    selector = ProjectionRead("studio/figure_set.json", "studio_figure_v1", "A", "a" * 64)
    good = command(read_set={}, write_set=[selector.resource], projected_reads=[selector], projected_writes=[selector])
    assert good.to_payload()["projected_writes"] == [selector.to_payload()]
    with pytest.raises(ValueError, match="identical selected read"):
        command(read_set={}, write_set=[selector.resource], projected_writes=[selector])
    with pytest.raises(ValueError, match="previous bytes"):
        command(read_set={}, write_set=[selector.resource])


def test_saved_native_adoption_is_a_distinct_audited_command_not_a_force_write():
    adopted = NativeAdoption("studio/A.vsz", "a" * 64, "b" * 64, "c" * 64)
    admitted = ProjectCommand.create("native_import", "adopt-a", project_id="project-a",
                                    expected_generation="generation-a", read_set={adopted.resource: "a" * 64},
                                    write_set=[adopted.resource], request={}, native_adoptions=[adopted])
    assert ProjectCommand.from_payload(admitted.to_payload()).command_digest == admitted.command_digest
    with pytest.raises(ValueError, match="Only explicit native import"):
        command(native_adoptions=[adopted])
    with pytest.raises(ValueError, match="saved VSZ"):
        NativeAdoption("raw.csv", "a" * 64, "b" * 64, "c" * 64)
    with pytest.raises(ValueError, match="prior stored revision"):
        ProjectCommand.create("native_import", "bad", project_id="project-a", expected_generation="generation-a",
                              read_set={adopted.resource: "d" * 64}, write_set=[adopted.resource],
                              request={}, native_adoptions=[adopted])


@pytest.mark.parametrize("path", ["/absolute", "../outside", "a/../b", "a//b", "a\\b", "@missing"],
                         ids=["absolute", "parent", "embedded-parent", "double-separator", "backslash", "missing-root"])
def test_wire_resource_aliases_cannot_become_host_paths(path):
    with pytest.raises(ValueError, match="resource"):
        command(read_set={path: None}, write_set=[path])
