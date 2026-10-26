"""Grouped raw-marker intent must materialize without changing summary data."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_categorical_source_identity import written

from sciplot_core.policy.categorical import MIN_BOX_REPLICATES
from sciplot_core.studio_core.veusz_bar_error import _add_error_lines
from sciplot_core.studio_core.veusz_primitives import _add_veusz_xy_series
from sciplot_core.veusz_worker.widget_bindings import _visible_mark_channels


class Capture:
    """Record the real primitive writer's settings in Veusz's lookup shape."""
    def __init__(self):
        self.settings = SimpleNamespace(setdict={})
        self.added = []
        for name in ("FillAbove/hide", "FillBelow/hide"):
            self.Set(name, True)

    def Add(self, kind, **kwargs):
        self.added.append((kind, kwargs["name"]))

    def To(self, _path):
        pass

    def Set(self, path, value):
        settings = self.settings
        components = path.split("/")
        for part in components[:-1]:
            settings = settings.setdict.setdefault(part, SimpleNamespace(setdict={}))
        settings.setdict[components[-1]] = SimpleNamespace(val=value)


@pytest.mark.parametrize("replicates", [1, 2, 3])
def test_grouped_bar_native_marker_channel_matches_each_group_contract(tmp_path: Path, monkeypatch, replicates):
    source = tmp_path / "single_value_groups.csv"
    rows = ["Sample,Condition,Cell size (µm)"]
    originals = [("E0", "33%", 147.6), ("E0", "50%", 107.1), ("E2", "33%", 32.0), ("E2", "50%", 56.4)]
    for sample, condition, value in originals:
        rows.extend(f"{sample},{condition},{value + index * 10}" for index in range(replicates))
    source.write_text("\n".join(rows) + "\n")
    original = source.read_bytes()
    spec = written({"input": str(source), "template": "bar",
        "render_options": {"size": "60x55", "y_min": 0.0, "y_max": 200.0}}, tmp_path, monkeypatch, "generated")
    categorical = spec["categorical"]
    assert categorical["presentation_kind"] == "grouped_bar_error"
    assert categorical["raw_replicate_count"] == 4 * replicates
    groups = {group["y_name"]: group for group in categorical["groups"]}
    for item in spec["series"]:
        group = groups[item["y_name"]]
        assert item["presentation_kind"] == "categorical_grouped_replicates"
        assert item["y_values"] == group["raw_values"] and group["replicate_count"] == replicates
        assert group["bar_mean"] == pytest.approx(sum(item["y_values"]) / replicates)
        assert item["raw_points_visible"] == group["raw_points_visible"] == (replicates < MIN_BOX_REPLICATES)
        interface = Capture()
        _add_veusz_xy_series(interface, item, spec["style"])
        channels = _visible_mark_channels(SimpleNamespace(typename="xy", settings=interface.settings))
        assert ("marker" in channels) is group["raw_points_visible"]
        assert "line" not in channels
        assert interface.settings.setdict["ErrorBarLine"].setdict["hide"].val is True
    errors = Capture()
    _add_error_lines(errors, bar_groups=list(groups.values()), bar_style=categorical["visual_style"],
                     bar_width=categorical["visual_style"]["bar_width_fraction"])
    if replicates == 1:
        assert all(group["bar_error"] == 0.0 for group in groups.values())
        assert errors.added == []
    else:
        assert all(group["bar_error"] > 0.0 for group in groups.values())
        assert len(errors.added) == 12
    assert source.read_bytes() == original


@pytest.mark.parametrize("marker", ["diamond", "none"])
def test_explicit_grouped_marker_override_is_not_replaced_by_default(tmp_path: Path, monkeypatch, marker):
    source = tmp_path / "grouped.csv"
    source.write_text("Sample,Condition,Cell size (µm)\nE0,33%,147.6\nE0,50%,107.1\nE2,33%,32.0\nE2,50%,56.4\n")
    request = {"input": str(source), "template": "bar"}
    baseline = written(request, tmp_path, monkeypatch, "baseline")
    selected = baseline["series"][0]
    updated = written({**request, "render_options": {"series_styles": [
        {"label": selected["label"], "marker": marker}]}}, tmp_path, monkeypatch, "override")
    actual = updated["series"][0]
    assert actual["marker"] == actual["encoding"]["marker"]["shape"] == marker
    assert "marker.shape" in actual["encoding"]["request_bound_fields"]
    assert actual["raw_points_visible"] is True
    assert [item["y_values"] for item in updated["series"]] == [item["y_values"] for item in baseline["series"]]
    assert updated["categorical"]["raw_replicate_count"] == baseline["categorical"]["raw_replicate_count"] == 4
