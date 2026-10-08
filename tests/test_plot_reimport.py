"""Native-only reimport retains scientific authority and semantic identities."""

from copy import deepcopy
import pytest

from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import commit, load_head
from test_plot_engine import FakeBackend


class ImportBackend(FakeBackend):
    def initial(self):
        doc, binding = super().initial()
        binding.update({"document": str(self.native), "project": str(self.directory), "figure_id": "main",
                        "native_audit_at_import": deepcopy(self.audit), "targets": {
                            name: {"object_path": "/native/" + name} for name in doc["presentation"]["objects"]}})
        return doc, binding

    def import_project(self, project, figure_id=None, plot_id=None):
        doc, binding = self.initial()
        doc["presentation"]["objects"]["series:E2"]["properties"]["style.line.width"] = "0.6pt"
        if plot_id:
            doc["plot_id"] = plot_id
        return seal_document(doc), binding


@pytest.fixture
def imported(tmp_path):
    backend = ImportBackend(tmp_path / "backend")
    doc, binding = backend.initial()
    # Explicit template IDs differ from labels and must survive reimport.
    obj = doc["presentation"]["objects"].pop("series:E2")
    doc["presentation"]["objects"]["series:control"] = obj
    binding["targets"]["series:control"] = binding["targets"].pop("series:E2")
    binding["template_adoption"] = {"identity": "retained"}
    root = tmp_path / "plot"
    commit(root, seal_document(doc), binding, "import")
    backend.native.write_bytes(b"manually saved native width")
    return PlotService(backend), root, backend


def test_reimport_frozen_review_preserves_ids_and_science_without_native_write(imported):
    service, root, backend = imported
    before = load_head(root)["document"]
    request = service.describe(root)["next_step"]["request"]
    review = service.decide(root, request)
    assert review["status"] == "needs_review" and load_head(root)["document"] == before
    assert service.decide(root, request)["decision_id"] == review["decision_id"]
    assert backend.calls["render"] == 1
    result = PlotService(backend).decide(root, review["next_step"]["request"])
    assert result["ready_to_use"] and result["revision"] == 1
    after = load_head(root)
    assert after["document"]["scientific_hash"] == before["scientific_hash"]
    assert after["document"]["presentation"]["objects"]["series:control"]["properties"]["style.line.width"] == "0.6pt"
    assert after["binding"]["template_adoption"] == {"identity": "retained"}
    assert backend.calls["apply"] == backend.native_writes == 0
    assert service.decide(root, request)["replayed"]
    assert backend.calls["export"] == 1


def test_changed_source_never_offers_reimport(imported):
    service, root, backend = imported
    request = service.describe(root)["next_step"]["request"]
    backend.raw.write_bytes(b"different science")
    assert "next_step" not in service.describe(root)
    with pytest.raises(EngineError, match="frozen native-only"):
        service.decide(root, request)
    assert backend.calls["render"] == backend.calls["apply"] == 0


@pytest.mark.parametrize("stage", ["offered", "reviewed"])
def test_reimport_changed_native_cannot_use_stale_decision(imported, stage):
    service, root, backend = imported
    request = service.describe(root)["next_step"]["request"]
    if stage == "reviewed":
        request = service.decide(root, request)["next_step"]["request"]
    backend.native.write_bytes(b"another manual edit")
    with pytest.raises(EngineError):
        service.decide(root, request)
    assert load_head(root)["document"]["revision"] == 0 and backend.calls["apply"] == 0


def test_rejected_reimport_keeps_native_and_old_semantic_head(imported):
    service, root, backend = imported
    review = service.decide(root, service.describe(root)["next_step"]["request"])
    rejected = service.decide(root, {**review["next_step"]["request"], "accept": False})
    assert rejected["status"] == "rejected" and service.describe(root)["status"] == "stale"
    assert backend.native.read_bytes() == b"manually saved native width"
    assert load_head(root)["document"]["revision"] == 0 and backend.calls["apply"] == 0


def test_failed_native_audit_never_enters_review(imported):
    service, root, backend = imported
    backend.audit = {"status": "failed"}
    with pytest.raises(EngineError, match="numerical and mapping audit"):
        service.decide(root, service.describe(root)["next_step"]["request"])
    assert backend.calls["render"] == backend.calls["apply"] == 0


def test_interrupted_reservation_restores_active_review_on_same_request(imported):
    service, root, backend = imported
    request = service.describe(root)["next_step"]["request"]
    review = service.decide(root, request)
    (root / "active.json").unlink()
    replayed = PlotService(backend).decide(root, request)
    assert replayed["decision_id"] == review["decision_id"] and backend.calls["render"] == 1
    assert service.decide(root, replayed["next_step"]["request"])["ready_to_use"]
    assert backend.calls["apply"] == 0


def test_stale_review_can_be_rejected_and_new_native_save_reimported(imported):
    service, root, backend = imported
    request = service.describe(root)["next_step"]["request"]
    review = service.decide(root, request)
    backend.native.write_bytes(b"later manual save")
    rejected = service.decide(root, {**review["next_step"]["request"], "accept": False})
    assert rejected["status"] == "rejected" and backend.calls["apply"] == 0
    fresh = service.describe(root)["next_step"]["request"]
    assert fresh != request
    assert service.decide(root, fresh)["status"] == "needs_review"
    assert load_head(root)["document"]["revision"] == 0
