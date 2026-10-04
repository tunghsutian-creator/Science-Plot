"""Failure injection for native creation orchestration; fixture bytes are not VSZ QA."""

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sciplot_core import rheology_tts_native as native
from sciplot_core import rheology_tts_render_creation as creation
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_spec import compile_tts_spec


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _snapshot(root):
    return {str(path.relative_to(root)): (file_sha256(path), path.stat().st_ino,
                                        path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    source, prepared = tmp_path / "source.csv", tmp_path / "prepared.json"
    source.write_text("synthetic fixture\nx,y\n1,3\n2,4\n")
    prepared.write_text('{"fixture": "not measurement"}')
    def binding(path):
        return {"path": str(path), "sha256": file_sha256(path)}
    spec = compile_tts_spec({"version": 1,
        "source_binding": {"sources": [binding(source)], "prepared_plan": binding(prepared)},
        "transform_ledger": {"operation": "fixture identity"},
        "figures": [{"id": identifier, "width_mm": 60, "height_mm": 55, "panels": [{
            "id": "panel", "rect_mm": [0, 0, 60, 55], "x_label": "x", "y_label": "y",
            "series": [{"label": "fixture", "x": [1, 2], "y": [3, 4],
                        "color": "#222222", "marker": "circle"}]}]}
            for identifier in ("Alpha", "Beta")]})
    case = SimpleNamespace(spec=spec, out=tmp_path / "native", source=source,
                           prepared=prepared, saves=[], exports=[])

    def save(figure, path):
        case.saves.append(figure["id"])
        assert not path.exists(), "A native document must never be overwritten."
        path.write_bytes(f"orchestration fixture only: {figure['id']}".encode())

    def export(path, out, figure, *, check_presentation):
        assert check_presentation is True
        case.exports.append(figure["id"])
        names, digest = creation._names(figure["id"]), file_sha256(path)
        exports = []
        for fmt in creation._FORMATS:
            target = out / names[fmt]
            target.write_bytes(f"fixture export {figure['id']} {fmt}".encode())
            exports.append({"format": fmt, "path": str(target), "sha256": file_sha256(target)})
        audit = {"status": "passed", "document": str(path), "document_sha256": digest,
                 "test_fixture_only": True}
        audit_path = out / names["audit"]
        _write_json(audit_path, audit)
        return {"document": str(path), "document_sha256": digest, "export_dir": str(out),
                "native_audit": audit, "native_audit_path": str(audit_path), "exports": exports}

    monkeypatch.setattr(native, "save_native_figure", save)
    case.export = export
    case.run = lambda **kwargs: creation.render_native_creation(
        case.spec, case.out, resume=kwargs.pop("resume", False),
        export_figure=kwargs.pop("export", case.export), **kwargs)
    case.state_path = lambda identifier="Beta": case.out / ".creation" / f"{identifier}.json"
    case.state = lambda identifier="Beta": json.loads(case.state_path(identifier).read_text())
    return case


def _fail_second(case):
    def export(path, out, figure, **kwargs):
        if figure["id"] == "Beta":
            (out / "Beta.pdf").write_bytes(b"unsealed partial export")
            raise RuntimeError("injected partial export failure")
        return case.export(path, out, figure, **kwargs)
    with pytest.raises(RuntimeError, match="partial export"):
        case.run(export=export)


def test_second_partial_export_resume_reuses_vsz_and_completed_receipt(scenario):
    case = scenario
    _fail_second(case)
    assert [case.state(identifier)["state"] for identifier in ("Alpha", "Beta")] == ["completed", "saved"]
    old_attempt = case.state()["attempts"][0]
    partial = creation._stage(case.out, "Beta", old_attempt) / "Beta.pdf"
    saved = {path: (file_sha256(path), path.stat().st_ino, path.stat().st_mtime_ns)
             for path in case.out.glob("*.vsz")}
    first = _snapshot(case.out)
    result = case.run(resume=True)
    assert case.saves == ["Alpha", "Beta"] and case.exports == ["Alpha", "Beta"]
    assert [item["id"] for item in result["figures"]] == ["Alpha", "Beta"]
    assert all((file_sha256(path), path.stat().st_ino, path.stat().st_mtime_ns) == value
               for path, value in saved.items())
    assert partial.read_bytes() == b"unsealed partial export"
    assert len(case.state()["attempts"]) == 2
    assert all(_snapshot(case.out)[name] == value for name, value in first.items()
               if Path(name).name.startswith("Alpha"))
    complete = _snapshot(case.out)
    assert case.run(resume=True) == result == creation.verify_native_creation(case.spec, case.out)
    assert _snapshot(case.out) == complete
    assert case.saves == ["Alpha", "Beta"] and case.exports == ["Alpha", "Beta"]
    with pytest.raises(FileExistsError, match="explicit resume"):
        case.run()


@pytest.mark.parametrize("linked", [False, True])
def test_sealed_partial_publication_is_resumed_without_save_or_export(scenario, monkeypatch, linked):
    case, original_link, calls = scenario, creation.os.link, []

    def link(source, target):
        if target.parent != case.out or target.name not in creation._names("Alpha").values():
            return original_link(source, target)
        calls.append(target)
        if len(calls) == 2:
            if linked:
                original_link(source, target)
            raise OSError("injected publication interruption")
        return original_link(source, target)

    monkeypatch.setattr(creation.os, "link", link)
    with pytest.raises(OSError, match="publication interruption"):
        case.run()
    state = case.state("Alpha")
    assert state["state"] == "saved" and state["receipt"] is not None
    assert state["sealed_attempt"] in state["attempts"]
    published = {path: (file_sha256(path), path.stat().st_ino, path.stat().st_mtime_ns)
                 for path in case.out.iterdir() if path.is_file()}
    monkeypatch.setattr(creation.os, "link", original_link)
    case.run(resume=True)
    assert case.saves == ["Alpha", "Beta"] and case.exports == ["Alpha", "Beta"]
    assert all((file_sha256(path), path.stat().st_ino, path.stat().st_mtime_ns) == value
               for path, value in published.items())
    assert not list(case.out.glob(".creation-*"))


@pytest.mark.parametrize("failure", ["before_save", "after_save", "saved_checkpoint"])
def test_uncertain_save_never_regenerates_even_when_document_is_missing(scenario, monkeypatch, failure):
    case, save, write = scenario, native.save_native_figure, creation.atomic_write_json

    def interrupted_save(figure, path):
        if failure == "after_save":
            save(figure, path)
        raise RuntimeError("injected uncertain save")

    def interrupted_checkpoint(path, state):
        if state.get("state") == "saved":
            raise RuntimeError("injected uncertain save")
        return write(path, state)

    if failure == "saved_checkpoint":
        monkeypatch.setattr(creation, "atomic_write_json", interrupted_checkpoint)
    else:
        monkeypatch.setattr(native, "save_native_figure", interrupted_save)
    with pytest.raises(RuntimeError, match="uncertain save"):
        case.run()
    assert case.state("Alpha")["state"] == "saving"
    before = _snapshot(case.out)
    monkeypatch.setattr(native, "save_native_figure", save)
    monkeypatch.setattr(creation, "atomic_write_json", write)
    with pytest.raises(ValueError, match="Uncertain native Save"):
        case.run(resume=True)
    assert _snapshot(case.out) == before and not case.exports


@pytest.mark.parametrize("target", ["source", "prepared", "spec", "ledger", "document",
                                   "sidecar", "missing_document", "missing_sidecar"])
def test_saved_bindings_reject_drift_without_any_retry_side_effect(scenario, target):
    case = scenario
    _fail_second(case)
    if target in {"source", "prepared"}:
        getattr(case, target).write_text("changed source bytes")
    elif target == "spec":
        case.spec["figures"][1]["panels"][0]["series"][0]["y_values"][0] += 1
    elif target == "ledger":
        case.spec["transform_ledger"]["operation"] = "changed scientific ledger"
    else:
        suffix = ".vsz" if "document" in target else ".spec.json"
        path = case.out / ("Beta" + suffix)
        if target.startswith("missing"):
            path.unlink()
        else:
            path.write_text("changed saved evidence")
    before, calls = _snapshot(case.out), (case.saves[:], case.exports[:])
    with pytest.raises(ValueError, match="changed|missing"):
        case.run(resume=True)
    assert _snapshot(case.out) == before and (case.saves, case.exports) == calls


@pytest.mark.parametrize("target", ["audit", "export", "sealed_export", "receipt", "receipt_export",
                                   "receipt_audit", "artifact_digest", "sealed_attempt", "attempts",
                                   "extra_checkpoint", "checkpoint_array", "checkpoint_state", "format_array",
                                   "version_boolean", "version_float"])
def test_completed_evidence_tampering_blocks_read_and_resume(scenario, target):
    case = scenario
    case.run()
    state = case.state()
    if target in {"audit", "export", "sealed_export"}:
        name = creation._names("Beta")["audit" if target == "audit" else "pdf"]
        directory = (creation._stage(case.out, "Beta", state["sealed_attempt"])
                     if target == "sealed_export" else case.out)
        (directory / name).write_text("tampered evidence")
    else:
        if target == "receipt":
            state["receipt"]["document_sha256"] = "0" * 64
        elif target == "receipt_export":
            state["receipt"]["exports"][0]["path"] = "/unbound.pdf"
        elif target == "receipt_audit":
            state["receipt"]["native_audit"]["status"] = "failed"
        elif target == "artifact_digest":
            state["artifacts"]["Beta.pdf"] = "0" * 64
        elif target == "sealed_attempt":
            state["sealed_attempt"] = "f" * 32
        elif target == "attempts":
            state["attempts"] *= 2
        elif target == "extra_checkpoint":
            state["unknown"] = True
        elif target == "checkpoint_array":
            state = []
        elif target == "format_array":
            state["receipt"]["exports"][0]["format"] = []
        elif target.startswith("version_"):
            state["version"] = True if target == "version_boolean" else 1.0
        else:
            state["state"] = []
        _write_json(case.state_path(), state)
    before, calls = _snapshot(case.out), (case.saves[:], case.exports[:])
    for action in (lambda: case.run(resume=True),
                   lambda: creation.verify_native_creation(case.spec, case.out)):
        with pytest.raises(ValueError):
            action()
    assert _snapshot(case.out) == before and (case.saves, case.exports) == calls


@pytest.mark.parametrize("target", ["document", "sidecar", "checkpoint", "export", "staged_export"])
@pytest.mark.parametrize("link_kind", ["soft", "hard"])
def test_linked_evidence_rejected_before_resume(scenario, target, link_kind):
    case = scenario
    case.run()
    state = case.state()
    paths = {"document": case.out / "Beta.vsz", "sidecar": case.out / "Beta.spec.json",
             "checkpoint": case.state_path(), "export": case.out / "Beta.pdf",
             "staged_export": creation._stage(case.out, "Beta", state["sealed_attempt"]) / "Beta.pdf"}
    path, outside = paths[target], case.out.parent / "preserved_alias"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    if link_kind == "soft":
        path.symlink_to(outside)
    else:
        path.hardlink_to(outside)
    before, data = _snapshot(case.out), outside.read_bytes()
    with pytest.raises(ValueError, match="symbolic|unaliased"):
        case.run(resume=True)
    assert _snapshot(case.out) == before and outside.read_bytes() == data
    assert case.saves == ["Alpha", "Beta"] and case.exports == ["Alpha", "Beta"]


@pytest.mark.parametrize("target", ["unknown", "checkpoint", "attempt", "stage_file", "native"])
def test_unknown_partial_never_adopted(scenario, target):
    case = scenario
    _fail_second(case)
    targets = {"unknown": case.out / "unknown", "checkpoint": case.out / ".creation/other.json",
               "attempt": case.out / ".creation/Beta.exports/unrecorded",
               "stage_file": creation._stage(case.out, "Beta", case.state()["attempts"][0]) / "unknown"}
    if target == "native":
        case.state_path().unlink()
    else:
        targets[target].write_text("unrecognized partial must survive")
    before = _snapshot(case.out)
    with pytest.raises(ValueError, match="Unrecognized|lack a valid|Invalid native creation"):
        case.run(resume=True)
    assert _snapshot(case.out) == before


@pytest.mark.parametrize("target", ["document", "sidecar", "checkpoint", "export"])
def test_later_figure_created_during_previous_export_is_not_overwritten(scenario, target):
    case = scenario
    suffix = {"document": ".vsz", "sidecar": ".spec.json", "checkpoint": ".json", "export": ".pdf"}[target]
    directory = case.out / ".creation" if target == "checkpoint" else case.out
    external = directory / ("Beta" + suffix)

    def export(path, out, figure, **kwargs):
        result = case.export(path, out, figure, **kwargs)
        external.write_bytes(b"concurrent external content")
        return result

    with pytest.raises(ValueError):
        case.run(export=export)
    assert external.read_bytes() == b"concurrent external content"
    assert case.saves == ["Alpha"] and case.exports == ["Alpha"]


def test_publication_collision_never_replaces_concurrent_destination(scenario, monkeypatch):
    case, original = scenario, os.link

    def concurrent_link(source, target):
        if target == case.out / "Alpha.pdf":
            target.write_bytes(b"concurrent user artifact")
        return original(source, target)

    monkeypatch.setattr(creation.os, "link", concurrent_link)
    with pytest.raises(FileExistsError):
        case.run()
    assert (case.out / "Alpha.pdf").read_bytes() == b"concurrent user artifact"
    monkeypatch.setattr(creation.os, "link", original)
    before = _snapshot(case.out)
    with pytest.raises(ValueError, match="Changed or unsealed"):
        case.run(resume=True)
    assert _snapshot(case.out) == before and case.saves == ["Alpha"]


def test_resume_requires_bool_and_case_unique_names(scenario):
    case = scenario
    with pytest.raises(ValueError, match="boolean"):
        case.run(resume="yes")
    case.spec["figures"][1] = deepcopy(case.spec["figures"][0])
    case.spec["figures"][1]["id"] = "aLPHA"
    with pytest.raises(ValueError, match="unique"):
        case.run()
    assert not case.out.exists() and not case.saves


@pytest.mark.parametrize("target", ["sidecar", "checkpoint", "document"])
def test_first_save_exclusively_preserves_concurrent_files(scenario, monkeypatch, target):
    case, original = scenario, creation._new_json
    path = {"sidecar": case.out / "Alpha.spec.json", "checkpoint": case.state_path("Alpha"),
            "document": case.out / "Alpha.vsz"}[target]

    def collide(destination, value):
        if destination == path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"concurrent user content")
        original(destination, value)
        if target == "document" and destination == case.state_path("Alpha"):
            path.write_bytes(b"concurrent user content")

    monkeypatch.setattr(creation, "_new_json", collide)
    with pytest.raises(FileExistsError):
        case.run()
    assert path.read_bytes() == b"concurrent user content"
    if target == "document":
        candidate = case.out / ".creation/Alpha.saving/Alpha.vsz"
        assert candidate.read_bytes() == b"orchestration fixture only: Alpha"
        before = _snapshot(case.out)
        with pytest.raises(ValueError, match="Uncertain native Save"):
            case.run(resume=True)
        assert _snapshot(case.out) == before
    assert not case.exports


@pytest.mark.parametrize("fmt", ["pdf", "tiff_300", "png_300"])
def test_unsealed_shared_export_temporary_file_is_retained_and_retry_uses_new_attempt(scenario, fmt):
    case = scenario
    suffix = creation._names("Alpha")[fmt].removeprefix("Alpha")
    partials = []

    def interrupted(path, out, figure, **kwargs):
        temporary = out / f".{figure['id']}.{'a' * 32}{suffix}"
        temporary.write_bytes(b"shared exporter interrupted during native Export")
        partials.append(temporary)
        raise RuntimeError("injected shared export temporary")

    with pytest.raises(RuntimeError, match="shared export temporary"):
        case.run(export=interrupted)
    saved = _snapshot(case.out)
    case.run(resume=True)
    assert all(partial.read_bytes() == b"shared exporter interrupted during native Export" for partial in partials)
    assert case.saves == ["Alpha", "Beta"] and case.exports == ["Alpha", "Beta"]
    assert _snapshot(case.out)["Alpha.vsz"] == saved["Alpha.vsz"]
    assert len(case.state("Alpha")["attempts"]) == 2


@pytest.mark.parametrize("name", [".Beta.bad.pdf", ".Other.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf",
                                  ".Beta.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"])
def test_sealed_attempt_rejects_extra_temporary_files(scenario, name):
    case = scenario
    case.run()
    (creation._stage(case.out, "Beta", case.state()["sealed_attempt"]) / name).write_bytes(b"extra")
    before = _snapshot(case.out)
    with pytest.raises(ValueError, match="Unrecognized native export partial"):
        case.run(resume=True)
    assert _snapshot(case.out) == before


def test_sealed_audit_receipt_tampering_is_rejected_before_first_publication(scenario, monkeypatch):
    case, publish = scenario, creation._publish_exports

    def interrupted(*args):
        raise RuntimeError("injected before publication")

    monkeypatch.setattr(creation, "_publish_exports", interrupted)
    with pytest.raises(RuntimeError, match="before publication"):
        case.run()
    state = case.state("Alpha")
    state["receipt"]["native_audit"]["unchecked_annotation"] = "tampered"
    _write_json(case.state_path("Alpha"), state)
    before = _snapshot(case.out)
    monkeypatch.setattr(creation, "_publish_exports", publish)
    with pytest.raises(ValueError, match="Sealed native audit content"):
        case.run(resume=True)
    assert _snapshot(case.out) == before and not list(case.out.glob("*.pdf"))


@pytest.mark.parametrize("target", ["source", "prepared", "document", "sidecar", "checkpoint"])
def test_export_time_drift_is_not_sealed_or_published(scenario, target):
    case = scenario

    def drift(path, out, figure, **kwargs):
        result = case.export(path, out, figure, **kwargs)
        changed = {"source": case.source, "prepared": case.prepared, "document": path,
                   "sidecar": path.with_suffix(".spec.json"),
                   "checkpoint": case.state_path("Alpha")}[target]
        if target == "checkpoint":
            state = case.state("Alpha")
            state["concurrent_annotation"] = "preserve"
            _write_json(changed, state)
        else:
            changed.write_text("concurrent evidence change")
        return result

    with pytest.raises(ValueError, match="changed"):
        case.run(export=drift)
    assert not list(case.out.glob("*.pdf")) and case.state("Alpha")["sealed_attempt"] is None
    if target == "checkpoint":
        assert case.state("Alpha")["concurrent_annotation"] == "preserve"
    assert case.saves == ["Alpha"] and case.exports == ["Alpha"]


def test_new_nested_output_creates_parent_before_session_lease(scenario):
    case = scenario
    case.out = case.out / "new_parent" / "native"
    assert case.run()["status"] == "completed"


def test_completed_missing_export_uses_sealed_copy_without_regeneration(scenario):
    case = scenario
    result = case.run()
    (case.out / "Beta.pdf").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        creation.verify_native_creation(case.spec, case.out)
    assert case.run(resume=True) == result
    assert case.saves == ["Alpha", "Beta"] and case.exports == ["Alpha", "Beta"]


@pytest.mark.parametrize("tamper", [False, True])
def test_native_audit_json_round_trip_accepts_tuples_but_rejects_changed_values(scenario, tamper):
    case = scenario

    def export(path, out, figure, **kwargs):
        result = case.export(path, out, figure, **kwargs)
        result["native_audit"]["presentation"] = {"series": [{"fields": [
            {"actual": ("",), "expected": ("",)}]}]}
        _write_json(Path(result["native_audit_path"]), result["native_audit"])
        if tamper:
            result["native_audit"]["presentation"]["series"][0]["fields"][0]["actual"] = ("changed",)
        return result

    if tamper:
        with pytest.raises(ValueError, match="Native creation audit content changed"):
            case.run(export=export)
        assert not list(case.out.glob("*.pdf")) and case.state("Alpha")["sealed_attempt"] is None
    else:
        result = case.run(export=export)
        persisted = result["figures"][0]["native_audit"]["presentation"]
        assert persisted["series"][0]["fields"][0] == {"actual": [""], "expected": [""]}
        before = _snapshot(case.out)
        assert case.run(resume=True) == result == creation.verify_native_creation(case.spec, case.out)
        assert _snapshot(case.out) == before
        assert case.saves == ["Alpha", "Beta"] and case.exports == ["Alpha", "Beta"]
