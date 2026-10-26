from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
    write_delivery_launcher,
)
from sciplot_core.launchers.delivery_binding import make_delivery_binding
from sciplot_core.studio_core.delivery_target import resolve_delivery_target
from sciplot_core.studio_core.studio_prepare import prepare_studio_document
import sciplot_core.studio_core.studio_prepare_core as preparation
import sciplot_core.studio_core.studio_command as command


def _linked_delivery(tmp_path: Path, *, multiple: bool = False):
    root = tmp_path / "Visible"
    project = tmp_path / ".sciplot" / "managed"
    canonical = project / "studio" / "document.vsz"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"canonical Veusz project")
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    request_path = project / "plot_request.json"
    request = {"input": str(source), "delivery_output": str(root)}
    request_path.write_text(json.dumps(request), encoding="utf-8")
    (root / "project").mkdir(parents=True)
    documents = []
    for name in ("secondary", "primary") if multiple else ("primary",):
        path = root / "project" / f"{name}.vsz"
        shutil.copy2(canonical, path)
        documents.append(
            {
                "path": str(path),
                "figure_id": name,
                "delivery_sha256": existing_file_sha256(path),
            }
        )
    binding = make_delivery_binding(
        root=root,
        manifest={
            "request_path": str(request_path),
            "resolved_figure_plan": {"primary_figure_id": "primary"},
        },
        documents=documents,
    )
    launcher = write_delivery_launcher(root, binding=binding)
    return root, project, canonical, launcher


def test_delivery_default_returns_the_same_project_for_multiple_figures(tmp_path: Path):
    root, project, canonical, launcher = _linked_delivery(tmp_path, multiple=True)
    expected = {
        "mode": "project",
        "project_dir": project,
        "request": project / "plot_request.json",
    }
    assert inspect_delivery_launcher_contract(root)["ready"] is True
    assert resolve_delivery_target(launcher) == expected
    assert resolve_delivery_target(root) == expected
    assert canonical.exists()


@pytest.mark.parametrize(
    "change", ["copy", "move", "missing_project", "foreign_owner", "foreign_source"]
)
def test_copied_or_unassociated_delivery_opens_portable_copy(
    tmp_path: Path, capsys, change: str
):
    root, project, _, launcher = _linked_delivery(tmp_path, multiple=True)
    if change in {"copy", "move"}:
        moved = tmp_path / "Moved"
        if change == "copy":
            shutil.copytree(root, moved)
        else:
            root.rename(moved)
        root = moved
        launcher = root / launcher.name
    elif change == "missing_project":
        shutil.rmtree(project)
    else:
        request_path = project / "plot_request.json"
        request = json.loads(request_path.read_text())
        request["delivery_output" if change == "foreign_owner" else "input"] = str(
            tmp_path / "unrelated"
        )
        request_path.write_text(json.dumps(request))
    result = resolve_delivery_target(launcher)
    assert result == {"mode": "vsz", "document": root / "project" / "primary.vsz"}
    assert "portable Veusz copy" in capsys.readouterr().err


def test_delivery_open_does_not_ignore_visible_edits(tmp_path: Path):
    root, _, canonical, launcher = _linked_delivery(tmp_path)
    visible = root / "project" / "primary.vsz"
    visible.write_bytes(b"unique portable edit")
    with pytest.raises(ValueError, match="skip these edits") as error:
        resolve_delivery_target(launcher)
    assert str(visible) in str(error.value)
    assert visible.read_bytes() == b"unique portable edit"
    assert canonical.read_bytes() == b"canonical Veusz project"


