"""The single reviewed omega spelling cannot hide glyph, geometry or pixel drift."""

from copy import deepcopy
import json

from PIL import Image
import pytest

from rendering_profiles_helpers import NativeSnapshot, _compare_golden, _normalize_native_text, load_profile
from rheology_profile_helpers import FIXTURES
from sciplot_core.foundation.file_hashing import file_sha256
from test_rendering_profiles_helpers import _profile


def _policy():
    rule = deepcopy(load_profile(FIXTURES / "manifest-gp.json").manifest["native_text_equivalences"][0])
    rule["paths"] = ["/axes/x/label", "/painted_text/0/text"]
    return [rule]


def _structure(text):
    return {"axes": {"x": {"label": text, "font_size": 7}},
            "painted_text": [{"text": text, "bounds": [1, 2, 3, 4]}]}


def test_reviewed_spelling_is_equivalent_without_mutating_original():
    old = _structure(r"\omega (rad s⁻¹)")
    before = deepcopy(old)
    assert _normalize_native_text(old, _policy()) == _structure("ω (rad s⁻¹)")
    assert old == before


@pytest.mark.parametrize("text", [r"\Omega (rad s⁻¹)", r"\unknown (rad s⁻¹)", "Ω (rad s⁻¹)", "ω (rad s⁻²)"])
def test_other_commands_glyphs_and_units_are_never_normalized(text):
    actual = _structure(text)
    assert _normalize_native_text(actual, _policy()) == actual
    assert _normalize_native_text(actual, _policy()) != _structure("ω (rad s⁻¹)")


def test_arbitrary_equivalence_and_nontext_paths_rejected():
    policy = _policy()
    policy[0]["from"] = r"\unknown"
    with pytest.raises(AssertionError, match="Unreviewed"):
        _normalize_native_text(_structure(r"\unknown"), policy)
    policy = _policy()
    policy[0]["paths"] = ["/axes/x/font_size"]
    with pytest.raises(AssertionError, match="reviewed text path"):
        _normalize_native_text(_structure(r"\omega (rad s⁻¹)"), policy)


def test_equivalence_requires_zero_actual_pixel_differences(tmp_path):
    profile = _profile(tmp_path / "fixture")
    structure = _structure(r"\omega (rad s⁻¹)")
    profile.files["golden_structure"].write_text(json.dumps(structure), encoding="utf-8")
    manifest = deepcopy(profile.manifest)
    manifest["files"]["golden_structure"]["sha256"] = file_sha256(profile.files["golden_structure"])
    manifest["native_text_equivalences"] = _policy()
    profile.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    profile = load_profile(profile.manifest_path)
    drift = tmp_path / "tiny-channel-drift.png"
    image = Image.open(profile.files["golden_png"]).convert("RGB")
    image.putpixel((10, 10), (1, 1, 1))  # Below the ordinary 8-level AA tolerance.
    image.save(drift)
    snapshot = NativeSnapshot(tmp_path, _structure("ω (rad s⁻¹)"), {"font_sha256": "fixed-font"}, drift, {}, {}, {})
    result = _compare_golden(profile, snapshot, tmp_path / "report")
    assert result["structure"]["status"] == "passed"
    assert result["raw_structure"]["status"] == "failed"
    assert result["raster"]["status"] == "passed"
    assert result["raster"]["raw_changed_pixels"] == 1
    assert result["status"] == "failed"
    assert result["text_equivalence_gate"] == "requires_exact_pixels_not_antialias_tolerance"
