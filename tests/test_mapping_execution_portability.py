"""Current confirmed mapping proofs remain exact after official bundle import."""

import json
from pathlib import Path
import shutil

import pytest

from sciplot_core import task_control, task_execution
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.request_resolution import resolve_data_mapping_request
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.preparation_commands import source_identity_for_locator
from sciplot_core.studio_core.project_creation import request_from_verified_plan
from test_project_export_use_case import publication as publication


def confirmed_project(tmp_path, monkeypatch, *, project_override=None, include_metadata=True, certify_trees=True,
                      internal_origin=False):
    origin = tmp_path / "project/origin" if internal_origin else tmp_path / "origin"
    origin.mkdir(parents=True)
    raw = origin / "UVvis.csv"
    raw.write_text("Wavelength (nm),,Absorbance (a.u.),Absorbance (a.u.)\n500,,1,9\n450,,4,3\n400,,2,7\n")
    project = project_override or tmp_path / "project"
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    captured = []

    def capture_creation(source, **kwargs):
        # Only the native producer is excluded from this pure counter. The
        # public question/confirmation/execution/plan/request owners run real.
        project.mkdir(exist_ok=True)
        with mapping_input_reads(kwargs["expected_plan"]["data_mapping"]["data_mapping_execution"]) as readset:
            request = request_from_verified_plan(source, verified=kwargs["expected_plan"],
                project_dir=project, delivery_root=delivery)
            if project_override is not None:
                # The existing publication fixture is a supported legacy
                # single saved native, not a task-aware generated figure set.
                request.pop("resolved_figure_plan", None)
            readset.seal()
            captured.append(readset)
        (project / "plot_request.json").write_text(json.dumps(request))
        return {"project_dir": str(project), "studio_run": {"ready_to_use": True, "failure_reason": None}}

    monkeypatch.setattr(task_execution, "create_project", capture_creation)
    task = origin / "task"
    question = task_control.start_task({"version": 1, "action": "create", "source": str(raw),
        "rule_id": "uvvis_spectrum"}, task_dir=task)
    assert question["status"] == "needs_input"
    complete = task_control.resume_task(task, {"expected_question_id": question["question"]["question_id"],
        "column_mapping": {"x_column": 0, "y_column": 3}})
    assert complete["status"] == "complete", complete
    request = json.loads((project / "plot_request.json").read_bytes())
    execution = load_data_mapping_execution(request["data_mapping_execution"])
    assert Path(execution["effective_input"]).read_text().splitlines()[1:] == ["500,9", "450,3", "400,7"]
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    inputs = {str(raw): file_sha256(raw), **{item["path"]: item["sha256"] for item in execution["outputs"]}}
    inputs[str(execution["effective_input"])] = file_sha256(Path(execution["effective_input"]))
    prepared = tuple(PreparedSource(source_identity_for_locator(before, literal), literal, digest,
        Path(literal).read_bytes(), mode=before["sources"].get(source_identity_for_locator(before, literal), {})
            .get(digest, {}).get("mode", 0o600)) for literal, digest in inputs.items())
    # Same exact captured-readset → PreparedSource handoff as the real native
    # producer; numeric, confirmation and execution verification are not stubbed.
    if include_metadata:
        prepared = (*prepared, *captured[0].prepared_sources(before))
    command = ProjectCommand.create("figure_set", "capture-confirmed-mapping-sources",
        project_id=before["project_id"], expected_generation=before["generation"],
        read_set={name: item["sha256"] for name, item in before["files"].items()}, write_set=[],
        request={"fixture": "actual-public-confirmed-mapping"},
        source_trees=tuple(captured[0].trees.values()) if include_metadata and certify_trees else ())
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=prepared,
        input_reads=captured[0].input_reads(before) if include_metadata else ()))
    return origin, project, store, request, execution


