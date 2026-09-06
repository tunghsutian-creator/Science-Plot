from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.launchers import write_delivery_launcher
from sciplot_core.launchers.delivery_binding import make_delivery_binding
from sciplot_core.studio_core import project_query as query
from sciplot_core.studio_core import project_query_evidence as evidence
from sciplot_core.studio_core.project_query_evidence import source_indicators


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _inventory(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "managed"
    source = project / "source" / "data.csv"
    source.parent.mkdir(parents=True)
    source.write_text("x,y\n1,2\n")
    _write(project / "plot_request.json", {"input": str(source)})
    entries = []
    for identity in ("first", "second"):
        document = (
            project
            / "studio"
            / ("document.vsz" if identity == "first" else "figures/second.vsz")
        )
        spec = (
            document.with_name("spec.json")
            if identity == "first"
            else document.with_suffix(".spec.json")
        )
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(f"saved document {identity}")
        _write(
            spec,
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
        entries.append(
            {"figure_id": identity, "title": identity.title(), "status": "ready"}
        )
    _write(
        project / "studio/figure_set.json",
        {
            "kind": "sciplot_studio_figure_set",
            "version": 1,
            "primary_figure_id": "first",
            "figures": entries,
        },
    )
    return project


def _delivery(project: Path) -> Path:
    root = project.parent / "Visible"
    request_path = project / "plot_request.json"
    request = json.loads(request_path.read_text())
    request["delivery_output"] = str(root)
    _write(request_path, request)
    (root / "project").mkdir(parents=True)
    visible = root / "project" / "first.vsz"
    shutil.copy2(project / "studio/document.vsz", visible)
    binding = make_delivery_binding(
        root=root,
        manifest={
            "request_path": str(request_path),
            "resolved_figure_plan": {"primary_figure_id": "first"},
        },
        documents=[
            {
                "path": str(visible),
                "figure_id": "first",
                "delivery_sha256": file_sha256(visible),
            }
        ],
    )
    write_delivery_launcher(root, binding=binding)
    return root


def _run(project: Path, name: str = "studio_001") -> Path:
    run = project / "runs" / name
    run.mkdir(parents=True)
    shutil.copytree(project / "studio", run / "studio")
    request = json.loads((project / "plot_request.json").read_text())
    _write(run / "request_snapshot.json", request)
    documents = [run / "studio/document.vsz", run / "studio/figures/second.vsz"]
    exports, pdfs, tiffs = [], [], []
    for index, document in enumerate(documents):
        for fmt, suffix, qa in (
            ("pdf", ".pdf", pdfs),
            ("tiff_300", "_300dpi.tiff", tiffs),
        ):
            path = run / f"figure{index}{suffix}"
            path.write_bytes(b"fixture artifact bytes")
            record = {"path": str(path), "sha256": file_sha256(path)}
            exports.append({**record, "document": str(document), "format": fmt})
            qa.append(record)
    _write(
        run / "manifest.json",
        {
            "kind": "sciplot_run",
            "request": request,
            "ready_to_use": True,
            "veusz_document_hashes": {
                str(path): file_sha256(path) for path in documents
            },
            "qa": {"status": "passed", "pdfs": pdfs, "tiffs": tiffs},
            "result": {"exports": exports},
        },
    )
    return run


def test_summary_reads_all_saved_figures_without_qt_or_writing(project, monkeypatch):
    before = _inventory(project)
    monkeypatch.setattr(
        query, "_inspect_document", lambda _: pytest.fail("summary must not start Qt")
    )
    result = query.inspect_project(project)
    assert result["status"] == "ok"
    assert [f["figure_id"] for f in result["figures"]] == ["first", "second"]
    assert result["primary_figure_id"] == "first"
    assert result["readiness_evaluated"] is False and result["ready_to_use"] is None
    assert result["qa"]["current"] is None
    assert "selected_figure" not in result
    assert _inventory(project) == before


def test_explicit_object_has_saved_hash_target_and_scoped_native_capabilities(
    project, monkeypatch
):
    second = project / "studio/figures/second.vsz"
    widgets = {
        "/page1/graph1/x": {
            "name": "x",
            "type": "axis",
            "settings": {},
            "editable_fields": [{"field_id": "label_size"}],
        },
        "/page1/graph1/y": {"name": "y", "type": "axis", "settings": {}},
    }
    monkeypatch.setattr(
        query,
        "_inspect_document",
        lambda path: {
            "document": {"path": str(path), "sha256": file_sha256(path)},
            "widgets": widgets,
        },
    )
    result = query.inspect_project(
        project, figure_id="second", object_path="/page1/graph1/x"
    )
    selected = result["selected_figure"]
    assert selected["document"] == str(second)
    assert list(selected["objects"]) == ["/page1/graph1/x"]
    assert selected["objects"]["/page1/graph1/x"]["target"] == {
        "figure_id": "second",
        "object_path": "/page1/graph1/x",
        "document_sha256": file_sha256(second),
    }
    with pytest.raises(ValueError, match="Unknown object_path"):
        query.inspect_project(project, figure_id="second", object_path="/missing")


@pytest.mark.parametrize(
    "entry",
    [".", "plot_request.json", "studio/document.vsz", "studio/figures/second.vsz"],
)
def test_explicit_managed_entries_resolve_canonical_project(project, entry):
    target = project / entry
    assert query.resolve_project_path(target) == project
    selected = query.resolve_project_figure(target)
    assert selected["figure_id"] == ("second" if "second" in entry else "first")
    assert Path(selected["spec"]).is_file()


def test_bound_delivery_remains_queryable_with_unmerged_visible_edits(project):
    root = _delivery(project)
    visible = root / "project/first.vsz"
    visible.write_bytes(b"unmerged visible styling")
    before = _inventory(root)
    for entry in (root, root / "Open_in_Veusz.command", visible):
        assert query.resolve_project_path(entry) == project
        result = query.inspect_project(entry)
        assert result["delivery"]["current"] is False
        assert result["delivery"]["binding_current"] is True
    assert _inventory(root) == before


@pytest.mark.parametrize("mutation", ["copy", "source", "owner"])
def test_delivery_resolver_rejects_portable_missing_source_or_foreign_binding(
    project, mutation
):
    root = _delivery(project)
    if mutation == "copy":
        copy = root.with_name("Copied")
        shutil.copytree(root, copy)
        root = copy
    elif mutation == "source":
        (project / "source/data.csv").unlink()
    else:
        request = json.loads((project / "plot_request.json").read_text())
        request["delivery_output"] = str(root.with_name("Other"))
        _write(project / "plot_request.json", request)
    with pytest.raises(ValueError, match="binding|source"):
        query.resolve_project_path(root)


def test_corrupt_registry_and_unregistered_document_do_not_fallback_to_primary(project):
    rogue = project / "studio/rogue.vsz"
    rogue.write_text("rogue")
    with pytest.raises(ValueError, match="not a registered"):
        query.resolve_project_path(rogue)
    with pytest.raises(ValueError, match="Unknown figure_id"):
        query.resolve_project_figure(project, "unknown")
    (project / "studio/figure_set.json").write_text('{"invalid": true}')
    with pytest.raises(ValueError, match="registry"):
        query.inspect_project(project)


def test_query_rejects_project_member_symlink(project):
    spec = project / "studio/spec.json"
    moved = project / "original_spec.json"
    spec.rename(moved)
    spec.symlink_to(moved)
    with pytest.raises(ValueError, match="symlink"):
        query.inspect_project(project)


@pytest.mark.parametrize(
    "mutation", ["document", "secondary", "spec", "request", "export"]
)
def test_recorded_success_never_hides_current_qa_mismatch(project, mutation):
    run = _run(project)
    assert query.inspect_project(project)["qa"]["current"] is True
    path = {
        "document": project / "studio/document.vsz",
        "secondary": project / "studio/figures/second.vsz",
        "spec": project / "studio/spec.json",
        "request": project / "plot_request.json",
        "export": run / "figure0.pdf",
    }[mutation]
    if mutation in {"request", "spec"}:
        value = json.loads(path.read_text())
        value["changed"] = True
        _write(path, value)
    else:
        path.write_text("changed bytes")
    result = query.inspect_project(project)
    assert result["last_run"]["recorded_ready_to_use"] is True
    assert result["qa"]["current"] is False
    assert result["ready_to_use"] is None


def test_latest_failed_run_is_reported_without_falling_back_to_old_success(project):
    _run(project)
    newer = _run(project, "studio_002")
    _write(newer / "manifest.json", {"ready_to_use": False, "qa": {"status": "failed"}})
    result = query.inspect_project(project)
    assert result["last_run"]["manifest"] == str(newer / "manifest.json")
    assert result["last_run"]["recorded_ready_to_use"] is False
    assert result["qa"]["current"] is False


def test_source_indicator_detects_changed_prepared_input_bytes(project):
    request = json.loads((project / "plot_request.json").read_text())
    request["resolved_figure_plan"] = {
        "source_sha256": source_tree_sha256(Path(request["input"]))
    }
    figures = query.inspect_project(project)["figures"]
    assert source_indicators(project, request, figures)["current"] is True
    Path(request["input"]).write_text("x,y\n1,999\n")
    result = source_indicators(project, request, figures)
    assert result["current"] is False
    assert result["input"]["current"] is False
    assert result["prepared"]["current"] is False
    assert result["scientific_audit_evaluated"] is False


def test_worker_race_rejects_a_target_from_different_saved_bytes(project, monkeypatch):
    def inspect(path):
        digest = file_sha256(path)
        path.write_text("changed concurrently")
        return {"document": {"path": str(path), "sha256": digest}, "widgets": {}}

    monkeypatch.setattr(query, "_inspect_document", inspect)
    with pytest.raises(ValueError, match="changed during inspection"):
        query.inspect_project(project, figure_id="first")


@pytest.mark.parametrize(
    ("source_current", "status"),
    [(None, "unknown"), (False, "stale"), (True, "current")],
)
def test_delivery_currentness_preserves_unknown_source_evidence(
    project, monkeypatch, source_current, status
):
    _delivery(project)
    _run(project)
    monkeypatch.setattr(
        evidence,
        "verify_delivery_package",
        lambda *_, **__: {
            "passed": True,
            "failed_checks": [],
        },
    )
    request = json.loads((project / "plot_request.json").read_text())
    figures = query.inspect_project(project)["figures"]
    source = {
        "current": source_current,
        "input": {"current": source_current},
        "prepared": {"current": True},
        "raw": {"current": True},
    }
    result = evidence.publication_indicators(project, request, figures, source)
    assert result["qa"]["current"] is True
    delivery = result["delivery"]
    assert delivery["binding_current"] is True
    assert delivery["package_current"] is True
    assert delivery["source_current"] is source_current
    assert delivery["qa_current"] is True
    assert delivery["current"] is source_current
    assert delivery["status"] == status
