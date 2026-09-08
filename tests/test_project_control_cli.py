from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from sciplot_core.cli.dispatch import project as command
from sciplot_core.cli.parsers import build_parser
from sciplot_core.cli.dispatch.interfaces import dispatch_interfaces
from sciplot_core.studio_core.project_session import (
    ProjectSessionBusy,
    ProjectSessionLease,
)
from sciplot_core.studio_core.control_results import compact_result


@pytest.mark.parametrize("full", [False, True])
def test_cli_query_uses_shared_compact_projection_with_full_opt_in(tmp_path, monkeypatch, capsys, full):
    payload = {"kind": "sciplot_project_inspection", "ready_to_use": None,
               "source": {"current": None}, "selected_figure": {
                   "document_sha256": "a" * 64, "objects": {"/graph/series": {
                       "settings": {"key": "E3", "xData": "x_1", "irrelevant": list(range(100))},
                       "editable_fields": [{"setting_path": "/graph/series/PlotLine/color",
                                            "current_value": "#222222"}],
                   }}}}
    monkeypatch.setattr(command, "inspect_project", lambda *a, **k: payload)
    args = build_parser().parse_args(["project", "inspect", str(tmp_path), "--json",
                                     *(["--full"] if full else [])])
    assert command.dispatch_project_control(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == (payload if full else compact_result(payload))
    assert "settings" in payload["selected_figure"]["objects"]["/graph/series"]


@pytest.mark.parametrize("full", [False, True])
def test_cli_edit_preview_keeps_signed_state_in_saved_review(tmp_path, monkeypatch, capsys, full):
    path = tmp_path / "changes.json"
    path.write_text('[]')
    payload = {"kind": "sciplot_document_edit_preview", "status": "ready",
               "base_state": {"project_files": {"studio/document.vsz": "a" * 64}},
               "operation_id": "b" * 64, "review_path": str(tmp_path / "review.json"),
               "scientific_audit": {"status": "passed"}}
    monkeypatch.setattr(command, "preview_document_edit", lambda *a, **k: payload)
    args = build_parser().parse_args([
        "project", "edit-preview", str(tmp_path), "--changes", str(path),
        "--expected-document", "a" * 64, "--out", str(tmp_path / "preview"), "--json",
        *(["--full"] if full else []),
    ])
    assert command.dispatch_project_control(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert ("base_state" in result) is full
    assert result["review_path"] == payload["review_path"]
    assert result["operation_id"] == payload["operation_id"]
    assert "base_state" in payload


def test_inspect_dispatch_preserves_exact_target_and_scope(
    tmp_path, monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(
        command,
        "inspect_project",
        lambda path, **kw: (
            calls.append((path, kw)) or {"status": "ok", "ready_to_use": None}
        ),
    )
    args = build_parser().parse_args(
        [
            "project",
            "inspect",
            str(tmp_path),
            "--figure",
            "specific-id",
            "--object",
            "/page1/graph1/x",
            "--json",
        ]
    )
    assert command.dispatch_project_control(args) == 0
    assert calls == [
        (tmp_path, {"figure_id": "specific-id", "object_path": "/page1/graph1/x"})
    ]
    assert json.loads(capsys.readouterr().out)["ready_to_use"] is None


@pytest.mark.parametrize("contents", ["null", "{}", "[1]", '"changes"'])
def test_edit_preview_rejects_non_operation_payload_before_calling_service(
    tmp_path, monkeypatch, contents
):
    path = tmp_path / "changes.json"
    path.write_text(contents)
    monkeypatch.setattr(
        command,
        "preview_document_edit",
        lambda *a, **k: pytest.fail("invalid operations reached native service"),
    )
    args = build_parser().parse_args(
        [
            "project",
            "edit-preview",
            str(tmp_path),
            "--changes",
            str(path),
            "--expected-document",
            "a" * 64,
            "--out",
            str(tmp_path / "preview"),
            "--json",
        ]
    )
    with pytest.raises(ValueError, match="JSON list"):
        command.dispatch_project_control(args)


def test_edit_apply_loads_the_complete_receipt(tmp_path, monkeypatch, capsys):
    path = tmp_path / "edit-preview.json"
    review = {"kind": "sciplot_document_edit_preview", "operation_id": "f" * 64}
    path.write_text(json.dumps(review))
    calls = []
    monkeypatch.setattr(
        command,
        "apply_document_edit",
        lambda p, r: (
            calls.append((p, r))
            or {"status": "already_applied", "export_required": None}
        ),
    )
    args = build_parser().parse_args(
        ["project", "edit-apply", str(tmp_path), "--preview", str(path), "--json"]
    )
    assert command.dispatch_project_control(args) == 0
    assert calls == [(tmp_path, review)]
    assert json.loads(capsys.readouterr().out)["status"] == "already_applied"


def test_edit_preview_requires_a_saved_document_revision():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "project",
                "edit-preview",
                "project",
                "--changes",
                "changes.json",
                "--out",
                "preview",
            ]
        )


@pytest.mark.parametrize("flags", [["--export", "pdf"], ["--prepare-only"], ["--json"]])
def test_all_headless_studio_writes_exclude_native_sessions_without_loading_gui(
    tmp_path, monkeypatch, flags
):
    (tmp_path / "plot_request.json").write_text("{}")

    def forbidden():
        pytest.fail("headless Studio loaded GUI presentation")

    monkeypatch.setitem(
        sys.modules,
        "sciplot_gui.main_window_menu",
        SimpleNamespace(install_studio_window_presentation=forbidden),
    )
    args = build_parser().parse_args(["studio", str(tmp_path), *flags])
    lease = ProjectSessionLease(tmp_path, native=True)
    try:
        with pytest.raises(ProjectSessionBusy):
            dispatch_interfaces(args, [], serve_intake=lambda **_: None)
    finally:
        lease.close()