def test_current_confirmed_mapping_survives_official_bundle_with_original_task_and_raw_offline(tmp_path, monkeypatch):
    origin, project, store, request, execution = confirmed_project(tmp_path, monkeypatch)
    expected_request = (project / "plot_request.json").read_bytes()
    expected_execution = Path(request["data_mapping_execution"]).read_bytes()
    original = store.snapshot()
    bundle = store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold")
    origin.rename(tmp_path / "original-task-and-raw-offline")
    project.rename(tmp_path / "original-project-offline")
    assert not Path(request["data_mapping_execution"]).exists()
    with project_runtime(cold):
        effective, application = resolve_data_mapping_request(request, base_dir=cold.root)
        loaded = load_data_mapping_execution(request["data_mapping_execution"])
    assert loaded == execution
    assert effective["input"] == execution["effective_input"]
    assert application["outputs_verified"] is True and application["raw_inputs_preserved"] is True
    assert application["confirmation_id"] == execution["confirmation_id"]
    assert application["proposal_sha256"] == execution["proposal_sha256"]
    assert cold.read_bytes("plot_request.json") == expected_request
    assert cold.snapshot()["sources"] == original["sources"]
    assert Path(tmp_path / "original-task-and-raw-offline" / Path(request["data_mapping_execution"]).relative_to(origin)).read_bytes() == expected_execution


@pytest.mark.parametrize("field", ["execution", "proposal", "confirmation", "preview", "request_candidate",
    "request_seed", "base_request_snapshot", "transform_ledger", "mapped_output", "effective_input"])
def test_every_confirmed_mapping_input_is_rechecked_after_before_head(tmp_path, monkeypatch, field):
    from sciplot_core.project_store import state

    _origin, project, store, request, execution = confirmed_project(tmp_path, monkeypatch)
    target = Path(request["data_mapping_execution"] if field == "execution" else
        execution["outputs"][0]["path"] if field == "mapped_output" else execution[field])
    before = store.snapshot()
    with project_runtime(store), mapping_input_reads(request["data_mapping_execution"]) as readset:
        load_data_mapping_execution(readset.execution)
        sources = readset.prepared_sources(before)
    command = ProjectCommand.create("figure_set", "mapping-drift-" + field, project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"witness.txt": None}, write_set=["witness.txt"], request={"field": field})
    boundary = state.boundary

    def drift(name):
        if name == "before_head":
            target.write_bytes(target.read_bytes() + b"\n")
        boundary(name)

    monkeypatch.setattr(state, "boundary", drift)
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"witness.txt": b"new"}, {}, prepared_sources=sources))
    assert store.snapshot()["generation"] == before["generation"]
    assert not (project / "witness.txt").exists()
    assert ProjectCommands(store).query("mapping-drift-" + field)["phase"] != "complete"


@pytest.mark.parametrize("change", ["missing", "symlink", "permissions", "foreign_execution", "foreign_metadata"])
def test_mapping_inputs_reject_missing_alias_permissions_and_foreign_locators(tmp_path, monkeypatch, change):
    _origin, _project, store, request, execution = confirmed_project(tmp_path, monkeypatch)
    target = Path(execution["confirmation"])
    reference = request["data_mapping_execution"]
    if change == "missing":
        target.unlink()
    elif change == "symlink":
        copy = target.with_name("same-bytes.json")
        copy.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(copy)
    elif change == "permissions":
        target.chmod(0o600 if target.stat().st_mode & 0o777 != 0o600 else 0o644)
    else:
        foreign = tmp_path / "foreign"
        shutil.copytree(Path(reference).parent, foreign)
        if change == "foreign_execution":
            reference = str(foreign / "execution.json")
        else:
            from sciplot_core.data_mapping.execution_inputs import mapping_read_json

            with project_runtime(store), pytest.raises(ProjectConflict, match="Unregistered"):
                mapping_read_json(foreign / "confirmation.json")
            return
    with project_runtime(store), pytest.raises((ValueError, OSError)):
        load_data_mapping_execution(reference)


def test_prepared_mapping_metadata_has_no_writeback_resource_capability(tmp_path, monkeypatch):
    _origin, _project, store, request, execution = confirmed_project(tmp_path, monkeypatch)
    before = store.snapshot()
    for name in (request["data_mapping_execution"], execution["proposal"], execution["confirmation"],
                 execution["request_seed"], execution["transform_ledger"]):
        with pytest.raises(ProjectStoreError, match="outside"):
            store.logical_path(Path(name))
    assert store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("drift", [False, True], ids=["migrate-live-proof", "late-proof-drift"])
