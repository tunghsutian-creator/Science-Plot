from __future__ import annotations

import json
from contextlib import contextmanager
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
    monkeypatch.setattr(paper, "capture_publication", lambda selection: {"fixture": selection["project"]})
    monkeypatch.setattr(paper, "assert_publication_current", lambda *_: None)
    monkeypatch.setattr("sciplot_core.task_paper_status.assert_publication_current", lambda *_: None)
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


@pytest.mark.parametrize("drift", ["raw", "native", "semantic_spec", "semantic_request"])
def test_inspection_preserves_frozen_selection_and_requires_review_of_changed_sources(case, drift):
    tmp, request, projects, sealed, _ = case
    completed = paper.start_paper(request, paper_dir=tmp / "task")
    record = (tmp / "task/paper.json").read_bytes()
    if drift == "raw":
        (tmp / "raw0.csv").write_text("x,y\n1,9\n")
    elif drift == "native":
        (projects[0] / "studio/document.vsz").write_text("later manual frame save")
    else:
        path = projects[0] / ("studio/spec.json" if drift == "semantic_spec" else "plot_request.json")
        changed = json.loads(path.read_text())
        changed["revision"] = "new_semantic_revision"
        path.write_text(json.dumps(changed))
    originals = {p: file_inventory(p) for p in [*projects, tmp / "raw0.csv", tmp / "raw1.csv"]}
    package = file_inventory(Path(request["out"]))
    inspected = paper.inspect_paper(tmp / "task")
    assert inspected["status"] == "blocked"
    assert inspected["recorded_status"] == "complete"
    assert inspected["ready_to_use"] is False
    assert inspected["selection_scope"] == "frozen_selected_versions"
    assert inspected["result_scope"] == "historical_frozen_delivery"
    assert inspected["blocker"]["reason_code"] == "paper_selection_changed"
    assert inspected["next_step"]["action"] == "review_changed_sources_and_start_new_selection"
    assert inspected["repair"]["new_output_required"] is True
    assert inspected["repair"]["automatic_overwrite"] is False
    assert [i["current"] for i in inspected["current_selections"]] == [False, True]
    assert inspected["delivery_current"] is True
    assert inspected["items"] == completed["items"]
    assert inspected["result"] == completed["result"]
    assert (tmp / "task/paper.json").read_bytes() == record
    assert all(file_inventory(p) == before for p, before in originals.items())
    assert file_inventory(Path(request["out"])) == package
    assert sealed == ["001_Fig1", "002_Fig2"]


@pytest.mark.parametrize("drift", ["bytes", "extra_member", "missing_member"])
def test_completed_paper_inspection_blocks_changed_delivery_without_overwrite_or_receipt_mutation(case, drift):
    tmp, request, projects, sealed, _ = case
    completed = paper.start_paper(request, paper_dir=tmp / "task")
    record = (tmp / "task/paper.json").read_bytes()
    out = Path(request["out"])
    if drift == "bytes":
        (out / "selected").write_text("owner changed delivered frame")
    elif drift == "extra_member":
        (out / "foreign_figure").write_text("unselected figure")
    else:
        (out / "selected").unlink()
    package = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    originals = {p: file_inventory(p) for p in [*projects, tmp / "raw0.csv", tmp / "raw1.csv"]}
    inspected = paper.inspect_paper(tmp / "task")
    assert inspected["status"] == "blocked"
    assert inspected["recorded_status"] == "complete"
    assert inspected["ready_to_use"] is False
    assert inspected["delivery_current"] is False
    assert inspected["source_versions_current"] is True
    assert inspected["blocker"]["reason_code"] == "paper_delivery_changed"
    assert inspected["next_step"]["action"] == "preserve_changed_package_and_start_new_selection"
    assert inspected["repair"]["new_output_required"] is True
    assert inspected["repair"]["automatic_overwrite"] is False
    assert inspected["items"] == completed["items"]
    assert inspected["result"] == completed["result"]
    assert (tmp / "task/paper.json").read_bytes() == record
    assert all(file_inventory(p) == before for p, before in originals.items())
    assert {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()} == package
    assert sealed == ["001_Fig1", "002_Fig2"]


