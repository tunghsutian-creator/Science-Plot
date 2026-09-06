from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sciplot_core.studio_core import source_update_commit as transaction


def _bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def revisions(tmp_path: Path):
    project, candidate = tmp_path / "current", tmp_path / "candidate"
    for root, label in ((project, "old"), (candidate, "new")):
        _write(
            root / "raw" / "instrument.json", b'{ "raw" : "' + label.encode() + b'" }\n'
        )
        _write(
            root / "source" / "data.json",
            json.dumps(
                {
                    "instrument_field": str(root / "source" / "literal-data-value"),
                    "values": [1, 2] if label == "old" else [4, 5],
                },
                separators=(", ", " : "),
            ).encode()
            + b"\n",
        )
        _write(root / "studio" / "document.vsz", label.encode() + b" VSZ")
        _write(
            root / "studio" / "spec.json",
            json.dumps(
                {
                    "source": str(root / "source" / "data.json"),
                    "document": str(root / "studio" / "document.vsz"),
                }
            ).encode(),
        )
        _write(
            root / "plot_request.json",
            json.dumps(
                {
                    "input": str(root / "source"),
                    "project": str(root),
                    "delivery_output": str(tmp_path / "visible"),
                }
            ).encode(),
        )
        _write(
            root / "intake_manifest.json",
            json.dumps(
                {
                    "raw": str(root / "raw" / "instrument.json"),
                }
            ).encode(),
        )
    _write(project / "runs" / "studio_001" / "manifest.json", b"old immutable run")
    _write(project / "delivery" / "legacy.vsz", b"old internal delivery")
    _write(tmp_path / "visible" / "project" / "old.vsz", b"visible manual edit")
    return project, candidate


def test_source_transaction_relocates_only_metadata_and_retains_old_evidence(revisions):
    project, candidate = revisions
    previous = _bytes(project)
    raw, source = _bytes(candidate / "raw"), _bytes(candidate / "source")
    visible = _bytes(project.parent / "visible")
    validation = []

    def validate():
        validation.append(True)
        assert json.loads((project / "studio/spec.json").read_text()) == {
            "source": str(project / "source/data.json"),
            "document": str(project / "studio/document.vsz"),
        }
        assert json.loads((project / "plot_request.json").read_text())["input"] == str(
            project / "source"
        )
        assert _bytes(project / "raw") == raw
        assert _bytes(project / "source") == source

    archive = transaction.install_source_update(
        project,
        candidate,
        expected=transaction.project_inventory(project),
        validate=validate,
    )
    assert validation == [True]
    assert _bytes(archive) == {
        key: value
        for key, value in previous.items()
        if not key.startswith(("runs/", "delivery/"))
    }
    assert (
        project / "runs/studio_001/manifest.json"
    ).read_bytes() == b"old immutable run"
    assert (project / "delivery/legacy.vsz").read_bytes() == b"old internal delivery"
    assert _bytes(project.parent / "visible") == visible


def test_source_transaction_post_audit_failure_restores_whole_project(revisions):
    project, candidate = revisions
    before = _bytes(project)

    def failed_audit():
        assert (project / "studio/document.vsz").read_bytes() == b"new VSZ"
        raise ValueError("injected scientific audit failure")

    with pytest.raises(ValueError, match="injected scientific audit failure"):
        transaction.install_source_update(
            project,
            candidate,
            expected=transaction.project_inventory(project),
            validate=failed_audit,
        )
    assert _bytes(project) == before
    assert (candidate / "studio/document.vsz").read_bytes() == b"new VSZ"


@pytest.mark.parametrize("phase", ["archive", "install"])
def test_source_transaction_partial_replace_failure_rolls_back(
    revisions, monkeypatch, phase
):
    project, candidate = revisions
    before = _bytes(project)
    replace = os.replace
    injected = []

    def fail_one(source, destination):
        source = Path(source)
        match = source == (project if phase == "archive" else candidate) / "source"
        if match and not injected:
            injected.append(True)
            raise OSError("injected partial replacement failure")
        return replace(source, destination)

    monkeypatch.setattr(transaction.os, "replace", fail_one)
    with pytest.raises(OSError, match="injected partial replacement failure"):
        transaction.install_source_update(
            project,
            candidate,
            expected=transaction.project_inventory(project),
            validate=lambda: None,
        )
    assert injected == [True]
    assert _bytes(project) == before
    assert (candidate / "raw/instrument.json").is_file()
    assert (candidate / "source/data.json").is_file()
    assert (candidate / "studio/document.vsz").read_bytes() == b"new VSZ"


def test_source_transaction_stale_inventory_refuses_any_install(revisions):
    project, candidate = revisions
    expected = transaction.project_inventory(project)
    (project / "studio/document.vsz").write_bytes(b"concurrent edit")
    before = _bytes(project)
    with pytest.raises(ValueError, match="changed after preview"):
        transaction.install_source_update(
            project, candidate, expected=expected, validate=lambda: None
        )
    assert _bytes(project) == before
    assert not (project.parent / ".source_update_history").exists()


def test_source_transaction_precommit_rejection_preserves_project(revisions):
    project, candidate = revisions
    before = _bytes(project)

    def changed_source():
        raise ValueError("selected source changed after preview")

    with pytest.raises(ValueError, match="selected source changed"):
        transaction.install_source_update(
            project,
            candidate,
            expected=transaction.project_inventory(project),
            validate=lambda: None,
            precommit=changed_source,
        )
    assert _bytes(project) == before
    assert not (project.parent / ".source_update_history").exists()


@pytest.mark.parametrize("location", ["project", "candidate", "candidate_source"])
def test_source_transaction_rejects_symbolic_link_paths(revisions, location):
    project, candidate = revisions
    expected = transaction.project_inventory(project)
    before = _bytes(project)
    supplied_project, supplied_candidate = project, candidate
    if location == "project":
        supplied_project = project.with_name("linked_project")
        supplied_project.symlink_to(project, target_is_directory=True)
    elif location == "candidate":
        supplied_candidate = candidate.with_name("linked_candidate")
        supplied_candidate.symlink_to(candidate, target_is_directory=True)
    else:
        source = candidate / "source"
        actual = candidate.with_name("external_source")
        source.rename(actual)
        source.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic|symlink"):
        transaction.install_source_update(
            supplied_project,
            supplied_candidate,
            expected=expected,
            validate=lambda: None,
        )
    assert _bytes(project) == before
    assert not (project.parent / ".source_update_history").exists()
