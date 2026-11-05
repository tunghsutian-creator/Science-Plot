"""Exact native read scopes preserve independence without hiding real conflicts."""

from copy import deepcopy
import json

import pytest

from sciplot_core.project_commands.read_projections import merge_projection, projection_digest


def registry():
    tasks = [{"figure_id": name, "source": {"sha256": name * 64}, "metric": name}
             for name in ("a", "b")]
    return {"kind": "sciplot_studio_figure_set", "version": 2,
            "primary_figure_id": "a", "status": "ready",
            "figures": [{"figure_id": task["figure_id"], "status": "ready",
                         "document": f"studio/{task['figure_id']}.vsz",
                         "spec": f"studio/{task['figure_id']}.spec.json",
                         "resolved_figure_task": task,
                         "document_state": {"current_hash": "old"}, "document_authority": "generated"}
                        for task in tasks],
            "resolved_figure_plan": {"tasks": tasks, "source_sha256": "c" * 64,
                                    "outcomes": [{"figure_id": name, "status": "editable", "artifacts": []}
                                                 for name in ("a", "b")]}}


def digest(value):
    return projection_digest(json.dumps(value).encode(), kind="studio_figure_v1", key="a")


def test_other_figure_publication_and_selected_export_do_not_invalidate_business_read():
    value = registry()
    before = digest(value)
    value["figures"][1].update(document_state={"current_hash": "new"}, exports=["b.pdf"])
    value["figures"][0].update(document_state={"current_hash": "new"}, document_authority="saved")
    value["resolved_figure_plan"]["outcomes"][1]["artifacts"] = ["new-b.pdf"]
    value["status"] = "partially_available"
    assert digest(value) == before


@pytest.mark.parametrize("change", ["member", "path", "spec", "source", "task", "status", "primary", "unknown"])
def test_selected_membership_paths_sources_tasks_and_unknown_business_fields_conflict(change):
    value = registry()
    before = digest(value)
    entry = value["figures"][0]
    if change == "member":
        value["figures"] = value["figures"][1:]
        with pytest.raises(ValueError, match="absent"):
            digest(value)
        return
    if change in {"path", "spec"}:
        entry["document" if change == "path" else "spec"] = "studio/remapped"
    elif change == "source":
        value["resolved_figure_plan"]["source_sha256"] = "d" * 64
    elif change == "task":
        entry["resolved_figure_task"]["metric"] = "remapped scientific metric"
    elif change == "status":
        entry["status"] = "unavailable"
    elif change == "primary":
        value["primary_figure_id"] = "b"
    else:
        entry["future_scientific_binding"] = {"source": "changed"}
    assert digest(value) != before


@pytest.mark.parametrize("bad", [b"[]", b"null", b"{", b'{"kind":"x","kind":"y"}', b'{"value":NaN}'])
def test_projection_rejects_malformed_or_ambiguous_json(bad):
    with pytest.raises(ValueError):
        projection_digest(bad, kind="studio_figure_v1", key="a")