def test_completed_unchanged_paper_inspection_can_offer_current_frozen_delivery(case):
    tmp, request, _, _, _ = case
    completed = paper.start_paper(request, paper_dir=tmp / "task")
    record = (tmp / "task/paper.json").read_bytes()
    inspected = paper.inspect_paper(tmp / "task")
    assert inspected["status"] == inspected["recorded_status"] == "complete"
    assert inspected["ready_to_use"] is True
    assert inspected["source_versions_current"] is inspected["delivery_current"] is True
    assert inspected["items"] == completed["items"]
    assert inspected["next_step"]["action"] == "review_selected_exports_and_deliver"
    assert (tmp / "task/paper.json").read_bytes() == record


@pytest.mark.parametrize("entry", ["start", "resume"])
@pytest.mark.parametrize("drift", ["source", "native", "delivery"])
def test_completed_paper_replay_blocks_drift_with_the_same_read_only_inspection(case, monkeypatch, entry, drift):
    tmp, request, projects, sealed, _ = case
    completed = paper.start_paper(request, paper_dir=tmp / "task")
    record = (tmp / "task/paper.json").read_bytes()
    target = {"source": tmp / "raw0.csv", "native": projects[0] / "studio/document.vsz",
              "delivery": Path(request["out"]) / "selected"}[drift]
    target.write_text("later owner revision")
    protected = [*projects, tmp / "raw0.csv", tmp / "raw1.csv", Path(request["out"])]
    before = {path: file_inventory(path) for path in protected}
    expected = paper.inspect_paper(tmp / "task")
    lease_depth = 0

    @contextmanager
    def existing_lease(root):
        nonlocal lease_depth
        lease_depth += 1
        assert lease_depth == 1, "A currentness projection cannot acquire a nested lease."
        try:
            yield
        finally:
            lease_depth -= 1

    monkeypatch.setattr(paper, "external_project_session", existing_lease)
    monkeypatch.setattr(paper, "_run", lambda *args: pytest.fail("A completed replay cannot execute or write."))
    replay = (paper.start_paper(request, paper_dir=tmp / "task") if entry == "start"
              else paper.resume_paper(tmp / "task"))
    assert replay == expected
    assert replay["status"] == "blocked" and replay["ready_to_use"] is False
    assert replay["recorded_status"] == "complete"
    assert replay["blocker"]["reason_code"] == ("paper_delivery_changed" if drift == "delivery" else "paper_selection_changed")
    assert replay["next_step"]["action"] != "review_selected_exports_and_deliver"
    assert replay["repair"]["automatic_overwrite"] is False
    assert replay["items"] == completed["items"] and replay["result"] == completed["result"]
    assert (tmp / "task/paper.json").read_bytes() == record
    assert all(file_inventory(path) == inventory for path, inventory in before.items())
    assert sealed == ["001_Fig1", "002_Fig2"] and lease_depth == 0


@pytest.mark.parametrize("entry", ["start", "resume"])
def test_completed_paper_lost_reply_replay_returns_current_delivery_without_execution_or_write(case, monkeypatch, entry):
    tmp, request, projects, sealed, _ = case
    completed = paper.start_paper(request, paper_dir=tmp / "task")
    record = (tmp / "task/paper.json").read_bytes()
    protected = [*projects, tmp / "raw0.csv", tmp / "raw1.csv", Path(request["out"])]
    before = {path: file_inventory(path) for path in protected}
    expected = paper.inspect_paper(tmp / "task")
    monkeypatch.setattr(paper, "_run", lambda *args: pytest.fail("A completed replay cannot execute or write."))
    replay = (paper.start_paper(request, paper_dir=tmp / "task") if entry == "start"
              else paper.resume_paper(tmp / "task"))
    assert replay == expected
    assert replay["status"] == "complete" and replay["ready_to_use"] is True
    assert replay["items"] == completed["items"] and replay["result"] == completed["result"]
    assert replay["next_step"]["action"] == "review_selected_exports_and_deliver"
    assert (tmp / "task/paper.json").read_bytes() == record
    assert all(file_inventory(path) == inventory for path, inventory in before.items())
    assert sealed == ["001_Fig1", "002_Fig2"]
