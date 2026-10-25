"""New Studio processed sources bind to this command's exact sealed output."""

from uuid import uuid4

import pytest

from sciplot_core.project_commands import PreparedFile, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ResourceRoot, state
from sciplot_core.project_store.io import sha

from test_project_store import fixture_store


def prepared(store, before, *, resource="studio/processed/new.csv", data=b"x,y\n1,7\n", source_data=None,
             output_mode=0o640, source_mode=0o640, locator=None):
    source = PreparedSource(uuid4().hex, locator or str(store.root / resource), sha(source_data or data),
                            source_data or data, (), source_mode, produced_resource=resource)
    mutation = ProjectMutation({resource: PreparedFile(data, output_mode)}, {}, prepared_sources=(source,))
    command = ProjectCommand.create("figure_set", "produce-" + uuid4().hex, project_id=before["project_id"],
        expected_generation=before["generation"], read_set={resource: before["files"].get(resource, {}).get("sha256")},
        write_set=[resource], request={})
    return command, mutation, source


def test_new_processed_source_uses_frozen_same_command_bytes_before_live_install(tmp_path):
    store, before = fixture_store(tmp_path)
    command, mutation, source = prepared(store, before)
    assert not (store.root / "studio/processed/new.csv").exists()
    receipt = ProjectCommands(store).execute(command, lambda: mutation)
    assert receipt["phase"] == "complete"
    assert store.read_bytes("studio/processed/new.csv") == source.data
    assert store.snapshot()["sources"][source.source_id][source.version]["locator"] == source.locator
    assert (store.root / "studio/processed/new.csv").stat().st_mode & 0o777 == source.mode


@pytest.mark.parametrize("change", ["bytes", "mode", "locator", "raw", "source", "external"])
def test_missing_source_does_not_bypass_raw_freshness_or_mismatched_frozen_output(tmp_path, change):
    store, before = fixture_store(tmp_path)
    kwargs = ({"source_data": b"different captured source"} if change == "bytes"
        else {"source_mode": 0o600} if change == "mode"
        else {"locator": str(store.root / "studio/processed/other.csv")} if change == "locator"
        else {"resource": "raw/new.csv"} if change == "raw"
        else {"resource": "source/new.csv"} if change == "source"
        else {"locator": str(tmp_path / "same-name" / "new.csv")})
    command, mutation, _source = prepared(store, before, **kwargs)
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).execute(command, lambda: mutation)
    assert store.snapshot()["generation"] == before["generation"]
    assert not (store.root / next(iter(mutation.writes))).exists()


def test_live_input_still_rechecked_after_derived_source_matches_sealed_output(tmp_path, monkeypatch):
    store, before = fixture_store(tmp_path)
    command, mutation, _source = prepared(store, before)
    raw = tmp_path / "original.csv"
    raw.write_bytes(b"original input")
    original = PreparedSource(uuid4().hex, str(raw), sha(raw.read_bytes()), raw.read_bytes(), (), 0o644)
    mutation = ProjectMutation(mutation.writes, {}, prepared_sources=(*mutation.prepared_sources, original))
    def changed(name):
        if name == "before_head":
            raw.write_bytes(b"changed before head")
    monkeypatch.setattr(state, "boundary", changed)
    with pytest.raises(ProjectConflict, match="original source changed"):
        ProjectCommands(store).execute(command, lambda: mutation)
    assert raw.read_bytes() == b"changed before head"
    assert not (store.root / "studio/processed/new.csv").exists()
    assert store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("resource", ["other-products/exact.csv", "@delivery/derived.txt"])
def test_explicit_produced_binding_accepts_any_declared_output_not_a_directory_guess(tmp_path, resource):
    store, before = fixture_store(tmp_path)
    if resource.startswith("@"):
        delivery = tmp_path / "delivery"
        delivery.mkdir()
        store = FileProjectStore(store.root, locations={"delivery": ResourceRoot(delivery, ("derived.txt",))})
        literal = str(delivery / "derived.txt")
    else:
        literal = str(store.root / resource)
    command, mutation, source = prepared(store, before, resource=resource, locator=literal)
    assert ProjectCommands(store).execute(command, lambda: mutation)["phase"] == "complete"
    assert store.read_bytes(resource) == source.data
    assert store.snapshot()["sources"][source.source_id][source.version]["produced_resource"] == resource


def test_untagged_missing_source_never_infers_production_from_path_or_matching_bytes(tmp_path):
    store, before = fixture_store(tmp_path)
    command, mutation, source = prepared(store, before)
    untagged = PreparedSource(source.source_id, source.locator, source.version, source.data, (), source.mode)
    with pytest.raises(ProjectConflict, match="original source is missing"):
        ProjectCommands(store).execute(command, lambda: ProjectMutation(mutation.writes, {}, prepared_sources=(untagged,)))
    assert store.snapshot()["generation"] == before["generation"]


def test_existing_exact_source_version_can_add_proven_output_binding_without_rewriting_history(tmp_path):
    # A separate legacy import supplies an exact old witness without production metadata.
    other_root = tmp_path / "legacy-derived-project"
    other_root.mkdir()
    (other_root / "exact.csv").write_bytes(b"already existing derived table")
    store = FileProjectStore(other_root)
    before = store.snapshot(import_legacy=True)
    entry = before["files"]["exact.csv"]
    source_id = next(iter(before["sources"]))
    source = PreparedSource(source_id, str(other_root / "exact.csv"), entry["sha256"],
        (other_root / "exact.csv").read_bytes(), (), entry["mode"], produced_resource="exact.csv")
    mutation = ProjectMutation({"exact.csv": PreparedFile(source.data, source.mode)}, {}, prepared_sources=(source,))
    command = ProjectCommand.create("figure_set", "bind exact existing output", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"exact.csv": source.version}, write_set=["exact.csv"], request={})
    assert ProjectCommands(store).execute(command, lambda: mutation)["phase"] == "complete"
    assert "produced_resource" not in before["sources"][source_id][source.version]
    assert store.snapshot()["sources"][source_id][source.version]["produced_resource"] == "exact.csv"
