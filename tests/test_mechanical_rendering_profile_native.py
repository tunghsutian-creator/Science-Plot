"""Historical mechanical delivery, legacy replay and Managed all face one golden."""

import json
from pathlib import Path
import shutil

import pytest

from rendering_profile_mechanical import mechanical_document, replay_legacy
from rendering_profile_mechanical_projection import mechanical_projection
from rendering_profiles_helpers import assert_accepted_golden, assert_three_way, capture_native, load_profile
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_ir import compile_document
from sciplot_core.plot_transforms import resolve_transforms
from sciplot_core.plot_layout import native_publication_qa
from sciplot_core.studio_core.veusz_save import save_veusz_document_from_spec
from sciplot_core.studio_core.document_edit_state import run_document_worker


_FIXTURE = Path(__file__).parent / "fixtures/rendering_profiles/mechanical-v1"


@pytest.mark.comprehensive
def test_long_instrument_category_labels_remain_visible_in_fixed_production_frame(tmp_path):
    profile = load_profile(_FIXTURE / "manifest.json")
    projection = mechanical_projection(profile.manifest["roles"]["accepted"])
    spec = json.loads((_FIXTURE / "legacy/spec.json").read_text())
    # Test-only layout case, not a real-source acceptance figure. The fixture's
    # E0/E2/E3/E4 order and original data/colors remain paired; E2's original name
    # is 6-66 2 ADR. Never replace or redefine the immutable historical golden.
    labels = ["E0 2MM", "6-66 2 ADR", "E3 2MM", "E4 2MM"]
    spec["axes"]["x"]["category_labels"] = labels
    for label, group, series in zip(labels, spec["categorical"]["groups"], spec["series"], strict=True):
        group["label"] = series["label"] = label
    spec_path = tmp_path / "long-labels.json"
    spec_path.write_text(json.dumps(spec))
    document = tmp_path / "long-labels.vsz"
    save_veusz_document_from_spec(document, spec, spec_path=spec_path)
    captured = capture_native(document, tmp_path / "long-capture", lambda payload: {"canvas": payload["geometry"]["pages"][0]["size_mm"]})
    axis = captured.inventory["/page1/graph1/x"]["settings"]
    assert axis["TickLabels/rotate"] == "0"
    assert axis["TickLabels/size"] == {"pt": 7.0}
    assert captured.capture["geometry"]["pages"][0]["size_mm"] == [60.0, 55.0]
    text = captured.capture["painted_text"]
    display = ["E0 2MM", r"6-66 2\\ADR", "E3 2MM", "E4 2MM"]
    assert captured.datasets["category_axis_labels"]["data"] == labels
    assert captured.datasets["category_axis_display_labels"]["data"] == display
    assert [value.replace(r"\\", " ") for value in display] == labels
    assert captured.inventory["/page1/graph1/category_axis_label_provider"]["settings"]["labels"] == "category_axis_display_labels"
    for label in [*display, "Sample"]:
        assert sum(item["text"] == label for item in text) == 1
    observations = [{"semantic_id": f"text:{index}", "role": "tick_label", "view_id": "main",
                     "bounds_mm": [item["bounds_mm"][0], item["bounds_mm"][1],
                                   item["bounds_mm"][2] - item["bounds_mm"][0],
                                   item["bounds_mm"][3] - item["bounds_mm"][1]]}
                    for index, item in enumerate(text)]
    layout = {"width_mm": 60, "height_mm": 55, "panels": [{"view_id": "main", "column": 0,
              "cell_mm": [0, 0, 60, 55], "plot_mm": [14, 5.5, 41.5, 38.5]}]}
    qa = native_publication_qa(layout, observations)
    (tmp_path / "long-labels-qa.json").write_text(json.dumps(qa, indent=2))
    assert qa["status"] == "passed", qa
    audit = run_document_worker("audit-spec-data", document, spec_path)
    (tmp_path / "long-labels-audit.json").write_text(json.dumps(audit, indent=2))
    assert audit["status"] == "passed"
    # The same modified production owner must leave short historical names and
    # their pinned pixels intact, not merely make the new long-label case pass.
    short_document = replay_legacy(_FIXTURE, tmp_path / "short-replay")
    short = capture_native(short_document, tmp_path / "short-capture", projection)
    assert short.inventory["/page1/graph1/x"]["settings"]["TickLabels/rotate"] == "0"
    assert_accepted_golden(profile, capture_native(profile.files["accepted_vsz"], tmp_path / "accepted", projection),
                           output_dir=tmp_path / "accepted-gate")
    from sciplot_core.qa.rendering_regression import compare_rasters, structural_diff
    diff = structural_diff(short.structure, json.loads(profile.files["golden_structure"].read_text()))
    assert diff["status"] == "passed", diff
    assert compare_rasters(short.image, profile.files["golden_png"], output_dir=tmp_path / "short-diff")["raw_changed_pixels"] == 0


