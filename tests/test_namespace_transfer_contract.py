"""Namespace retirement is a closed attachment operation, never a force write."""

from dataclasses import replace

import pytest

from sciplot_core.project_commands import MembershipRead, NamespaceMember, NamespaceTransfer, ProjectCommand


def transfer():
    return NamespaceTransfer("old/plot", "old/history", "a" * 32,
                             "1" * 64, "2" * 64, "3" * 64, "4" * 64,
                             (NamespaceMember("head.json", "1" * 64, 10, 0o600),))


def command(**options):
    item = transfer()
    values = {"project_id": "project", "expected_generation": "generation",
        "read_set": {"old/plot/head.json": item.original_head_sha256,
                     "old/plot/.sciplot_semantic_owner.json": None,
                     "old/history/.sciplot_semantic_owner.json": None},
        "write_set": ["old/plot/head.json", "old/plot/.sciplot_semantic_owner.json",
                      "old/history/.sciplot_semantic_owner.json"],
        "request": {"prepared_digest": "f" * 64},
        "namespace_transfers": [item],
        "read_memberships": [MembershipRead.capture({"old/plot/head.json": {}}, "old/plot"),
                             MembershipRead.capture({}, "old/history")]}
    values.update(options)
    return ProjectCommand.create("attachment_import", "transfer", **values)


def test_namespace_transfer_roundtrips_exact_identity_and_changes_digest_on_refusal_drift():
    current = command()
    assert ProjectCommand.from_payload(current.to_payload()) == current
    altered = command(namespace_transfers=[replace(transfer(), refusal_sha256="5" * 64)])
    assert altered.command_digest != current.command_digest
    payload = current.to_payload()
    payload["namespace_transfers"][0]["force"] = True
    with pytest.raises(ValueError, match="exact closed fields"):
        ProjectCommand.from_payload(payload)


@pytest.mark.parametrize("prefix,history", [
    ("same", "same"), ("old", "old/history"), ("old/history", "old"),
    ("../old", "history"), (".sciplot_store/commands", "history"),
    ("old/plot", ".sciplot_resources/history"),
])
def test_namespace_transfer_refuses_overlap_escape_and_private_store_aliases(prefix, history):
    with pytest.raises(ValueError):
        replace(transfer(), prefix=prefix, history_prefix=history)


def test_namespace_transfer_requires_attachment_kind_both_memberships_and_original_head():
    value = command()
    with pytest.raises(ValueError, match="attachment import"):
        ProjectCommand.create("semantic_record", "transfer", project_id="project", expected_generation=None,
            read_set=dict(value.read_set), write_set=value.write_set, request={},
            read_memberships=value.read_memberships, namespace_transfers=[transfer()])
    with pytest.raises(ValueError, match="both member sets"):
        command(read_memberships=value.read_memberships[:1])
    with pytest.raises(ValueError, match="original head"):
        command(read_set={**dict(value.read_set), "old/plot/head.json": None})
    with pytest.raises(ValueError, match="both member sets"):
        command(read_memberships=[next(item for item in value.read_memberships if item.prefix == "old/plot"), MembershipRead.capture(
            {"old/history/head.json": {}}, "old/history")])


def test_observed_legacy_namespace_may_be_newer_than_its_original_project_snapshot():
    current = command(read_set={**dict(command().read_set), "old/plot/head.json": "9" * 64})
    assert dict(current.read_set)["old/plot/head.json"] != current.namespace_transfers[0].original_head_sha256
    payload = current.to_payload()
    payload["namespace_transfers"][0]["members"][0]["force"] = True
    with pytest.raises(ValueError, match="exact closed fields"):
        ProjectCommand.from_payload(payload)


def test_inside_project_physical_backup_has_explicit_identity_and_cannot_alias_old_namespace():
    value = command(namespace_transfers=[replace(transfer(), physical_backup_prefix="old/physical-backup")])
    assert ProjectCommand.from_payload(value.to_payload()) == value
    assert value.namespace_transfers[0].physical_backup_prefix == "old/physical-backup"
    with pytest.raises(ValueError, match="disjoint"):
        replace(transfer(), physical_backup_prefix="old/plot/history")
