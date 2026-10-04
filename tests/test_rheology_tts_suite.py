from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sciplot_core.cli.parsers import build_parser
from sciplot_core.workflow.rheology_tts_plot_helpers import master_panel, frequency_panel, arrhenius_panel
from sciplot_core.workflow.rheology_tts_suite import _check_sources, _compiled_figures, _publish


def test_revision_output_keeps_original_suite_and_uses_distinct_evidence(tmp_path: Path):
    from sciplot_core.workflow.rheology_tts_suite import _output_paths

    source = tmp_path / "FS210.csv"
    source.write_text("raw")
    old = tmp_path / "Figures"
    (old / "data").mkdir(parents=True)
    (old / "data" / "delivery_manifest.json").write_text(json.dumps({
        "kind": "sciplot_rheology_tts_suite", "sources": [{"path": str(source)}]
    }))
    delivery, work = _output_paths(source, old / "Revision_02")
    assert delivery == old / "Revision_02"
    assert work == tmp_path / ".sciplot" / "Figures__Revision_02"
    assert not delivery.exists()


def test_revision_output_rejects_unrelated_parent_or_hidden_evidence(tmp_path: Path):
    from sciplot_core.workflow.rheology_tts_suite import _output_paths

    source = tmp_path / "FS210.csv"
    with pytest.raises(ValueError, match="source-adjacent"):
        _output_paths(source, tmp_path / "unrelated" / "child")
    with pytest.raises(ValueError, match="hidden evidence"):
        _output_paths(source, tmp_path / ".sciplot")


def test_source_change_blocks_reexport(tmp_path: Path):
    path = tmp_path / "source.csv"
    path.write_bytes(b"raw,original\n")
    sources = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
    _check_sources(sources)
    path.write_bytes(b"raw,changed\n")
    with pytest.raises(ValueError, match="Original source changed"):
        _check_sources(sources)


def test_master_plan_preserves_each_temperature_acquisition_order():
    blocks = [{"points": [{"omega_reduced_rad_s": x, "storage_modulus_Pa": y} for x, y in values]}
              for values in ([(10, 100), (1, 20)], [(40, 130), (4, 30)])]
    sample = {"sample_id": "HDPE-2UDC", "polymer": "HDPE", "udc_wt_percent": 2, "master_curves": blocks}
    result = master_panel([sample], "d", "TTS")
    assert [curve["x"] for curve in result["series"]] == [[10, 1], [40, 4]]
    assert [curve["y"] for curve in result["series"]] == [[100, 20], [130, 30]]
    assert all(curve["line_style"] == "none" for curve in result["series"])
    assert [curve["label"] for curve in result["series"]] == ["HDPE-2UDC", ""]


def test_frequency_plan_does_not_mix_polymer_and_encodes_both_metrics():
    points = [{"omega_rad_s": .1, "storage_modulus_Pa": 2, "loss_modulus_Pa": 5}]
    samples = [{"polymer": p, "udc_wt_percent": 0, "block": {"points": points}} for p in ("HDPE", "LDPE")]
    result = frequency_panel(samples, "HDPE", "a")
    assert len(result["series"]) == 2
    assert [s["y"] for s in result["series"]] == [[2], [5]]
    assert [s["line_style"] for s in result["series"]] == ["solid", "dash"]
    assert result["series"][0]["color"] == result["series"][1]["color"]


def test_arrhenius_plan_separates_observed_shifts_and_regression():
    s = {"sample_id": "LDPE-Control", "polymer": "LDPE", "udc_wt_percent": 0,
         "arrhenius": {"rows": [{"inverse_temperature_1000_K": 2, "ln_aT": 1, "ln_aT_fit": .9},
                                 {"inverse_temperature_1000_K": 2.2, "ln_aT": 2, "ln_aT_fit": 2.1}]}}
    result = arrhenius_panel([s], "e", "Arrhenius")
    assert result["series"][0]["y"] == [1, 2]
    assert result["series"][1]["y"] == [.9, 2.1]
    assert result["series"][0]["line_style"] == "none"


