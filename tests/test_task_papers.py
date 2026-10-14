from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_contract import normalize_paper_request
from sciplot_core.task_paper_sources import capture_selection
from sciplot_core import task_papers as paper


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr("sciplot_core.task_paper_sources.native_link_sources", lambda document: [])
    projects = []
    for index in range(2):
        source = tmp_path / f"raw{index}.csv"
        source.write_text(f"x,y\n1,{index + 1}\n")
        project = tmp_path / f"project{index}"
        studio = project / "studio"
        studio.mkdir(parents=True)
        (project / "plot_request.json").write_text(json.dumps({"input": str(source)}))
        (studio / "document.vsz").write_text("saved native figure")
        (studio / "spec.json").write_text(json.dumps({"series": [{"source_artifacts": [
            {"path": str(source), "sha256": file_sha256(source)}]}]}))
        projects.append(project)
    request = {"version": 1, "title": "Selected paper", "out": str(tmp_path / "paper-delivery"),
               "items": [{"project": str(project), "figure_id": "primary", "label": f"Fig{index + 1}",
                          "expected_version": capture_selection(project, "primary")["version"]}
                         for index, project in enumerate(projects)]}
    sealed = []

    def seal(root, state, selection, item):
        sealed.append(item["stem"])
        attempt = root / "attempts" / item["stem"] / "attempt"
        attempt.mkdir(parents=True)
        (attempt / "artifact").write_bytes(b"frozen native output")
        item.update(status="sealed", attempt=str(attempt), files=file_inventory(attempt),
                    scientific_sha256="a" * 64, prepared_source_sha256="b" * 64, portable_native={})
        paper._save(root, state)

    def publish(root, state, *, checkpoint):
        out = Path(state["request"]["out"])
        out.mkdir()
        (out / "selected").write_text("paper")
        return {"path": str(out)}

    monkeypatch.setattr(paper, "_seal", seal)
    monkeypatch.setattr(paper, "publish_paper", publish)
    return tmp_path, request, projects, sealed, seal


@pytest.mark.parametrize("label", ["../Fig1", "Fig/1", "Fig\\1", "..", "a b", "-flag", "", "a" * 65])
def test_paper_labels_cannot_escape_or_ambiguous_filename(case, label):
    _, request, _, _, _ = case
    request["items"][0]["label"] = label
    with pytest.raises(TaskControlError, match="label"):
        normalize_paper_request(request)


def test_duplicate_labels_and_exact_figures_fail_before_allocation(case):
    tmp, request, _, _, _ = case
    request["items"][1]["label"] = "fIG1"
    with pytest.raises(TaskControlError) as caught:
        paper.start_paper(request, paper_dir=tmp / "task")
    assert caught.value.reason_code == "duplicate_paper_label"
    assert not (tmp / "task").exists()
    request["items"][1] = {**request["items"][0], "label": "Fig2"}
    with pytest.raises(TaskControlError) as caught:
        paper.start_paper(request, paper_dir=tmp / "task")
    assert caught.value.reason_code == "duplicate_paper_figure"


def test_exact_version_prevents_stale_native_selection(case):
    tmp, request, projects, _, _ = case
    (projects[0] / "studio/document.vsz").write_text("new manual save")
    with pytest.raises(TaskControlError) as caught:
        paper.start_paper(request, paper_dir=tmp / "task")
    assert caught.value.reason_code == "paper_selection_changed"
    assert not (tmp / "task").exists()


@pytest.mark.parametrize("target", ["existing", "project", "source", "task"])
def test_output_is_new_and_disjoint_from_source_project_and_receipt(case, target):
    tmp, request, projects, _, _ = case
    out = {"existing": tmp / "old", "project": projects[0], "source": tmp / "raw0.csv", "task": tmp / "task"}[target]
    if target == "existing":
        out.mkdir()
        (out / "user.txt").write_text("old")
    before = file_inventory(out) if out.exists() else None
    request["out"] = str(out)
    with pytest.raises((TaskControlError, ValueError)):
        paper.start_paper(request, paper_dir=tmp / "task")
    assert before is None or file_inventory(out) == before


def test_partial_failure_reuses_only_sealed_item_and_preserves_projects(case, monkeypatch):
    tmp, request, projects, sealed, real = case
    before = {p: file_inventory(p) for p in projects}

    def fail_second(root, state, selection, item):
        if item["stem"].startswith("002"):
            raise RuntimeError("injected second export failure")
        real(root, state, selection, item)

    monkeypatch.setattr(paper, "_seal", fail_second)
    failed = paper.start_paper(request, paper_dir=tmp / "task")
    assert failed["status"] == "blocked"
    assert [i["status"] for i in failed["items"]] == ["sealed", "pending"]
    assert not Path(request["out"]).exists()
    monkeypatch.setattr(paper, "_seal", real)
    complete = paper.resume_paper(tmp / "task")
    assert complete["status"] == "complete"
    assert sealed == ["001_Fig1", "002_Fig2"]
    assert all(file_inventory(p) == before[p] for p in projects)
    assert paper.resume_paper(tmp / "task")["status"] == "complete"
    assert sealed == ["001_Fig1", "002_Fig2"]


@pytest.mark.parametrize("drift", ["raw", "native", "spec", "stage", "unknown_stage_file"])
def test_retry_never_reuses_changed_source_or_native_or_stage(case, monkeypatch, drift):
    tmp, request, projects, sealed, real = case

    def fail_second(root, state, selection, item):
        if item["stem"].startswith("002"):
            raise RuntimeError("injected")
        real(root, state, selection, item)

    monkeypatch.setattr(paper, "_seal", fail_second)
    paper.start_paper(request, paper_dir=tmp / "task")
    state = paper._load(tmp / "task")
    paths = {"raw": tmp / "raw0.csv", "native": projects[0] / "studio/document.vsz",
             "spec": projects[0] / "studio/spec.json", "stage": Path(state["items"][0]["attempt"]) / "artifact",
             "unknown_stage_file": Path(state["items"][0]["attempt"]) / "foreign.txt"}
    path = paths[drift]
    path.write_bytes((path.read_bytes() if path.exists() else b"") + b" ")
    monkeypatch.setattr(paper, "_seal", real)
    blocked = paper.resume_paper(tmp / "task")
    assert blocked["status"] == "blocked"
    assert sealed == ["001_Fig1"]
    assert not Path(request["out"]).exists()


def test_request_order_and_label_cannot_change_after_checkpoint(case):
    tmp, request, _, _, _ = case
    paper.start_paper(request, paper_dir=tmp / "task")
    request["items"].reverse()
    with pytest.raises(TaskControlError) as caught:
        paper.start_paper(request, paper_dir=tmp / "task")
    assert caught.value.reason_code == "paper_already_exists"


def test_inspection_is_read_only_and_reports_current_evidence_separately(case):
    tmp, request, projects, sealed, _ = case
    paper.start_paper(request, paper_dir=tmp / "task")
    record = (tmp / "task/paper.json").read_bytes()
    (projects[0] / "studio/document.vsz").write_text("later save")
    inspected = paper.inspect_paper(tmp / "task")
    assert inspected["status"] == "complete"
    assert [i["current"] for i in inspected["current_selections"]] == [False, True]
    assert inspected["delivery_current"] is True
    assert (tmp / "task/paper.json").read_bytes() == record
    assert sealed == ["001_Fig1", "002_Fig2"]
