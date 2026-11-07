from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_project_probe import _copy_project_fixture








def _copyable_project(tmp_path: Path) -> Path:
    project = tmp_path / "original"
    (project / "raw").mkdir(parents=True)
    (project / "source").mkdir()
    (project / "studio").mkdir()
    (project / "raw" / "input.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    source = project / "source" / "prepared.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    document = project / "studio" / "document.vsz"
    document.write_text("# exact-current native document\n", encoding="utf-8")
    spec = project / "studio" / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "kind": "sciplot_veusz_plot_spec",
                "series": [
                    {
                        "source_artifacts": [
                            {
                                "path": str(source),
                                "sha256": file_sha256(source),
                            }
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project / "studio" / "figure_set.json").write_text(
        json.dumps(
            {
                "primary_document": str(document),
                "figures": [{"document": str(document), "spec": str(spec)}],
                "resolved_figure_plan": {
                    "outcomes": [{"artifacts": [str(document), str(spec)]}]
                },
            }
        ),
        encoding="utf-8",
    )
    (project / "plot_request.json").write_text(
        json.dumps(
            {
                "source": str(source),
            }
        ),
        encoding="utf-8",
    )
    return project


@pytest.mark.parametrize("preserve_registry", [False, True])
def test_probe_fixture_copy_rebinds_only_proven_sources(
    tmp_path: Path,
    preserve_registry: bool,
) -> None:
    original = _copyable_project(tmp_path)
    original_files = {
        p.relative_to(original): p.read_bytes()
        for p in original.rglob("*")
        if p.is_file()
    }

    copied = _copy_project_fixture(
        original,
        tmp_path / "probe",
        preserve_stale_registry_paths=preserve_registry,
    )

    for path in ("raw/input.csv", "source/prepared.csv", "studio/document.vsz"):
        assert (copied / path).read_bytes() == original_files[Path(path)]
    spec = json.loads((copied / "studio/spec.json").read_text())
    assert spec["series"][0]["source_artifacts"] == [
        {
            "path": str(copied / "source/prepared.csv"),
            "sha256": file_sha256(copied / "source/prepared.csv"),
        }
    ]
    registry = json.loads((copied / "studio/figure_set.json").read_text())
    expected_root = original if preserve_registry else copied
    assert registry["primary_document"] == str(expected_root / "studio/document.vsz")
    assert registry["figures"][0]["spec"] == str(expected_root / "studio/spec.json")
    assert registry["resolved_figure_plan"]["outcomes"][0]["artifacts"] == [
        str(expected_root / "studio/document.vsz"),
        str(expected_root / "studio/spec.json"),
    ]
    assert original_files == {
        p.relative_to(original): p.read_bytes()
        for p in original.rglob("*")
        if p.is_file()
    }


def test_probe_fixture_copy_rejects_unproven_prepared_source(tmp_path: Path) -> None:
    original = _copyable_project(tmp_path)
    (original / "source/prepared.csv").write_text("x,y\n1,999\n", encoding="utf-8")

    with pytest.raises(ValueError, match="specification hash"):
        _copy_project_fixture(original, tmp_path / "probe")


@pytest.mark.parametrize("preserve_registry", [False, True])
def test_probe_managed_clone_preserves_admitted_science_and_exact_native(
    tmp_path: Path, preserve_registry: bool,
) -> None:
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime, resolve_runtime_path

    original = _copyable_project(tmp_path)
    before = FileProjectStore(original).snapshot(import_legacy=True)
    inventory = {
        p.relative_to(original): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
        for p in original.rglob("*") if p.is_file()
    }
    copied = _copy_project_fixture(
        original, tmp_path / "probe", preserve_stale_registry_paths=preserve_registry,
    )
    store = project_store(copied)
    current = store.snapshot()
    assert current["projection_status"] == "current"
    for field in ("project_id", "generation", "sources", "locators", "files", "commands"):
        assert current[field] == before[field]
    for name in ("plot_request.json", "studio/spec.json", "studio/figure_set.json", "studio/document.vsz"):
        assert (copied / name).read_bytes() == inventory[Path(name)][0]
    literal = original / "source/prepared.csv"
    identity = next(key for key, versions in before["sources"].items()
                    if any(item["locator"] == str(literal) for item in versions.values()))
    with project_runtime(store):
        assert resolve_runtime_path(literal, expected_sha256=file_sha256(literal), source_id=identity) == copied / "source/prepared.csv"
    assert inventory == {
        p.relative_to(original): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
        for p in original.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("change", ["request", "source", "native", "mode", "alias"])
def test_probe_managed_clone_does_not_repair_unadmitted_changes(
    tmp_path: Path, change: str,
) -> None:
    from sciplot_core.project_store import FileProjectStore, ProjectConflict

    original = _copyable_project(tmp_path)
    FileProjectStore(original).snapshot(import_legacy=True)
    target = original / {"request": "plot_request.json", "native": "studio/document.vsz"}.get(
        change, "source/prepared.csv")
    if change == "mode":
        target.chmod((target.stat().st_mode & 0o777) ^ 0o200)
    elif change == "alias":
        outside = tmp_path / "same-bytes.csv"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    else:
        target.write_bytes(target.read_bytes() + b"\n# outside change\n")
    head = (original / ".sciplot_store/head.json").read_bytes()
    if change == "alias":
        import errno

        with pytest.raises(OSError) as rejected:
            _copy_project_fixture(original, tmp_path / "probe")
        assert rejected.value.errno == errno.ELOOP
    else:
        reason = "canonical request differs" if change == "request" else "unadmitted"
        with pytest.raises(ProjectConflict, match=reason):
            _copy_project_fixture(original, tmp_path / "probe")
    assert (original / ".sciplot_store/head.json").read_bytes() == head
    assert not (tmp_path / "probe/project").exists()


def test_probe_setup_uses_current_generation_without_rewriting_scientific_sources(tmp_path: Path) -> None:
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_project_probe import _publish_fixture_setup

    original = _copyable_project(tmp_path)
    original_store = FileProjectStore(original)
    before = original_store.snapshot(import_legacy=True)
    copied = _copy_project_fixture(original, tmp_path / "probe")
    store = project_store(copied)
    native = (copied / "studio/document.vsz").read_bytes()
    spec = (copied / "studio/spec.json").read_bytes()
    request = (copied / "plot_request.json").read_bytes()
    launcher = copied / "Open_SciPlot_Project.command"
    manifest = copied / "intake_manifest.json"
    _publish_fixture_setup(copied, {launcher: b"#!/bin/zsh\nsciplot workbench .\n",
                                    manifest: b'{"launcher": "/foreign/stale/legacy.command"}'})
    current = store.snapshot()
    assert current["projection_status"] == "current"
    assert current["generation"] != before["generation"]
    assert current["project_id"] == before["project_id"]
    assert current["sources"] == before["sources"]
    assert current["locators"] == before["locators"]
    assert store.read_bytes("studio/spec.json", generation=before["generation"]) == spec
    assert (copied / "studio/document.vsz").read_bytes() == native
    assert (copied / "studio/spec.json").read_bytes() == spec
    assert (copied / "plot_request.json").read_bytes() == request
    assert store.read_bytes("intake_manifest.json") == manifest.read_bytes()
    assert store.read_bytes("Open_SciPlot_Project.command") == launcher.read_bytes()
    assert original_store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("internal", [True, False], ids=["project-default", "explicit-override"])
def test_project_delivery_review_uses_the_host_selected_studio_root_without_writes(tmp_path, monkeypatch, internal):
    from test_project_delivery_runtime import _project_and_delivery
    from sciplot_core.project_store import directories
    from sciplot_core.studio_core.project_export import verify_project_delivery

    project, delivery, store = _project_and_delivery(tmp_path, internal=internal)
    manifest = json.loads(store.read_bytes("runs/studio_001/manifest.json"))
    def inventory():
        return {str(p): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                for root in (project, delivery) for p in root.rglob("*") if p.is_file()}
    before = inventory()
    def no_view(*_args, **_kwargs):
        raise AssertionError("Delivery review cannot materialize source views")
    monkeypatch.setattr(directories, "resolve", no_view)
    evidence = verify_project_delivery(project, manifest["delivery_package"], expected_manifest=manifest)
    assert evidence["passed"] is True, evidence
    assert evidence["expected_root"] == str(delivery)
    assert inventory() == before


@pytest.mark.parametrize("internal", [True, False], ids=["project-default", "explicit-override"])
def test_project_delivery_review_keeps_official_relocation_and_exact_root_identity(tmp_path, internal):
    from test_project_delivery_runtime import _project_and_delivery
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_core.project_export import verify_project_delivery

    project, delivery, store = _project_and_delivery(tmp_path, internal=internal)
    manifest = json.loads(store.read_bytes("runs/studio_001/manifest.json"))
    record = manifest["delivery_package"]
    original = store.read_bytes("plot_request.json"), store.read_bytes("runs/studio_001/manifest.json")
    bundle = store.export_bundle(tmp_path / "portable.bundle")
    project.rename(tmp_path / "offline-project")
    if not internal:
        delivery.rename(tmp_path / "offline-delivery")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    evidence = verify_project_delivery(moved.root, record, expected_manifest=manifest)
    assert evidence["passed"] is True, evidence
    assert evidence["expected_root"] == str(moved.locations.get("delivery", moved.root / "delivery"))
    assert (moved.read_bytes("plot_request.json"), moved.read_bytes("runs/studio_001/manifest.json")) == original
    foreign = tmp_path / "foreign-root"
    foreign.mkdir()
    forged = {**record, "path": str(foreign)}
    rejected = verify_project_delivery(moved.root, forged, expected_manifest=manifest)
    assert rejected["passed"] is False
    assert "canonical_root" in rejected["failed_checks"]


def test_project_delivery_review_refuses_same_bytes_foreign_cap_and_mode_drift(tmp_path):
    import shutil
    from test_project_delivery_runtime import _project_and_delivery
    from sciplot_core.project_store import FileProjectStore, ProjectConflict
    from sciplot_core.studio_core.project_export import verify_project_delivery

    project, delivery, store = _project_and_delivery(tmp_path)
    manifest = json.loads(store.read_bytes("runs/studio_001/manifest.json"))
    foreign = tmp_path / "same-bytes-foreign"
    shutil.copytree(delivery, foreign)
    original = store.snapshot()
    with pytest.raises((ValueError, ProjectConflict)):
        FileProjectStore(project, locations={"delivery": foreign}).snapshot()
    assert store.snapshot()["generation"] == original["generation"]
    launcher = delivery / "Open_in_Veusz.command"
    launcher.chmod((launcher.stat().st_mode & 0o777) ^ 0o100)
    with pytest.raises((ValueError, ProjectConflict)):
        verify_project_delivery(project, manifest["delivery_package"], expected_manifest=manifest)
    assert store.snapshot()["generation"] == original["generation"]


def test_project_delivery_review_keeps_unadmitted_legacy_noncreating_and_invalid_store_closed(tmp_path):
    from test_project_delivery_runtime import _project_and_delivery
    from sciplot_core.studio_core.project_export import verify_project_delivery

    project, _delivery, store = _project_and_delivery(tmp_path)
    manifest = json.loads(store.read_bytes("runs/studio_001/manifest.json"))
    metadata = project / ".sciplot_store"
    metadata.rename(tmp_path / "original-store")
    evidence = verify_project_delivery(project, manifest["delivery_package"], expected_manifest=manifest)
    assert evidence["passed"] is True, evidence
    assert not metadata.exists()
    metadata.mkdir()
    with pytest.raises(ValueError):
        verify_project_delivery(project, manifest["delivery_package"], expected_manifest=manifest)
    assert list(metadata.iterdir()) == []


def test_probe_source_drift_control_selects_exact_cloned_source_not_original(tmp_path: Path) -> None:
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_project_probe import _source_mutation_target

    original = _copyable_project(tmp_path)
    FileProjectStore(original).snapshot(import_legacy=True)
    copied = _copy_project_fixture(original, tmp_path / "probe")
    target = _source_mutation_target(str(original / "source/prepared.csv"), project_dir=copied)
    assert target == copied / "source/prepared.csv"
    assert target != original / "source/prepared.csv"
    foreign = tmp_path / "foreign/prepared.csv"
    foreign.parent.mkdir()
    foreign.write_bytes(target.read_bytes())
    assert _source_mutation_target(str(foreign), project_dir=copied) is None


@pytest.mark.parametrize("spec_evidence", [True, False], ids=["sealed-spec", "no-source-evidence"])
def test_legacy_source_only_query_requires_its_declared_exact_evidence(tmp_path: Path, spec_evidence: bool) -> None:
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core.project_query_sources import current_source_files

    original = _copyable_project(tmp_path)
    FileProjectStore(original).snapshot(import_legacy=True)
    copied = _copy_project_fixture(original, tmp_path / "probe")
    store = project_store(copied)
    before = store.snapshot()
    inventory = {p.relative_to(copied): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                 for p in copied.rglob("*") if p.is_file()}
    source = original / "source/prepared.csv"
    digest = file_sha256(source)
    assert json.loads(store.read_bytes("plot_request.json")) == {"source": str(source)}
    owners = [identity for identity, versions in before["sources"].items()
              if versions.get(digest, {}).get("locator") == str(source)]
    assert len(owners) == 1
    figures = [{"status": "ready", "spec": str(copied / "studio/spec.json")}] if spec_evidence else []
    with project_runtime(store):
        files, identities = current_source_files(copied, source, figures)
        assert files == ({str(source): digest} if spec_evidence else {})
        assert identities == ({str(source): owners[0]} if spec_evidence else {})
        # A same-byte foreign file is neither a locator alias nor selected input.
        foreign = tmp_path / "foreign.csv"
        foreign.write_bytes(source.read_bytes())
        assert current_source_files(copied, foreign, figures) == ({}, {})
    assert store.snapshot()["generation"] == before["generation"]
    assert {p.relative_to(copied): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
            for p in copied.rglob("*") if p.is_file()} == inventory
    assert (copied / "source/prepared.csv").read_bytes() == source.read_bytes()


def test_probe_positive_legacy_setup_explicitly_admits_before_its_single_publication(tmp_path):
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.studio_project_probe import _publish_fixture_setup

    original = _copyable_project(tmp_path)
    native = (original / "studio/document.vsz").read_bytes()
    request = (original / "plot_request.json").read_bytes()
    assert not (original / ".sciplot_store").exists()
    manifest = original / "intake_manifest.json"
    _publish_fixture_setup(original, {manifest: b'{"display":"legacy setup"}'})
    snapshot = project_store(original).snapshot()
    assert len(snapshot["commands"]) == 1
    assert manifest.read_bytes() == b'{"display":"legacy setup"}'
    assert (original / "studio/document.vsz").read_bytes() == native
    assert (original / "plot_request.json").read_bytes() == request


def test_saved_query_refuses_changed_canonical_request_without_reusing_history(tmp_path):
    from sciplot_core.project_store import FileProjectStore, ProjectConflict
    from sciplot_core.studio_core.project_query import inspect_project
    from sciplot_core.studio_core.source_content_observation import observe_studio_source_content

    project = _copyable_project(tmp_path)
    (project / "studio/figure_set.json").unlink()  # This fixture is a legacy single figure.
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": str(project / "source/prepared.csv")}))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    request.write_bytes(request.read_bytes() + b" ")
    inventory = {str(p): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                 for p in project.rglob("*") if p.is_file()}
    with pytest.raises(ProjectConflict):
        inspect_project(project, native=False)
    assert store.snapshot()["generation"] == before["generation"]
    assert {str(p): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
            for p in project.rglob("*") if p.is_file()} == inventory
    request.write_bytes(request.read_bytes()[:-1])
    current = observe_studio_source_content(project / "source/prepared.csv",
        project_dir=project, request_path=request, audit_source=True)
    assert current["exists"] is True
    assert current["content"]["sha256"] == file_sha256(project / "source/prepared.csv")


@pytest.mark.parametrize("previous", [False, True], ids=["no-prior-evidence", "historical-saved-evidence"])
def test_saved_query_propagates_observer_failure_without_reusing_history(tmp_path, monkeypatch, previous):
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_core import project_query

    project = _copyable_project(tmp_path)
    (project / "studio/figure_set.json").unlink()
    (project / "plot_request.json").write_text(json.dumps({"input": str(project / "source/prepared.csv")}))
    if previous:
        run = project / "runs/studio_001"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text(json.dumps({"ready_to_use": True,
            "qa": {"status": "passed"}, "historical": "not current authorization"}))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    inventory = {str(p): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                 for p in project.rglob("*") if p.is_file()}
    error = RuntimeError("unexpected observer failure")
    def fail(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(project_query, "publication_indicators", fail)
    with pytest.raises(RuntimeError) as result:
        project_query.inspect_project(project, native=False)
    assert result.value is error
    assert store.snapshot()["generation"] == before["generation"]
    assert {str(p): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
            for p in project.rglob("*") if p.is_file()} == inventory


@pytest.mark.parametrize("change", ["equivalent_restore", "unrelated", "request", "mode"])
def test_probe_producer_revisions_preserve_selected_editing_read_guards(
    tmp_path: Path, change: str,
) -> None:
    from sciplot_core.project_commands.resources import PreparedFile
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store import FileProjectStore, ProjectConflict
    from sciplot_core.project_store.adapters import publish_files
    from sciplot_core.studio_project_probe import _publish_fixture_setup

    original = _copyable_project(tmp_path)
    FileProjectStore(original).snapshot(import_legacy=True)
    copied = _copy_project_fixture(original, tmp_path / "probe")
    store = project_store(copied)
    before = store.snapshot()
    baseline = {"project_id": before["project_id"], "generation": before["generation"],
                "files": {name: item["sha256"] for name, item in before["files"].items()}}
    registry = copied / "studio/figure_set.json"
    data, mode = registry.read_bytes(), registry.stat().st_mode & 0o777
    if change == "equivalent_restore":
        _publish_fixture_setup(copied, {registry: None})
        _publish_fixture_setup(copied, {registry: data}, modes={registry: mode})
        assert registry.read_bytes() == data and registry.stat().st_mode & 0o777 == mode
    elif change == "unrelated":
        _publish_fixture_setup(copied, {copied / "probe_notes.json": b'{"display": "fixture"}'})
    elif change == "request":
        _publish_fixture_setup(copied, {copied / "plot_request.json": b'{"source": "changed"}'})
    else:
        _publish_fixture_setup(copied, {registry: data}, modes={registry: mode ^ 0o200})
    selected = store.snapshot()
    native = (copied / "studio/document.vsz").read_bytes()
    writes = {"studio/document.vsz": PreparedFile(native, before["files"]["studio/document.vsz"]["mode"])}
    if change in {"request", "mode"}:
        with pytest.raises(ProjectConflict, match="declared project (read|resource)"):
            publish_files(store, writes, kind="save", baseline=baseline)
        assert store.snapshot()["generation"] == selected["generation"]
    else:
        result = publish_files(store, writes, kind="save", baseline=baseline)
        assert result["phase"] == "complete"
        assert store.snapshot()["generation"] != selected["generation"]
    assert (copied / "studio/document.vsz").read_bytes() == native


def test_surviving_native_diagnostics_import_without_a_gui_package():
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    code = '''
import importlib
import importlib.abc
import sys
class NoProductGUI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "sciplot_gui" or fullname.startswith("sciplot_gui."):
            raise AssertionError("retired GUI imported: " + fullname)
sys.meta_path.insert(0, NoProductGUI())
project = importlib.import_module("sciplot_core.studio_project_probe")
baseline = importlib.import_module("sciplot_core.automation_baseline_probe")
importlib.import_module("sciplot_core.studio_figure_set_probe")
assert not hasattr(project, "run_studio_project_probe")
assert not hasattr(baseline, "_run_selected_object_cycle")
assert "sciplot_gui" not in sys.modules
'''
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (environment.get("PYTHONPATH", ""), str(root / "src"))))
    result = subprocess.run([sys.executable, "-c", code], cwd=root,
        env=environment, capture_output=True,
        text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "src/sciplot_core/studio_assistant_probe.py").exists()


def test_retired_project_dock_probe_is_not_a_silent_success(tmp_path):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    marker = tmp_path / "unchanged.vsz"
    marker.write_bytes(b"user native bytes")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (environment.get("PYTHONPATH", ""), str(root / "src"))))
    result = subprocess.run([sys.executable, "-m", "sciplot_core.studio_project_probe", str(marker)],
        cwd=root, env=environment,
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0
    assert "studio_project_probe_retired" in result.stderr
    assert marker.read_bytes() == b"user native bytes"
