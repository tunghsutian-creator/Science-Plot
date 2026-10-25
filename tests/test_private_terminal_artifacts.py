"""Only an inherited private locator may bypass a standalone project writer."""

import json

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.studio_core.preparation_artifacts import export_private_request
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate


def test_unbound_request_has_no_private_compilation_capability(tmp_path):
    target = tmp_path / "not-created/plot_request.json"
    assert export_private_request(target, formats=["pdf"], terminal_source_binding=None,
                                   terminal_source_prepared=False) is None
    assert not target.parent.exists()


@pytest.mark.parametrize("relative", [None, "plot_request.json", "nested/other.json"])
def test_private_worker_rejects_foreign_root_or_nonterminal_request(tmp_path, relative):
    project = tmp_path / "project"
    project.mkdir()
    (project / "plot_request.json").write_bytes(b"{}")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store) as candidate:
        request = candidate.project_dir / relative if relative else tmp_path / "foreign/plot_request.json"
        with pytest.raises(ProjectConflict, match="nested terminal artifact"):
            export_private_request(request, formats=["pdf"], terminal_source_binding=None,
                                   terminal_source_prepared=False)
    assert store.snapshot()["generation"] == before["generation"]
    assert not (tmp_path / "foreign").exists()


def test_private_terminal_artifact_never_calls_a_public_project_writer(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "plot_request.json").write_bytes(b"{}")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    calls = []

    def prepare(candidate, **options):
        calls.append("prepare")
        assert options["request_target"] is True
        native = candidate.project_dir / "studio/document.vsz"
        candidate.write_member("studio/document.vsz", b"private native port double")
        return {"document": str(native)}

    def audit(candidate, payload):
        calls.append("audit")
        return [], []

    def export(document, **options):
        calls.append("export")
        assert options["output_dir"] == document.parent / "exports"
        assert document.read_bytes() == b"private native port double"
        return {"exports": []}

    def forbidden(*args, **kwargs):
        pytest.fail("A private terminal artifact must not create or publish a nested project")

    monkeypatch.setattr("sciplot_core.studio_core.preparation_commands.prepare_studio_candidate", prepare)
    monkeypatch.setattr("sciplot_core.studio_core.preparation_commands.audit_studio_candidate", audit)
    monkeypatch.setattr("sciplot_core.studio_core.native_export_adapter.export_studio_document", export)
    monkeypatch.setattr("sciplot_core.studio_core.studio_prepare.prepare_studio_document", forbidden)
    monkeypatch.setattr("sciplot_core.studio_core.export_execution.export_studio_document", forbidden)
    from sciplot_core.veusz_worker.operations import export_request

    with studio_preparation_candidate(store) as candidate:
        request = candidate.project_dir / "run/figures/single/plot_request.json"
        request.parent.mkdir(parents=True)
        request.write_text(json.dumps({"input": "/original/data.csv", "template": "curve"}))
        result = export_request(request, formats=["pdf"])
        assert result["document"] == str(request.parent / "studio/document.vsz")
        assert not list(candidate.project_dir.rglob(".sciplot_store"))
        assert json.loads(request.read_text())["input"] == "/original/data.csv"
    assert calls == ["prepare", "audit", "export"]
    assert store.snapshot()["generation"] == before["generation"]


def test_materialized_binding_keeps_literal_identity_while_verifying_private_bytes(tmp_path):
    from types import SimpleNamespace
    from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding, TerminalSourceBindingError

    project = tmp_path / "project"
    project.mkdir()
    source = project / "source.csv"
    source.write_bytes(b"x,y\n0,1\n")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store) as candidate:
        physical = candidate.project_dir / "source.csv"
        binding = MaterializedTerminalSourceBinding.create(task_key="curve", rule_id="example_rule",
            template="curve", x_metric="x", y_metric="y", raw_sources=[physical],
            prepared_source=physical, terminal_source=physical, sample_order=["A"], point_counts={"A": 1})
        assert {item.path for item in (*binding.raw_sources, binding.prepared_source, binding.terminal_source)} == {str(source)}
        request = candidate.project_dir / "figures/_veusz/single/plot_request.json"
        request.parent.mkdir(parents=True)
        payload = {"rule_id": "example_rule", "template": "curve", "input": str(source),
                   "x_metric": "x", "y_metric": "y", "series_order": ["A"],
                   "render_options": {"x_metric": "x", "y_metric": "y"}}
        request.write_text(json.dumps(payload))
        sealed = binding.seal(request, payload)
        assert sealed.request.path == str(project / "figures/_veusz/single/plot_request.json")
        sealed.validate_request(request, payload)
        binding.validate_series([SimpleNamespace(label="A", x_values=[0], y_values=[1],
            source_artifacts=((str(source), binding.terminal_source.sha256),))])
        physical.write_bytes(b"x,y\n0,999\n")
        with pytest.raises(TerminalSourceBindingError) as error:
            binding.verify_sources()
        assert error.value.reason_code == "terminal_source_binding_source_changed"
    assert source.read_bytes() == b"x,y\n0,1\n"
    assert store.snapshot()["generation"] == before["generation"]
