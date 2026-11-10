"""New output placement never relocates inputs or grants cleanup authority."""

import json
from pathlib import Path

import pytest

from sciplot_core.foundation.research_destination import require_data_destination, software_root


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "software"
    (root / "src/sciplot_core").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "sciplot-core"\n')
    (root / "original.csv").write_bytes(b"x,y\n1,2\n2,3\n")
    return root


def files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("relative", ["result", ".tmp_verify/private-input/new", "src/sciplot_core/new", "nested/delivery.pdf"])
def test_new_output_rejects_actual_checkout_without_touching_existing_data(checkout, relative):
    before = files(checkout)
    destination = checkout / relative
    with pytest.raises(ValueError, match="New research output"):
        require_data_destination(destination)
    assert software_root(destination) == checkout
    assert files(checkout) == before
    assert not destination.exists()


def test_research_git_and_tmp_named_directories_are_not_deletion_or_software_authority(tmp_path):
    research = tmp_path / ".tmp_verify" / "paper-delivery"
    (research / ".git").mkdir(parents=True)
    (research / "pyproject.toml").write_text('[project]\nname = "my-research"\n')
    target = research / "figures"
    assert require_data_destination(target) == target
    assert software_root(target) is None
    assert not target.exists()


def test_non_sciplot_python_project_keeps_its_research_outputs(tmp_path):
    project = tmp_path / "research"
    (project / "src/sciplot_core").mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname = "unrelated-analysis"\n')
    assert require_data_destination(project / "figures") == project / "figures"


