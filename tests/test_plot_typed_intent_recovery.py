"""Typed text edits exercise the real managed journal with a fake candidate writer.

These are unit fault-injection tests. They do not certify the native Veusz worker.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_managed_rollback import ManagedFixtureBackend
from test_plot_engine import SimulatedCrash
from test_plot_typed_intent import _document, _request

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine import execution
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import commit, load_head, read, transaction_path


class FigureCandidateBackend(ManagedFixtureBackend):
    """Keep the original native file immutable and export the saved candidate."""

    def refresh_binding(self, binding: dict, applied: dict) -> dict:
        updated = super().refresh_binding(binding, applied)
        updated["document"] = applied["document"]
        return updated

    def export(self, binding: dict) -> dict:
        self.native = Path(binding["document"])
        return super().export(binding)


def _engine(tmp_path: Path) -> tuple[PlotService, Path, FigureCandidateBackend, Path, Path]:
    document = _document(tmp_path)
    source = tmp_path / "figure.csv"
    backend = FigureCandidateBackend(tmp_path / "backend")
    backend.raw = source
    original_native = backend.native
    binding = {"document": str(original_native), "fingerprint": {"files": {
        str(source): file_sha256(source), str(original_native): file_sha256(original_native)}}}
    root = tmp_path / "plot"
    commit(root, document, binding, "import")
    return PlotService(backend), root, backend, source, original_native


def _restart(tmp_path: Path, source: Path) -> tuple[PlotService, FigureCandidateBackend]:
    backend = FigureCandidateBackend(tmp_path / "backend")
    backend.raw = source
    return PlotService(backend), backend


def test_identical_typed_retry_and_equivalent_alias_share_one_real_patch_transaction(tmp_path: Path) -> None:
    service, root, backend, source, original_native = _engine(tmp_path)
    before = load_head(root)["document"]
    original_source = source.read_bytes()
    original_native_bytes = original_native.read_bytes()
    applied = service.intent(root, _request(mode="apply"))
    after = load_head(root)["document"]
    assert applied["status"] == "complete" and applied["ready_to_use"] is True
    assert after["revision"] == 1 and after["scientific_hash"] == before["scientific_hash"]
    assert after["presentation_hash"] != before["presentation_hash"]
    assert source.read_bytes() == original_source and original_native.read_bytes() == original_native_bytes
    writes = backend.native_writes
    assert service.intent(root, _request(mode="apply"))["replayed"] is True
    assert backend.native_writes == writes == 1

    # The facade normalizes both selectors to the same stable semantic patch.
    alias = _request(mode="apply", target_id="axis:xb")
    alias.pop("target_label")
    assert service.intent(root, alias)["replayed"] is True
    assert backend.native_writes == writes
    with pytest.raises(EngineError) as changed:
        service.intent(root, _request(mode="apply", value="Different text"))
    assert changed.value.reason_code == "document_idempotency_conflict"
    assert backend.native_writes == writes


@pytest.mark.parametrize("drift", ["source", "native"])
def test_interrupted_typed_apply_requires_original_base_and_recovers_once(
        tmp_path: Path, drift: str, monkeypatch: pytest.MonkeyPatch) -> None:
    service, root, backend, source, original_native = _engine(tmp_path)
    before = load_head(root)["document"]
    path = source if drift == "source" else original_native
    original_bytes = path.read_bytes()
    original_native_bytes = original_native.read_bytes()
    actual_apply = backend.apply

    def crash_after_candidate(binding: dict, review: dict) -> dict:
        actual_apply(binding, review)
        raise SimulatedCrash()

    monkeypatch.setattr(backend, "apply", crash_after_candidate)
    with pytest.raises(SimulatedCrash):
        service.intent(root, _request(mode="apply"))
    saved = read(transaction_path(root, "same-key"))
    assert saved["phase"] == "applying"
    assert saved["before"] == before and load_head(root)["document"] == before
    assert backend.native_writes == 1

    with pytest.raises(EngineError) as different_key:
        service.intent(root, _request(mode="apply", idempotency_key="second-edit"))
    assert different_key.value.reason_code == "document_transaction_pending"
    assert different_key.value.repair == {
        "action": "plot.describe", "plot": str(root), "description": {"scope": "summary"},
        "pending": {"idempotency_key": "same-key", "phase": "applying"},
    }
    with pytest.raises(EngineError) as plan:
        service.intent(root, _request(idempotency_key="second-edit"))
    assert plan.value.reason_code == "document_transaction_pending"
    assert plan.value.repair == different_key.value.repair
    assert read(transaction_path(root, "same-key")) == saved
    assert not transaction_path(root, "second-edit").exists()
    with pytest.raises(EngineError) as changed_intent:
        service.intent(root, _request(mode="apply", value="Unrelated text"))
    assert changed_intent.value.reason_code == "document_idempotency_conflict"
    assert backend.native_writes == 1

    restarted, recovered_backend = _restart(tmp_path, source)
    path.write_bytes(original_bytes + b"external modification")
    blocked = restarted.intent(root, _request(mode="apply"))
    assert blocked["status"] == "blocked"
    assert blocked["error"]["reason_code"] == "document_inputs_changed"
    assert load_head(root)["document"] == before and recovered_backend.native_writes == 1

    path.write_bytes(original_bytes)
    finished = restarted.intent(root, _request(mode="apply"))
    assert finished["status"] == "complete" and finished["revision"] == 1
    assert recovered_backend.native_writes == 1 and recovered_backend.calls["preview"] == 0
    assert original_native.read_bytes() == original_native_bytes
    assert load_head(root)["document"]["scientific_hash"] == before["scientific_hash"]


def test_interrupted_head_commit_replays_without_second_candidate_or_stale_delivery(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, root, backend, source, original_native = _engine(tmp_path)
    actual_commit = execution.commit

    def crash_after_commit(*args: object) -> None:
        actual_commit(*args)
        raise SimulatedCrash()

    monkeypatch.setattr(execution, "commit", crash_after_commit)
    with pytest.raises(SimulatedCrash):
        service.intent(root, _request(mode="apply"))
    assert read(transaction_path(root, "same-key"))["phase"] == "native_applied"
    assert load_head(root)["document"]["revision"] == 1 and backend.native_writes == 1
    monkeypatch.setattr(execution, "commit", actual_commit)

    restarted, recovered_backend = _restart(tmp_path, source)
    finished = restarted.intent(root, _request(mode="apply"))
    assert finished["status"] == "complete" and finished["revision"] == 1
    assert recovered_backend.native_writes == 1 and recovered_backend.calls["preview"] == 0
    assert original_native.read_bytes() == b"original native state"

    newer = _request(mode="apply", base_revision=1, idempotency_key="next-text",
                     target_id="axis:xb", value="Frequency / Hz")
    newer.pop("target_label")
    assert restarted.intent(root, newer)["revision"] == 2
    writes = recovered_backend.native_writes
    historical = restarted.intent(root, _request(mode="apply"))
    assert historical["historical"] is True and historical["ready_to_use"] is False
    assert historical["exports"] == [] and historical["current_revision"] == 2
    assert recovered_backend.native_writes == writes


def test_typed_retry_after_completed_source_drift_fails_closed(tmp_path: Path) -> None:
    service, root, backend, source, _ = _engine(tmp_path)
    assert service.intent(root, _request(mode="apply"))["status"] == "complete"
    source.write_bytes(source.read_bytes() + b"changed source")
    with pytest.raises(EngineError) as stale:
        service.intent(root, _request(mode="apply"))
    assert stale.value.reason_code == "document_inputs_changed"
    assert backend.native_writes == 1


def test_pending_repair_survives_rpc_cli_and_mcp_error_adapters(tmp_path: Path) -> None:
    from sciplot_core.cli.value_io import _cli_runtime_error_payload
    from sciplot_core.mcp_server.errors import error_payload
    from sciplot_core.plot_protocol.rpc import RemoteError, error_response

    error = EngineError("document_transaction_pending", "Finish or reject the pending transaction first.",
                        action="plot.describe", plot=str(tmp_path / "plot"),
                        description={"scope": "summary"},
                        pending={"idempotency_key": "original", "phase": "applying"})
    wire = error_response(7, error)
    remote = RemoteError(wire["error"])
    assert wire["error"]["data"]["reason_code"] == "document_transaction_pending"
    assert wire["error"]["data"]["repair"] == error.repair
    assert _cli_runtime_error_payload(remote)["repair"] == error.repair
    assert error_payload(remote)["repair"] == error.repair
