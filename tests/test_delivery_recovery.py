from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from sciplot_core.figure_plan import FigureTask, ResolvedFigurePlan
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.launchers.delivery_binding import DeliveryBinding
from sciplot_core.launchers.delivery_launcher import write_delivery_launcher
from sciplot_core.studio_core import delivery_recovery as recovery
from sciplot_core.studio_core import delivery_recovery_state as state


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def recoverable(tmp_path: Path, monkeypatch):
    project = tmp_path / "managed"
    visible = tmp_path / "visible"
    for path in (
        project / "raw",
        project / "source",
        project / "studio",
        visible / "project",
    ):
        path.mkdir(parents=True)
    source = project / "source" / "sample.csv"
    raw = project / "raw" / "sample.csv"
    source.write_bytes(b"x,y\n1,2\n2,3\n")
    shutil.copy2(source, raw)
    document = project / "studio" / "document.vsz"
    document.write_bytes(b"baseline native document")
    candidate = visible / "project" / "figure.vsz"
    candidate.write_bytes(b"edited native document")
    task = FigureTask("curve", 1, "Curve", "x", "y", "curve", "curve", "curve")
    plan = ResolvedFigurePlan.planned(
        rule_id="dsc_curve",
        selection_policy="single",
        primary_figure_id="curve",
        tasks=(task,),
        source_sha256=source_tree_sha256(project / "source"),
    )
    request = {
        "input": str(project / "source"),
        "delivery_output": str(visible),
        "resolved_figure_plan": plan.to_payload(),
        "study_model": {
            "samples": [
                {
                    "replicates": [
                        {
                            "source_file": {
                                "raw_path": str(raw),
                                "sha256": file_sha256(raw),
                            }
                        }
                    ]
                }
            ]
        },
    }
    _json(project / "plot_request.json", request)
    _json(
        project / "studio" / "spec.json",
        {
            "series": [
                {
                    "source_artifacts": [
                        {"path": str(source), "sha256": file_sha256(source)}
                    ]
                }
            ]
        },
    )
    _json(
        project / "studio" / "figure_set.json",
        {"figures": [{"document": str(document)}]},
    )
    baseline = file_sha256(document)
    write_delivery_launcher(
        visible,
        binding=DeliveryBinding(
            root=str(visible),
            request=str(project / "plot_request.json"),
            source=str(project / "source"),
            primary=candidate.name,
            documents=((candidate.name, baseline),),
        ),
    )
    run = project / "runs" / "studio_001"
    (run / "raw").mkdir(parents=True)
    shutil.copytree(project / "source", run / "raw" / "source")
    shutil.copytree(project / "studio", run / "studio")
    _json(run / "request_snapshot.json", request)
    _json(
        run / "manifest.json",
        {
            "ready_to_use": True,
            "request_path": str(project / "plot_request.json"),
            "request": request,
            "raw_archive": {"path": str(run / "raw" / "source")},
            "delivery_package": {
                "complete": True,
                "path": str(visible),
                "project_documents": [
                    {
                        "path": str(candidate),
                        "source": str(run / "studio" / "document.vsz"),
                        "delivery_sha256": baseline,
                        "source_sha256": baseline,
                    }
                ],
            },
        },
    )
    # Recovery's filesystem and evidence gates remain real. Native scientific
    # auditing and the existing registry validator have separate real coverage.
    monkeypatch.setattr(
        state, "_read_studio_figure_set", lambda *a, **k: {"figures": [{}]}
    )
    monkeypatch.setattr(
        recovery,
        "_audit_candidate",
        lambda *a: {"status": "passed", "unit_count": 1, "prepared_unit_count": 1},
    )
    return project, document, candidate


def test_recovery_archives_original_and_preserves_visible_bytes(recoverable):
    project, document, candidate = recoverable
    original, visible = document.read_bytes(), candidate.read_bytes()
    before = {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file() and ".sciplot_store" not in p.relative_to(project).parts}
    preview = recovery.preview_delivery_recovery(project)
    assert preview["status"] == "ready", preview
    assert before == {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file() and ".sciplot_store" not in p.relative_to(project).parts}
    result = recovery.apply_delivery_recovery(project, json.loads(json.dumps(preview)))
    assert result["status"] == "recovered"
    assert Path(result["archive"]).read_bytes() == original
    assert document.read_bytes() == candidate.read_bytes() == visible
    assert result["export_required"] is True


def test_recovery_holds_project_lock_during_audit_and_replacement(recoverable, monkeypatch):
    from sciplot_core.foundation.project_session_lease import ProjectSessionBusy, ProjectSessionLease
    from sciplot_core.project_store import state
    project, _, _ = recoverable
    preview = recovery.preview_delivery_recovery(project)
    boundary = state.boundary
    stages = []
    def checked(name):
        if name == "before_projection":
            with pytest.raises(ProjectSessionBusy):
                ProjectSessionLease(project, native=True)
            stages.append(name)
        boundary(name)
    monkeypatch.setattr(state, "boundary", checked)
    monkeypatch.setattr(recovery, "_audit_candidate", lambda *_args: pytest.fail("frozen recovery must not rerun native audit"))
    assert recovery.apply_delivery_recovery(project, preview)["status"] == "recovered"
    assert stages == ["before_projection"]
    with ProjectSessionLease(project, native=True):
        pass