def test_alias_into_checkout_is_rejected_but_external_sibling_is_allowed(checkout, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(checkout, target_is_directory=True)
    with pytest.raises(ValueError, match="New research output"):
        require_data_destination(alias / "new")
    destination = tmp_path / "research" / "delivery"
    assert require_data_destination(destination) == destination
    assert not destination.exists()


def test_existing_namespace_allows_derived_children_without_reauthorizing_an_independent_root(checkout, tmp_path):
    old_project = checkout / "old-project"
    old_project.mkdir()
    old_raw = old_project / "raw.csv"
    old_raw.write_bytes(b"original scientific bytes")
    child = old_project / "history" / "next"
    assert require_data_destination(child, existing_namespace=old_project) == child
    assert not child.exists()
    with pytest.raises(ValueError, match="existing application namespace"):
        require_data_destination(tmp_path / "other", existing_namespace=old_project)
    with pytest.raises(ValueError, match="existing application namespace"):
        require_data_destination(checkout / "elsewhere", existing_namespace=old_project)
    assert old_raw.read_bytes() == b"original scientific bytes"


def test_existing_namespace_cannot_follow_a_child_alias_outside_its_owner(checkout, tmp_path):
    old_project = checkout / "old-project"
    old_project.mkdir()
    (old_project / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="existing application namespace"):
        require_data_destination(old_project / "alias" / "escaped", existing_namespace=old_project)


def test_loaded_package_itself_is_never_a_new_output_destination():
    import sciplot_core

    package = Path(sciplot_core.__file__).parent
    with pytest.raises(ValueError, match="New research output"):
        require_data_destination(package / "test-must-not-create")


def test_ordinary_creation_keeps_in_checkout_input_but_requires_external_outputs(checkout, tmp_path):
    from sciplot_core.output_contract import resolve_user_output_layout
    from sciplot_core.studio_core.project_creation import require_new_layout

    source = checkout / "original.csv"
    original = source.read_bytes()
    with pytest.raises(ValueError, match="New research output"):
        require_new_layout(resolve_user_output_layout(source))
    layout = resolve_user_output_layout(source, requested_delivery_root=tmp_path / "research" / "figure")
    require_new_layout(layout)
    assert not layout.delivery_root.exists() and not layout.workspace_root.exists()
    assert source.read_bytes() == original


@pytest.mark.parametrize("bad_target", ["task", "delivery"])
def test_task_rejects_new_root_or_delivery_before_checkpoint_or_scientific_execution(checkout, tmp_path, bad_target):
    from sciplot_core.task_control import start_task

    source = checkout / "original.csv"
    task = checkout / "new-task" if bad_target == "task" else tmp_path / "new-task"
    delivery = checkout / "new-delivery" if bad_target == "delivery" else tmp_path / "new-delivery"
    before = files(checkout)
    request = {"version": 1, "action": "create", "source": str(source), "out": str(delivery),
               "rule_id": "uvvis_spectrum", "template": "curve"}
    with pytest.raises(ValueError, match="New research output"):
        start_task(request, task_dir=task)
    assert not task.exists() and not delivery.exists()
    assert files(checkout) == before


def test_batch_rejects_checkout_before_removing_any_preexisting_results(checkout, tmp_path):
    from sciplot_core.batch.run import run_batch

    output = checkout / "results"
    (output / "runs").mkdir(parents=True)
    (output / "runs/raw.csv").write_bytes(b"protected research")
    (output / "batch_manifest.json").write_bytes(b"historical record")
    before = files(checkout)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    with pytest.raises(ValueError, match="New research output"):
        run_batch(inputs, output_dir=output)
    assert files(checkout) == before


def test_render_rejects_checkout_before_backend_and_keeps_raw_data(checkout, monkeypatch):
    from sciplot_core.render import public_api

    monkeypatch.setattr(public_api, "_render_to_dir_veusz", lambda *_a, **_k: pytest.fail("backend ran before placement admission"))
    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        public_api.render_to_dir(checkout / "original.csv", template="curve", output_dir=checkout / "rendered")
    assert files(checkout) == before


def test_wire_context_cannot_supply_the_internal_output_namespace(checkout):
    from sciplot_core.render.public_api import render_to_dir

    with pytest.raises(ValueError, match="Internal terminal-source authority"):
        render_to_dir(checkout / "original.csv", template="curve", output_dir=checkout / "rendered",
                      request_context={"_output_namespace": str(checkout)})


def test_recipe_refuses_new_checkout_output_before_recipe_dispatch(checkout, monkeypatch):
    import sciplot_recipes

    monkeypatch.setattr(sciplot_recipes, "get_recipe_module", lambda *_a: pytest.fail("recipe dispatched before admission"))
    with pytest.raises(ValueError, match="New research output"):
        sciplot_recipes.run_recipe("curve", checkout / "original.csv", output_dir=checkout / "recipe")
    assert not (checkout / "recipe").exists()


@pytest.mark.parametrize("operation", ["export", "import"])
def test_portable_destination_is_checked_before_store_or_bundle_io(checkout, tmp_path, operation):
    from sciplot_core.project_store.portable import export_bundle, import_bundle

    destination = checkout / "portable"
    source = tmp_path / "bundle"
    source.mkdir()
    with pytest.raises(ValueError, match="New research output"):
        if operation == "export":
            export_bundle(object(), destination)
        else:
            import_bundle(source, destination, factory=lambda *_a: pytest.fail("import factory ran before admission"))
    assert not destination.exists()


def test_new_panel_layout_refuses_checkout_before_any_layout_write(checkout):
    from sciplot_core.panel_assembly.model import new_document
    from sciplot_core.panel_assembly.storage import save

    path = checkout / "layout.json"
    with pytest.raises(ValueError, match="New research output"):
        save(new_document(), path, expected_revision=None)
    assert not path.exists()


def test_panel_export_checks_destination_before_rendering_or_copying_sources(checkout, tmp_path, monkeypatch):
    from PIL import Image
    from sciplot_core.panel_assembly import export as exporting
    from sciplot_core.panel_assembly.model import apply_operations, new_document
    from sciplot_core.panel_assembly.sources import capture_source

    image = tmp_path / "original.png"
    Image.new("RGB", (30, 20), "red").save(image)
    original = image.read_bytes()
    source = capture_source({"kind": "image", "path": str(image)})
    document = apply_operations(new_document(), [{"op": "add_panel", "panel": {
        "id": "image", "source": source, "row": 0, "column": 0, "row_span": 1,
        "column_span": 1, "label": None, "crop": None}}])
    monkeypatch.setattr(exporting, "assert_source_current", lambda *_a: pytest.fail("export source read before destination admission"))
    with pytest.raises(ValueError, match="New research output"):
        exporting.export_document(document, checkout / "panel-export")
    assert image.read_bytes() == original and not (checkout / "panel-export").exists()


@pytest.mark.parametrize("field", ["output", "delivery_output"])
def test_fresh_workflow_checks_both_independent_roots_before_transaction(checkout, tmp_path, monkeypatch, field):
    from sciplot_core.workflow import request_run

    output, delivery = tmp_path / "run", tmp_path / "delivery"
    request = {"input": str(checkout / "original.csv"), "output": str(output),
               "delivery_output": str(delivery), "recipe": "auto"}
    request[field] = str(checkout / field)
    path = tmp_path / "unregistered.json"
    path.write_text(json.dumps(request))
    monkeypatch.setattr(request_run, "_managed_output_transaction", lambda *_a: pytest.fail("transaction allocated before destination admission"))
    with pytest.raises(ValueError, match="New research output"):
        request_run.run_request(path)
    assert not output.exists() and not delivery.exists() and not (checkout / field).exists()


def test_intake_session_rejects_output_before_classification_or_state_write(checkout):
    from sciplot_core.intake.session import _observe_intake_session

    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        _observe_intake_session(checkout / "original.csv", output_root=checkout / "intake")
    assert files(checkout) == before


@pytest.mark.parametrize("field", ["output_root", "delivery_root", "plot_output"])
def test_intake_project_checks_every_independent_destination_before_copy(checkout, tmp_path, field):
    from sciplot_core.intake import IncomingFile, IntakeGroupInput
    from sciplot_core.intake.project.project_builder import create_intake_project

    values = {"output_root": tmp_path / "projects", "delivery_root": tmp_path / "delivered",
              "plot_output": tmp_path / "plots"}
    values[field] = checkout / field
    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        create_intake_project(project_name="research", data_type_id="mechanical", experiment_type_id="unknown_mechanical",
            groups=[IntakeGroupInput(sample="sample", files=(IncomingFile(name="raw.csv", content=b"x,y\n1,2\n"),))],
            studio_preparer=lambda *_a: pytest.fail("preparer ran before placement admission"), **values)
    assert not values["output_root"].exists()
    assert files(checkout) == before


def test_preview_new_destination_and_existing_bound_derived_destination_are_distinct(checkout, tmp_path):
    from sciplot_core.studio_core.document_edit_state import new_preview_directory

    project = tmp_path / "existing-project"
    project.mkdir()
    (project / "plot_request.json").write_text(json.dumps({"input": str(checkout / "original.csv")}))
    destination = checkout / "preview"
    with pytest.raises(ValueError, match="New research output"):
        new_preview_directory(project, destination)
    owner = checkout / "already-bound-task"
    owner.mkdir()
    derived = owner / "preview"
    assert new_preview_directory(project, derived, _output_namespace=owner) == derived
    assert derived.is_dir()
    with pytest.raises(ValueError, match="existing application namespace"):
        new_preview_directory(project, checkout / "independent", _output_namespace=owner)
    assert not (checkout / "independent").exists()


@pytest.mark.parametrize("operation", ["request", "result"])
def test_cleanup_artifacts_refuse_checkout_before_mkdir(checkout, operation):
    from sciplot_core.assisted_cleanup import write_cleanup_request, write_cleanup_result

    destination = checkout / "cleanup"
    with pytest.raises(ValueError, match="New research output"):
        if operation == "request":
            write_cleanup_request(destination, input_path=checkout / "original.csv")
        else:
            write_cleanup_result(destination, cleaned_data=checkout / "original.csv")
    assert not destination.exists()


def mapping_inputs(tmp_path: Path, output: Path):
    from sciplot_core.data_mapping import create_data_mapping_confirmation
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference

    source = tmp_path / "raw"
    source.mkdir()
    raw = source / "spectrum.csv"
    raw.write_bytes(b"Wavelength (nm),Absorbance (a.u.)\n400,2\n500,1\n")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"input": str(raw), "rule_id": "uvvis_spectrum", "template": "curve"}))
    proposal = DataMappingProposal(proposal_id="confirmed_spectrum", provider="external_task",
        base_request_sha256=file_sha256(request),
        sources=(DataSourceReference("sample", raw.name, file_sha256(raw)),),
        columns=(DataColumnMapping("sample", 0, "Wavelength (nm)", "x", expected_header="Wavelength (nm)"),
                 DataColumnMapping("sample", 1, "Absorbance (a.u.)", "y", expected_header="Absorbance (a.u.)")),
        sample_labels={"sample": "sample"}, request_patch={"rule_id": "uvvis_spectrum", "template": "curve"})
    receipt = create_data_mapping_confirmation(proposal, source_root=source, request_path=request,
        output_root=output, confirmed_by="placement regression")
    return source, request, proposal, receipt


