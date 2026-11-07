"""Owned patch admission preserves refusal, history and one synchronous shape check."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from managed_plot_helpers import patch, request_for_source
from test_native_suite_project_commands import bound as bound, request as native_request
from test_plot_engine import FakeBackend, request
from test_project_lifecycle import ManagedBackend, MemoryRepository, application

from sciplot_core.plot_document import DocumentError, validate_patch
from sciplot_core.plot_document.requests import PatchRequest, RequestBody, admit_patch
from sciplot_core.plot_document.schema import patch_schema
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.project_lifecycle.contracts import NormalizedCommand, RevisionToken
from sciplot_core.workflow import native_suite_transactions as native


def shape_counter(monkeypatch):
    observed = []
    original = Draft202012Validator.iter_errors

    def observe(self, value, *args, **kwargs):
        if self.schema == patch_schema():
            observed.append(deepcopy(value))
        return original(self, value, *args, **kwargs)

    monkeypatch.setattr(Draft202012Validator, "iter_errors", observe)
    return observed


def test_patch_owns_input_and_wire_copies_without_losing_literal_identity():
    original = request()
    original["changes"][0]["value"] = [1, 1.0, True, -0.0, "μ"]
    expected = json.dumps(original, ensure_ascii=False)
    owned = admit_patch(original)
    original["changes"][0]["value"].clear()
    owned.to_payload()["changes"].clear()
    assert json.dumps(owned.to_payload(), ensure_ascii=False) == expected
    assert admit_patch(owned) is owned
    assert validate_patch(owned) == json.loads(expected)


@pytest.mark.parametrize("invalid", [None, [], 1, {"bad": True},
    {**request(), "base_revision": True},
    {**request(), "changes": [{"op": "set", "target": [], "property": "x", "value": 1}]},
    {**request(), "changes": [{"op": "set", "target": ["x"], "property": "x", "value": float("nan")}]},
])
def test_raw_patch_keeps_original_contract_error_and_pointers(invalid):
    with pytest.raises(DocumentError) as original:
        validate_wire(invalid, patch_schema(), code="document_invalid_patch")
    with pytest.raises(DocumentError) as owned:
        admit_patch(invalid)
    assert owned.value.reason_code == original.value.reason_code
    assert owned.value.issues == original.value.issues


def test_finite_command_body_does_not_certify_patch_shape(monkeypatch):
    observations = shape_counter(monkeypatch)
    finite = RequestBody({"plot_id": "not-a-patch"})
    with pytest.raises(DocumentError) as failure:
        admit_patch(finite)
    assert failure.value.reason_code == "document_invalid_patch"
    assert len(observations) == 1


@pytest.mark.parametrize("managed", [False, True])
def test_public_patch_checks_shape_once_and_journals_plain_wire(tmp_path, monkeypatch, managed):
    repo = MemoryRepository()
    if managed:
        backend = ManagedBackend()
        app = application(backend, repo)
        created = app.create(request_for_source(tmp_path))
        root = Path(created["plot"])
        wire = patch(created, "style", "style.line.width", "1.2pt", "series:A")
    else:
        backend = FakeBackend(tmp_path / "native")
        root = tmp_path / "plot"
        document, binding = backend.initial()
        repo.commit(root, document, binding, "import")
        app = application(backend, repo)
        wire = request()
    from sciplot_core.plot_engine.service import PlotService
    service = PlotService(backend, repository=repo, capabilities=app.capabilities, targets=app.targets)
    before = deepcopy(wire)
    observations = shape_counter(monkeypatch)
    result = service.patch(root, wire)
    assert result["ready_to_use"] and result["revision"] == 1
    assert observations == [before] and wire == before
    records = [value for path, value in repo.values.items() if path.endswith("/transaction.json")
               and value["request"]["idempotency_key"] == wire["idempotency_key"]]
    assert len(records) == 1 and records[0]["request"] == before
    assert records[0]["normalized_command"]["business_request"] == before
    # This is a new journal observation after a reply loss, not a reuse of a
    # mutable wire object or of a previous operation's currentness judgment.
    assert service.patch(root, deepcopy(before))["replayed"]
    assert observations == [before, before]
    assert backend.calls["preview"] == backend.calls["apply"] == 1


def test_native_patch_keeps_owned_value_through_runtime_and_replay(bound, monkeypatch):
    wire = native_request(bound)
    target = Path(bound[3][0]["path"])
    observations = shape_counter(monkeypatch)
    owned = PatchRequest(wire)
    preview = native.patch_native(target, owned)
    assert preview["status"] == "needs_review" and observations == [wire]
    assert bound[5] == ["patch", "export"]
    assert native.patch_native(target, deepcopy(wire))["decision_id"] == preview["decision_id"]
    assert observations == [wire, wire] and bound[5] == ["patch", "export"]


def test_invalid_native_wire_refuses_before_runtime_or_repair(tmp_path, monkeypatch):
    from sciplot_core.workflow import native_suite_runtime as runtime

    monkeypatch.setattr(runtime, "read_bound_store", lambda *_: pytest.fail("invalid wire entered project IO"))
    with pytest.raises(DocumentError) as failure:
        native.patch_native(tmp_path / "not-opened.vsz", {"changes": []})
    assert failure.value.reason_code == "document_invalid_patch"
    assert list(tmp_path.iterdir()) == []


def test_native_replay_cannot_replace_integer_literal_with_equal_float(bound, monkeypatch):
    from sciplot_core.workflow import native_suite_runtime as runtime

    wire = native_request(bound)
    target = Path(bound[3][0]["path"])
    native.patch_native(target, wire)
    altered = deepcopy(wire)
    altered["base_revision"] = float(wire["base_revision"])
    assert altered == wire
    calls = list(bound[5])
    monkeypatch.setattr(runtime.FileProjectStore, "recover", lambda *_: pytest.fail("wrong literal authorized repair"))
    with pytest.raises(ValueError, match="exact original identity"):
        native.patch_native(target, altered)
    assert bound[5] == calls


def test_python_equal_numbers_cannot_substitute_canonical_business_identity(tmp_path):
    backend, repo = FakeBackend(tmp_path / "native"), MemoryRepository()
    root = tmp_path / "plot"
    document, binding = backend.initial()
    repo.commit(root, document, binding, "import")
    original = request(changes=[{"op": "set", "target": ["title:main"],
        "property": "title.visible", "value": 1}])
    business = deepcopy(original)
    business["changes"][0]["value"] = True
    assert original == business
    command = NormalizedCommand.create("patch", original, business_request=business,
        expected_revision=RevisionToken.of(document))
    assert command.request_digest != command.original_request_digest
    before = deepcopy(repo.values)
    with pytest.raises(ValueError, match="canonical business request"):
        application(backend, repo).execute(root, command)
    assert repo.values == before and not backend.native_writes


def test_journal_read_rechecks_literal_business_identity(tmp_path):
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.project_lifecycle.journal_identity import saved_command

    backend = FakeBackend(tmp_path / "native")
    document, _binding = backend.initial()
    original = request(changes=[{"op": "set", "target": ["title:main"],
        "property": "title.visible", "value": True}])
    command = NormalizedCommand.create("patch", original, expected_revision=RevisionToken.of(document))
    transaction = {"request": deepcopy(original), "request_hash": command.request_digest,
                   "before": document, "normalized_command": command.to_payload()}
    assert saved_command(transaction) == command
    transaction["request"]["changes"][0]["value"] = 1
    transaction["request_hash"] = canonical_json_sha256(transaction["request"], allow_nan=False)
    assert transaction["request"] == original
    with pytest.raises(ValueError, match="saved normalized command"):
        saved_command(transaction)