def test_existing_saved_export_captures_missing_mapping_metadata_in_the_same_publication(tmp_path, monkeypatch, publication, drift):
    from sciplot_core.studio_core import publication_prepare
    from sciplot_core.studio_core.project_export import export_project_document

    project, calls, _published = publication
    _origin, _project, store, request, execution = confirmed_project(tmp_path, monkeypatch,
        project_override=project, include_metadata=False)
    before = store.snapshot()
    assert not any(entry["locator"] == request["data_mapping_execution"]
        for versions in before["sources"].values() for entry in versions.values())
    native = (project / "studio/document.vsz").read_bytes()
    prepare = publication_prepare.prepare_studio_export_run

    def real_mapping_before_private_prepare(**kwargs):
        _effective, application = resolve_data_mapping_request(request, base_dir=project)
        assert application["outputs_verified"] is True
        result = prepare(**kwargs)
        if drift:
            path = Path(execution["confirmation"])
            path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", real_mapping_before_private_prepare)
    if drift:
        with pytest.raises(ProjectConflict, match="hash changed"):
            export_project_document(project_dir=project, formats=["pdf"])
        assert store.snapshot()["generation"] == before["generation"]
        assert not (project / "runs").exists()
    else:
        result = export_project_document(project_dir=project, formats=["pdf"])
        assert result.ready_to_use
        assert [item[0] for item in calls] == ["export", "publish"]
        metadata = [entry for versions in store.snapshot()["sources"].values() for entry in versions.values()
            if entry["locator"] == request["data_mapping_execution"]]
        assert len(metadata) == 1 and metadata[0]["sha256"] == file_sha256(Path(request["data_mapping_execution"]))
        command_id = result.run_payload["project_command"]["command_id"]
        record, = [item for item in store.commands() if item["command_id"] == command_id]
        assert record["phase"] == "complete" and record["generation"] == store.snapshot()["generation"]
        assert store.snapshot()["sequence"] == before["sequence"] + 1
    assert (project / "studio/document.vsz").read_bytes() == native


def test_current_mapping_refuses_new_worksheet_before_source_read_or_private_allocation(tmp_path, monkeypatch):
    from sciplot_core.intake import table_preview
    from sciplot_core.studio_core import source_update_staging

    _origin, project, store, _request, _execution = confirmed_project(tmp_path, monkeypatch)
    before = store.snapshot()
    replacement = tmp_path / "not_yet_confirmed.xlsx"
    replacement.write_bytes(b"must not be opened as a workbook")
    original = replacement.read_bytes()
    staging = tmp_path / "unallocated"
    monkeypatch.setattr(table_preview, "preview_table_payload", lambda **_k: pytest.fail("unconfirmed new worksheet was read"))
    monkeypatch.setattr(source_update_staging, "_build_source_candidate", lambda *_a, **_k: pytest.fail("unconfirmed candidate was allocated"))
    with project_runtime(store), pytest.raises(ValueError, match="fresh explicit data mapping"):
        with source_update_staging.prepare_candidate(project, replacement, staging, worksheet="Data"):
            pytest.fail("unconfirmed mapping yielded a candidate")
    assert store.snapshot() == before and not staging.exists()
    assert replacement.read_bytes() == original


def test_public_current_mapping_refuses_before_store_import_native_or_incoming_io(tmp_path, monkeypatch, publication):
    from sciplot_core.studio_core import project_command_scope, source_update
    from sciplot_core.task_storage import load_task

    project, _calls, _published = publication
    origin, _project, store, _request, _execution = confirmed_project(tmp_path, monkeypatch, project_override=project)
    # Creation intent predates the confirmed mapping; only the current admitted
    # project request may decide whether a new source needs new confirmation.
    creation_request = load_task(origin / "task")["request"]
    assert "data_mapping_execution" not in creation_request
    before = store.snapshot()
    native = (project / "studio/document.vsz").read_bytes()
    replacement = tmp_path / "never_read_new_source.csv"
    monkeypatch.setattr(project_command_scope, "project_store", lambda *_a, **_k: pytest.fail("missing mapping imported a store or inspected native state"))
    monkeypatch.setattr(source_update, "file_inventory", lambda *_a: pytest.fail("missing mapping read the incoming source"))
    monkeypatch.setattr(source_update, "_audit_exact_document_data", lambda **_k: pytest.fail("missing mapping audited native state"))
    result = source_update.preview_project_source_update(project, replacement)
    assert result["status"] == "blocked" and "fresh explicit data mapping" in result["reason"]
    assert store.snapshot() == before and not replacement.exists()
    assert (project / "studio/document.vsz").read_bytes() == native


