"""A source review reuses only the same immutable candidate and original read set."""
import json
import shutil

import pytest

from test_project_query import project as project
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core import source_update
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store
from sciplot_core.project_commands import ProjectCommands
from sciplot_core.studio_core.source_update_commands import source_review_binding, stage_source_update
from sciplot_core.studio_core.source_update_files import file_inventory, project_inventory
from sciplot_core.studio_core.source_update_review import payload_hash


def prepared(project, tmp_path):
    (project / "raw").mkdir()
    (project / "raw/original.csv").write_bytes(b"preserved instrument output")
    candidate = tmp_path / "frozen-source"
    shutil.copytree(project, candidate)
    (candidate / "source/data.csv").write_bytes(b"audited candidate table")
    source = tmp_path / "incoming.csv"
    source.write_bytes(b"confirmed new original source")
    review = {"kind": "sciplot_project_source_update", "version": 1, "status": "ready",
        "project": str(project), "source": str(source), "source_kind": "file", "worksheet": None,
        "source_files": file_inventory(source), "source_tree_sha256": source_tree_sha256(source),
        "annotation_decisions": [], "project_sha256": payload_hash(project_inventory(project)),
        "delivery_sha256": payload_hash(None), "changes": {}, "styles": []}
    return candidate, source, review


@pytest.mark.parametrize("deletion", [False, True])
def test_source_preview_replay_reconstructs_frozen_candidate_without_native_preparation(project, tmp_path, monkeypatch, deletion):
    candidate, source, review = prepared(project, tmp_path)
    if deletion:
        (project / "studio/old-metadata.json").write_bytes(b"old native preparation metadata")
        review["project_sha256"] = payload_hash(project_inventory(project))
    saved = stage_source_update(project, candidate, review)
    before = project_inventory(project)
    monkeypatch.setattr(source_update, "project_figures", lambda root: {"first": (root / "studio/document.vsz", root / "studio/spec.json")})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("must not reprepare a sealed candidate"))
    monkeypatch.setattr(source_update, "capture_project_styles", lambda *_a: pytest.fail("must not reinspect old native"))
    monkeypatch.setattr(source_update, "_audit_exact_document_data", lambda **_kw: pytest.fail("must not reaudit frozen science"))
    seen = []
    def preview(path, value):
        assert value == saved
        assert (path / "source/data.csv").read_bytes() == b"audited candidate table"
        assert not (path / "studio/old-metadata.json").exists()
        assert not (path / ".sciplot_store").exists()
        seen.append(path)
    assert source_update.preview_project_source_update(project, source, on_candidate=preview) == saved
    assert len(seen) == 1 and not seen[0].exists()
    assert project_inventory(project) == before
    assert len(ProjectCommands(project_store(project)).commands()) == 1


