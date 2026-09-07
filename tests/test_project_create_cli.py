from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.cli.dispatch import project_create as command
from sciplot_core.studio_core import project_creation as service
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.plan_preview import build_plan_preview


def _source(root: Path) -> Path:
    source = root / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n450,2\n500,3\n")
    return source


def _args(root: Path) -> Namespace:
    source = _source(root)
    plan = build_plan_preview(source, request={"rule_id": "uvvis_spectrum", "template": "curve"})
    assert plan["status"] == "planned", plan
    expected = root / "plan.json"
    expected.write_text(json.dumps(plan))
    return Namespace(target=source, expected_plan=expected, out=root / "Visible", json=True)


def _inventory(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): file_sha256(path)
            for path in root.rglob("*") if path.is_file()}


def _studio_payload() -> dict:
    return {
        "project_dir": "/managed", "document": "/managed/studio/document.vsz",
        "request": "/managed/plot_request.json",
        "studio_run": {"state": "ready", "ready_to_use": True,
                       "manifest": "/managed/runs/studio_001/manifest.json",
                       "delivery_package": {"path": "/Visible", "complete": True}},
    }


def _stub(monkeypatch, payload=None):
    payload = payload or _studio_payload()
    calls = []
    def prepare(*args, **kwargs):
        calls.append((args, kwargs))
        return payload
    monkeypatch.setattr(service, "prepare_studio_document", prepare)
    monkeypatch.setattr(service, "export_project_document", lambda **kwargs:
                        SimpleNamespace(run_payload=payload["studio_run"],
                                        ready_to_use=payload["studio_run"]["ready_to_use"]))
    return calls


def test_create_uses_shared_preparation_and_publication_once(tmp_path, monkeypatch, capsys):
    args = _args(tmp_path)
    calls = _stub(monkeypatch)
    assert command.dispatch_project_create(args) == 0
    layout = resolve_user_output_layout(args.target, requested_delivery_root=args.out)
    assert calls == [((args.target,), {
        "output_root": layout.workspace_root / "projects", "delivery_root": layout.delivery_root,
        "rule_id": "uvvis_spectrum", "template": "curve",
    })]
    assert json.loads(capsys.readouterr().out)["status"] == "created"


def test_shared_creation_has_no_protocol_stdout(tmp_path, monkeypatch, capsys):
    args = _args(tmp_path)
    _stub(monkeypatch)
    result = service.create_project(args.target, expected_plan=json.loads(args.expected_plan.read_text()),
                                    output_dir=args.out)
    assert result["studio_run"]["ready_to_use"] is True
    assert capsys.readouterr().out == ""


def test_source_changed_during_preparation_is_not_published(tmp_path, monkeypatch):
    args = _args(tmp_path)
    def prepare(*a, **kw):
        args.target.write_text(args.target.read_text().replace("450,2", "450,99"))
        return _studio_payload()
    monkeypatch.setattr(service, "prepare_studio_document", prepare)
    monkeypatch.setattr(service, "export_project_document", lambda **kw: pytest.fail("changed source published"))
    with pytest.raises(ValueError, match="Source changed during project"):
        command.dispatch_project_create(args)


def test_stale_expected_plan_creates_no_outputs_or_locks(tmp_path, monkeypatch):
    args = _args(tmp_path)
    args.target.write_text(args.target.read_text().replace("450,2", "450,22"))
    before = _inventory(tmp_path)
    monkeypatch.setattr(service, "prepare_studio_document", lambda *a, **k: pytest.fail("stale plan reached Studio"))
    with pytest.raises(ValueError, match="Source changed"):
        command.dispatch_project_create(args)
    assert _inventory(tmp_path) == before
    assert not (tmp_path / ".sciplot").exists()


@pytest.mark.parametrize("existing", ["visible", "workspace"])
def test_existing_output_or_workspace_is_preserved_before_runtime_allocation(tmp_path, monkeypatch, existing):
    args = _args(tmp_path)
    layout = resolve_user_output_layout(args.target, requested_delivery_root=args.out)
    path = layout.delivery_root if existing == "visible" else layout.workspace_root
    path.mkdir(parents=True)
    (path / "keep.txt").write_text("existing user evidence")
    before = _inventory(tmp_path)
    monkeypatch.setattr(service, "prepare_studio_document", lambda *a, **k: pytest.fail("existing output reached Studio"))
    with pytest.raises(ValueError, match="requires a new"):
        command.dispatch_project_create(args)
    assert _inventory(tmp_path) == before