@pytest.mark.parametrize("ambient", [False, True])
def test_mapping_admission_refuses_physical_request_drift_before_new_source_io(tmp_path, monkeypatch, ambient):
    from contextlib import nullcontext
    from sciplot_core.studio_core import source_update_staging

    _origin, project, store, _request, _execution = confirmed_project(tmp_path, monkeypatch)
    path = project / "plot_request.json"
    original = path.read_bytes()
    head = (project / ".sciplot_store/head.json").read_bytes()
    context = project_runtime(store) if ambient else nullcontext()
    with context:
        altered = {key: value for key, value in json.loads(original).items()
                   if key not in {"data_mapping", "data_mapping_application", "data_mapping_execution",
                                  "data_mapping_proposal_id", "data_mapping_plan_binding"}}
        path.write_text(json.dumps(altered))
        changed = path.read_bytes()
        monkeypatch.setattr(source_update_staging, "_worksheet_confirmation", lambda *_a: pytest.fail("physical drift read a new source"))
        monkeypatch.setattr(source_update_staging, "_build_source_candidate", lambda *_a, **_k: pytest.fail("physical drift allocated a candidate"))
        with pytest.raises(ProjectConflict, match="canonical request differs"):
            with source_update_staging.prepare_candidate(project, tmp_path / "unread.csv", tmp_path / "unallocated", worksheet=None):
                pytest.fail("an outside request edit bypassed current mapping admission")
    assert (project / ".sciplot_store/head.json").read_bytes() == head
    assert path.read_bytes() == changed and store.read_bytes("plot_request.json") == original
    assert not (tmp_path / "unread.csv").exists() and not (tmp_path / "unallocated").exists()


@pytest.mark.parametrize("entry", ["public", "staging", "explicit-old-snapshot"])
def test_current_mapping_admission_cannot_be_replaced_by_a_legal_historical_runtime(tmp_path, monkeypatch, publication, entry):
    from sciplot_core.studio_core import project_command_scope, source_update, source_update_staging
    from sciplot_core.task_storage import load_task

    origin, project, store, request, _execution = confirmed_project(tmp_path, monkeypatch, project_override=publication[0])

    def publish_request(value, key):
        before = store.snapshot()
        command = ProjectCommand.create("figure_set", key, project_id=before["project_id"],
            expected_generation=before["generation"],
            read_set={"plot_request.json": before["files"]["plot_request.json"]["sha256"]},
            write_set=["plot_request.json"], request={"fixture": key})
        ProjectCommands(store).execute(command, lambda: ProjectMutation(
            {"plot_request.json": json.dumps(value).encode()}, {}))
        return store.snapshot()

    creation_request = load_task(origin / "task")["request"]
    assert "data_mapping_execution" not in creation_request
    old = publish_request(creation_request, "fixture-original-unmapped-intent")
    current = publish_request(request, "fixture-current-confirmed-mapping")
    assert old["generation"] != current["generation"]
    assert json.loads(store.read_bytes("plot_request.json", generation=old["generation"])) == creation_request
    assert json.loads((project / "plot_request.json").read_bytes()) == request
    command_ids = [item["command_id"] for item in store.commands()]
    replacement, staging = tmp_path / "unread-new.xlsx", tmp_path / "unallocated"
    monkeypatch.setattr(project_command_scope, "adopt_saved_native", lambda *_a, **_k: pytest.fail("historical intent admitted a native write"))
    monkeypatch.setattr(source_update, "file_inventory", lambda *_a: pytest.fail("historical intent read the incoming source"))
    monkeypatch.setattr(source_update_staging, "_worksheet_confirmation", lambda *_a: pytest.fail("historical intent inspected a new worksheet"))
    monkeypatch.setattr(source_update_staging, "_build_source_candidate", lambda *_a, **_k: pytest.fail("historical intent allocated a private candidate"))
    with project_runtime(store, generation=old["generation"]) as selected:
        assert selected.generation == old["generation"]
        if entry == "public":
            result = source_update.preview_project_source_update(project, replacement)
            assert result["status"] == "blocked" and "fresh explicit data mapping" in result["reason"]
        else:
            explicit = {"snapshot": old, "mapping_request": request} if entry == "explicit-old-snapshot" else {}
            error, message = ((ProjectConflict, "current project generation") if explicit else
                              (ValueError, "fresh explicit data mapping"))
            with pytest.raises(error, match=message):
                with source_update_staging.prepare_candidate(project, replacement, staging, worksheet="Data", **explicit):
                    pytest.fail("historical intent yielded a new-source candidate")
    assert store.snapshot() == current
    assert [item["command_id"] for item in store.commands()] == command_ids
    assert json.loads((project / "plot_request.json").read_bytes()) == request
    assert not replacement.exists() and not staging.exists()


