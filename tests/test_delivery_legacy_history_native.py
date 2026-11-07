"""Registered generated legacy delivery evidence survives both real producers.

The old-format script is fixture data, never executed or treated as user history.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from stat import S_IMODE
from time import perf_counter, time_ns

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.delivery.package_transaction import _relocate_record
from sciplot_core.delivery_identity import DELIVERY_IDENTITY, read_delivery_binding
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.launchers import inspect_delivery_editor_launcher_contract, inspect_delivery_launcher_contract
from sciplot_core.launchers.delivery_editor_launcher import _delivery_editor_launcher_lines
from sciplot_core.project_commands import MembershipRead, PreparedFile, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_manifest import read_intake_project_manifest, stage_intake_project_manifest
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime, projected_runtime_artifact
from sciplot_core.studio_core.project_command_scope import whole_memberships
from sciplot_core.studio_core.project_export import export_project_document
from sciplot_core.studio_core.studio_prepare import prepare_studio_document
from sciplot_core.workflow.project_requests import _publication_store
from sciplot_core.workflow.request_run import run_request
from sciplot_core.workflow.run_projection import _project_manifest_after_run
from delivery_identity_helpers import write_legacy_delivery_launcher


def _register_generated_legacy_evidence(project, store, stage, manifest):
    """Publish fixture bytes and their registry together through the real writer."""
    before = store.snapshot()
    registry = read_intake_project_manifest(project, store=store)
    current = registry["delivery_package"]
    delivery = Path(current["path"])
    assert delivery == store.locations["delivery"]
    assert not (delivery / "Open_in_SciPlot.command").exists()
    assert not (delivery / "Open_in_Veusz.command").exists()
    with project_runtime(store):
        binding = read_delivery_binding(delivery)
    assert binding is not None
    stage.mkdir()
    for logical, item in before["files"].items():
        if logical.startswith("@delivery/"):
            target = stage / logical.removeprefix("@delivery/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.read_bytes(logical, generation=before["generation"]))
            target.chmod(item["mode"])
    (stage / DELIVERY_IDENTITY).unlink()
    native = write_legacy_delivery_launcher(stage, binding=binding)
    native.chmod(0o750)
    editor = stage / "Open_in_SciPlot.command"
    editor.write_text("\n".join(_delivery_editor_launcher_lines()) + "\n")
    editor.chmod(0o751)
    native_contract = inspect_delivery_launcher_contract(stage)
    editor_contract = inspect_delivery_editor_launcher_contract(stage)
    assert native_contract["ready"] is True and editor_contract["ready"] is True
    historical = _relocate_record(deepcopy(current), delivery, stage)
    historical["version"] = 6
    for key in ("identity", "identity_sha256", "identity_contract"):
        historical.pop(key)
    historical.update(open_in_veusz=str(native), open_in_veusz_sha256=file_sha256(native),
                      launcher_contract=native_contract,
                      open_in_sciplot=str(editor), open_in_sciplot_sha256=file_sha256(editor),
                      editor_launcher_contract=editor_contract)
    historical["artifacts"] = [item for item in historical["artifacts"] if item["id"] != "delivery_identity"]
    historical["artifacts"].extend([
        {"id": "open_in_veusz", "path": str(native), "exists": True, "details": native_contract},
        {"id": "open_in_sciplot", "path": str(editor), "exists": True, "details": editor_contract}])
    historical["verification"] = verify_delivery_package(historical, expected_root=stage, expected_manifest=manifest)
    assert historical["verification"]["passed"] is True, historical["verification"]
    historical = _relocate_record(historical, stage, delivery)
    run_logical = store.logical_path(Path(manifest["output"]) / "manifest.json")
    old_run = json.loads(store.read_bytes(run_logical))
    old_run["delivery_package"] = historical
    registry = _project_manifest_after_run(registry, old_run)
    writes = stage_intake_project_manifest(project, registry, store=store,
        project_writes={run_logical: PreparedFile(json.dumps(old_run).encode(), before["files"][run_logical]["mode"])})
    legacy = {path.name: (path.read_bytes(), S_IMODE(path.stat().st_mode)) for path in (native, editor)}
    for name, (content, mode) in legacy.items():
        writes["@delivery/" + name] = PreparedFile(content, mode)
    writes["@delivery/" + DELIVERY_IDENTITY] = None
    reads = {name: item["sha256"] for name, item in before["files"].items()}
    for name in writes:
        reads.setdefault(name, None)
    command = ProjectCommand.create("publish", "generated-legacy-delivery-fixture",
        project_id=before["project_id"], expected_generation=before["generation"],
        read_set=reads, write_set=sorted(writes),
        read_memberships=[MembershipRead(**item) for item in whole_memberships(store, before)],
        request={"fixture": "generated complete v6 record and v1 native/browser shells"})
    receipt = ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, {"registered": sorted(legacy)}))
    after = store.snapshot()
    assert receipt["phase"] == "complete" and after["sequence"] == before["sequence"] + 1
    assert after["outside_changes"] == {}
    assert not (delivery / DELIVERY_IDENTITY).exists()
    for name, (content, mode) in legacy.items():
        assert store.read_bytes("@delivery/" + name, generation=after["generation"]) == content
        assert after["files"]["@delivery/" + name]["mode"] == mode
    assert read_intake_project_manifest(project, store=store)["delivery_package"] == historical
    return legacy, receipt


def _assert_retained(project, store, legacy, manifest, *, version=7):
    with project_runtime(store):
        registry = read_intake_project_manifest(project, store=store)
        record = registry["delivery_package"]
        actual = store.locations["delivery"] / "Open_in_SciPlot.command"
        assert record["path"] == str(actual.parent)
        assert record["open_in_sciplot"] == str(actual)
        assert record["editor_launcher_contract"]["path"] == str(actual)
        for name, (content, mode) in legacy.items():
            path = actual.parent / name
            assert path.read_bytes() == content and S_IMODE(path.stat().st_mode) == mode
        assert record["version"] == version
        assert record["complete"] is True and record["verification"]["passed"] is True
        assert inspect_delivery_editor_launcher_contract(actual.parent)["ready"] is True
        binding = read_delivery_binding(actual.parent)
        assert binding is not None
        assert binding.root == literal_source_path(actual.parent)
        assert binding.request == literal_source_path(project / "plot_request.json")
        assert binding.source == literal_source_path(project / "source/data.csv")
        if version == 7:
            identity = actual.parent / DELIVERY_IDENTITY
            # New publication records current host locators. The binding above
            # retains the original literal identity through the admitted move.
            assert record["identity"] == str(identity)
            assert record["identity_contract"]["path"] == str(identity)
            old_native = actual.parent / "Open_in_Veusz.command"
            historical_native = record["legacy_veusz_launcher"]
            assert set(historical_native) == {"path", "sha256", "contract", "mode"}
            assert historical_native["path"] == str(old_native)
            assert historical_native["contract"]["path"] == str(old_native)
            assert historical_native["sha256"] == file_sha256(old_native)
            assert historical_native["mode"] == legacy[old_native.name][1]
            assert not {"open_in_veusz", "open_in_veusz_sha256", "launcher_contract"} & record.keys()
        else:
            assert not (actual.parent / DELIVERY_IDENTITY).exists()
        assert record["verification"]["expected_root"] == str(actual.parent)
        assert record["verification"]["recorded_root"] == str(actual.parent)
        stored_manifest = json.loads(projected_runtime_artifact(Path(manifest["output"]) / "manifest.json").read_bytes())
        assert stored_manifest["delivery_package"]["version"] == version
        identity_field = "identity" if version == 7 else "open_in_veusz"
        assert stored_manifest["delivery_package"][identity_field] == record[identity_field]
        for section in ("data", "pdf", "tiff", "project"):
            for collection in ("live_files", "recorded_files"):
                for path in record["verification"][section][collection]:
                    assert projected_runtime_artifact(path).is_file()
                    assert "sciplot-studio-candidate-" not in path and "sciplot-publication-" not in path
        for marker in ("sciplot-studio-candidate-", "sciplot-publication-"):
            assert marker not in json.dumps(binding.to_payload())
        verification = verify_delivery_package(record, expected_root=actual.parent, expected_manifest=manifest)
        assert verification["passed"] is True, verification
    assert store.snapshot()["outside_changes"] == {}
    return record


@pytest.mark.comprehensive
def test_registered_legacy_delivery_survives_real_producers_cold_reopen_and_bundle_move(tmp_path):
    project = tmp_path / "project"
    (project / "source").mkdir(parents=True)
    source = project / "source/data.csv"
    source.write_bytes(b"x,y\n0,1\n1,2\n2,4\n")
    source_bytes = source.read_bytes()
    delivery = tmp_path / "delivery"
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": "source/data.csv", "template": "curve",
        "output": str(project / "runs/run_001"), "delivery_output": str(delivery),
        "exports": ["pdf", "tiff_300"]}))
    (project / "intake_manifest.json").write_text(json.dumps({"kind": "sciplot_intake_project",
        "version": 1, "project_slug": "project"}))
    phases = []
    record = {"status": "incomplete", "started_utc": datetime.now(timezone.utc).isoformat(),
              "test_sha256": file_sha256(Path(__file__)), "source_sha256": file_sha256(source),
              "scope": "Generated legacy fixture registered through ProjectCommands; real Workflow/Studio/native and official bundle relocation; script never executed."}
    started = perf_counter()

    def run(name, operation):
        begin = perf_counter()
        try:
            return operation()
        finally:
            phases.append({"phase": name, "seconds": perf_counter() - begin})

    def direct_source(_path, **_kwargs):
        return {"semantic_family": "unknown", "rule_id": None, "confidence": 0,
                "needs_ai_intervention": True}

    try:
        first = run("workflow_fresh", lambda: run_request(request, _classifier=direct_source))
        assert first["delivery_package"]["complete"] is True
        assert not (delivery / "Open_in_SciPlot.command").exists()
        assert not (delivery / "Open_in_Veusz.command").exists()
        assert (delivery / DELIVERY_IDENTITY).is_file()
        store = _publication_store(project)
        legacy, registration = run("register_generated_legacy", lambda:
            _register_generated_legacy_evidence(project, store, tmp_path / "historical-stage", first))
        record["registration"] = registration
        historical_manifest = json.loads(store.read_bytes(store.logical_path(Path(first["output"]) / "manifest.json")))
        historical = _assert_retained(project, store, legacy, historical_manifest, version=6)
        second = run("workflow_legacy_republication", lambda: run_request(request, _classifier=direct_source))
        assert second["delivery_package"]["complete"] is True
        _assert_retained(project, store, legacy, second)
        assert source.read_bytes() == source_bytes
        native = project / "studio/document.vsz"
        specification = project / "studio/spec.json"
        native_bytes = native.read_bytes()
        spec_bytes = specification.read_bytes()
        original_request = json.loads(store.read_bytes("plot_request.json"))
        reopened = run("studio_cold_reopen", lambda: prepare_studio_document(project))
        assert reopened["preserved_existing_document"] is True
        published = run("studio_legacy_export", lambda: export_project_document(project_dir=project,
            formats=["pdf", "tiff_300"]))
        assert published.ready_to_use
        _assert_retained(project, store, legacy, published.run_payload)
        assert native.read_bytes() == native_bytes and specification.read_bytes() == spec_bytes
        assert source.read_bytes() == source_bytes

        # Use the actual portability entrypoint; old paths really disappear.
        bundle = run("export_complete_bundle", lambda: store.export_bundle(tmp_path / "bundle"))
        project.rename(tmp_path / "offline-project")
        delivery.rename(tmp_path / "offline-delivery")
        assert not project.exists() and not source.exists() and not delivery.exists()
        moved = run("import_complete_bundle", lambda: FileProjectStore.import_bundle(bundle, tmp_path / "moved"))
        moved_native = moved.root / "studio/document.vsz"
        moved_spec = moved.root / "studio/spec.json"
        moved_source = moved.root / "source/data.csv"
        assert moved_native.read_bytes() == native_bytes and moved_spec.read_bytes() == spec_bytes
        assert moved_source.read_bytes() == source_bytes
        assert json.loads(moved.read_bytes("plot_request.json")) == original_request
        moved_reopened = run("moved_studio_cold_reopen", lambda: prepare_studio_document(moved.root))
        assert moved_reopened["preserved_existing_document"] is True
        moved_export = run("moved_studio_legacy_export", lambda: export_project_document(project_dir=moved.root,
            formats=["pdf", "tiff_300"]))
        assert moved_export.ready_to_use
        final_delivery = _assert_retained(moved.root, moved, legacy, moved_export.run_payload)
        assert moved_native.read_bytes() == native_bytes and moved_spec.read_bytes() == spec_bytes
        assert moved_source.read_bytes() == source_bytes and not project.exists()
        for item in moved_export.exports:
            actual = Path(item["path"])
            assert actual.is_file() and actual.stat().st_size > 0
            assert file_sha256(actual) == item["sha256"]

        # A later mode-only mutation is outside the recorded authority. Refuse
        # instead of deleting, reauthenticating or silently regenerating it.
        editor = moved.locations["delivery"] / "Open_in_SciPlot.command"
        before_generation = moved.snapshot()["generation"]
        editor.chmod(0o640)
        with pytest.raises(ValueError) as refusal:
            run("registered_mode_drift_refused", lambda: export_project_document(project_dir=moved.root,
                formats=["pdf", "tiff_300"]))
        assert moved.snapshot()["generation"] == before_generation
        assert editor.read_bytes() == legacy[editor.name][0] and S_IMODE(editor.stat().st_mode) == 0o640
        retained_native = moved.locations["delivery"] / "Open_in_Veusz.command"
        assert retained_native.read_bytes() == legacy[retained_native.name][0]
        assert S_IMODE(retained_native.stat().st_mode) == legacy[retained_native.name][1]
        assert moved_native.read_bytes() == native_bytes and moved_spec.read_bytes() == spec_bytes
        assert moved_source.read_bytes() == source_bytes
        record.update(status="passed", historical_record=historical, final_record=final_delivery,
                      native_sha256=file_sha256(moved_native), spec_sha256=file_sha256(moved_spec),
                      moved_exports=moved_export.export_payload,
                      refusal={"type": type(refusal.value).__name__, "message": str(refusal.value)})
    except BaseException as exc:
        record.update(status="failed", failure={"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        record.update(phases=phases, total_seconds=perf_counter() - started)
        output = Path(os.environ.get("SCIPLOT_DELIVERY_PROOF_DIR", str(REPO_ROOT / ".tmp_verify/delivery-history-proof")))
        output.mkdir(parents=True, exist_ok=True)
        (output / f"native-{time_ns()}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
