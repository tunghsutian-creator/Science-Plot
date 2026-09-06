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
import sciplot_core.studio_core.studio_prepare as preparation
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
    calls = []

    def reuse(**kwargs):
        assert kwargs["document_path"] == canonical
        return {
            "mode": "project",
            "project_dir": str(project),
            "request": str(project / "plot_request.json"),
            "document": str(canonical),
        }

    def forbidden(**kwargs):
        raise AssertionError("continuing a delivery must never regenerate its source")

    monkeypatch.setattr(preparation, "reuse_existing_studio_document", reuse)
    monkeypatch.setattr(preparation, "generate_studio_document", forbidden)
    prepared = prepare_studio_document(launcher)
    assert Path(prepared["document"]) == canonical
    canonical.write_bytes(b"edited in the live managed document")

    def export(document, *, formats):
        calls.append(("export", document))
        assert document.read_bytes() == b"edited in the live managed document"
        return {"exports": [], "document_sha256": existing_file_sha256(document)}

    def publish(**kwargs):
        calls.append(("publish", kwargs["document_path"]))
        assert kwargs["project_dir"] == project
        assert kwargs["request_path"] == project / "plot_request.json"
        assert kwargs["export_document_sha256"] == existing_file_sha256(canonical)
        return {"ready_to_use": True, "exports": [], "scope": "project_delivery"}

    monkeypatch.setattr(command, "maybe_reexec_with_qt_runtime", lambda *args: None)
    monkeypatch.setattr(command, "export_studio_document", export)
    monkeypatch.setattr(command, "publish_studio_export_run", publish)
    assert (
        command.run_studio_command(
            target=launcher, export="pdf,tiff_300", json_output=True
        )
        == 0
    )
    assert calls == [("export", canonical), ("publish", canonical)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["studio_run"]["ready_to_use"] is True
    assert "standalone_export" not in payload
    assert (root / "project" / "primary.vsz").read_bytes() == b"canonical Veusz project"


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
