"""The real workflow/store composition publishes once after private preparation."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.studio_core import preparation_commands
from sciplot_core.workflow.project_requests import run_project_request


def prepared(tmp_path, *, previous_delivery=None, delivery_files=None):
    project, delivery = tmp_path / "project", tmp_path / "delivery"
    project.mkdir()
    delivery.mkdir(exist_ok=True)
    for name, content in (delivery_files or {}).items():
        member = delivery / name
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(content)
    (project / "source.csv").write_bytes(b"x,y\n1,2\n")
    request = {"input": "source.csv", "output": str(project / "runs/run_001"), "delivery_output": str(delivery)}
    (project / "plot_request.json").write_text(json.dumps(request))
    registry = {"kind": "sciplot_intake_project", "version": 1, "project_slug": "project"}
    if previous_delivery is not None:
        registry["delivery_package"] = previous_delivery
    (project / "intake_manifest.json").write_text(json.dumps(registry))
    store = FileProjectStore(project, locations={"delivery": delivery, "snapshot": ResourceRoot(tmp_path, ("project.zip",))})
    before = store.snapshot(import_legacy=True)
    return project, request, store, before


def execution(events, project, original):
    def execute(**kwargs):
        assert (project / "plot_request.json").read_bytes() == original
        assert not (project / "runs/run_001").exists()
        output = kwargs["output_dir"]
        (output / "run-evidence.txt").write_bytes(b"prepared analysis")
        private, _logical = kwargs["staged_delivery"]
        private.mkdir(parents=True, exist_ok=True)
        (private / "data").mkdir(exist_ok=True)
        diagnostic = private / "data/incomplete.csv"
        diagnostic.write_bytes(b"this is an admitted but incomplete diagnostic")
        (private / "unrecorded.txt").write_bytes(b"this is not an admitted diagnostic")
        events.append("analysis")
        package = {"complete": False, "path": str(private), "data_dir": str(private / "data"),
                   "verification": {"recorded_root": str(private)},
                   "data_csvs": [{"path": str(diagnostic)}]}
        status = {"delivery_package": dict(package)}
        (output / "one_step_status.json").write_text(json.dumps(status))
        return {"created_at": "2026-10-25T20:00:00Z", "figures": [], "result": {},
                "output": str(output), "request_path": str(kwargs["request_path"]),
                "delivery_package": package, "one_step": status, "ready_to_use": False}
    return execute


def test_complete_workflow_generation_contains_native_run_manifest_and_matching_zip(tmp_path, monkeypatch):
    project, request, store, before = prepared(tmp_path)
    original = (project / "plot_request.json").read_bytes()
    events = []
    def prepare(candidate, **kwargs):
        assert (project / "plot_request.json").read_bytes() == original
        assert not (project / "studio/document.vsz").exists()
        path = candidate.project_dir / "studio/document.vsz"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic native candidate")
        events.append("native")
        return {"document": str(path)}
    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", prepare)
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda candidate, payload: ([{"kind": "synthetic-native-port"}], []))
    result = run_project_request(project / "plot_request.json", request, execute=execution(events, project, original),
        classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)
    after = store.snapshot()
    assert after["sequence"] == before["sequence"] + 1
    assert after["projection_status"] == "current"
    assert events == ["analysis", "native"]
    assert result["output"] == str(project / "runs/run_001")
    assert (project / "studio/document.vsz").read_bytes() == b"synthetic native candidate"
    assert not list((tmp_path / "delivery").iterdir())
    assert (project / "runs/run_001/run-evidence.txt").read_bytes() == b"prepared analysis"
    installed = project / "runs/run_001"
    manifest = json.loads((installed / "manifest.json").read_text())
    status = json.loads((installed / "one_step_status.json").read_text())
    assert status == manifest["one_step"]
    assert status["delivery_package"] == manifest["delivery_package"]
    diagnostics = Path(status["delivery_package"]["path"])
    assert (diagnostics / "data/incomplete.csv").read_bytes() == b"this is an admitted but incomplete diagnostic"
    assert not (diagnostics / "unrecorded.txt").exists()
    assert "sciplot-studio-candidate-" not in json.dumps(status)
    assert (project / "source.csv").read_bytes() == b"x,y\n1,2\n"
    import zipfile
    with zipfile.ZipFile(tmp_path / "project.zip") as archive:
        assert archive.read("project/studio/document.vsz") == (project / "studio/document.vsz").read_bytes()
        assert archive.read("project/intake_manifest.json") == (project / "intake_manifest.json").read_bytes()


def test_failed_native_audit_does_not_publish_any_analysis_or_project_members(tmp_path, monkeypatch):
    project, request, store, before = prepared(tmp_path)
    original = (project / "plot_request.json").read_bytes()
    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda candidate, **kwargs: {})
    def reject(*args):
        raise ValueError("exact native audit failed")
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", reject)
    with pytest.raises(ValueError, match="exact native audit failed"):
        run_project_request(project / "plot_request.json", request, execute=execution([], project, original),
            classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)
    assert store.snapshot()["generation"] == before["generation"]
    assert (project / "plot_request.json").read_bytes() == original
    assert not (project / "runs").exists()
    assert not (tmp_path / "project.zip").exists()
    assert not list((tmp_path / "delivery").iterdir())


def test_request_preparation_forwards_committed_delivery_evidence(tmp_path, monkeypatch):
    # This opaque record tests transport, not acceptance of any historical file.
    previous = {"fixture": "committed delivery evidence", "version": 6}
    project, request, store, before = prepared(tmp_path, previous_delivery=previous)
    original = (project / "plot_request.json").read_bytes()
    execute = execution([], project, original)
    observed = []

    def prepare(**kwargs):
        observed.append(kwargs["previous_delivery"])
        return execute(**kwargs)

    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda *_a, **_k: {})
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda *_a: ([], []))
    run_project_request(project / "plot_request.json", request, execute=prepare,
        classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)
    assert observed == [previous]
    assert store.snapshot()["sequence"] == before["sequence"] + 1
    assert (project / "source.csv").read_bytes() == b"x,y\n1,2\n"
    assert not list((tmp_path / "delivery").iterdir())


@pytest.mark.parametrize("unregistered", [False, True])
def test_complete_workflow_installs_only_the_registered_delivery_delta(tmp_path, monkeypatch, unregistered):
    from sciplot_core.policy import DELIVERY_DATA_DIR, DELIVERY_PDF_DIR, DELIVERY_TIFF_DIR

    initial = {f"{DELIVERY_DATA_DIR}/stable.csv": b"unchanged generated table", f"{DELIVERY_TIFF_DIR}/stable.tiff": b"unchanged generated image",
               f"{DELIVERY_PDF_DIR}/replaced.pdf": b"old export", f"{DELIVERY_DATA_DIR}/retired.csv": b"old output no longer produced"}
    root = tmp_path / "delivery"
    previous = {"kind": "sciplot_user_delivery_package", "version": 7, "path": str(root), "complete": True,
                "data_csvs": [], "figures": []}
    for name, content in initial.items():
        section, field = ("data_csvs", "sha256") if name.endswith(".csv") else ("figures", "delivery_sha256")
        previous[section].append({"path": str(root / name), field: sha256(content).hexdigest()})
    if unregistered:
        initial[f"{DELIVERY_PDF_DIR}/only_copy.pdf"] = b"not registered, must survive"
    project, request, store, before = prepared(tmp_path, delivery_files=initial, previous_delivery=previous)
    current = {f"{DELIVERY_DATA_DIR}/stable.csv": initial[f"{DELIVERY_DATA_DIR}/stable.csv"], f"{DELIVERY_TIFF_DIR}/stable.tiff": initial[f"{DELIVERY_TIFF_DIR}/stable.tiff"],
               f"{DELIVERY_PDF_DIR}/replaced.pdf": b"new export", f"{DELIVERY_PDF_DIR}/added.pdf": b"additional export"}

    def execute(**kwargs):
        output = kwargs["output_dir"]
        (output / "run-evidence.txt").write_bytes(b"controlled native publication port")
        private, _logical = kwargs["staged_delivery"]
        assert not list(private.iterdir())  # The second generation is built independently.
        for name, content in current.items():
            member = private / name
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_bytes(content)
        return {"created_at": "2026-11-07T18:00:00Z", "figures": [], "result": {},
                "output": str(output), "request_path": str(kwargs["request_path"]),
                "delivery_package": {"complete": True, "path": str(private)}, "ready_to_use": True}

    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda *_a, **_k: {})
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda *_a: ([], []))
    def run():
        return run_project_request(project / "plot_request.json", request, execute=execute,
            classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)

    if unregistered:
        with pytest.raises(ValueError, match="only_copy.pdf"):
            run()
        assert store.snapshot()["generation"] == before["generation"]
        assert {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file()} == initial
        return
    result = run()
    assert result["delivery_package"]["complete"] is True
    assert {p.relative_to(tmp_path / "delivery").as_posix(): p.read_bytes()
            for p in (tmp_path / "delivery").rglob("*") if p.is_file()} == current
    after = store.snapshot()
    writes = store.commands()[-1]["draft"]["writes"]
    for name in (f"{DELIVERY_DATA_DIR}/stable.csv", f"{DELIVERY_TIFF_DIR}/stable.tiff"):
        logical = "@delivery/" + name
        assert logical not in writes
        assert after["files"][logical] == before["files"][logical]
    assert writes[f"@delivery/{DELIVERY_DATA_DIR}/retired.csv"] is None
    assert {f"@delivery/{DELIVERY_PDF_DIR}/replaced.pdf", f"@delivery/{DELIVERY_PDF_DIR}/added.pdf"} <= writes.keys()
    assert (project / "source.csv").read_bytes() == b"x,y\n1,2\n"


@pytest.mark.parametrize("foreign", [False, True], ids=["registered-retirement", "foreign-file-preserved"])
def test_two_figure_delivery_can_publish_one_figure_in_the_next_generation(tmp_path, monkeypatch, foreign):
    from copy import deepcopy
    from dataclasses import replace

    from sciplot_core.delivery.package_builder import _build_staged_delivery, build_delivery_package
    from sciplot_core.delivery.package_validation import verify_delivery_package
    from test_delivery_project_documents import _builder_manifest

    root = tmp_path / "delivery"
    run, both, plan = _builder_manifest(tmp_path)
    both["request"]["delivery_output"] = str(root)
    previous = build_delivery_package(run, manifest=both)
    assert previous["complete"] and len(previous["figures"]) == 4
    if foreign:
        (root / "figures/notes.txt").write_bytes(b"only copy of user's notes")
    previous_bytes = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    inode = root.stat().st_ino
    project, request, store, before = prepared(tmp_path, previous_delivery=previous)

    # Keep the same real producer, changed selection, and same registered
    # destination. The retired figure's artifacts still exist in the preimage.
    retained = set(plan.outcomes[0].artifacts)
    one = deepcopy(both)
    selected = replace(plan, tasks=plan.tasks[:1], outcomes=plan.outcomes[:1]).to_payload()
    one["resolved_figure_plan"] = one["result"]["resolved_figure_plan"] = one["study_model"]["run"]["resolved_figure_plan"] = selected
    one["figures"] = [path for path in one["figures"] if path in retained]
    one["veusz_documents"] = [path for path in one["veusz_documents"] if path in retained]
    one["veusz_document_hashes"] = {path: digest for path, digest in one["veusz_document_hashes"].items() if path in retained}
    one["result"]["exports"] = [row for row in one["result"]["exports"] if row["path"] in retained]
    for kind in ("pdfs", "tiffs"):
        one["qa"][kind] = [row for row in one["qa"][kind] if row["path"] in retained]

    def execute(**kwargs):
        stage, final = kwargs["staged_delivery"]
        record = _build_staged_delivery(run, manifest=one, delivery_dir=stage, final_root=final,
                                        previous_delivery=kwargs["previous_delivery"])
        return {**one, "created_at": "2026-11-27T06:00:00Z",
                "output": str(kwargs["output_dir"]), "request_path": str(kwargs["request_path"]),
                "delivery_package": record, "ready_to_use": record["complete"]}

    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda *_a, **_k: {})
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda *_a: ([], []))
    def publish():
        return run_project_request(project / "plot_request.json", request, execute=execute,
                                   classifier=lambda *_a, **_k: {}, new_creation=False, previous_request=None)

    if foreign:
        with pytest.raises(ValueError, match="figures/notes.txt"):
            publish()
        assert store.snapshot()["generation"] == before["generation"]
        assert root.stat().st_ino == inode
        assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == previous_bytes
        return
    result = publish()
    record = result["delivery_package"]
    assert record["complete"] is True, record["verification"]
    assert root.stat().st_ino == inode
    assert store.snapshot()["sequence"] == before["sequence"] + 1
    assert verify_delivery_package(record, expected_root=root, expected_manifest=one)["passed"]
    assert {Path(row["path"]).name for row in record["figures"]} == {"figure_a.pdf", "figure_a_300dpi.tiff"}
    assert not list(root.rglob("figure_b*"))
    assert Path(record["path"]) == root
    assert all(Path(row["path"]).is_relative_to(root) for row in record["project_documents"] + record["figures"])
