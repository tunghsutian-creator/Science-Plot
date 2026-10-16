"""Delivery checkpoint/publication faults; native ports are tested separately."""

from collections import Counter
from test_managed_backend import managed_ir
from sciplot_core.plot_ir import seal_ir
from pathlib import Path
import json
import shutil
import zipfile

import pytest

from sciplot_core.plot_engine import managed_delivery as managed, managed_delivery_publication as managed_publication
from sciplot_core.plot_engine.managed_delivery_contract import normalize_request
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import read
from sciplot_core.plot_protocol.rpc import handle


@pytest.fixture
def case(tmp_path, monkeypatch):
    service = PlotService(backend=object())
    selections, heads = [], {}
    for index in range(2):
        plot = tmp_path / f"plot{index}"
        plot.mkdir()
        source = tmp_path / f"source{index}.csv"
        source.write_bytes(b"original header\n1,2\n3,4\n")
        output = tmp_path / f"artifacts{index}"
        output.mkdir()
        native = output / "document.vsz"
        native.write_bytes(b"fake native fixture; not a native acceptance")
        (output / "build.json").write_text(json.dumps({"compiler_identity": {"test_runtime": "stable"}}))
        heads[str(plot)] = {"document": {"plot_type": "ManagedPlot", "plot_id": f"plot:{index}", "revision": 0,
                "scientific_hash": str(index) * 64, "presentation_hash": "a" * 64,
                "presentation": {"export_configuration": {"formats": ["pdf", "tiff_300"]}},
                "scientific": {"data_sources": [{"source_id": f"raw:{index}", "path": str(source), "sha256": file_sha256(source)}]}},
                "binding": {"document": str(native), "output": str(output), "ir_hash": "c" * 64}}
        selections.append({"plot": str(plot), "plot_id": f"plot:{index}", "revision": 0, "label": f"P0.{index}/0.7"})
    request = {"idempotency_key": "delivery-1", "out": str(tmp_path / "new delivery"),
               "title": "Ordered snapshots", "mode": "native_snapshot", "items": selections}
    calls = Counter()
    failures = set()

    def selection(_service, item, root, out):
        head = heads[item["plot"]]
        for source in head["document"]["scientific"]["data_sources"]:
            if file_sha256(Path(source["path"])) != source["sha256"]:
                raise EngineError("source_changed", "Source changed")
        return head

    def seed_export(plot):
        output = Path(heads[str(plot)]["binding"]["output"]) / "exports"
        output.mkdir(exist_ok=True)
        exports = []
        for fmt, suffix in (("pdf", ".pdf"), ("tiff_300", ".tiff")):
            path = output / ("audited" + suffix)
            path.write_bytes(fmt.encode() + b" exported fixture")
            exports.append({"format": fmt, "path": str(path), "sha256": file_sha256(path)})
        return {"status": "exported", "ready_to_use": True, "publication_qa": {"status": "passed"}, "exports": exports}

    def portable(source, target, imports):
        target.parent.mkdir(parents=True, exist_ok=True)
        imports.mkdir(parents=True)
        shutil.copy2(source, target)
        return {"status": "passed", "native_state_sha256": "b" * 64, "original_sha256": file_sha256(source)}

    for plot, head in heads.items():
        exported = seed_export(Path(plot))
        ir = Path(head["binding"]["output"]) / "ir.json"
        payload = managed_ir()
        payload.update(scientific_hash=head["document"]["scientific_hash"], presentation_hash=head["document"]["presentation_hash"])
        payload = seal_ir(payload)
        head["binding"]["ir_hash"] = payload["ir_hash"]
        exported["ir_hash"] = payload["ir_hash"]
        ir.write_text(json.dumps(payload))
        head["binding"]["ir_path"] = str(ir)
        files = {head["binding"]["document"]: file_sha256(Path(head["binding"]["document"])),
                 **{e["path"]: e["sha256"] for e in exported["exports"]}}
        (Path(plot) / "export-cache.json").write_text(json.dumps({"export": exported, "artifact_files": files}))

    def inspect(binding):
        plot = next(name for name, head in heads.items() if head["binding"] is binding)
        calls[plot] += 1
        if plot in failures:
            raise RuntimeError("injected fresh audit failure")
        return {"document_sha256": file_sha256(Path(binding["document"])), "publication_qa": {"status": "passed"}}

    monkeypatch.setattr(managed, "_selection", selection)
    monkeypatch.setattr(service, "export", lambda *_: pytest.fail("Delivery must not export or rebuild originals"))
    monkeypatch.setattr(managed, "inspect_managed_native", inspect)
    monkeypatch.setattr(managed, "portable_native", portable)
    monkeypatch.setattr(managed_publication, "verify_relocated_native", lambda *_: None)
    return service, request, heads, calls, failures