def test_continue_edit_then_export_uses_canonical_project_without_regeneration(
    tmp_path: Path, monkeypatch, capsys
):
    root, project, canonical, launcher = _linked_delivery(tmp_path, multiple=True)
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store.adapters import publish_files
    from sciplot_core.studio_core import project_publication_commands
    from sciplot_core.studio_core.preparation_candidate import require_preparation_candidate

    calls, reused = [], []
    source = tmp_path / "source.csv"
    raw_bytes = source.read_bytes()
    request_path = project / "plot_request.json"
    request_bytes = request_path.read_bytes()
    visible_bytes = {path: path.read_bytes() for path in (root / "project").glob("*.vsz")}

    def reuse(**kwargs):
        private = kwargs["project_dir"]
        assert require_preparation_candidate(private).logical_root == project
        assert private != project
        assert kwargs["document_path"] == private / canonical.relative_to(project)
        assert kwargs["request_path"] == private / request_path.relative_to(project)
        assert kwargs["document_path"].read_bytes() == canonical.read_bytes()
        assert kwargs["request_path"].read_bytes() == request_bytes
        reused.append(private)
        return {
            "mode": "project",
            "project_dir": str(private),
            "request": str(kwargs["request_path"]),
            "document": str(kwargs["document_path"]),
            "preserved_existing_document": True,
        }

    def forbidden(**kwargs):
        raise AssertionError("continuing a delivery must never regenerate its source")

    monkeypatch.setattr(preparation, "reuse_existing_studio_document", reuse)
    monkeypatch.setattr(preparation, "generate_studio_document", forbidden)
    prepared = prepare_studio_document(launcher)
    assert Path(prepared["document"]) == canonical
    store = project_store(project)
    records = store.commands()
    assert len(records) == 1 and records[0]["phase"] == "complete"
    replayed = ProjectCommands(store).resume(ProjectCommand.from_payload(records[0]["metadata"]))
    assert Path(replayed["result"]["document"]) == canonical and len(reused) == 1
    edited = b"edited in the live managed document"
    publish_files(store, {"studio/document.vsz": edited}, kind="save")
    assert canonical.read_bytes() == edited
    edited_sha = existing_file_sha256(canonical)

    def publish(**kwargs):
        calls.append(("publish", kwargs["document_path"]))
        assert kwargs["project_dir"] == project
        assert kwargs["request_path"] == request_path
        assert kwargs["formats"] == ["pdf", "tiff_300"]
        assert kwargs["document_path"].read_bytes() == edited
        assert existing_file_sha256(kwargs["document_path"]) == edited_sha
        return {"ready_to_use": True, "exports": [], "scope": "project_delivery",
                "document_sha256": edited_sha}

    monkeypatch.setattr(command, "maybe_reexec_with_qt_runtime", lambda *args: None)
    monkeypatch.setattr(project_publication_commands, "publish_project_exports", publish)
    assert (
        command.run_studio_command(
            target=launcher, export="pdf,tiff_300", json_output=True
        )
        == 0
    )
    assert calls == [("publish", canonical)] and len(reused) == 2
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["document"]) == canonical
    assert payload["studio_run"]["ready_to_use"] is True
    assert payload["studio_run"]["document_sha256"] == edited_sha
    assert "standalone_export" not in payload
    assert canonical.read_bytes() == edited and source.read_bytes() == raw_bytes
    assert request_path.read_bytes() == request_bytes
    assert (root / "project" / "primary.vsz").read_bytes() == b"canonical Veusz project"
    assert {path: path.read_bytes() for path in visible_bytes} == visible_bytes


def test_binding_is_inert_and_malformed_binding_does_not_pass_launcher_check(
    tmp_path: Path,
):
    root, _, _, launcher = _linked_delivery(tmp_path)
    text = launcher.read_text()
    launcher.write_text(
        text.replace(
            "SCIPLOT_DELIVERY_BINDING_V1 {",
            'SCIPLOT_DELIVERY_BINDING_V1 {"unknown":true,',
        )
    )
    assert inspect_delivery_launcher_contract(root)["ready"] is False
    with pytest.raises(ValueError, match="not a valid SciPlot launcher"):
        resolve_delivery_target(launcher)
