"""The golden gate must reject coordinated renderer drift and changed authority."""

import json

from PIL import Image, ImageDraw
import pytest

from rendering_profiles_helpers import NativeSnapshot, assert_three_way, load_profile
from sciplot_core.foundation.file_hashing import file_sha256


def _profile(root):
    root.mkdir()
    (root / "raw.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (root / "accepted.vsz").write_text("# immutable test authority\n", encoding="utf-8")
    image = Image.new("RGB", (50, 50), "white")
    ImageDraw.Draw(image).line((10, 10, 10, 40), fill="black", width=2)
    image.save(root / "golden.png")
    for name, value in (("structure", {"axis": {"width_pt": .8}}), ("environment", {"font_sha256": "fixed-font"})):
        (root / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
    filenames = {"raw": "raw.csv", "accepted_vsz": "accepted.vsz", "golden_png": "golden.png",
                 "golden_structure": "structure.json", "golden_environment": "environment.json"}
    manifest = {"schema_version": 1, "profile_id": "synthetic-helper-test", "family": "test",
                "roles": {}, "identity": {"source": "synthetic-test-data"}, "unsupported": [],
                "files": {role: {"path": name, "sha256": file_sha256(root / name)} for role, name in filenames.items()}}
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_profile(path)


def _snapshot(directory, image, profile):
    return NativeSnapshot(directory, {"axis": {"width_pt": .8}}, {"font_sha256": "fixed-font"}, image, {}, {},
                          {"document_sha256": profile.manifest["files"]["accepted_vsz"]["sha256"]})


def test_changed_raw_authority_rejected_before_rendering(tmp_path):
    profile = _profile(tmp_path / "fixture")
    profile.files["raw"].write_text("x,y\n1,200\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="Immutable fixture changed or missing: raw"):
        load_profile(profile.manifest_path)


def test_fixed_golden_rejects_identical_drift_in_all_current_renderers(tmp_path):
    profile = _profile(tmp_path / "fixture")
    drifted = tmp_path / "drift.png"
    image = Image.new("RGB", (50, 50), "white")
    ImageDraw.Draw(image).line((11, 10, 11, 40), fill="black", width=2)
    image.save(drifted)
    # All current routes agree. Comparing them with each other would falsely pass.
    snapshot = _snapshot(tmp_path, drifted, profile)
    with pytest.raises(AssertionError, match="Three-way profile failed"):
        assert_three_way(profile, snapshot, snapshot, snapshot, output_dir=tmp_path / "gates")
    report = json.loads((tmp_path / "gates/three-way-report.json").read_text())
    assert set(report["gates"]) == {"accepted_current_environment", "legacy_fresh_replay", "managed"}
    assert all(gate["raster"]["status"] == "failed" for gate in report["gates"].values())


def test_current_environment_must_match_pinned_golden_environment(tmp_path):
    profile = _profile(tmp_path / "fixture")
    clean = _snapshot(tmp_path, profile.files["golden_png"], profile)
    changed = NativeSnapshot(tmp_path, clean.structure, {"font_sha256": "replacement-font"}, clean.image, {}, {}, clean.capture)
    with pytest.raises(AssertionError, match="Three-way profile failed"):
        assert_three_way(profile, changed, clean, clean, output_dir=tmp_path / "gates")
    report = json.loads((tmp_path / "gates/three-way-report.json").read_text())
    assert report["gates"]["accepted_current_environment"]["environment"]["status"] == "failed"
    assert report["gates"]["legacy_fresh_replay"]["status"] == "passed"


def test_profile_rejects_fixture_escape(tmp_path):
    profile = _profile(tmp_path / "fixture")
    manifest = profile.manifest
    outside = tmp_path / "raw.csv"
    outside.write_bytes(profile.files["raw"].read_bytes())
    manifest["files"]["raw"]["path"] = "../raw.csv"
    profile.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError, match="Pinned fixture escapes"):
        load_profile(profile.manifest_path)


def test_accepted_route_cannot_substitute_a_freshly_generated_document(tmp_path):
    profile = _profile(tmp_path / "fixture")
    clean = _snapshot(tmp_path, profile.files["golden_png"], profile)
    substituted = NativeSnapshot(tmp_path, clean.structure, clean.environment, clean.image, {}, {},
                                 {"document_sha256": "freshly-generated-document"})
    with pytest.raises(AssertionError, match="did not reopen the immutable accepted VSZ"):
        assert_three_way(profile, substituted, clean, clean, output_dir=tmp_path / "gates")