def test_product_generates_index_originals_canonical_launcher_and_archive(case):
    service, request, heads, calls, _ = case
    result = service.deliver(request)
    assert result["status"] == "complete", result
    assert result["capabilities"] == {"local_managed_semantic_continuation": True, "portable_managed_project": False,
                                      "independent_native_snapshot_editor": True, "human_managed_editor_provided": False}
    out = Path(request["out"])
    index = json.loads((out / "index.json").read_text())
    assert [item["label"] for item in index["items"]] == [item["label"] for item in request["items"]]
    assert index["managed_project_included"] is False
    for item in index["items"]:
        assert (out / item["files"]["editable"]).is_file()
        for source in item["sources"]:
            assert file_sha256(out / source["path"]) == source["sha256"]
    launcher = (out / "Open_in_Veusz.command").read_text()
    assert 'find_sciplot()' in launcher and 'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}"' in launcher
    with zipfile.ZipFile(out / "Figures.zip") as archive:
        assert "Figures.zip" not in archive.namelist()
        assert all(archive.read(name) == (out / name).read_bytes() for name in archive.namelist())
    assert len(calls) == len(heads) == 2


def test_partial_retry_only_audits_unsealed_plot_and_completed_replay_is_read_only(case):
    service, request, _, calls, failures = case
    second = request["items"][1]["plot"]
    failures.add(second)
    first = service.deliver(request)
    assert first["status"] == "partial" and not first["ready_to_use"]
    assert [item["status"] for item in first["items"]] == ["sealed", "failed"]
    assert not Path(request["out"]).exists()
    failures.clear()
    result = service.deliver(request)
    assert result["status"] == "complete", result
    assert calls == {request["items"][0]["plot"]: 1, second: 2}
    before = dict(calls)
    assert service.deliver(request)["status"] == "complete"
    assert calls == before


def test_recover_lost_reply_after_exclusive_install_without_reexport(case, monkeypatch):
    service, request, _, calls, _ = case
    install = managed_publication.install_new_delivery

    def installed_then_lost(candidate, out):
        install(candidate, out)
        raise RuntimeError("injected lost completion after native install")

    monkeypatch.setattr(managed_publication, "install_new_delivery", installed_then_lost)
    result = service.deliver(request)
    assert result["status"] == "blocked" and Path(request["out"]).exists()
    before = dict(calls)
    assert service.deliver(request)["status"] == "complete"
    assert calls == before


def test_changed_published_file_is_preserved_and_blocks_replay(case):
    service, request, _, calls, _ = case
    assert service.deliver(request)["ready_to_use"]
    target = next((Path(request["out"]) / "project").glob("*.vsz"))
    target.write_bytes(b"user manual edits")
    result = service.deliver(request)
    assert result["status"] == "blocked"
    assert result["blocker"]["reason_code"] == "managed_delivery_external_edit"
    assert target.read_bytes() == b"user manual edits"
    assert all(count == 1 for count in calls.values())


def test_edited_sealed_partial_item_is_not_silently_regenerated(case):
    service, request, _, calls, failures = case
    failures.add(request["items"][1]["plot"])
    result = service.deliver(request)
    state = read(Path(result["checkpoint"]) / "delivery.json")
    target = next((Path(state["items"][0]["attempt"]) / "project").glob("*.vsz"))
    target.write_bytes(b"external staged edits")
    failures.clear()
    for _ in range(2):
        result = service.deliver(request)
        assert result["status"] == "partial"
        assert result["items"][0]["status"] == "conflict"
    assert target.read_bytes() == b"external staged edits"
    assert calls[request["items"][0]["plot"]] == 1
    assert not Path(request["out"]).exists()


def test_existing_empty_output_and_changed_request_never_replace_files(case):
    service, request, _, calls, _ = case
    out = Path(request["out"])
    out.mkdir()
    with pytest.raises(EngineError) as caught:
        service.deliver(request)
    assert caught.value.reason_code == "managed_delivery_output_exists"
    assert out.is_dir() and list(out.iterdir()) == [] and not calls