def test_unknown_source_preview_does_not_bypass_its_saved_key(project, tmp_path, monkeypatch):
    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    binding, intent, key = source_review_binding(store, snapshot, review)
    command = command_for_binding(store, binding, kind="source_update", key=key, writes=[], request=intent)
    store.reserve(key, command.command_digest, expected_generation=command.expected_generation,
        read_set=dict(command.read_set), write_set=[], metadata=command.to_payload())
    store.mark_applying(key, command.command_digest)
    monkeypatch.setattr(source_update, "project_figures", lambda root: {"first": (root / "studio/document.vsz", root / "studio/spec.json")})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("must not retry unknown preview"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked" and "already entered execution" in result["reason"]
    assert len(store.commands()) == 1 and store.query(key)["phase"] == "unknown"


def test_source_identity_and_entire_read_witness_are_part_of_the_normalized_intent(project, tmp_path):
    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    _binding, _intent, key = source_review_binding(store, snapshot, review)
    same_name = tmp_path / "other" / source.name
    same_name.parent.mkdir()
    same_name.write_bytes(source.read_bytes())
    assert source_review_binding(store, snapshot, {**review, "source": str(same_name)})[2] != key
    newer = json.loads(json.dumps(snapshot))
    newer["files"]["runs/late.json"] = {"sha256": "a" * 64, "size": 4, "mode": 0o644, "file_id": "b" * 32}
    assert source_review_binding(store, newer, review)[2] != key


@pytest.mark.parametrize("normalized", [False, True], ids=["fresh-intent", "normalized-intent"])
def test_source_preview_replay_uses_the_current_canonical_witness_without_accepting_supplied_drift(
    project, tmp_path, normalized,
):
    from sciplot_core.project_store import ProjectConflict
    from sciplot_core.studio_core.source_update_commands import verified_source_preview

    candidate, source, review = prepared(project, tmp_path)
    saved = stage_source_update(project, candidate, review)
    store = project_store(project)
    snapshot = store.snapshot()
    _binding, intent, _key = source_review_binding(store, snapshot, review)
    supplied = dict(intent)
    if not normalized:
        del supplied["read_witness"]  # The ordinary fresh-admission caller has not normalized it yet.
    before, records = project_inventory(project), store.commands()
    record = verified_source_preview(store, snapshot, supplied)
    assert record["decision_id"] == saved["decision_id"]
    assert record["metadata"]["request"] == intent
    assert supplied == (intent if normalized else {key: value for key, value in intent.items() if key != "read_witness"})
    for changed in ({**supplied, "read_witness": "0" * 64}, {**supplied, "unknown_witness": "0" * 64}):
        with pytest.raises(ProjectConflict, match="command identity"):
            verified_source_preview(store, snapshot, changed)
    assert project_inventory(project) == before and store.commands() == records
    original = source.read_bytes()
    source.write_bytes(original + b" changed after the reviewed observation")
    with pytest.raises(ProjectConflict):
        verified_source_preview(store, snapshot, supplied)
    assert project_inventory(project) == before and store.commands() == records


@pytest.mark.parametrize("mismatch", ["kind", "intent"])
def test_exact_source_preview_key_cannot_replay_a_different_command_kind(project, tmp_path, mismatch):
    from dataclasses import replace

    from sciplot_core.project_commands import ProjectMutation, SourceTreeRead
    from sciplot_core.project_store import ProjectConflict
    from sciplot_core.studio_core.source_update_commands import verified_source_preview

    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    binding, intent, key = source_review_binding(store, snapshot, review)
    command = command_for_binding(store, binding, kind="style" if mismatch == "kind" else "source_update", key=key,
        writes=[], request={**intent, "worksheet": "different saved intent"} if mismatch == "intent" else intent)
    command = replace(command, source_trees=(SourceTreeRead(str(source), review["source_tree_sha256"]),))
    record = ProjectCommands(store).preview(command, lambda: ProjectMutation({}, {}, review=review))
    before = project_inventory(project)
    with pytest.raises(ProjectConflict, match="command identity"):
        verified_source_preview(store, snapshot, intent)
    assert store.query(key) == record and project_inventory(project) == before


@pytest.mark.parametrize("change", ["locator", "worksheet", "mapping", "annotations", "read-witness"])
def test_new_source_intent_cannot_read_incoming_data_while_searching_saved_previews(project, tmp_path, monkeypatch, change):
    from sciplot_core.project_commands import ProjectCommand, ProjectMutation
    from sciplot_core.project_store import source_trees
    from sciplot_core.studio_core import source_update_state

    candidate, source, review = prepared(project, tmp_path)
    stage_source_update(project, candidate, review)
    store = project_store(project)
    kwargs = {}
    if change == "locator":
        other = tmp_path / "other" / source.name
        other.parent.mkdir()
        other.write_bytes(source.read_bytes())
        source = other
    elif change == "worksheet":
        kwargs["worksheet"] = "New worksheet"
    elif change == "mapping":
        kwargs["mapping_request"] = {"rule_id": "new-scientific-intent", "template": "curve"}
    elif change == "annotations":
        kwargs["annotation_decisions"] = [{"figure_id": "first", "id": "different", "action": "remove"}]
    else:
        before = store.snapshot()
        command = ProjectCommand.create("style", "fixture-new-current-member", project_id=before["project_id"],
            expected_generation=before["generation"], read_set={"current-note.json": None}, write_set=["current-note.json"], request={})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"current-note.json": b"{}"}, {}))
    before = project_inventory(project)
    records = store.commands()
    monkeypatch.setattr(source_trees, "observe", lambda *_a, **_k: pytest.fail("new intent read an old declared input before admission"))
    monkeypatch.setattr(source_update, "file_inventory", lambda *_a: pytest.fail("new intent read incoming bytes before admission"))
    monkeypatch.setattr(source_update_state, "file_inventory", lambda *_a: pytest.fail("new intent used a saved preview's input permission"))
    result = source_update.preview_project_source_update(project, source, **kwargs)
    assert result["status"] == "blocked"
    expected = "confirmed experiment and template" if change == "mapping" else "fresh explicit data mapping"
    assert expected in result["reason"]
    assert project_inventory(project) == before and store.commands() == records


