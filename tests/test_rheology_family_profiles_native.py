"""Real historical PP Gprime/Gdoubleprime golden regression, not a synthetic demo."""

import pytest

from rendering_profiles_helpers import load_profile
from rheology_profile_helpers import FIXTURES, audit_source_points, run_profile


@pytest.mark.parametrize("case_id", ["gp", "gpp"])
def test_historical_rheology_raw_points_and_native_edit_chain(case_id):
    profile = load_profile(FIXTURES / ("manifest-" + case_id + ".json"))
    assert [record["points"] for record in audit_source_points(profile)] == [16, 16]
    from rheology_profile_helpers import read
    outcome = read(profile.files["historical_edit_outcome"])
    assert outcome["result_sha256"] == profile.manifest["files"]["accepted_vsz"]["sha256"]
    changes = read(profile.files["historical_edit"])["actual_changes"]
    assert len(changes) == 6
    assert all(change["setting_path"].endswith("/color") for change in changes)


@pytest.mark.comprehensive
@pytest.mark.parametrize("case_id", ["gp", "gpp"])
def test_rheology_historical_golden_legacy_managed_rebuild(case_id, tmp_path):
    report = run_profile(case_id, tmp_path)
    assert report["status"] == "passed"