def test_fresh_mapping_refuses_checkout_before_numeric_preparation_or_copy(checkout, tmp_path, monkeypatch):
    from sciplot_core.data_mapping import execution

    output = checkout / "mapping"
    source, request, proposal, receipt = mapping_inputs(tmp_path, output)
    before = files(source)
    monkeypatch.setattr(execution, "_prepare_mapping_frames", lambda *_a, **_k: pytest.fail("numeric mapping ran before admission"))
    with pytest.raises(ValueError, match="New research output"):
        execution.execute_data_mapping_proposal(proposal, receipt, source_root=source, request_path=request, output_root=output)
    assert not output.exists() and files(source) == before


@pytest.mark.parametrize("relative", ["confirmation.json", "new-confirmation-directory"])
def test_mapping_confirmation_refuses_new_checkout_file_and_directory(checkout, tmp_path, relative):
    from sciplot_core.data_mapping import write_data_mapping_confirmation

    _source, _request, _proposal, receipt = mapping_inputs(tmp_path, tmp_path / "executions")
    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        write_data_mapping_confirmation(checkout / relative, receipt)
    assert files(checkout) == before and not (checkout / relative).exists()


def test_automatic_render_refuses_output_before_persisting_its_generated_request(checkout, monkeypatch):
    from types import SimpleNamespace
    from sciplot_core.cli.dispatch.rendering import _render_auto
    import sciplot_core.render

    monkeypatch.setattr(sciplot_core.render, "inspect_payload", lambda *_a: {
        "inspection_resolution": {"status": "ready_rule_authoritative", "rule_id": "uvvis_spectrum"}})
    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        _render_auto(checkout / "original.csv", SimpleNamespace(sheet=0, template="curve", out=checkout / "automatic"), {})
    assert files(checkout) == before and not (checkout / "automatic").exists()


