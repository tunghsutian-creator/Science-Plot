"""Current admission precedes mutations and leaves durable replay semantics intact."""

from copy import deepcopy
from contextlib import nullcontext

import pytest
from test_current_unit_admission import expert_wire, managed

from sciplot_core.project_lifecycle import managed_creation
from sciplot_core.project_lifecycle import application as service
from sciplot_core.plot_engine.content_store import intern_document, resolve_provenance_value
from sciplot_core.plot_engine.contracts import validate_create
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import digest, write


def forbidden(*args, **kwargs):
    raise AssertionError("An effect ran before unit admission or during saved replay")


def patch_for(document, *, parameters=None):
    return {"plot_id": document["plot_id"], "base_revision": document["revision"],
            "idempotency_key": "update", "intent_class": "scientific",
            "changes": [{"op": "set", "target": ["transform:unit"], "property": "transform.parameters",
                         "value": parameters or deepcopy(document["scientific"]["transforms"][-1]["parameters"])}]}


def test_create_rejects_before_creation_journal_or_executor_or_native_effect(tmp_path, monkeypatch):
    wire = expert_wire(tmp_path, header="Charge_C", rename=True)
    monkeypatch.setattr(managed_creation, "resolve_science", forbidden)
    monkeypatch.setattr(managed_creation, "make_binding", forbidden)
    monkeypatch.setattr(managed_creation, "write", forbidden)
    before = (tmp_path / "figure.csv").read_bytes()
    with pytest.raises(ValueError) as error:
        PlotService(backend=object()).create(wire)
    assert error.value.reason_code == "transform_unit_incompatible"
    assert not list(tmp_path.rglob("managed-creation.json"))
    assert (tmp_path / "figure.csv").read_bytes() == before


def test_scientific_patch_rejects_after_real_diff_before_binding_reservation_or_persist(tmp_path, monkeypatch):
    document = managed(expert_wire(tmp_path, header="Charge_C", quantity="charge", target="C"))
    head = {"document": document, "binding": {"plot_type": "ManagedPlot"}}
    monkeypatch.setattr(service, "load_head", lambda root: head)
    monkeypatch.setattr(service, "require_current", forbidden)
    monkeypatch.setattr(service, "persist", forbidden)
    from sciplot_core.plot_engine import managed_state
    monkeypatch.setattr(managed_state, "scientific_binding", forbidden)
    request = patch_for(document, parameters={"columns": ["column:1"], "from_unit": "C", "to_unit": "K"})
    before = deepcopy(head)
    with pytest.raises(ValueError) as error:
        PlotService(backend=object())._patch(tmp_path / "store", request)
    assert error.value.reason_code in {"transform_unit_incompatible", "managed_unit_lineage_unsupported"}
    assert head == before and not (tmp_path / "store").exists()


def test_scientific_noop_does_not_reinterpret_or_rewrite_old_request(tmp_path, monkeypatch):
    document = managed(expert_wire(tmp_path, header="Charge_C", quantity="charge", target="C"))
    head = {"document": document, "binding": {"plot_type": "ManagedPlot"}}
    monkeypatch.setattr(service, "load_head", lambda root: head)
    observed_inputs = []

    def observe_current(backend, binding, *, input_document=None):
        observed_inputs.append(deepcopy(input_document))

    monkeypatch.setattr(service, "require_current", observe_current)
    from sciplot_core.plot_engine import current_unit_admission, managed_state, publication_repair
    monkeypatch.setattr(current_unit_admission, "admit_current_units", forbidden)
    monkeypatch.setattr(managed_state, "scientific_binding", forbidden)
    monkeypatch.setattr(publication_repair, "authorize_pending", lambda *args: None)
    monkeypatch.setattr(publication_repair, "reserve_repair", lambda *args: None)
    monkeypatch.setattr(service, "persist", lambda *args: None)
    monkeypatch.setattr(PlotService, "_cached_export", lambda *args: None)
    monkeypatch.setattr(service, "advance", lambda root, tx, backend: tx)
    original = deepcopy(document)
    result = PlotService(backend=object())._patch(tmp_path / "store", patch_for(document))
    assert result["diff"] == [] and result["document"] == original and document == original
    assert observed_inputs == [original]