def test_create_rechecks_output_after_obtaining_its_path_lease(tmp_path, monkeypatch):
    args = _args(tmp_path)
    @contextmanager
    def raced_lease(project):
        args.out.mkdir()
        (args.out / "keep.txt").write_text("concurrent owner")
        yield
    monkeypatch.setattr(service, "external_project_session", raced_lease)
    monkeypatch.setattr(service, "prepare_studio_document", lambda *a, **k: pytest.fail("concurrent output reached Studio"))
    with pytest.raises(ValueError, match="requires a new"):
        command.dispatch_project_create(args)
    assert (args.out / "keep.txt").read_text() == "concurrent owner"


def test_creation_stdout_is_compact_and_points_to_full_manifest(tmp_path, monkeypatch, capsys):
    args = _args(tmp_path)
    payload = _studio_payload()
    payload["studio"] = {"result": {"series": [{"x_values": list(range(10000))}]}}
    payload["studio_run"]["qa"] = {"internal_arrays": list(range(10000))}
    payload["figure_set"] = {"primary_figure_id": "curve", "figures": [{
        "figure_id": "curve", "title": "Measured curve", "document": payload["document"],
        "resolved_figure_task": {"scientific_values": list(range(10000))},
    }]}
    payload["studio_run"]["delivery_package"]["figures"] = [{
        "figure_id": "curve", "format": "pdf", "path": "/Visible/figures/curve.pdf",
        "internal_array": list(range(10000)),
    }]
    _stub(monkeypatch, payload)
    assert command.dispatch_project_create(args) == 0
    stdout = capsys.readouterr().out
    result = json.loads(stdout)
    assert len(stdout.encode()) < 15000
    assert result["kind"] == "sciplot_project_creation_result" and result["status"] == "created"
    assert result["studio_run"]["manifest"] == payload["studio_run"]["manifest"]
    assert result["figures"][0]["exports"] == [{"format": "pdf", "path": "/Visible/figures/curve.pdf"}]
    assert all(key not in stdout for key in ("x_values", "internal_arrays", "scientific_values", "resolved_figure_task"))


def test_creation_failure_retains_reason_and_never_returns_success(tmp_path, monkeypatch, capsys):
    args = _args(tmp_path)
    payload = _studio_payload()
    payload["studio_run"].update({"state": "failed", "ready_to_use": False,
                                 "failure_stage": "quality_or_delivery_gate",
                                 "failure_reason": "Current artifact QA failed."})
    _stub(monkeypatch, payload)
    assert command.dispatch_project_create(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked"
    assert result["studio_run"]["ready_to_use"] is False
    assert result["studio_run"]["failure_reason"] == "Current artifact QA failed."


def _cli(*arguments: object) -> dict:
    completed = subprocess.run(
        [str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, arguments), "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.comprehensive
def test_real_public_create_returns_a_resumable_native_project(tmp_path):
    source = _source(tmp_path)
    original = file_sha256(source)
    plan = _cli("plan", source, "--rule", "uvvis_spectrum", "--template", "curve")
    assert plan["status"] == "planned"
    expected = tmp_path / "expected-plan.json"
    expected.write_text(json.dumps(plan))
    visible = tmp_path / "Visible"
    created = _cli(
        "project", "create", source, "--expected-plan", expected, "--out", visible
    )
    assert created["studio_run"]["ready_to_use"] is True, created
    project = Path(created["project_dir"])
    assert Path(created["document"]) == project / "studio/document.vsz"
    assert (project / "studio/spec.json").is_file()
    assert (project / "studio/figure_set.json").is_file()
    assert len(list((project / "runs").glob("studio_*"))) == 1
    before = _inventory(tmp_path)
    inspected = _cli("project", "inspect", project)
    assert inspected["project"] == str(project)
    assert inspected["qa"]["current"] is True
    assert inspected["delivery"]["current"] is True
    details = _cli(
        "project", "inspect", visible, "--figure", inspected["primary_figure_id"]
    )
    assert details["selected_figure"]["objects"]["/page1/graph1/x"]["editable_fields"]
    assert _inventory(tmp_path) == before
    assert file_sha256(source) == original