def test_source_drift_and_unknown_mode_are_rejected_before_export(case):
    service, request, heads, calls, _ = case
    source = Path(next(iter(heads.values()))["document"]["scientific"]["data_sources"][0]["path"])
    source.write_bytes(b"changed source")
    with pytest.raises(EngineError, match="Source changed"):
        service.deliver(request)
    assert not calls and not Path(request["out"]).exists()
    with pytest.raises(ValueError):
        normalize_request({**request, "mode": "portable_managed"})


def test_request_key_label_or_order_cannot_change_at_same_destination(case):
    service, request, _, calls, _ = case
    assert service.deliver(request)["ready_to_use"]
    for changed in ({**request, "idempotency_key": "new"}, {**request, "items": list(reversed(request["items"]))}):
        with pytest.raises(EngineError) as caught:
            service.deliver(changed)
        assert caught.value.reason_code == "managed_delivery_request_conflict"
    assert all(count == 1 for count in calls.values())


def test_shared_rpc_contract_routes_deliver_without_plot_parameter(case):
    service, request, _, _, _ = case
    result = handle(service, {"jsonrpc": "2.0", "id": "delivery", "method": "plot.deliver", "params": {"request": request}})
    assert result["result"]["status"] == "complete"
    bad = handle(service, {"jsonrpc": "2.0", "id": "bad", "method": "plot.deliver", "params": {"plot": "/wrong", "request": request}})
    assert bad["error"]["data"]["reason_code"] == "invalid_rpc_params"


def test_snapshot_open_reconnects_only_exact_current_local_authority(case, monkeypatch):
    from sciplot_core.plot_engine import managed_delivery_continuation as managed_continuation

    service, request, heads, _, _ = case
    assert service.deliver(request)["ready_to_use"]
    out = Path(request["out"])
    index = json.loads((out / "index.json").read_text())
    monkeypatch.setattr(managed_continuation, "load_head", lambda path: heads[str(path)])
    with pytest.raises(EngineError) as caught:
        managed_continuation.local_managed_target(out, None)
    assert caught.value.reason_code == "managed_delivery_choose_figure"
    chosen = index["items"][0]
    assert managed_continuation.local_managed_target(out, chosen["id"])["plot"] == Path(request["items"][0]["plot"])
    heads[request["items"][0]["plot"]]["document"]["revision"] = 1
    with pytest.raises(EngineError) as caught:
        managed_continuation.local_managed_target(out, chosen["id"])
    assert caught.value.reason_code == "managed_delivery_original_changed"
    target = out / chosen["files"]["editable"]
    target.write_bytes(b"native snapshot edits must not be discarded")
    with pytest.raises(EngineError) as caught:
        managed_continuation.local_managed_target(out, chosen["id"])
    assert caught.value.reason_code == "managed_delivery_snapshot_changed"


def _existing_exports(case, monkeypatch):
    service, request, heads, calls, _ = case
    calls.clear()
    monkeypatch.setattr(managed, "inspect_managed_native", lambda binding: {
        "document_sha256": file_sha256(Path(binding["document"])), "publication_qa": {"status": "passed"}})


def test_existing_sealed_exports_get_fresh_native_qa_without_rebuild(case, monkeypatch):
    _existing_exports(case, monkeypatch)
    service, request, _, calls, _ = case
    assert service.deliver(request)["ready_to_use"]
    assert not calls, "Packaging sealed current exports must not trigger runtime-refresh/recompile."


@pytest.mark.parametrize("change", ["wrong_ir", "changed_figure", "missing_figure", "missing_qa", "missing_cached_qa"])
def test_cache_guards_never_reexport_or_overwrite_existing_figures(case, monkeypatch, change):
    _existing_exports(case, monkeypatch)
    service, request, _, calls, _ = case
    cache_file = Path(request["items"][0]["plot"]) / "export-cache.json"
    cache = json.loads(cache_file.read_text())
    target = Path(cache["export"]["exports"][0]["path"])
    if change == "wrong_ir":
        cache["export"]["ir_hash"] = "e" * 64
        cache_file.write_text(json.dumps(cache))
    elif change == "changed_figure":
        target.write_bytes(b"user-edited existing figure")
    elif change == "missing_figure":
        target.unlink()
    elif change == "missing_cached_qa":
        cache["export"].pop("publication_qa")
        cache_file.write_text(json.dumps(cache))
    else:
        monkeypatch.setattr(managed, "inspect_managed_native", lambda binding: {"document_sha256": file_sha256(Path(binding["document"]))})
    before = target.read_bytes() if target.exists() else None
    result = service.deliver(request)
    assert not result["ready_to_use"] and not Path(request["out"]).exists()
    assert (target.read_bytes() if target.exists() else None) == before
    assert not calls