def test_saved_transaction_replay_does_not_reenter_new_admission(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import current_unit_admission, publication_repair
    saved = tmp_path / "saved.json"
    write(saved, {"phase": "complete", "original": "frozen scientific request"})
    monkeypatch.setattr(service, "transaction_path", lambda *args: saved)
    monkeypatch.setattr(service, "load_head", forbidden)
    monkeypatch.setattr(current_unit_admission, "admit_current_units", forbidden)
    monkeypatch.setattr(publication_repair, "prepare_saved", lambda root, tx, request, backend: tx)
    monkeypatch.setattr(service, "replay", lambda root, tx, backend: tx)
    assert PlotService(backend=object())._patch(tmp_path, {"idempotency_key": "saved"})["original"] == "frozen scientific request"


def test_saved_creation_state_replay_bypasses_new_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(managed_creation, "external_project_session", lambda _: nullcontext())
    request = validate_create(expert_wire(tmp_path, header="Charge_C"))
    document = managed(request)
    root = tmp_path / ".sciplot_documents" / "managed" / digest(request["idempotency_key"])
    write(root / "managed-creation.json", {"request_hash": digest(request), "request": request,
          "document": document, "phase": "committed"})
    write(root / "head.json", {})
    monkeypatch.setattr(managed_creation, "admit_current_units", forbidden)
    monkeypatch.setattr(managed_creation, "resolve_science", forbidden)
    binding = {"ir_hash": "frozen", "source_fingerprint": "original", "template_id": "fixture"}
    monkeypatch.setattr(managed_creation, "load_head", lambda root: {"document": document, "binding": binding})
    monkeypatch.setattr(managed_creation, "export_head", lambda *args: {})
    monkeypatch.setattr(managed_creation, "authority_status", lambda *args: {})
    monkeypatch.setattr(managed_creation, "plot_object_handle", lambda *args, **kwargs: {})
    from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
    from sciplot_core.project_lifecycle.context import repository
    location = FilesystemProjectTargets(repository()).managed_creation(request)
    assert managed_creation.create_managed(request, object(), location=location)["ir_hash"] == "frozen"


def test_presentation_alias_does_not_reinterpret_historical_unit_graph(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import current_unit_admission, publication_repair
    document = managed(expert_wire(tmp_path, header="Charge_C"))
    original_science = deepcopy(document["scientific"])
    monkeypatch.setattr(service, "load_head", lambda root: {"document": document, "binding": {}})
    observed_inputs = []

    def observe_current(backend, binding, *, input_document=None):
        observed_inputs.append(deepcopy(input_document))

    monkeypatch.setattr(service, "require_current", observe_current)
    monkeypatch.setattr(current_unit_admission, "admit_current_units", forbidden)
    monkeypatch.setattr(publication_repair, "authorize_pending", lambda *args: None)
    monkeypatch.setattr(publication_repair, "reserve_repair", lambda *args: None)
    monkeypatch.setattr(service, "advance", lambda root, tx, backend: tx)
    request = {"plot_id": "test", "base_revision": 0, "idempotency_key": "label", "intent_class": "presentation",
               "changes": [{"op": "set", "target": ["layer:modulus"], "property": "series.display_label", "value": "Temperature alias"}]}
    result = PlotService(backend=object())._patch(tmp_path, request)
    assert result["document"]["scientific"] == original_science and result["phase"] == "planned"
    assert len(observed_inputs) == 1
    observed = observed_inputs[0]
    assert observed["revision"] == document["revision"]
    assert observed["scientific"] == original_science
    assert observed["presentation"] == result["document"]["presentation"]
    assert observed["presentation"] != document["presentation"]


def test_targeted_binding_read_verifies_bytes_and_does_not_decode_other_arrays(tmp_path):
    document = managed(expert_wire(tmp_path))
    document["scientific"]["provenance"]["binding"]["proof"] = {"original": "source fact"}
    document["scientific"]["provenance"]["datasets"] = {"large": list(range(100))}
    from sciplot_core.plot_document import seal_document
    compact = intern_document(tmp_path, seal_document(document), minimum_bytes=2)
    arrays = compact["scientific"]["provenance"]["datasets"]
    (tmp_path / "content" / (arrays["sha256"] + ".json")).write_bytes(b"corrupt unrelated array")
    original = deepcopy(compact)
    assert resolve_provenance_value(tmp_path, compact, "binding")["proof"] == {"original": "source fact"}
    assert compact == original
    reference = compact["scientific"]["provenance"]["binding"]
    (tmp_path / "content" / (reference["sha256"] + ".json")).write_bytes(b"corrupt binding")
    with pytest.raises(ValueError) as error:
        resolve_provenance_value(tmp_path, compact, "binding")
    assert error.value.reason_code == "document_content_corrupt"