def test_fresh_confirmed_mapping_can_be_verified_before_candidate_request_changes(tmp_path, monkeypatch):
    from test_task_mapping_plan import _mapped_case
    from sciplot_core.plan_preview import build_plan_preview

    _origin, project, store, _request, _execution = confirmed_project(tmp_path, monkeypatch)
    target = tmp_path / "fresh-confirmation"
    target.mkdir()
    source, selection, _new_execution = _mapped_case(target)
    before = store.snapshot()
    original = (project / "plot_request.json").read_bytes()
    with project_runtime(store):
        result = build_plan_preview(source, request=selection)
    assert result["status"] == "planned", result["blocker"]
    assert result["source"] == str(source)
    assert (project / "plot_request.json").read_bytes() == original
    assert store.snapshot()["generation"] == before["generation"]


def test_existing_publication_replays_the_exact_confirmed_closure_after_official_cold_import(tmp_path, monkeypatch, publication):
    from sciplot_core.studio_core.project_export import export_project_document

    project, calls, _published = publication
    origin, project, store, request, execution = confirmed_project(tmp_path, monkeypatch, project_override=project)
    native, spec = ((project / "studio" / name).read_bytes() for name in ("document.vsz", "spec.json"))
    before = store.snapshot()
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    origin.rename(tmp_path / "origin-offline")
    project.rename(tmp_path / "project-offline")
    with project_runtime(cold):
        result = export_project_document(project_dir=cold.root, formats=["pdf"])
    assert result.ready_to_use and [call[0] for call in calls] == ["export", "publish"]
    assert (cold.root / "studio/document.vsz").read_bytes() == native
    assert (cold.root / "studio/spec.json").read_bytes() == spec
    assert cold.snapshot()["sources"] == before["sources"]
    assert not Path(request["data_mapping_execution"]).exists() and not Path(execution["data_dir"]).exists()
    assert cold.commands()[-1]["phase"] == "complete"


def test_cold_publication_cannot_invent_missing_original_tree_certification(tmp_path, monkeypatch, publication):
    from sciplot_core.studio_core.project_export import export_project_document

    project, calls, _published = publication
    origin, project, store, _request, _execution = confirmed_project(tmp_path, monkeypatch,
        project_override=project, certify_trees=False)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    before = cold.snapshot()["generation"]
    origin.rename(tmp_path / "origin-offline")
    project.rename(tmp_path / "project-offline")
    with project_runtime(cold), pytest.raises(ProjectConflict, match="complete directory witness"):
        export_project_document(project_dir=cold.root, formats=["pdf"])
    assert cold.snapshot()["generation"] == before and not (cold.root / "runs").exists()


@pytest.mark.parametrize("directory_reference", [False, True], ids=["execution-file", "execution-directory"])
def test_file_and_directory_execution_references_preserve_the_same_verified_closure(tmp_path, monkeypatch, directory_reference):
    origin, project, store, request, expected = confirmed_project(tmp_path, monkeypatch)
    reference = str(Path(request["data_mapping_execution"]).parent) if directory_reference else request["data_mapping_execution"]
    with project_runtime(store), mapping_input_reads(reference) as reads:
        assert load_data_mapping_execution(reference) == expected
        assert reads.execution == request["data_mapping_execution"]
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    origin.rename(tmp_path / "origin-offline")
    project.rename(tmp_path / "project-offline")
    with project_runtime(cold), mapping_input_reads(reference) as reads:
        assert load_data_mapping_execution(reference) == expected
        assert reads.execution == request["data_mapping_execution"]


def test_completed_publication_is_not_retracted_by_later_original_metadata_drift(tmp_path, monkeypatch, publication):
    from sciplot_core.project_store import state
    from sciplot_core.studio_core.project_export import export_project_document

    project, _calls, _published = publication
    _origin, project, store, _request, execution = confirmed_project(tmp_path, monkeypatch, project_override=project)
    before = store.snapshot()["generation"]
    boundary = state.boundary

    def change_after_commit(name):
        if name == "after_head":
            target = Path(execution["confirmation"])
            target.write_bytes(target.read_bytes() + b" ")
        boundary(name)

    monkeypatch.setattr(state, "boundary", change_after_commit)
    result = export_project_document(project_dir=project, formats=["pdf"])
    assert result.ready_to_use and store.snapshot()["generation"] != before
    assert store.commands()[-1]["phase"] == "complete"