def test_exact_unknown_source_preview_is_reported_without_reading_incoming_data(project, tmp_path, monkeypatch):
    from sciplot_core.project_store import source_trees
    from sciplot_core.studio_core import source_update_state

    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    binding, intent, key = source_review_binding(store, snapshot, review)
    command = command_for_binding(store, binding, kind="source_update", key=key, writes=[], request=intent)
    store.reserve(key, command.command_digest, expected_generation=command.expected_generation,
        read_set=dict(command.read_set), write_set=[], metadata=command.to_payload())
    store.mark_applying(key, command.command_digest)
    monkeypatch.setattr(source_trees, "observe", lambda *_a, **_k: pytest.fail("unknown operation reread incoming data"))
    monkeypatch.setattr(source_update_state, "file_inventory", lambda *_a: pytest.fail("unknown operation inventoried incoming data"))
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_k: pytest.fail("unknown operation reentered preparation"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked" and "already entered execution" in result["reason"]
    assert len(store.commands()) == 1 and store.query(key)["phase"] == "unknown"


@pytest.mark.parametrize("change", ["source-bytes", "source-mode", "source-alias", "project-spec", "delivery", "command-metadata"])
def test_saved_source_preview_refuses_drift_before_exposing_its_frozen_view(project, tmp_path, monkeypatch, change):
    from sciplot_core.project_store.command_records import command_path
    from sciplot_core.studio_core import source_update_replay

    delivery = tmp_path / "visible"
    if change == "delivery":
        request_path = project / "plot_request.json"
        request_path.write_text(json.dumps({**json.loads(request_path.read_bytes()), "delivery_output": str(delivery)}))
        delivery.mkdir()
        (delivery / "visible.pdf").write_bytes(b"original visible delivery")
    candidate, source, review = prepared(project, tmp_path)
    if change == "delivery":
        review["delivery_sha256"] = payload_hash(file_inventory(delivery))
    saved = stage_source_update(project, candidate, review)
    head = (project / ".sciplot_store/head.json").read_bytes()
    if change == "source-bytes":
        source.write_bytes(source.read_bytes() + b" changed")
    elif change == "source-mode":
        source.chmod(0o600 if source.stat().st_mode & 0o777 != 0o600 else 0o644)
    elif change == "source-alias":
        original = source.with_name("same-bytes-foreign.csv")
        source.rename(original)
        source.symlink_to(original)
    elif change == "project-spec":
        (project / "studio/spec.json").write_text("{}")
    elif change == "delivery":
        (delivery / "visible.pdf").write_bytes(b"changed visible delivery")
    else:
        path = project / ".sciplot_store" / command_path(saved["command_key"])
        record = json.loads(path.read_bytes())
        record["metadata"]["request"]["read_witness"] = "a" * 64
        path.write_text(json.dumps(record))
    monkeypatch.setattr(source_update_replay, "frozen_source_candidate", lambda *_a, **_k: pytest.fail("changed witness exposed a frozen preview"))
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_k: pytest.fail("changed witness silently reexecuted"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked"
    assert (project / ".sciplot_store/head.json").read_bytes() == head


def test_source_preview_uses_unchanged_full_read_witness_after_an_unrelated_head_advance(project, tmp_path):
    from sciplot_core.project_commands import ProjectCommand, ProjectMutation

    candidate, source, review = prepared(project, tmp_path)
    saved = stage_source_update(project, candidate, review)
    store = project_store(project)
    before = store.snapshot()
    command = ProjectCommand.create("style", "fixture-no-project-byte-change", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}))
    after = store.snapshot()
    assert after["generation"] != before["generation"] and after["files"] == before["files"]
    assert source_update.preview_project_source_update(project, source) == saved
    assert store.snapshot()["generation"] == after["generation"] and len(store.commands()) == 2


