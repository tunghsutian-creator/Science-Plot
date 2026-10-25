"""Finite source registration, membership and owned output metadata controls."""

from uuid import uuid4

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import MembershipRead, PreparedSource
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.io import sha

from test_project_store import fixture_store, reserve


@pytest.mark.parametrize("managed", [False, True])
def test_whole_set_frozen_candidate_rejects_new_member_without_overwriting_either(tmp_path, managed):
    store, baseline = fixture_store(tmp_path)
    name = "studio/document.vsz"
    command = ProjectCommand.create("source_update", "whole", project_id=baseline["project_id"],
        expected_generation=baseline["generation"], read_set={name: baseline["files"][name]["sha256"]},
        write_set=[name], request={}, read_memberships=[MembershipRead.capture(baseline["files"])])
    app = ProjectCommands(store)
    preview = app.preview(command, lambda: ProjectMutation({name: b"whole candidate"}, {}))
    extra = "studio/exports/new-b.pdf"
    if managed:
        reserve(store, store.snapshot(), "independent", (extra,))
        store.publish("independent", "independent-digest", writes={extra: b"independent B"}, result={})
    else:
        target = store.root / extra
        target.parent.mkdir(parents=True)
        target.write_bytes(b"independent B")
    with pytest.raises(ProjectConflict, match="membership"):
        app.decide(command, decision_id=preview["decision_id"], accept=True)
    assert (store.root / name).read_bytes() == b"native old"
    assert (store.root / extra).read_bytes() == b"independent B"


def test_prepared_source_alias_union_preserves_origin_and_old_generation(tmp_path):
    store, baseline = fixture_store(tmp_path)
    raw = tmp_path / "original.csv"
    raw.write_bytes(b"registered original bytes")
    identity = uuid4().hex
    version = sha(raw.read_bytes())
    app = ProjectCommands(store)

    def publish(key, aliases):
        source = PreparedSource(identity, str(raw), version, raw.read_bytes(), aliases, 0o644)
        candidate = ProjectMutation({}, {}, prepared_sources=(source,))
        snapshot = store.snapshot()
        command = ProjectCommand.create("attachment_import", key, project_id=snapshot["project_id"],
            expected_generation=snapshot["generation"], read_set={}, write_set=[],
            request={"prepared_digest": candidate.prepared_digest})
        return app.publish_prepared(command, candidate)

    publish("first", ("A",))
    old = store.snapshot()
    publish("second", ("B",))
    latest = store.snapshot()
    assert old["sources"][identity][version]["aliases"] == ["A"]
    assert latest["sources"][identity][version]["aliases"] == ["A", "B"]
    assert latest["sources"][identity][version]["locator"] == str(raw)
    assert store.resolve_path(raw, expected_sha256=version, source_id="A") == raw
    assert store.resolve_path(raw, expected_sha256=version, source_id="B") == raw
    with pytest.raises(ProjectConflict):
        store.resolve_path(raw, expected_sha256=version, source_id="unknown")
    assert latest["project_id"] == baseline["project_id"]


@pytest.mark.parametrize("tamper", ["mode", "hardlink"])
def test_declared_output_metadata_drift_is_never_silently_replaced(tmp_path, tamper):
    store, snapshot = fixture_store(tmp_path)
    target = store.root / "studio/document.vsz"
    reserve(store, snapshot)
    if tamper == "mode":
        target.chmod(0o755)
    else:
        (tmp_path / "same-bytes-alias.vsz").hardlink_to(target)
    with pytest.raises(ProjectConflict):
        store.publish("edit", "edit-digest", writes={"studio/document.vsz": b"must not replace",
            "studio/spec.json": b"must not replace"}, result={})
    assert target.read_bytes() == b"native old"
    if tamper == "mode":
        assert target.stat().st_mode & 0o777 == 0o755
    else:
        assert target.stat().st_nlink == 2