def test_internal_fixed_mapping_metadata_is_immutable_without_locking_ordinary_raw_data(tmp_path, monkeypatch):
    _origin, _project, store, request, execution = confirmed_project(tmp_path, monkeypatch, internal_origin=True)
    before = store.snapshot()
    paths = [request["data_mapping_execution"], *(execution[field] for field in
             ("proposal", "confirmation", "request_seed", "transform_ledger"))]
    for index, path in enumerate(paths):
        logical = store.logical_path(Path(path))
        assert logical in before["input_resources"]
        command = ProjectCommand.create("figure_set", f"cannot-rewrite-metadata-{index}",
            project_id=before["project_id"], expected_generation=before["generation"],
            read_set={logical: before["files"][logical]["sha256"]}, write_set=[logical], request={"index": index})
        with pytest.raises(ProjectConflict, match="input"):
            ProjectCommands(store).execute(command, lambda name=logical: ProjectMutation({name: b"{}"}, {}))
    assert store.logical_path(Path(request["input"])) not in before["input_resources"]
    assert store.snapshot()["generation"] == before["generation"]


def test_metadata_permission_change_at_before_head_is_refused(tmp_path, monkeypatch):
    from sciplot_core.project_store import state

    _origin, project, store, request, execution = confirmed_project(tmp_path, monkeypatch)
    before = store.snapshot()
    with project_runtime(store), mapping_input_reads(request["data_mapping_execution"]) as reads:
        load_data_mapping_execution(reads.execution)
    mutation = ProjectMutation({"ready.txt": b"ready"}, {}, prepared_sources=reads.prepared_sources(before))
    command = ProjectCommand.create("figure_set", "metadata-late-mode", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"ready.txt": None}, write_set=["ready.txt"], request={},
        source_trees=tuple(reads.trees.values()))
    boundary = state.boundary

    def chmod_after_prepare(name):
        if name == "before_head":
            Path(execution["confirmation"]).chmod(0o600)
        boundary(name)

    monkeypatch.setattr(state, "boundary", chmod_after_prepare)
    with pytest.raises(ProjectConflict, match="permissions"):
        ProjectCommands(store).execute(command, lambda: mutation)
    assert store.snapshot()["generation"] == before["generation"] and not (project / "ready.txt").exists()


@pytest.mark.parametrize("when", ["complete", "after-render", "before-head"])
def test_general_workflow_executes_with_the_same_sealed_mapping_witness_and_one_head(tmp_path, monkeypatch, publication, when):
    from sciplot_core.project_store import state
    from sciplot_core.project_store.worker_binding import native_mapping_binding
    from sciplot_core.studio_core import preparation_commands
    from sciplot_core.workflow.project_requests import run_project_request

    project, _calls, _published = publication
    _origin, project, store, request, execution = confirmed_project(tmp_path, monkeypatch, project_override=project)
    before = store.snapshot()
    confirmation = Path(execution["confirmation"])
    seen = []

    def drift():
        confirmation.write_bytes(confirmation.read_bytes() + b" ")

    def execute(**kwargs):
        packet = native_mapping_binding()
        assert packet["execution"] == request["data_mapping_execution"]
        assert next(item for item in packet["files"] if item["path"] == str(confirmation))["sha256"] == file_sha256(confirmation)
        seen.append("sealed before first render")
        kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
        kwargs["staged_delivery"][0].mkdir(parents=True, exist_ok=True)
        (kwargs["staged_delivery"][0] / "figure.pdf").write_bytes(b"controlled render")
        if when == "after-render":
            drift()
        return {"delivery_package": {"complete": True}}

    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda candidate, **_kw:
        {"document": str(candidate.project_dir / "studio/document.vsz")})
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda candidate, _payload:
        ([], [item for reads in candidate.mapping_inputs.values() for item in reads.prepared_sources(candidate.snapshot)]))
    boundary = state.boundary

    def before_head(name):
        if name == "before_head" and when == "before-head":
            drift()
        boundary(name)

    monkeypatch.setattr(state, "boundary", before_head)
    if when == "complete":
        run_project_request(project / "plot_request.json", request, execute=execute, classifier=lambda **_kw: {},
            new_creation=False, previous_request=None)
        assert store.snapshot()["generation"] != before["generation"] and store.commands()[-1]["phase"] == "complete"
    else:
        with pytest.raises(ProjectConflict):
            run_project_request(project / "plot_request.json", request, execute=execute, classifier=lambda **_kw: {},
                new_creation=False, previous_request=None)
        assert store.snapshot()["generation"] == before["generation"]
    assert seen == ["sealed before first render"]
