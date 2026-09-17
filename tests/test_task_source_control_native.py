from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core import task_control, task_execution, task_source_execution
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.task_storage import load_task
from test_project_source_update_native import _files, _native, _source


def _cli(*args: object, code: int = 0) -> dict:
    result = subprocess.run(
        [str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == code, result.stdout + result.stderr
    return json.loads(result.stdout)


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value))
    return path


@pytest.mark.comprehensive
def test_killed_native_source_install_resumes_through_public_task(tmp_path):
    import sys
    from sciplot_core.veusz_runtime import veusz_worker_environment

    old_source, new_source = tmp_path / "old.csv", tmp_path / "new.csv"
    _source(old_source)
    _source(new_source, changed=True)
    created = task_control.start_task({"version": 1, "action": "create", "source": str(old_source),
                                      "rule_id": "uvvis_spectrum"}, task_dir=tmp_path / "create")
    assert created["status"] == "complete", created
    project = Path(created["project"])
    task = tmp_path / "update"
    review = task_control.start_task({"version": 1, "action": "update_source", "project": str(project),
                                      "source": str(new_source)}, task_dir=task)
    assert review["status"] == "needs_review", review
    code = """
import json, os, sys
from pathlib import Path
from sciplot_core.task_control import resume_task
project, task = map(Path, sys.argv[1:3])
replace = os.replace
def kill_after_archive(source, target):
    replace(source, target)
    if Path(source) == project / 'source' and '.source_update_history' in Path(target).parts:
        os._exit(91)
os.replace = kill_after_archive
resume_task(task, {'accept_source_update': True, 'expected_revision_id': sys.argv[3]})
"""
    killed = subprocess.run([sys.executable, "-c", code, str(project), str(task), review["revision_id"]],
                            env=veusz_worker_environment(), capture_output=True, text=True, timeout=60)
    assert killed.returncode == 91, killed.stdout + killed.stderr
    assert not (project / "source").exists()
    resumed = _cli("task", "resume", task, "--response", _write(tmp_path / "retry.json", {"retry": True}))
    assert resumed["status"] == "complete", resumed
    assert all(resumed["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    assert _native(project / "studio/document.vsz")["series"]["A"]["y"] == [8, 9, 10]
    history = project.parent / ".source_update_history" / project.name
    assert len(list(history.glob("*.rollback.json"))) == 1
    assert len(list(history.glob("*.interrupted"))) == 1


@pytest.mark.comprehensive
def test_public_source_update_reviews_native_images_recovers_and_exports_current_project(tmp_path, monkeypatch):
    old_source, new_source = tmp_path / "old_uvvis.csv", tmp_path / "new_uvvis.csv"
    _source(old_source)
    _source(new_source, changed=True)
    raw_before = old_source.read_bytes(), new_source.read_bytes()
    request, response = tmp_path / "request.json", tmp_path / "response.json"
    created = _cli("task", "start", "--request", _write(request, {
        "version": 1, "action": "create", "source": str(old_source),
        "rule_id": "uvvis_spectrum", "out": str(tmp_path / "UVvis_SciPlot"),
    }), "--task-dir", tmp_path / "create")
    assert created["status"] == "complete", created
    project = Path(created["project"])
    document = project / "studio/document.vsz"
    visible = Path(created["result"]["studio_run"]["delivery_package"]["path"])
    previous, old_visible = _files(project), _files(visible)
    _write(request, {"version": 1, "action": "update_source", "project": str(project), "source": str(new_source)})

    rejected_task = tmp_path / "reject_update"
    rejected_review = _cli("task", "start", "--request", request, "--task-dir", rejected_task)
    assert rejected_review["status"] == "needs_review", rejected_review
    state_bytes = (rejected_task / "task.json").read_bytes()
    stale = _cli("task", "resume", rejected_task, "--response", _write(response, {
        "accept_source_update": True, "expected_revision_id": "0" * 64,
    }), code=1)
    assert stale["reason_code"] == "stale_source_review", stale
    assert (rejected_task / "task.json").read_bytes() == state_bytes
    cancelled = _cli("task", "resume", rejected_task, "--response", _write(response, {
        "accept_source_update": False, "expected_revision_id": rejected_review["revision_id"],
    }))
    assert cancelled["status"] == "cancelled"
    assert _files(project) == previous and _files(visible) == old_visible

    task = tmp_path / "update"
    review = _cli("task", "start", "--request", request, "--task-dir", task)
    assert review["status"] == "needs_review", review
    assert {item["scope"] for item in review["previews"]} == {"before", "candidate"}
    images = {}
    for item in review["previews"]:
        path = Path(item["preview"]["path"])
        assert file_sha256(path) == item["preview"]["sha256"]
        with Image.open(path) as image:
            images[item["scope"]] = image.convert("RGB")
        assert min(images[item["scope"]].size) > 200
        assert images[item["scope"]].getextrema() != ((255, 255),) * 3
    assert images["before"].size == images["candidate"].size
    assert ImageChops.difference(images["before"], images["candidate"]).getbbox() is not None
    assert _files(project) == previous and _files(visible) == old_visible
    bound = json.loads(Path(review["preview"]["review_path"]).read_text())
    assert bound["source_update"]["changes"]["figures"][0]["sample_order_changed"] is True

    apply = task_source_execution.apply_source_update_review
    apply_calls = []

    def lose_first_reply(*args, **kwargs):
        result = apply(*args, **kwargs)
        apply_calls.append(result["status"])
        if len(apply_calls) == 1:
            raise OSError("injected lost source-update success reply")
        return result

    monkeypatch.setattr(task_source_execution, "apply_source_update_review", lose_first_reply)
    accepted = {"accept_source_update": True, "expected_revision_id": review["revision_id"]}
    lost = task_control.resume_task(task, accepted)
    assert lost["status"] == "blocked" and lost["phase"] == "applying", lost
    assert apply_calls == ["updated"]
    adopted = document.read_bytes()
    assert adopted != previous["studio/document.vsz"]
    assert _files(visible) == old_visible
    current = _native(document)
    assert list(current["series"]) == ["B", "A"]
    assert current["series"]["B"]["y"] == [9, 10, 11]
    assert current["series"]["A"]["y"] == [8, 9, 10]

    export = task_execution.export_project

    def fail_export(*args, **kwargs):
        raise OSError("injected export failure after source checkpoint")

    monkeypatch.setattr(task_execution, "export_project", fail_export)
    export_failed = task_control.resume_task(task, {"retry": True})
    assert export_failed["status"] == "blocked" and export_failed["phase"] == "exporting", export_failed
    assert apply_calls == ["updated", "already_applied"]
    saved = load_task(task)
    assert saved["source_update_outcome"]["status"] == "already_applied"
    archive = Path(saved["source_update_outcome"]["archive"])
    assert (archive / "studio/document.vsz").read_bytes() == previous["studio/document.vsz"]
    assert (archive / "studio/spec.json").read_bytes() == previous["studio/spec.json"]
    assert document.read_bytes() == adopted and _files(visible) == old_visible

    monkeypatch.setattr(task_execution, "export_project", export)
    monkeypatch.setattr(task_source_execution, "apply_source_update_review",
                        lambda *a, **k: pytest.fail("export retry must not reapply source"))
    complete = task_control.resume_task(task, {"retry": True})
    assert complete["status"] == "complete", complete
    assert complete["result"]["studio_run"]["ready_to_use"] is True
    assert complete["project"] == str(project) and document.read_bytes() == adopted
    inspected = _cli("task", "inspect", task)["current_project"]
    assert inspected["qa"]["current"] is True and inspected["delivery"]["current"] is True
    assert inspected["source"]["status"] == "current", inspected["source"]
    assert all(figure["document_sha256"] == file_sha256(Path(figure["document"])) for figure in inspected["figures"])
    delivery = complete["result"]["studio_run"]["delivery_package"]
    assert delivery["complete"] is True
    delivered_documents = list((Path(delivery["path"]) / "project").glob("*.vsz"))
    assert len(delivered_documents) == 1 and delivered_documents[0].read_bytes() == adopted
    csv_paths = list((visible / "data").glob("*.csv"))
    assert len(csv_paths) == 1
    with csv_paths[0].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[2] == ["B", "B", "A", "A"]
    assert [list(map(float, row)) for row in rows[3:]] == [[400, 9, 400, 8], [450, 10, 450, 9], [500, 11, 500, 10]]
    assert (old_source.read_bytes(), new_source.read_bytes()) == raw_before
    before_repeat = _files(project), _files(visible), _files(archive.parent)
    assert _cli("task", "resume", task, "--response", _write(response, accepted))["status"] == "complete"
    assert (_files(project), _files(visible), _files(archive.parent)) == before_repeat