@pytest.mark.parametrize(
    "changed",
    [
        "document",
        "candidate",
        "source",
        "raw",
        "request",
        "registry",
        "launcher",
        "evidence",
    ],
)
def test_changed_preview_inputs_cannot_be_adopted(recoverable, changed):
    project, document, candidate = recoverable
    preview = recovery.preview_delivery_recovery(project)
    assert preview["ready_to_apply"] is True
    paths = {
        "document": document,
        "candidate": candidate,
        "source": project / "source" / "sample.csv",
        "raw": project / "raw" / "sample.csv",
        "request": project / "plot_request.json",
        "registry": project / "studio" / "figure_set.json",
        "launcher": candidate.parent.parent / "Open_in_Veusz.command",
        "evidence": project / "runs" / "studio_001" / "manifest.json",
    }
    paths[changed].write_bytes(paths[changed].read_bytes() + b"\n ")
    before = document.read_bytes(), candidate.read_bytes()
    with pytest.raises(ValueError, match="stale or modified"):
        recovery.apply_delivery_recovery(project, preview)
    assert (document.read_bytes(), candidate.read_bytes()) == before
    assert not (project / ".recovery").exists()


def test_three_way_conflict_and_modified_caller_preview_fail_closed(recoverable):
    project, document, candidate = recoverable
    document.write_bytes(b"independent managed edit")
    preview = recovery.preview_delivery_recovery(project)
    assert preview["reason_code"] == "canonical_diverged"
    forged = deepcopy(preview)
    forged.update(status="ready", ready_to_apply=True)
    with pytest.raises(ValueError, match="stale or modified"):
        recovery.apply_delivery_recovery(project, forged)
    assert document.read_bytes() == b"independent managed edit"
    assert candidate.read_bytes() == b"edited native document"
    assert not (project / ".recovery").exists()


def test_recovery_only_accepts_bound_primary_and_unchanged_sources(recoverable):
    project, _, candidate = recoverable
    wrong = project / "other.vsz"
    wrong.write_bytes(candidate.read_bytes())
    assert (
        recovery.preview_delivery_recovery(project, wrong)["reason_code"]
        == "foreign_candidate"
    )
    raw = project / "raw" / "sample.csv"
    raw.write_bytes(b"changed raw source")
    assert (
        recovery.preview_delivery_recovery(project)["reason_code"]
        == "raw_source_changed"
    )
    assert not (project / ".recovery").exists()


@pytest.mark.parametrize("after_replace", ["before_head", "before_projection", "after_projection"])
def test_recovery_replacement_failure_preserves_both_versions(recoverable, monkeypatch, after_replace):
    from sciplot_core.project_store import state
    from sciplot_core.studio_core.project_command_scope import project_store
    project, document, candidate = recoverable
    preview = recovery.preview_delivery_recovery(project)
    before = document.read_bytes(), candidate.read_bytes()
    boundary = state.boundary
    def fail(name):
        if name == after_replace:
            raise OSError("injected replacement failure")
        boundary(name)
    monkeypatch.setattr(state, "boundary", fail)
    with pytest.raises(OSError, match="injected replacement failure"):
        recovery.apply_delivery_recovery(project, preview)
    assert candidate.read_bytes() == before[1]
    if after_replace != "after_projection":
        assert document.read_bytes() == before[0]
    assert not list(document.parent.glob(".document.delivery-*"))
    monkeypatch.setattr(state, "boundary", boundary)
    project_store(project).recover()
    result = recovery.apply_delivery_recovery(project, preview)
    assert document.read_bytes() == candidate.read_bytes() == before[1]
    assert Path(result["archive"]).read_bytes() == before[0]


def test_recovery_rejects_an_unbound_or_multiple_document_delivery(recoverable):
    project, document, candidate = recoverable
    root = candidate.parent.parent
    binding = DeliveryBinding(
        root=str(root),
        request=str(project / "plot_request.json"),
        source=str(project / "source"),
        primary=candidate.name,
        documents=((candidate.name, file_sha256(document)), ("other.vsz", "0" * 64)),
    )
    write_delivery_launcher(root, binding=binding)
    assert (
        recovery.preview_delivery_recovery(project)["reason_code"] == "multiple_figures"
    )
    binding = DeliveryBinding(
        root=str(root / "previous_location"),
        request=str(project / "plot_request.json"),
        source=str(project / "source"),
        primary=candidate.name,
        documents=((candidate.name, file_sha256(document)),),
    )
    write_delivery_launcher(root, binding=binding)
    assert (
        recovery.preview_delivery_recovery(project)["reason_code"] == "foreign_delivery"
    )
    assert not (project / ".recovery").exists()
