"""Physical native request drift cannot grant another host resource root."""
import json

import pytest

from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.store_composition import existing_store
from sciplot_core.project_store.repository import FileProjectStore


@pytest.mark.parametrize("drift", ["none", "foreign_bytes", "symbolic_request"])
def test_native_capability_factory_requires_the_admitted_request_bytes(tmp_path, monkeypatch, drift):
    project = tmp_path / "project"
    project.mkdir()
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": str(project / "source.csv"), "template": "curve"}))
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "figure.pdf").write_bytes(b"owned publication")
    store = FileProjectStore(project, locations={"delivery": delivery})
    initial = store.snapshot(import_legacy=True)
    calls = []
    from sciplot_core.studio_core import project_command_scope

    def factory(root):
        assert root == project
        calls.append(root)
        return store

    monkeypatch.setattr(project_command_scope, "project_store", factory)
    if drift == "foreign_bytes":
        request.write_text(json.dumps({"output_dir": str(tmp_path / "foreign-private-root")}))
    elif drift == "symbolic_request":
        foreign = tmp_path / "private-request.json"
        foreign.write_text(json.dumps({"output_dir": str(tmp_path / "foreign-private-root")}))
        request.unlink()
        request.symlink_to(foreign)
    if drift == "none":
        assert existing_store(project) is store
        assert calls == [project]
    else:
        with pytest.raises(EngineError):
            existing_store(project)
        assert calls == []
    assert store.read_bytes("plot_request.json") == (json.dumps({"input": str(project / "source.csv"), "template": "curve"})).encode()
    with store._locked(allow_pending=True) as (_io, current):
        assert current["generation"] == initial["generation"]