def test_default_intake_has_source_adjacent_evidence_and_visible_delivery_without_changing_input(tmp_path):
    from sciplot_core.intake import IncomingFile, IntakeGroupInput
    from sciplot_core.intake.project.project_builder import create_intake_project
    from sciplot_core.output_contract import resolve_user_output_layout

    source = tmp_path / "research.csv"
    original = b"x,y\n1,2\n2,3\n"
    source.write_bytes(original)
    created = create_intake_project(project_name="daily science", data_type_id="mechanical",
        experiment_type_id="unknown_mechanical", groups=[IntakeGroupInput(sample="sample", files=(
            IncomingFile(name=source.name, content=original, source_path=str(source)),))],
        studio_preparer=lambda *_a: {})
    layout = resolve_user_output_layout(source, project_name="daily science")
    project = Path(created["project_dir"])
    assert project.is_relative_to(layout.workspace_root / "intake_projects")
    assert source.read_bytes() == original
    assert any(path.read_bytes() == original for path in project.rglob("*.csv"))


def test_in_memory_intake_requires_explicit_destination_instead_of_a_cwd_fallback(tmp_path):
    from sciplot_core.intake import IncomingFile, IntakeGroupInput
    from sciplot_core.intake.project.project_builder import create_intake_project

    with pytest.raises(ValueError, match="explicit external output_root"):
        create_intake_project(project_name="upload", data_type_id="mechanical", experiment_type_id="unknown_mechanical",
            groups=[IntakeGroupInput(sample="sample", files=(IncomingFile(name="raw.csv", content=b"1,2\n"),))],
            studio_preparer=lambda *_a: pytest.fail("ambiguous upload reached preparation"))


def test_old_saved_layout_can_be_reopened_and_saved_at_its_existing_checkout_location(checkout):
    from sciplot_core.panel_assembly.model import new_document
    from sciplot_core.panel_assembly.storage import load, save

    path = checkout / "historical-layout.json"
    original = new_document()
    path.write_text(json.dumps(original))
    loaded = load(path)
    assert save(loaded, path, expected_revision=loaded["revision"]) == path
    assert load(path) == loaded


def host_project(root: Path, request: dict) -> Path:
    root.mkdir()
    (root / "source.csv").write_bytes(b"x,y\n1,2\n")
    (root / "plot_request.json").write_text(json.dumps({"input": "source.csv", **request}))
    return root


@pytest.mark.parametrize("field,keyword", [("delivery_output", "create_delivery"), ("output", "create_output")])
def test_unregistered_project_cannot_choose_new_external_checkout_resource(checkout, tmp_path, field, keyword):
    from sciplot_core.project_host_factory import project_store

    destination = checkout / field
    project = host_project(tmp_path / "project", {field: str(destination)})
    source = (project / "source.csv").read_bytes()
    with pytest.raises(ValueError, match="New research output"):
        project_store(project, **{keyword: True})
    assert not destination.exists() and (project / "source.csv").read_bytes() == source


