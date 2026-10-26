"""Source archival reads selected bytes while retaining original scientific locators."""
from pathlib import Path

import pytest

from sciplot_core.project_store.errors import ProjectStoreError
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.request_paths import _archive_studio_input


def source_project(root: Path) -> tuple[FileProjectStore, Path, bytes]:
    source = root / "source/original.csv"
    source.parent.mkdir(parents=True)
    data = b"Time,Force\ns,N\n0,1\n1,3\n"
    source.write_bytes(data)
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    return store, source, data


def test_offline_archive_uses_current_bound_bytes_and_original_locator_and_name(tmp_path):
    store, original, data = source_project(tmp_path / "original-project")
    bundle = store.export_bundle(tmp_path / "bundle")
    store.root.rename(tmp_path / "offline-project")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold-project")
    assert not original.exists()
    output = tmp_path / "publication"
    with project_runtime(cold):
        archived = _archive_studio_input(original, output)
    assert archived == {"kind": "file", "source": str(original), "path": str(output / "raw/original.csv")}
    assert Path(archived["path"]).read_bytes() == data
    assert (cold.root / "source/original.csv").read_bytes() == data


@pytest.mark.parametrize("tamper", ["request_binding", "source_binding"])
def test_public_attached_export_rejects_broken_admission_before_raw_archival(tmp_path, tamper):
    import json
    from copy import deepcopy
    from test_plot_engine import FakeBackend
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_backends.veusz_identity import fingerprint
    from sciplot_core.plot_document import seal_document
    from sciplot_core.plot_engine.service import PlotService

    project = tmp_path / "project"
    project.mkdir()

    class Backend(FakeBackend):
        def import_project(self, _project, figure_id=None, plot_id=None):
            document, binding = self.initial()
            document["plot_id"] = plot_id or document["plot_id"]
            files = {str(path): file_sha256(path) for path in (self.raw, self.native, spec, request)}
            binding.update(kind="sciplot_veusz_binding", project=str(project), figure_id=figure_id,
                           document=str(self.native), spec=str(spec), files=files, source_trees={}, projected_reads=[])
            binding["fingerprint"] = {"files": deepcopy(files), "source_trees": {}, "projections": {}}
            return seal_document(document), binding

        def fingerprint(self, binding):
            # Real selected-store byte/currentness admission; only rendering is synthetic.
            return fingerprint(binding)

        def export(self, _binding):
            self.calls["export"] += 1
            _archive_studio_input(Path(json.loads(request.read_text())["input"]), output)
            pytest.fail("A broken public binding reached raw publication")

    backend = Backend(project / "studio")
    spec = project / "studio/spec.json"
    spec.write_text("{}")
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": str(backend.raw), "template": "curve"}))
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    service = PlotService(backend=backend, resolve_figure=lambda target, _figure: {"project": str(target), "figure_id": "primary"})
    output = tmp_path / "publication"
    try:
        with project_runtime(store):
            opened = service.open(project, figure_id="primary")
        before = store.snapshot()
        if tamper == "request_binding":
            foreign = tmp_path / "unregistered/raw.csv"
            foreign.parent.mkdir()
            foreign.write_bytes(b"x,y\n9,99\n")
            request.write_text(json.dumps({"input": str(foreign), "template": "curve"}))
        else:
            backend.raw.unlink()
        with project_runtime(store), pytest.raises(ValueError) as error:
            service.export(Path(opened["plot"]))
        assert getattr(error.value, "reason_code", None) in {"document_inputs_changed", "semantic_project_changed"}
        assert backend.calls["export"] == 0 and not output.exists()
        assert store.snapshot()["generation"] == before["generation"]
    finally:
        service.close()


def test_archive_rejects_bytes_different_from_the_selected_generation_hash(tmp_path):
    store, original, data = source_project(tmp_path / "project")
    changed = data + b"2,99\n"
    original.write_bytes(changed)
    output = tmp_path / "publication"
    with project_runtime(store), pytest.raises(ProjectStoreError):
        _archive_studio_input(original, output)
    assert not output.exists() and original.read_bytes() == changed


def test_unattached_local_archive_preserves_existing_filesystem_contract(tmp_path):
    source = tmp_path / "original.csv"
    source.write_bytes(b"x,y\n1,2\n")
    result = _archive_studio_input(source, tmp_path / "publication")
    assert result["source"] == str(source) and Path(result["path"]).read_bytes() == source.read_bytes()