def test_cli_exposes_creation_and_exact_export():
    parser = build_parser()
    create = parser.parse_args(["rheology", "tts", "--request", "/tmp/request.json", "--json"])
    assert create.rheology_command == "tts"
    export = parser.parse_args(["rheology", "export", "/tmp/workspace", "--json"])
    assert export.workspace == Path("/tmp/workspace")
    prepared = parser.parse_args(["rheology", "plot", "--request", "/tmp/prepared.json", "--json"])
    assert prepared.rheology_command == "plot"
    assert parser.parse_args(["rheology", "capabilities", "--json"]).rheology_command == "capabilities"
    preview = parser.parse_args(["rheology", "style-preview", "/tmp/workspace", "--json"])
    assert preview.workspace == Path("/tmp/workspace")
    apply = parser.parse_args(["rheology", "style-apply", "/tmp/workspace", "--preview", "/tmp/preview.json", "--json"])
    assert apply.preview == Path("/tmp/preview.json")


def _publication_fixture(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    identifiers = ["Panel_d", "Panel_d_HDPE"]
    receipts = []
    for identifier in identifiers:
        native = stage / f"{identifier}.vsz"
        native.write_bytes(f"native {identifier}".encode())
        exports = []
        for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png"):
            path = stage / f"{identifier}{suffix}"
            path.write_bytes(path.name.encode())
            exports.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        receipts.append({"id": identifier, "document": str(native),
                         "document_sha256": hashlib.sha256(native.read_bytes()).hexdigest(), "exports": exports})
    return stage, {"figures": [{"id": name} for name in identifiers]}, {"figures": receipts}


def test_publication_uses_exact_names_without_prefix_duplicates(tmp_path):
    stage, spec, receipts = _publication_fixture(tmp_path)
    documents = _publish(stage, tmp_path / "delivery", spec, receipts)
    assert len(documents) == 2
    assert all(len(document["exports"]) == 3 for document in documents)
    assert all(len({Path(path).name for path in document["exports"]}) == 3 for document in documents)
    assert not any("HDPE" in Path(path).name for path in documents[0]["exports"])


def test_publication_uses_sealed_root_outputs_despite_retained_export_attempts(tmp_path):
    stage, spec, receipts = _publication_fixture(tmp_path)
    history = stage / ".creation/Panel_d.exports" / ("a" * 32) / "exports"
    history.mkdir(parents=True)
    for path in list(stage.iterdir()):
        if path.is_file():
            (history / path.name).write_bytes(b"retained failed attempt: " + path.read_bytes())
    before = {p: p.read_bytes() for p in history.iterdir()}
    documents = _publish(stage, tmp_path / "delivery", spec, receipts)
    assert {p: p.read_bytes() for p in history.iterdir()} == before
    for document, receipt in zip(documents, receipts["figures"], strict=True):
        assert Path(document["path"]).read_bytes() == Path(receipt["document"]).read_bytes()
        expected = {Path(item["path"]).name: Path(item["path"]).read_bytes() for item in receipt["exports"]}
        assert {Path(path).name: Path(path).read_bytes() for path in document["exports"]} == expected


@pytest.mark.parametrize("failure", ["historical_receipt", "outside_receipt", "symbolic_link", "hard_link"])
def test_publication_rejects_unbound_or_aliased_root_output_before_copy(tmp_path, failure):
    import os

    stage, spec, receipts = _publication_fixture(tmp_path)
    source = stage / "Panel_d.pdf"
    other = tmp_path / "other.pdf"
    other.write_bytes(source.read_bytes())
    if failure == "historical_receipt":
        historical = stage / ".creation/Panel_d.exports" / ("a" * 32) / "exports/Panel_d.pdf"
        historical.parent.mkdir(parents=True)
        historical.write_bytes(source.read_bytes())
        receipts["figures"][0]["exports"][0]["path"] = str(historical)
    elif failure == "outside_receipt":
        receipts["figures"][0]["exports"][0]["path"] = str(other)
    else:
        source.unlink()
        if failure == "symbolic_link":
            source.symlink_to(other)
        else:
            os.link(other, source)
    with pytest.raises(ValueError):
        _publish(stage, tmp_path / "delivery", spec, receipts)
    assert not (tmp_path / "delivery").exists()


@pytest.mark.parametrize("failure", ["missing_tiff", "duplicate_png", "changed_native", "changed_pdf"])
def test_publication_rejects_incomplete_or_changed_render_set_before_copy(tmp_path, failure):
    stage, spec, receipts = _publication_fixture(tmp_path)
    if failure == "missing_tiff":
        (stage / "Panel_d_300dpi.tiff").unlink()
    elif failure == "duplicate_png":
        (stage / "extra").mkdir()
        (stage / "extra/Panel_d_300dpi.png").write_bytes((stage / "Panel_d_300dpi.png").read_bytes())
    elif failure == "changed_native":
        (stage / "Panel_d.vsz").write_bytes(b"changed data")
    else:
        (stage / "Panel_d.pdf").write_bytes(b"changed PDF")
    destination = tmp_path / "delivery"
    with pytest.raises(ValueError):
        _publish(stage, destination, spec, receipts)
    assert not destination.exists()


def test_modified_compiled_spec_is_rejected_before_native_reexport(tmp_path):
    spec_path = tmp_path / "Panel_a.spec.json"
    source = [{"path": "/original.csv", "sha256": "source digest"}]
    original = {"source_binding": {"sources": source}, "figure": {"id": "Panel_a", "series": [1, 2, 3]}}
    spec_path.write_text(json.dumps(original))
    receipt = {"id": "Panel_a", "spec_path": str(spec_path),
               "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest()}
    manifest = {"sources": source, "native_result": {"figures": [receipt]}, "documents": [{"id": "Panel_a"}]}
    assert _compiled_figures(manifest)["Panel_a"] == original["figure"]
    spec_path.write_text(json.dumps({**original, "figure": {"id": "Panel_a", "series": [4, 5, 6]}}))
    with pytest.raises(ValueError, match="Compiled figure specification changed"):
        _compiled_figures(manifest)
    receipt.pop("spec_sha256")
    with pytest.raises(ValueError, match="creation SHA"):
        _compiled_figures(manifest)


def _saved_export_suite(tmp_path, monkeypatch):
    from sciplot_core import rheology_tts_render
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.workflow.rheology_tts_tables import write_json

    stage, plan, native = _publication_fixture(tmp_path)
    source = tmp_path / "original.csv"
    source.write_text("immutable measurements\n")
    sources = [{"path": str(source), "sha256": file_sha256(source)}]
    workspace, delivery = tmp_path / ".sciplot/Figures", tmp_path / "Figures"
    workspace.mkdir(parents=True)
    documents = _publish(stage, delivery, plan, native)
    for receipt in native["figures"]:
        spec = stage / f"{receipt['id']}.spec.json"
        write_json(spec, {"source_binding": {"sources": sources}, "figure": {"id": receipt["id"]}})
        receipt.update(spec_path=str(spec), spec_sha256=file_sha256(spec))
    manifest = {"kind": "sciplot_rheology_tts_suite", "version": 1, "sources": sources,
        "workspace": str(workspace), "delivery": str(delivery), "native_result": native, "documents": documents}
    write_json(workspace / "suite.json", manifest)
    write_json(delivery / "data/delivery_manifest.json", manifest)

    def audit(path, _figure, **_kwargs):
        return {"status": "passed", "document": str(path), "document_sha256": file_sha256(path)}

    def export(path, out_base, figure_spec=None):
        out_base.parent.mkdir(parents=True, exist_ok=True)
        exports = []
        for format_name, suffix in [("pdf", ".pdf"), ("tiff_300", "_300dpi.tiff"), ("png_300", "_300dpi.png")]:
            target = out_base.parent / f"{out_base.name}{suffix}"
            target.write_bytes(f"new native export {target.name}".encode())
            exports.append({"format": format_name, "path": str(target), "sha256": file_sha256(target)})
        native_audit = audit(path, figure_spec)
        audit_path = out_base.parent / f"{out_base.name}.native-audit.json"
        write_json(audit_path, native_audit)
        return {"kind": "sciplot_studio_export", "document": str(path), "document_sha256": file_sha256(path),
            "export_dir": str(out_base.parent), "exports": exports, "native_audit": native_audit,
            "native_audit_path": str(audit_path)}

    def batch(documents):
        for path, _out_base, figure in documents:
            rheology_tts_render.audit_tts_document(path, figure)
        return [rheology_tts_render.export_tts_document(path, out_base, figure)
                for path, out_base, figure in documents]

    monkeypatch.setattr(rheology_tts_render, "audit_tts_document", audit)
    monkeypatch.setattr(rheology_tts_render, "export_tts_document", export)
    monkeypatch.setattr(rheology_tts_render, "export_tts_documents", batch)
    return workspace, delivery, manifest, export


def test_failed_later_reexport_keeps_entire_visible_delivery_unchanged(tmp_path, monkeypatch):
    from sciplot_core import rheology_tts_render
    from sciplot_core.workflow.rheology_tts_style_storage import snapshot
    from sciplot_core.workflow.rheology_tts_suite import export_suite

    workspace, delivery, manifest, export = _saved_export_suite(tmp_path, monkeypatch)
    first_pdf = Path(manifest["documents"][0]["exports"][0])
    original_pdf = first_pdf.read_bytes()
    original = snapshot([p for p in delivery.rglob("*") if p.is_file()] + [workspace / "suite.json"])

    def fail_second(path, out_base, figure_spec=None):
        if path.stem == manifest["documents"][1]["id"]:
            raise RuntimeError("injected last-figure export failure")
        return export(path, out_base, figure_spec)

    monkeypatch.setattr(rheology_tts_render, "export_tts_document", fail_second)
    with pytest.raises(RuntimeError, match="last-figure export failure"):
        export_suite(workspace)
    assert first_pdf.read_bytes() == original_pdf
    assert snapshot([Path(path) for path in original]) == original


@pytest.mark.parametrize("target", ["source", "earlier_native", "compiled_spec", "manifest", "candidate"])
def test_drift_during_later_export_cannot_publish_partial_suite(tmp_path, monkeypatch, target):
    from sciplot_core import rheology_tts_render
    from sciplot_core.workflow.rheology_tts_style_storage import snapshot
    from sciplot_core.workflow.rheology_tts_suite import export_suite

    workspace, delivery, manifest, export = _saved_export_suite(tmp_path, monkeypatch)
    protected = [Path(p) for document in manifest["documents"] for p in document["exports"]]
    protected.append(delivery / "data/delivery_manifest.json")
    original = snapshot(protected)
    first_candidate = None

    def mutate_after_export(path, out_base, figure_spec=None):
        nonlocal first_candidate
        receipt = export(path, out_base, figure_spec)
        if first_candidate is None:
            first_candidate = Path(receipt["exports"][0]["path"])
        else:
            changed = {
                "source": Path(manifest["sources"][0]["path"]),
                "earlier_native": Path(manifest["documents"][0]["path"]),
                "compiled_spec": Path(manifest["native_result"]["figures"][0]["spec_path"]),
                "manifest": workspace / "suite.json",
                "candidate": first_candidate,
            }[target]
            changed.write_bytes(changed.read_bytes() + b"\nchanged during later export")
        return receipt

    monkeypatch.setattr(rheology_tts_render, "export_tts_document", mutate_after_export)
    with pytest.raises(ValueError, match="changed|Stale"):
        export_suite(workspace)
    assert snapshot(protected) == original


def test_reexport_recovers_missing_artifacts_from_current_native_and_updates_bound_receipts(tmp_path, monkeypatch):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.workflow.rheology_tts_style_storage import snapshot
    from sciplot_core.workflow.rheology_tts_suite import export_suite

    workspace, delivery, manifest, _ = _saved_export_suite(tmp_path, monkeypatch)
    missing = Path(manifest["documents"][0]["exports"][0])
    missing.unlink()
    # The saved native file, including a user's accepted style edit, is authority.
    native = Path(manifest["documents"][0]["path"])
    native.write_bytes(native.read_bytes() + b" user native style edit")
    protected = snapshot([Path(s["path"]) for s in manifest["sources"]] +
                         [Path(d["path"]) for d in manifest["documents"]])

    result = export_suite(workspace)

    assert result["status"] == "ready" and result["exact_saved_export"] is True
    assert missing.is_file()
    assert snapshot([Path(p) for p in protected]) == protected
    updated = json.loads((workspace / "suite.json").read_text())
    assert updated == json.loads((delivery / "data/delivery_manifest.json").read_text())
    for document, receipt in zip(updated["documents"], updated["last_export"], strict=True):
        assert document["sha256"] == receipt["document_sha256"] == file_sha256(Path(document["path"]))
        assert receipt["document"] == document["path"]
        assert set(document["exports"]) == {entry["path"] for entry in receipt["exports"]}
        for entry in receipt["exports"]:
            assert entry["sha256"] == file_sha256(Path(entry["path"]))
            assert Path(entry["path"]).parent == Path(receipt["export_dir"])
        assert Path(receipt["native_audit_path"]).is_relative_to(delivery)
        assert json.loads(Path(receipt["native_audit_path"]).read_text()) == receipt["native_audit"]


def test_suite_publication_failure_rolls_back_exports_and_both_manifests(tmp_path, monkeypatch):
    from sciplot_core.workflow import rheology_tts_style_storage as storage
    from sciplot_core.workflow.rheology_tts_suite import export_suite

    workspace, delivery, _, _ = _saved_export_suite(tmp_path, monkeypatch)
    original = storage.snapshot([p for p in delivery.rglob("*") if p.is_file()] + [workspace / "suite.json"])
    replace = storage.os.replace

    def fail_visible_manifest(source, target):
        if Path(target) == delivery / "data/delivery_manifest.json":
            raise OSError("injected final manifest publication failure")
        return replace(source, target)

    monkeypatch.setattr(storage.os, "replace", fail_visible_manifest)
    with pytest.raises(OSError, match="final manifest publication failure"):
        export_suite(workspace)
    assert storage.snapshot([Path(p) for p in original]) == original
    assert {str(p) for p in delivery.rglob("*") if p.is_file()} == {p for p in original if p != str(workspace / "suite.json")}


def test_reexport_respects_existing_workspace_session(tmp_path, monkeypatch):
    from sciplot_core.studio_core.project_session import ProjectSessionBusy, external_project_session
    from sciplot_core.workflow.rheology_tts_suite import export_suite

    workspace, _, _, _ = _saved_export_suite(tmp_path, monkeypatch)
    with external_project_session(workspace), pytest.raises(ProjectSessionBusy):
        export_suite(workspace)


def test_compiled_spec_change_between_validation_and_snapshot_blocks_export(tmp_path, monkeypatch):
    from sciplot_core.workflow import rheology_tts_suite as suite
    from sciplot_core.workflow.rheology_tts_style_storage import snapshot

    workspace, delivery, manifest, _ = _saved_export_suite(tmp_path, monkeypatch)
    original = snapshot([p for p in delivery.rglob("*") if p.is_file()] + [workspace / "suite.json"])
    compiled = suite._compiled_figures

    def changed_after_read(value):
        figures = compiled(value)
        path = Path(manifest["native_result"]["figures"][0]["spec_path"])
        path.write_bytes(path.read_bytes() + b"\nchanged after validation")
        return figures

    monkeypatch.setattr(suite, "_compiled_figures", changed_after_read)
    with pytest.raises(ValueError, match="Compiled figure specification changed"):
        suite.export_suite(workspace)
    assert snapshot([Path(p) for p in original]) == original


def test_suite_export_rejects_redirected_staging_before_native_writes(tmp_path, monkeypatch):
    from sciplot_core.workflow.rheology_tts_suite import export_suite

    workspace, _, _, _ = _saved_export_suite(tmp_path, monkeypatch)
    elsewhere = tmp_path / "unrelated"
    elsewhere.mkdir()
    (workspace / "export_stages").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="^Source update cannot follow symbolic links:"):
        export_suite(workspace)
    assert list(elsewhere.iterdir()) == []