def test_duplicate_members_and_unknown_projection_kind_fail_closed():
    value = registry()
    value["figures"].append(deepcopy(value["figures"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        digest(value)
    with pytest.raises(ValueError, match="Unsupported"):
        projection_digest(json.dumps(registry()).encode(), kind="json_pointer", key="a")


def suite():
    return {"kind": "sciplot_rheology_tts_suite", "version": 1,
            "workspace": "/workspace", "delivery": "/delivery",
            "sources": [{"path": "/source.csv", "sha256": "c" * 64}],
            "documents": [{"id": name, "path": f"/delivery/editable/{name}.vsz", "sha256": name * 64,
                           "exports": [f"/delivery/figures/{name}.pdf"]} for name in ("a", "b")],
            "native_result": {"figures": [{"id": name, "spec_path": f"/workspace/{name}.json",
                                           "spec_sha256": name * 64} for name in ("a", "b")]}}


def native_digest(value):
    return projection_digest(json.dumps(value).encode(), kind="native_suite_figure_v1", key="a")


def test_native_other_figure_exports_and_partial_spec_overlay_preserve_selected_read():
    value = suite()
    before = native_digest(value)
    value["documents"][1]["exports"] = ["/delivery/figures/new-b.pdf"]
    value["presentation_revision"] = {"figures": [{"id": "b", "spec_path": "/workspace/new-b.json",
                                                  "spec_sha256": "d" * 64}], "preview": "new-preview"}
    value["last_export"] = [{"document": "/delivery/editable/b.vsz", "exports": ["new-b.pdf"]}]
    assert native_digest(value) == before


@pytest.mark.parametrize("field", ["path", "sha256", "source", "spec_path", "spec_sha256", "export"])
def test_native_selected_bindings_remain_conflicts(field):
    value = suite()
    before = native_digest(value)
    if field in {"path", "sha256"}:
        value["documents"][0][field] = "remapped"
    elif field == "source":
        value["sources"][0]["sha256"] = "d" * 64
    elif field in {"spec_path", "spec_sha256"}:
        value["native_result"]["figures"][0][field] = "d" * 64 if field == "spec_sha256" else "remapped"
    else:
        value["last_export"] = [{"document": "/delivery/editable/a.vsz", "audit": "new-a-audit"}]
    assert native_digest(value) != before


def test_selected_studio_publish_merges_without_overwriting_concurrent_other_figure():
    base = registry()
    candidate = deepcopy(base)
    candidate["figures"][0]["document_state"] = {"current_hash": "new-a"}
    candidate["resolved_figure_plan"]["outcomes"][0]["artifacts"] = ["new-a.pdf"]
    current = deepcopy(base)
    current["figures"][1]["document_state"] = {"current_hash": "new-b"}
    current["resolved_figure_plan"]["outcomes"][1]["artifacts"] = ["new-b.pdf"]
    current["status"] = "changed aggregate publication status"
    merged = json.loads(merge_projection(json.dumps(current).encode(), json.dumps(candidate).encode(),
                                         kind="studio_figure_v1", key="a"))
    assert merged["figures"][0]["document_state"] == {"current_hash": "new-a"}
    assert merged["figures"][1] == current["figures"][1]
    assert merged["resolved_figure_plan"]["outcomes"][1] == current["resolved_figure_plan"]["outcomes"][1]
    assert merged["resolved_figure_plan"]["outcomes"][0]["artifacts"] == ["new-a.pdf"]
    assert merged["status"] == current["status"]


def test_selected_publication_cannot_write_a_scientific_binding():
    base, candidate = registry(), registry()
    candidate["figures"][0]["spec"] = "foreign-spec.json"
    with pytest.raises(ValueError, match="cannot change scientific"):
        merge_projection(json.dumps(base).encode(), json.dumps(candidate).encode(), kind="studio_figure_v1", key="a")


@pytest.fixture
def studio_figure(tmp_path):
    from sciplot_core.foundation.file_hashing import file_sha256

    project = tmp_path / "project"
    studio = project / "studio"
    studio.mkdir(parents=True)
    source = tmp_path / "measurements.csv"
    source.write_bytes(b"x,y\n1,2\n")
    (project / "plot_request.json").write_text("{}")
    for name in ("a", "b"):
        (studio / f"{name}.vsz").write_text(f"native {name}")
        (studio / f"{name}.spec.json").write_text(json.dumps({"series": [
            {"source_artifacts": [{"path": str(source), "sha256": file_sha256(source)}]}]}))
    (studio / "document.vsz").write_text("canonical primary native")
    (studio / "figure_set.json").write_text(json.dumps(registry()))
    selected = {"figure_id": "a", "document": str(studio / "a.vsz"), "spec": str(studio / "a.spec.json")}
    return project, selected


def test_studio_typed_observation_preserves_v1_payload_hash_and_explicit_destination(studio_figure):
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.project_commands import FigureReadWitness
    from sciplot_core.studio_core.project_command_scope import (
        command_for_binding, figure_binding, figure_read_state, figure_read_witness, project_store,
    )

    project, selected = studio_figure
    witness = figure_read_witness(project, selected)
    reads = figure_read_state(project, selected)
    assert isinstance(witness, FigureReadWitness) and reads == witness.to_read_state_payload()
    store = project_store(project)
    binding = figure_binding(project, selected, store=store)
    original = {"files": reads["project_files"], "source_files": reads["source_files"],
                "projected_reads": reads["projected_reads"]}
    command = command_for_binding(store, binding, kind="save", key="copy", writes=["studio/copy.vsz"], request={})
    assert command.expected_revision == canonical_json_sha256(original)
    assert command.expected_generation == binding["generation"]
    assert dict(command.read_set) == {**original["files"], "studio/copy.vsz": None}
    assert binding == {"project_id": store.snapshot()["project_id"],
                       "generation": store.snapshot()["generation"], **original}


def test_observed_native_keeps_registered_prior_and_actual_witness_separate(studio_figure):
    from pathlib import Path
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio_core.observed_figure_binding import (
        observed_figure_binding, observed_figure_read_state, observed_figure_read_witness,
    )
    from sciplot_core.studio_core.project_command_scope import figure_binding, project_store

    project, selected = studio_figure
    store = project_store(project)
    registered = figure_binding(project, selected, store=store)
    document, spec = Path(selected["document"]), Path(selected["spec"])
    document.write_bytes(b"human saved native")
    selected = {**selected, "document_sha256": file_sha256(document), "spec_sha256": file_sha256(spec)}
    before, observed = observed_figure_read_witness(project, selected)
    assert observed_figure_read_state(project, selected) == (before, observed.to_read_state_payload())
    with pytest.raises(ValueError, match="exact passed"):
        observed_figure_binding(project, selected, {"status": "failed"})
    result = observed_figure_binding(project, selected, {"status": "passed",
        "document_sha256": file_sha256(document), "spec_sha256": file_sha256(spec)})
    assert result == registered
    assert dict(observed.files)["studio/a.vsz"] == file_sha256(document)
    assert dict(observed.files)["studio/a.vsz"] != result["files"]["studio/a.vsz"]


@pytest.mark.parametrize("relative", ["notes.json", "studio/b.vsz"])
def test_selected_studio_read_and_generic_inventory_keep_distinct_scopes(studio_figure, relative):
    from sciplot_core.studio_core.document_edit_state import edit_state

    project, selected = studio_figure
    selected_before, whole_before = edit_state(project, selected), edit_state(project)
    target = project / relative
    target.write_bytes(b"unrelated publication")
    assert edit_state(project, selected) == selected_before
    assert edit_state(project) != whole_before
    assert relative in edit_state(project)["project_files"]


@pytest.mark.parametrize("changed_mode", [False, True])
def test_observed_native_mode_is_checked_once_at_its_original_physical_path(studio_figure, monkeypatch, changed_mode):
    import inspect
    from pathlib import Path
    from sciplot_core.studio_core import observed_figure_binding as owner
    from sciplot_core.studio_core.project_command_scope import project_store

    project, selected = studio_figure
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    document = Path(selected["document"])
    assert store.logical_path(document) == document.relative_to(store.root).as_posix()
    if changed_mode:
        document.chmod(before["files"]["studio/a.vsz"]["mode"] ^ 0o200)
    actual_stat = Path.stat
    observations = []

    def observe(path, *args, **kwargs):
        if path == document and inspect.currentframe().f_back.f_code is owner.observed_figure_read_witness.__code__:
            observations.append(path)
        return actual_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", observe)
    if changed_mode:
        with pytest.raises(ValueError, match="native figure changed its registered permissions"):
            owner.observed_figure_read_witness(project, selected)
    else:
        owner.observed_figure_read_witness(project, selected)
    assert observations == [document]
    assert not store.commands()


@pytest.mark.parametrize("mapping", ["alias", "foreign", "unsupported"])
def test_observed_native_mode_dedup_never_admits_another_physical_member(studio_figure, mapping):
    from pathlib import Path
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.errors import ProjectStoreError
    from sciplot_core.studio_core import observed_figure_binding as owner
    from sciplot_core.studio_core.project_command_scope import project_store

    project, selected = studio_figure
    store = project_store(project)
    store.snapshot(import_legacy=True)
    if mapping == "alias":
        alias = project / "studio/alias.vsz"
        alias.symlink_to(selected["document"])
        selected = {**selected, "document": str(alias)}
    elif mapping == "foreign":
        foreign = project.parent / "foreign.vsz"
        foreign.write_bytes(Path(selected["document"]).read_bytes())
        selected = {**selected, "document": str(foreign)}
    else:
        # The Store rejects a second physical namespace for this project member
        # before it can supply an unsupported mapping to the observation owner.
        with pytest.raises(ProjectStoreError, match="second physical root alias"):
            FileProjectStore(project, locations={"studio": project / "studio"})
        assert not store.commands()
        return
    with pytest.raises((ValueError, KeyError)):
        owner.observed_figure_read_witness(project, selected)
    assert not store.commands()
