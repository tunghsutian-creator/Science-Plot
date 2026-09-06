from __future__ import annotations

import json

import pytest

from sciplot_core.cli.parsers import build_parser
from sciplot_core.cli.dispatch import project_revision as command


def _args(*values: str):
    return build_parser().parse_args(["studio", *values, "--json"])


def test_revision_cli_requires_a_preview_action_and_rejects_mixed_export(tmp_path):
    with pytest.raises(ValueError, match="require a revision"):
        command.dispatch_project_revision(_args("--worksheet", "Sheet2"))
    with pytest.raises(ValueError, match="separately"):
        command.dispatch_project_revision(
            _args(str(tmp_path), "--recover-delivery", "--export", "pdf")
        )


def test_revision_cli_saves_review_and_applies_exact_preview(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "plot_request.json").write_text("{}")
    source, output = tmp_path / "new.csv", tmp_path / "preview.json"
    source.write_text("raw")
    preview = {
        "kind": "sciplot_project_source_update",
        "status": "ready",
        "project": str(project),
        "source": str(source),
        "changes": {"a": 1},
    }
    monkeypatch.setattr(
        command, "preview_project_source_update", lambda p, s, worksheet: preview
    )
    assert (
        command.dispatch_project_revision(
            _args(
                str(project),
                "--update-source",
                str(source),
                "--preview-out",
                str(output),
            )
        )
        == 0
    )
    assert json.loads(output.read_text()) == preview
    assert json.loads(capsys.readouterr().out) == preview
    seen = []
    monkeypatch.setattr(
        command,
        "apply_project_source_update",
        lambda p, v: seen.append((p, v)) or {"status": "updated"},
    )
    assert (
        command.dispatch_project_revision(
            _args(str(project), "--apply-revision", str(output))
        )
        == 0
    )
    assert seen == [(project, preview)]


def test_revision_cli_never_overwrites_existing_preview_or_source(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "plot_request.json").write_text("{}")
    source = tmp_path / "new.csv"
    source.write_text("raw")
    monkeypatch.setattr(
        command, "preview_project_source_update", lambda *a, **kw: {"status": "ready"}
    )
    with pytest.raises(ValueError, match="new preview JSON"):
        command.dispatch_project_revision(
            _args(
                str(project),
                "--update-source",
                str(source),
                "--preview-out",
                str(source),
            )
        )
    assert source.read_text() == "raw"


def test_recovery_cli_rejects_unassociated_portable_target(tmp_path):
    with pytest.raises(ValueError, match="still-associated"):
        command.revision_project(tmp_path)