def test_unadmitted_source_preview_requires_a_decision_for_multiple_stored_versions(project, tmp_path, monkeypatch):
    from sciplot_core.project_store import source_trees

    candidate, source, review = prepared(project, tmp_path)
    first = stage_source_update(project, candidate, review)
    source.write_bytes(source.read_bytes() + b" a second confirmed version")
    second_review = {**review, "source_files": file_inventory(source), "source_tree_sha256": source_tree_sha256(source)}
    second = stage_source_update(project, candidate, second_review)
    assert first["command_key"] != second["command_key"]
    monkeypatch.setattr(source_trees, "observe", lambda *_a, **_k: pytest.fail("ambiguous previews guessed an incoming version"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked" and "Multiple stored source versions" in result["reason"]
    assert len(ProjectCommands(project_store(project)).commands()) == 2


@pytest.mark.parametrize("change", ["source-version", "native-save", "multiple-source-versions", "confirmed-mapping-version"])
def test_authorized_new_source_intent_can_leave_older_sealed_previews_untouched(project, tmp_path, monkeypatch, change):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plan_preview import build_plan_preview
    from sciplot_core.studio_core import native_scientific_audit

    (project / "studio/figure_set.json").unlink()  # This control uses the supported primary native route.
    request_path = project / "plot_request.json"
    request_path.write_text(json.dumps({**json.loads(request_path.read_bytes()),
        "rule_id": "uvvis_spectrum", "template": "curve"}))
    candidate, source, review = prepared(project, tmp_path)
    mapping_request = None
    captured_sources, captured_inputs = (), ()
    if change == "confirmed-mapping-version":
        from test_task_mapping_plan import _mapped_case
        from sciplot_core.data_mapping.execution_inputs import mapping_input_reads

        proof_root = tmp_path / "confirmed-mapping"
        proof_root.mkdir()
        source, mapping_request, execution = _mapped_case(proof_root)
        review["source"] = str(source)
        review["mapping_request"] = mapping_request
        store = project_store(project)
        snapshot = store.snapshot(import_legacy=True)
        with mapping_input_reads(mapping_request["data_mapping_execution"], expected_source=source) as reads:
            assert build_plan_preview(source, request=mapping_request)["status"] == "planned"
            captured_sources = tuple(reads.prepared_sources(snapshot))
            captured_inputs = tuple(reads.input_reads(snapshot))
            review["mapping_source_trees"] = [tree.to_payload() for tree in reads.trees.values()]
    else:
        source.write_text("Wavelength (nm),Absorbance (a.u.)\n400,0.3\n450,0.4\n500,0.5\n")
    review.update(source_files=file_inventory(source), source_tree_sha256=source_tree_sha256(source))
    saved = [stage_source_update(project, candidate, review, prepared_sources=captured_sources, input_reads=captured_inputs)]
    if change == "multiple-source-versions":
        source.write_text(source.read_text().replace("0.3", "0.7"))
        updated = {**review, "source_files": file_inventory(source), "source_tree_sha256": source_tree_sha256(source)}
        saved.append(stage_source_update(project, candidate, updated))
    store = project_store(project)
    originals = {item["command_key"]: store.query(item["command_key"]) for item in saved}
    if change == "native-save":
        (project / "studio/document.vsz").write_bytes(b"scientifically unchanged external native style save")
    else:
        source.write_text(source.read_text().replace("0.3", "0.9").replace("0.7", "0.9"))
    if change == "confirmed-mapping-version":
        from dataclasses import replace
        from sciplot_core.data_mapping import create_data_mapping_confirmation, execute_data_mapping_proposal, load_data_mapping_proposal

        old_output = tmp_path / "confirmed-mapping/mappings/chosen_columns"
        old_proposal = load_data_mapping_proposal(execution["proposal"])
        old_output.rename(tmp_path / "retained-confirmed-mapping-v0")
        proposal = replace(old_proposal, sources=tuple(replace(item, sha256=file_sha256(source)) for item in old_proposal.sources))
        confirmation = create_data_mapping_confirmation(proposal, source_root=proof_root, request_path=proof_root / "base.json",
            output_root=proof_root / "mappings", confirmed_by="explicit-new-version")
        fresh = execute_data_mapping_proposal(proposal, confirmation, source_root=proof_root, request_path=proof_root / "base.json",
            output_root=proof_root / "mappings")
        assert mapping_request["data_mapping_execution"] == str(old_output / "execution.json")
        assert fresh["proposal_sha256"] != execution["proposal_sha256"]
    # Stub only the native candidate auditor. The real saved-document producer
    # must snapshot document/spec/source bytes and emit its exact binding contract.
    monkeypatch.setattr(native_scientific_audit, "audit_native_candidate", lambda *_args, **_kwargs:
        {"status": "passed"})
    monkeypatch.setattr(source_update, "_audit_exact_document_data", lambda **_kwargs: {})
    monkeypatch.setattr(source_update, "capture_project_styles", lambda *_args: {})
    reached = []

    class NewPreparationReached(Exception):
        pass

    def prepare_new(_project, selected_source, _temporary, **kwargs):
        assert selected_source == source and kwargs.get("mapping_request") == mapping_request
        request = json.loads(request_path.read_bytes())
        plan = build_plan_preview(source, request=mapping_request or request)
        assert plan["status"] == "planned", plan.get("blocker")
        assert plan["scientific_transform"]["output"]["series"][0]["first_point"] == [400, 0.3 if change == "native-save" else 0.9]
        current_review = {**review, "source_files": file_inventory(source), "source_tree_sha256": source_tree_sha256(source),
                          "project_sha256": payload_hash(project_inventory(project))}
        key = source_review_binding(store, store.snapshot(), current_review)[2]
        assert key not in originals and store.query(key) is None
        reached.append(key)
        raise NewPreparationReached

    monkeypatch.setattr(source_update, "prepare_candidate", prepare_new)
    with pytest.raises(NewPreparationReached):
        source_update.preview_project_source_update(project, source, mapping_request=mapping_request)
    assert len(reached) == 1
    for key, original in originals.items():
        after = store.query(key)
        assert after["decision_id"] == original["decision_id"] and after["draft"] == original["draft"]
        assert after["metadata"] == original["metadata"] and after["phase"] == "needs_review"


@pytest.mark.parametrize("problem", [
    "missing-status", "failed-status", "missing-document", "wrong-document", "missing-spec", "wrong-spec",
])
def test_new_source_preview_refuses_incomplete_native_audit_before_preparation(project, tmp_path, monkeypatch, problem):
    from pathlib import Path
    import stat

    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio_core import native_scientific_audit

    (project / "studio/figure_set.json").unlink()
    request = project / "plot_request.json"
    request.write_text(json.dumps({**json.loads(request.read_bytes()), "rule_id": "uvvis_spectrum", "template": "curve"}))
    candidate, source, review = prepared(project, tmp_path)
    source.write_text("Wavelength (nm),Absorbance (a.u.)\n400,0.3\n450,0.4\n500,0.5\n")
    review.update(source_files=file_inventory(source), source_tree_sha256=source_tree_sha256(source))
    saved = stage_source_update(project, candidate, review)
    store = project_store(project)
    original = store.query(saved["command_key"])
    document = project / "studio/document.vsz"
    document.write_bytes(b"scientifically unchanged external native style save")
    before = {p.relative_to(project): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
              for p in project.rglob("*") if p.is_file()}
    source_before = source.read_bytes(), source.stat().st_mode, source.stat().st_mtime_ns
    snapshot = store.snapshot()
    monkeypatch.setattr(native_scientific_audit, "audit_native_candidate", lambda *_args, **_kwargs:
        {"status": "passed"})
    audit = native_scientific_audit.audit_edited_document
    produced = []

    def incomplete(document, spec):
        result = audit(document, spec)
        produced.append(dict(result))
        key = "document_sha256" if "document" in problem else "spec_sha256" if "spec" in problem else "status"
        if problem.startswith("missing-"):
            result.pop(key)
        else:
            result[key] = "failed" if key == "status" else "0" * 64
        return result

    monkeypatch.setattr(native_scientific_audit, "audit_edited_document", incomplete)
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_args, **_kwargs:
        pytest.fail("Incomplete native audit entered new source preparation"))
    monkeypatch.setattr(source_update, "_audit_exact_document_data", lambda **_kwargs:
        pytest.fail("Incomplete native audit entered baseline source replay"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked"
    assert ("does not bind these exact observed bytes" if "document" in problem else
            "requires the exact passed native and spec audit") in result["reason"]
    assert len(produced) == 1 and produced[0]["status"] == "passed"
    assert produced[0]["document_sha256"] == file_sha256(document)
    assert produced[0]["spec_sha256"] == file_sha256(project / "studio/spec.json")
    assert store.snapshot()["generation"] == snapshot["generation"]
    assert store.query(saved["command_key"]) == original and len(store.commands()) == 1
    after = {p.relative_to(project): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
             for p in project.rglob("*") if p.is_file()}
    assert {name: after[name] for name in before} == before
    # Explicit preparation may materialize only this selected immutable source
    # view; that disposable read artifact is not a generation or native adoption.
    baseline_source = project / "source/data.csv"
    digest = file_sha256(baseline_source)
    owners = [identity for identity, versions in snapshot["sources"].items()
              if versions.get(digest, {}).get("locator") == str(baseline_source)]
    assert len(owners) == 1
    cache = Path(".sciplot_store/sources") / owners[0] / digest / baseline_source.name
    assert set(after) - set(before) == {cache}
    assert not (project / cache).is_symlink()
    assert after[cache][0] == before[Path("source/data.csv")][0]
    assert stat.S_IMODE(after[cache][1]) == 0o400
    assert (source.read_bytes(), source.stat().st_mode, source.stat().st_mtime_ns) == source_before