@pytest.mark.comprehensive
def test_mechanical_delivery_three_way_golden_and_disposable_backend(tmp_path):
    profile = load_profile(_FIXTURE / "manifest.json")
    legacy_projection = mechanical_projection(profile.manifest["roles"]["accepted"])
    accepted = capture_native(profile.files["accepted_vsz"], tmp_path / "accepted-current", legacy_projection)
    # This must run before either fresh renderer: both can drift together.
    assert_accepted_golden(profile, accepted, output_dir=tmp_path / "accepted-first-gate")
    legacy_vsz = replay_legacy(_FIXTURE, tmp_path / "legacy-replay")
    legacy = capture_native(legacy_vsz, tmp_path / "legacy-capture", legacy_projection)
    document = mechanical_document(_FIXTURE)
    saved = tmp_path / "canonical-document.json"
    saved.write_text(json.dumps(document), encoding="utf-8")
    ir = compile_document(document)
    projection = mechanical_projection(profile.manifest["roles"]["managed"], ir)
    artifact_dir = tmp_path / "managed-artifacts"
    compiler = ManagedVeuszCompiler()
    try:
        result = compiler.compile_ir(ir, artifact_dir)
        assert result["publication_qa"]["status"] == "passed"
        assert result["publication_qa"]["native_text_checked"]
        managed = capture_native(Path(result["document"]), tmp_path / "managed-capture", projection)
        report = assert_three_way(profile, accepted, legacy, managed, output_dir=tmp_path / "three-way")
        assert compiler.export_ir(ir, Path(result["document"]), artifact_dir / "exports")["ready_to_use"]
        pixels = Path(result["preview"]["path"]).read_bytes()
    finally:
        compiler.close()
    shutil.rmtree(artifact_dir)
    # No backend artifact or old native worker remains: resolve the saved
    # document and raw bound sources again, then start a new compiler instance.
    canonical = json.loads(saved.read_text(encoding="utf-8"))
    rebuilt_document = resolve_transforms(canonical, load_sources(canonical, "tensile_curve"))["document"]
    rebuilt_ir = compile_document(rebuilt_document)
    assert rebuilt_ir == ir
    rebuilt_compiler = ManagedVeuszCompiler()
    try:
        rebuilt = rebuilt_compiler.compile_ir(rebuilt_ir, artifact_dir)
        assert rebuilt["native_state_hash"] == result["native_state_hash"]
        assert rebuilt["scientific_audit"] == result["scientific_audit"]
        assert Path(rebuilt["preview"]["path"]).read_bytes() == pixels
        assert rebuilt_compiler.export_ir(rebuilt_ir, Path(rebuilt["document"]), artifact_dir / "exports")["ready_to_use"]
    finally:
        rebuilt_compiler.close()
    assert load_profile(_FIXTURE / "manifest.json").manifest == profile.manifest
    report["rebuild"] = {"all_backend_artifacts_deleted": True, "new_native_worker": True,
                         "plot_ir_exact": True, "scientific_audit_exact": True,
                         "native_state_hash_exact": True, "preview_bytes_exact": True, "export_passed": True}
    (tmp_path / "mechanical-profile-acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
