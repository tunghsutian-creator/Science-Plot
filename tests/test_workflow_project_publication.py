"""Concrete workflow finalization can prepare a project without active writes."""

from pathlib import Path

import pytest

from sciplot_core.policy import DEFAULT_LAYOUT_POLICY
from sciplot_core.workflow import request_publish


def finalize(output: Path, request: Path, **options):
    manifest = {"result": {}, "figures": [], "qa": {}, "request": {},
                "output": str(output), "created_at": "2026-10-25T20:00:00Z"}
    request_publish._finalize_request_manifest(manifest, request_path=request,
        request={}, input_path=request.parent / "source.csv", raw_archive={},
        study_model={}, semantic={}, layout_policy=DEFAULT_LAYOUT_POLICY,
        output_dir=output, qa={}, completed_figure_plan=None, **options)
    return manifest


def test_private_workflow_finalization_keeps_visible_delivery_and_project_untouched(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    request = project / "plot_request.json"
    request.write_bytes(b'{"input":"source.csv"}')
    delivery = tmp_path / "visible"
    delivery.mkdir()
    manual = delivery / "manual.vsz"
    manual.write_bytes(b"last user native revision")
    original = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (request, manual)}
    output = tmp_path / "private-run"
    output.mkdir()
    stage = tmp_path / "private-delivery"
    def reject_active(*args, **kwargs):
        raise AssertionError("A private workflow must not invoke an active publication owner")
    monkeypatch.setattr(request_publish, "build_delivery_package", reject_active)
    monkeypatch.setattr(request_publish, "_update_intake_project_after_run", reject_active)
    result = finalize(output, request, staged_delivery=(stage, delivery), update_project=False)
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in original} == original
    assert sorted(path.name for path in project.iterdir()) == ["plot_request.json"]
    assert sorted(path.name for path in delivery.iterdir()) == ["manual.vsz"]
    assert (output / "manifest.json").is_file()
    assert (output / "one_step_status.json").is_file()
    assert stage.is_dir()
    assert result["delivery_package"]["complete"] is False
    assert result["ready_to_use"] is False


@pytest.mark.parametrize("nested", [False, True], ids=["same-root", "nested-in-active-root"])
def test_private_delivery_refuses_active_destination_before_package_creation(tmp_path, monkeypatch, nested):
    output = tmp_path / "private-run"
    output.mkdir()
    delivery = tmp_path / "visible"
    delivery.mkdir()
    marker = delivery / "manual.vsz"
    marker.write_bytes(b"user revision")
    stage = delivery / "candidate" if nested else delivery
    with pytest.raises(ValueError, match="outside its active destination"):
        finalize(output, tmp_path / "plot_request.json", staged_delivery=(stage, delivery), update_project=False)
    assert marker.read_bytes() == b"user revision"
    assert sorted(path.name for path in delivery.iterdir()) == ["manual.vsz"]
