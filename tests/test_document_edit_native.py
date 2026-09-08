from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
import subprocess
from time import perf_counter
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.document_edit_state import edit_state, preview_identity
from sciplot_core.studio_core.project_session import ProjectSessionLease


def _cli(*arguments, succeeds=True):
    result = subprocess.run(
        [str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, arguments), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert (result.returncode == 0) is succeeds, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_external_native_edit_preview_apply_export_and_cold_resume(tmp_path, monkeypatch):
    source = tmp_path / "UVvis.csv"
    source.write_text(
        "Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
        "A,A,B,B\n400,1,400,2\n450,2,450,3\n500,3,500,4\n",
        encoding="utf-8",
    )
    original_source = source.read_bytes()
    visible = tmp_path / "UVvis_SciPlot"
    created = _cli(
        "studio",
        source,
        "--out",
        visible,
        "--rule",
        "uvvis_spectrum",
        "--export",
        "pdf,tiff_300",
    )
    project, document = Path(created["project_dir"]), Path(created["document"])
    before = edit_state(project)
    old_document = document.read_bytes()
    summary = _cli("project", "inspect", visible)
    figure = summary["primary_figure_id"]
    detail = _cli("project", "inspect", project, "--figure", figure, "--full")
    objects = detail["selected_figure"]["objects"]
    operations = []
    for object_path, suffix, new in (("/page1/graph1/x", "/Label/size", "9pt"),):
        field = next(
            f
            for f in objects[object_path]["editable_fields"]
            if f["setting_path"].endswith(suffix)
        )
        operations.append(
            {
                "object_path": object_path,
                "setting_path": field["setting_path"],
                "expected_value": field["current_value"],
                "value": new,
            }
        )
    curve_path, curve = next(
        (p, w)
        for p, w in objects.items()
        if w["type"] == "xy"
        and any(
            f["setting_path"].endswith("/PlotLine/color") for f in w["editable_fields"]
        )
    )
    for suffix, new in (("/PlotLine/color", "#A020F0"), ("/PlotLine/width", "0.6pt")):
        field = next(
            f for f in curve["editable_fields"] if f["setting_path"].endswith(suffix)
        )
        operations.append(
            {
                "object_path": curve_path,
                "setting_path": field["setting_path"],
                "expected_value": field["current_value"],
                "value": new,
            }
        )
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps(operations))
    current = _cli(
        "project", "preview", project, "--figure", figure, "--out", tmp_path / "current"
    )
    review = _cli(
        "project",
        "edit-preview",
        project,
        "--figure",
        figure,
        "--changes",
        changes,
        "--out",
        tmp_path / "edit",
        "--expected-document",
        file_sha256(document),
        "--full",
    )
    assert review["scientific_audit"]["status"] == "passed"
    assert current["preview"]["sha256"] != review["preview"]["sha256"]
    assert edit_state(project) == before

    # The public apply cannot be made to install arbitrary, self-rehashed edits.
    forged = json.loads(json.dumps(review))
    forged.pop("review_path")
    forged["changes"][0]["setting_path"] = "/page1/graph1/x/label"
    forged["changes"][0]["expected_value"] = objects["/page1/graph1/x"]["settings"][
        "label"
    ]
    forged["changes"][0]["value"] = "Wrong scientific axis"
    forged["operation_id"] = preview_identity(forged)
    with pytest.raises(
        ValueError,
        match="outside the advertised safe setting catalog",
    ):
        apply_document_edit(project, forged)
    assert edit_state(project) == before

    # A clean writable native session is still an overwrite risk.
    lease = ProjectSessionLease(project, native=True)
    try:
        blocked = _cli(
            "project",
            "edit-apply",
            project,
            "--preview",
            review["review_path"],
            succeeds=False,
        )
        assert "writable Veusz session" in str(blocked)
    finally:
        lease.close()
    assert edit_state(project) == before
    # Exercise the same public CLI entry in this process so the native launches
    # are observable; all other CLI calls still start a fresh process.
    from sciplot_core.cli import main
    native_commands = []
    original_run = subprocess.run
    def observed_run(command, *args, **kwargs):
        if "sciplot_core.veusz_worker" in command:
            native_commands.append(command[3])
        return original_run(command, *args, **kwargs)
    output = StringIO()
    started = perf_counter()
    with monkeypatch.context() as patch, redirect_stdout(output):
        patch.setattr(subprocess, "run", observed_run)
        assert main(["project", "edit-apply", str(project), "--preview", review["review_path"], "--json"]) == 0
    elapsed = perf_counter() - started
    applied = json.loads(output.getvalue())
    assert native_commands == ["edit-document"]
    (tmp_path / "apply_measurement.json").write_text(json.dumps({
        "worker_starts": len(native_commands), "commands": native_commands, "elapsed_seconds": elapsed,
    }))
    assert applied["status"] == "applied"
    assert applied["export_required"] is True and applied["ready_to_use"] is False
    assert Path(applied["archive"]).read_bytes() == old_document
    expected = {
        **before,
        "project_files": {
            **before["project_files"],
            "studio/document.vsz": file_sha256(document),
        },
    }
    assert edit_state(project) == expected
    first_hash = file_sha256(document)
    assert (
        _cli("project", "edit-apply", project, "--preview", review["review_path"])[
            "status"
        ]
        == "already_applied"
    )
    assert file_sha256(document) == first_hash
    assert (
        _cli(
            "project", "operation", project, "--operation-id", applied["operation_id"]
        )["result_is_current"]
        is True
    )
    stale = _cli("project", "inspect", project)
    assert stale["qa"]["current"] is False and stale["delivery"]["current"] is False
    exported = _cli("studio", project, "--export", "pdf,tiff_300")
    assert exported["studio_run"]["ready_to_use"] is True
    assert file_sha256(document) == first_hash
    resumed = _cli("project", "inspect", visible, "--figure", figure, "--full")
    assert resumed["qa"]["current"] is True and resumed["delivery"]["current"] is True
    assert (
        resumed["selected_figure"]["objects"]["/page1/graph1/x"]["settings"][
            "Label/size"
        ]
        == "9pt"
    )
    assert source.read_bytes() == original_source
