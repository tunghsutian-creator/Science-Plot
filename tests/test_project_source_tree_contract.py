"""Explicit source-tree observations do not become directory write capabilities."""

from dataclasses import replace

import pytest

from sciplot_core.project_commands import ProjectCommand, SourceTreeRead


def command():
    return ProjectCommand.create("source_update", "source-update", project_id="project",
        expected_generation="generation", read_set={}, write_set=[], request={"source": "/original/source"})


def test_default_command_payload_and_digest_remain_unchanged_without_tree_observation():
    original = command()
    assert "source_trees" not in original.to_payload()
    assert ProjectCommand.from_payload(original.to_payload()) == original
    with pytest.raises(ValueError, match="nonempty"):
        ProjectCommand.from_payload({**original.to_payload(), "source_trees": []})


def test_source_tree_observation_roundtrips_and_changes_command_identity_without_writes():
    original = command()
    guarded = replace(original, source_trees=(SourceTreeRead("/original/source", "a" * 64),))
    assert ProjectCommand.from_payload(guarded.to_payload()) == guarded
    assert guarded.command_digest != original.command_digest
    assert guarded.write_set == original.write_set == ()
    assert replace(guarded, source_trees=(SourceTreeRead("/original/source", "b" * 64),)).command_digest != guarded.command_digest


def test_source_tree_observation_rejects_unknown_fields_duplicates_and_noncanonical_locators():
    guarded = replace(command(), source_trees=(SourceTreeRead("/original/source", "a" * 64),))
    payload = guarded.to_payload()
    payload["source_trees"][0]["allow_changed_members"] = True
    with pytest.raises(ValueError, match="closed"):
        ProjectCommand.from_payload(payload)
    with pytest.raises(ValueError, match="unique"):
        replace(guarded, source_trees=guarded.source_trees * 2)
    for invalid in ("relative/source", "/original/../source", "/original//source", "/original/source\x00"):
        with pytest.raises(ValueError):
            SourceTreeRead(invalid, "a" * 64)