def test_old_held_project_may_still_allocate_its_internal_delivery(checkout):
    from sciplot_core.project_host_factory import project_store

    project = host_project(checkout / "old-project", {})
    selected = project_store(project, create_delivery=True)
    assert selected.root == project and (project / "delivery").is_dir()
    assert (project / "source.csv").read_bytes() == b"x,y\n1,2\n"


def test_missing_registered_delivery_is_not_silently_recreated(tmp_path):
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store import ProjectRecoveryRequired

    delivery = tmp_path / "registered-delivery"
    project = host_project(tmp_path / "project", {"delivery_output": str(delivery)})
    store = project_store(project, create_delivery=True)
    store.snapshot(import_legacy=True)
    delivery.rename(tmp_path / "offline-delivery")
    before = files(project)
    with pytest.raises(ProjectRecoveryRequired):
        project_store(project, create_delivery=True)
    assert not delivery.exists() and files(project) == before


def test_source_creation_from_checkout_keeps_raw_input_and_moves_only_new_control_allocation(checkout, tmp_path, monkeypatch):
    import platformdirs
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_lifecycle import creation
    from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
    from sciplot_core.project_lifecycle.repository import FileProjectRepository

    state = tmp_path / "state"
    monkeypatch.setattr(platformdirs, "user_state_path", lambda *_a, **_k: state)
    monkeypatch.setattr(creation, "start_task", lambda *_a, **_k: {"status": "stopped-at-test-port"})
    monkeypatch.setattr(creation, "_result", lambda _service, _root, _state, task: task)
    source = checkout / "original.csv"
    request = {"source": str(source), "idempotency_key": "same-source-key"}
    before = files(checkout)
    service = PlotService(backend=object())
    with pytest.raises(ValueError, match="New research output"):
        service.create(request)
    assert not state.exists() and files(checkout) == before
    request["out"] = str(tmp_path / "delivery")
    assert service.create(request) == {"status": "stopped-at-test-port"}
    targets = FilesystemProjectTargets(FileProjectRepository())
    root = targets.creation_root(source, request["idempotency_key"])
    assert root.is_relative_to(state) and (root / "creation.json").is_file()
    assert targets.creation_root(source, request["idempotency_key"]) == root
    assert files(checkout) == before


def test_managed_checkout_input_requires_external_output_and_stable_external_control_root(checkout, tmp_path, monkeypatch):
    import platformdirs
    from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
    from sciplot_core.project_lifecycle.repository import FileProjectRepository

    state = tmp_path / "state"
    monkeypatch.setattr(platformdirs, "user_state_path", lambda *_a, **_k: state)
    targets = FilesystemProjectTargets(FileProjectRepository())
    request = {"idempotency_key": "fixed-key", "data_binding": {"data_sources": [{"path": str(checkout / "original.csv")}]}}
    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        targets.managed_creation(request)
    assert not state.exists()
    request["out"] = str(tmp_path / "managed-delivery")
    location = targets.managed_creation(request)
    assert location.root.is_relative_to(state) and location.output == tmp_path / "managed-delivery"
    assert targets.managed_creation(request) == location
    assert files(checkout) == before and not location.root.exists()


def test_saved_creation_receipt_retains_its_old_checkout_namespace(checkout):
    from sciplot_core.project_lifecycle.repository import FileProjectRepository, transaction_path
    from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets

    source = checkout / "original.csv"
    root = transaction_path(checkout / ".sciplot_documents/creations", "old-key").parent
    root.mkdir(parents=True)
    receipt = root / "creation.json"
    receipt.write_bytes(b'{"historical":"unchanged"}')
    assert FilesystemProjectTargets(FileProjectRepository()).creation_root(source, "old-key") == root
    assert receipt.read_bytes() == b'{"historical":"unchanged"}'


@pytest.mark.parametrize("relative", [".", "new-results"])
def test_new_research_destination_refuses_managed_development_cache_without_creating_it(tmp_path, monkeypatch, relative):
    from sciplot_core.foundation import research_destination

    cache = tmp_path / "synthetic-application-cache"
    monkeypatch.setattr(research_destination, "user_cache_path", lambda _app: cache)
    with pytest.raises(ValueError, match="evictable SciPlot"):
        require_data_destination(cache / "development" / relative)
    assert not cache.exists()
    research = tmp_path / "scientific-delivery"
    assert require_data_destination(research) == research
    # Product preview caches have their own owner and no development-GC grant.
    assert require_data_destination(cache / "product-preview") == cache / "product-preview"
    assert not research.exists()