@pytest.mark.parametrize("phase", ["sealed_partial", "complete"])
@pytest.mark.parametrize("change", ["replace", "missing"])
def test_original_native_exact_seal_blocks_resume_and_complete_replay(case, phase, change):
    service, request, heads, calls, failures = case
    if phase == "sealed_partial":
        failures.add(request["items"][1]["plot"])
    first = service.deliver(request)
    assert first["status"] == ("partial" if failures else "complete")
    failures.clear()
    native = Path(heads[request["items"][0]["plot"]]["binding"]["document"])
    if change == "replace":
        native.write_bytes(b"another native generation with unchanged semantic head")
    else:
        native.unlink()
    before = dict(calls)
    result = service.deliver(request)
    assert result["status"] == "blocked"
    assert result["blocker"]["reason_code"] == "managed_delivery_original_native_changed"
    assert calls == before
    assert (native.read_bytes() if native.exists() else None) == (b"another native generation with unchanged semantic head" if change == "replace" else None)


def test_publication_validates_original_seal_after_candidate_relocation(case, monkeypatch):
    service, request, heads, _, _ = case
    native = Path(heads[request["items"][0]["plot"]]["binding"]["document"])
    monkeypatch.setattr(managed_publication, "verify_relocated_native", lambda *_: native.write_bytes(b"concurrent original mutation"))
    result = service.deliver(request)
    assert result["status"] == "blocked" and not Path(request["out"]).exists()
    assert result["blocker"]["reason_code"] == "managed_delivery_original_native_changed"
    assert native.read_bytes() == b"concurrent original mutation"


def test_native_save_must_consume_freshly_audited_original_bytes(case, monkeypatch):
    service, request, _, _, _ = case
    save = managed.portable_native

    def wrong_original(*args):
        return {**save(*args), "original_sha256": "0" * 64}

    monkeypatch.setattr(managed, "portable_native", wrong_original)
    result = service.deliver(request)
    assert result["status"] == "partial" and not Path(request["out"]).exists()
    assert all(item["error"]["reason_code"] == "managed_delivery_native_changed" for item in result["items"])


def test_reconnect_requires_exact_members_and_original_native_seal(case, monkeypatch):
    from sciplot_core.plot_engine import managed_delivery_continuation as continuation

    service, request, heads, _, _ = case
    assert service.deliver(request)["ready_to_use"]
    out = Path(request["out"])
    item = json.loads((out / "index.json").read_text())["items"][0]
    monkeypatch.setattr(continuation, "load_head", lambda path: heads[str(path)])
    (out / ".DS_Store").write_bytes(b"incidental standalone Finder metadata")
    assert continuation.local_managed_target(out, item["id"])["plot"] == Path(request["items"][0]["plot"])
    extra = out / "another-project.vsz"
    extra.write_bytes(b"unindexed user project")
    with pytest.raises(EngineError) as caught:
        continuation.local_managed_target(out, item["id"])
    assert caught.value.reason_code == "managed_delivery_snapshot_changed"
    extra.unlink()
    Path(heads[request["items"][0]["plot"]]["binding"]["document"]).unlink()
    with pytest.raises(EngineError) as caught:
        continuation.local_managed_target(out, item["id"])
    assert caught.value.reason_code == "managed_delivery_original_native_changed"


def test_missing_cache_blocks_without_export_or_rebuild(case):
    service, request, _, calls, _ = case
    for selection in request["items"]:
        (Path(selection["plot"]) / "export-cache.json").unlink()
    result = service.deliver(request)
    assert result["status"] == "partial" and not calls
    assert all(item["error"]["reason_code"] == "managed_delivery_cache_missing" for item in result["items"])



def test_publication_checks_original_again_after_exclusive_install(case, monkeypatch):
    service, request, heads, _, _ = case
    install = managed_publication.install_new_delivery
    native = Path(heads[request["items"][0]["plot"]]["binding"]["document"])

    def install_then_original_changes(candidate, out):
        install(candidate, out)
        native.write_bytes(b"concurrent edit at publication boundary")

    monkeypatch.setattr(managed_publication, "install_new_delivery", install_then_original_changes)
    result = service.deliver(request)
    assert result["status"] == "blocked" and not result["ready_to_use"]
    assert result["blocker"]["reason_code"] == "managed_delivery_original_native_changed"
    assert Path(request["out"]).is_dir(), "Published evidence is preserved even when final currentness changed."
    assert native.read_bytes() == b"concurrent edit at publication boundary"