def test_existing_development_namespace_continuation_does_not_admit_an_independent_destination(tmp_path, monkeypatch):
    from sciplot_core.foundation import research_destination

    cache = tmp_path / "synthetic-application-cache"
    owner = cache / "development" / "historical-project"
    owner.mkdir(parents=True)
    original = owner / "raw.csv"
    original.write_bytes(b"historical research, never cleanup permission")
    monkeypatch.setattr(research_destination, "user_cache_path", lambda _app: cache)
    child = owner / "next-preview"
    assert require_data_destination(child, existing_namespace=owner) == child
    with pytest.raises(ValueError, match="existing application namespace"):
        require_data_destination(cache / "development" / "another-project", existing_namespace=owner)
    with pytest.raises(ValueError, match="evictable SciPlot"):
        require_data_destination(child)
    assert not child.exists() and original.read_bytes() == b"historical research, never cleanup permission"


def test_empty_managed_namespace_does_not_admit_a_new_checkout_output(checkout, tmp_path, monkeypatch):
    import platformdirs
    from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
    from sciplot_core.project_lifecycle.repository import FileProjectRepository, digest

    monkeypatch.setattr(platformdirs, "user_state_path", lambda *_a, **_k: tmp_path / "state")
    root = checkout / ".sciplot_documents/managed" / digest("interrupted-key")
    root.mkdir(parents=True)
    request = {"idempotency_key": "interrupted-key", "out": str(checkout / "new-delivery"),
               "data_binding": {"data_sources": [{"path": str(checkout / "original.csv")}]}}
    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        FilesystemProjectTargets(FileProjectRepository()).managed_creation(request)
    assert files(checkout) == before and not (checkout / "new-delivery").exists()


@pytest.mark.parametrize("receipt", [{"kind": "other"},
    {"kind": "sciplot_standalone_vsz_export", "document": "another.vsz"}])
def test_unrelated_receipt_cannot_admit_standalone_export(checkout, monkeypatch, receipt):
    from sciplot_core.studio_core import studio_command, context

    document = checkout / "original.vsz"
    document.write_bytes(b"untouched native input")
    output = checkout / "export"
    output.mkdir()
    (output / "standalone_export_receipt.json").write_text(json.dumps(receipt))
    monkeypatch.setattr(studio_command, "maybe_reexec_with_qt_runtime", lambda *_a: None)
    monkeypatch.setattr(studio_command, "prepare_studio_document", lambda *_a, **_k: {"document": str(document), "mode": "vsz"})
    monkeypatch.setattr(context, "resolve_studio_project_context", lambda *_a: None)
    monkeypatch.setattr(studio_command, "export_studio_document", lambda *_a, **_k: pytest.fail("native export preceded owner admission"))
    before = files(checkout)
    with pytest.raises(ValueError, match="another native document"):
        studio_command.run_studio_command(target=document, output_root=output, export="pdf", json_output=True)
    assert files(checkout) == before


def test_empty_store_is_not_a_standalone_output_binding(checkout, tmp_path, monkeypatch):
    from sciplot_core.studio_core import external_native_export

    document = tmp_path / "document.vsz"
    document.write_bytes(b"untouched native input")
    output = checkout / "new-export"
    (output / ".sciplot_store").mkdir(parents=True)
    monkeypatch.setattr(external_native_export, "resolve_project_figure", lambda *_a: {"project": str(tmp_path / "project")})
    before = files(checkout)
    with pytest.raises(ValueError, match="New research output"):
        external_native_export.export_external_native(document, formats=["pdf"], output_root=output)
    assert files(checkout) == before and not (output / ".sciplot_store/head.json").exists()


@pytest.mark.parametrize("alias", [False, True], ids=["copied", "symlink"])
def test_receipt_for_the_same_document_does_not_grant_a_different_output_root(checkout, tmp_path, alias):
    from sciplot_core.studio_core.standalone_receipt import has_standalone_binding

    document = tmp_path / "document.vsz"
    original_root = tmp_path / "existing-delivery"
    original_root.mkdir()
    original = original_root / "standalone_export_receipt.json"
    original.write_text(json.dumps({"kind": "sciplot_standalone_vsz_export", "document": str(document),
                                    "receipt_path": str(original)}))
    assert has_standalone_binding(original_root, document)
    new_root = checkout / "independent-output"
    new_root.mkdir()
    copied = new_root / original.name
    if alias:
        copied.symlink_to(original)
    else:
        copied.write_bytes(original.read_bytes())
    before = original.read_bytes()
    with pytest.raises(ValueError, match="symlink|another output root"):
        has_standalone_binding(new_root, document)
    assert original.read_bytes() == before
