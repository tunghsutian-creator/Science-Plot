from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.studio_render.domain_defaults import (
    _apply_domain_render_defaults, _explicit_render_options,
)
from sciplot_core.studio_render.models import StudioSeries
from sciplot_core.studio_render.series_domain import (
    _resolved_domain_render_options, _validate_log_domain_series,
)
from sciplot_core.studio_render.series_option_context import request_option_authority
from sciplot_core.studio_render.template_resolution import (
    _looks_like_frequency_axis, _looks_like_tensile_axis,
    _looks_like_torque_axis, _looks_like_wavenumber_axis,
)


@pytest.mark.parametrize("marker", [None, [], ["show_y_ticks", "x_min"], ("show_y_ticks", "x_min")])
def test_declared_options_preserve_false_none_and_legacy_fallback(marker) -> None:
    request = {"render_options": {"show_y_ticks": False, "x_min": None, "size": "60x55"}}
    if marker is not None:
        request["explicit_render_option_keys"] = marker
    expected = request["render_options"] if marker is None else {
        key: request["render_options"][key] for key in marker
    }
    assert _explicit_render_options(request) == expected
    assert request_option_authority(request, "show_y_ticks") == (
        ("direct_render_option", True) if marker is None else
        ("explicit_render_option", True) if "show_y_ticks" in marker else
        ("inherited_render_option", False)
    )


def test_missing_option_cannot_acquire_explicit_authority_from_marker_alone() -> None:
    request = {"render_options": {}, "explicit_render_option_keys": ["series_order"]}
    assert _explicit_render_options(request) == {}
    assert request_option_authority(request, "series_order") == ("inherited_render_option", False)


@pytest.mark.parametrize("marker", [[], ["x_min", "series_order"], {"x_min", "series_order"}, "legacy"])
def test_option_presence_preserves_zero_empty_and_malformed_legacy_marker(marker) -> None:
    options = {"x_min": 0.0, "series_order": []}
    request = {"render_options": options, "explicit_render_option_keys": marker}
    assert _explicit_render_options(request) == ({} if marker == [] else options)
    source = "direct_render_option" if marker == "legacy" else "explicit_render_option"
    expected = ("inherited_render_option", False) if marker == [] else (source, True)
    assert request_option_authority(request, "series_order") == expected


@pytest.mark.parametrize("rule,template,axis,requested,default", [
    ("ftir_spectrum", "stacked_curve", {"x_label": "Wavenumber (cm^-1)", "y_label": "Absorbance", "series_count": 2}, "legend", "inline"),
    ("torque_curve", "curve", {"x_label": "Time (s)", "y_label": "Screw torque (N·m)"}, "inline", "legend"),
])
@pytest.mark.parametrize("legacy", [False, True])
def test_presentation_defaults_do_not_replace_declared_label_mode(
    rule, template, axis, requested, default, legacy,
) -> None:
    request = {"rule_id": rule, "template": template, "render_options": {"series_label_mode": requested}}
    if not legacy:
        request["explicit_render_option_keys"] = ["series_label_mode"]
    before = deepcopy(request)
    result = _apply_domain_render_defaults(request["render_options"], request=request, axis_info=axis)
    assert result["series_label_mode"] == requested
    assert request == before
    inherited = {**request, "explicit_render_option_keys": []}
    assert _apply_domain_render_defaults(
        request["render_options"], request=inherited, axis_info=axis,
    )["series_label_mode"] == default


@pytest.mark.parametrize("detector,semantic", [
    (_looks_like_wavenumber_axis, {"x_label": "Wavenumber (cm^-1)"}),
    (_looks_like_torque_axis, {"y_metric": "screw_torque"}),
    (_looks_like_tensile_axis, {"x_label": "Tensile strain (%)", "y_label": "Stress (MPa)"}),
    (_looks_like_frequency_axis, {"x_label": "Frequency (Hz)"}),
])
def test_template_semantics_ignore_nonaxis_metadata(detector, semantic) -> None:
    neutral = {"x_label": "Time (s)", "y_label": "Signal (V)"}
    distractors = {
        "source_path": "/tmp/wavenumber_cm-1_torque_tensile_frequency_Hz/data.csv",
        "source_bindings": {"sample": "tensile torque wavenumber frequency"},
        "sha256": "torque",
        "category_labels": ["wavenumber", "tensile", "Hz"],
    }
    assert not detector({**neutral, **distractors})
    assert detector({**semantic, **distractors})


@pytest.mark.parametrize("rule,template,axis,mode", [
    ("ftir_spectrum", "stacked_curve", {"x_label": "Wavenumber (cm^-1)", "y_label": "Absorbance", "series_count": 2}, "legend"),
    ("torque_curve", "curve", {"x_label": "Time (s)", "y_label": "Screw torque (N·m)"}, "inline"),
])
def test_create_regenerate_and_cold_request_replay_preserve_declared_presentation(
    rule, template, axis, mode,
) -> None:
    series = [
        StudioSeries(label="A", x_name="x", y_name="y",
                     x_values=(1.0, 2.0, 3.0), y_values=(2.0, 3.0, 4.0), color="#FFFFFF"),
    ]
    request = {
        "rule_id": rule, "template": template,
        "render_options": {"series_label_mode": mode, "reverse_x": False, "show_y_ticks": False},
        "explicit_render_option_keys": ["series_label_mode", "reverse_x", "show_y_ticks"],
    }
    before = deepcopy(request)
    science = deepcopy(series)
    created = _resolved_domain_render_options(request, axis_info=axis, series=series)
    cold = json.loads(json.dumps({**request, "render_options": created}))
    repeated = _resolved_domain_render_options(cold, axis_info=axis, series=series)
    assert created == repeated
    for key, value in before["render_options"].items():
        assert created[key] == value
    assert cold["explicit_render_option_keys"] == before["explicit_render_option_keys"]
    assert request == before
    assert series == science


@pytest.mark.parametrize("scale", ["linear", "log"])
def test_mechanical_declared_layout_keeps_scientific_labels_scale_and_coordinates(scale) -> None:
    request = {
        "rule_id": "tensile_curve", "template": "curve",
        "render_options": {"axis_mode": "manual", "xscale": scale, "yscale": scale},
        "explicit_render_option_keys": ["axis_mode", "xscale", "yscale"],
    }
    series = [
        StudioSeries(label="A", x_name="x", y_name="y",
                     x_values=(1.0, 2.0), y_values=(3.0, 4.0), color="#FFFFFF"),
    ]
    before = deepcopy(series)
    result = _resolved_domain_render_options(
        request, axis_info={"x_label": "Tensile strain (%)", "y_label": "Tensile stress (MPa)"},
        series=series,
    )
    assert result["axis_mode"] == "manual"
    assert result["xscale"] == result["yscale"] == scale
    assert result["x_label_override"] == "Strain (%)"
    assert result["y_label_override"] == "Tensile stress (MPa)"
    _validate_log_domain_series(series, render_options=result)
    assert series == before


@pytest.mark.comprehensive
def test_declared_ftir_legend_and_ticks_reach_native_and_cold_export(tmp_path: Path) -> None:
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.render import render_to_dir

    source = tmp_path / "spectra.csv"
    source.write_text(
        "Wavenumber (cm^-1),Cedar,Birch\n1000,0.2,0.4\n2000,0.3,0.5\n3000,0.4,0.6\n"
    )
    source_sha = file_sha256(source)
    options = {"size": "120x110", "series_label_mode": "legend", "legend_position": "upper_right",
               "reverse_x": False, "show_y_ticks": False}
    result = render_to_dir(source, template="stacked_curve", output_dir=tmp_path / "rendered",
                           options=options, export_formats=("pdf",))
    spec = json.loads(Path(result["veusz_specs"][0]).read_text())
    document_path = Path(result["veusz_documents"][0])
    assert spec["legend"]["show"] is True
    assert spec["axes"]["x"]["reverse"] is False
    document_sha = file_sha256(document_path)

    # Keep Qt application/painting lifetime inside its owned child, as in the
    # other native lifecycle tests; no Qt object survives into pytest teardown.
    code = """
import json
from pathlib import Path
import sys
from sciplot_core.studio_render import domain_defaults
from sciplot_core.veusz_worker.document_edit import loaded_native_document
def unexpected_defaults(*args, **kwargs):
    raise AssertionError('Exact saved native export must not infer defaults again.')
domain_defaults._apply_domain_render_defaults = unexpected_defaults
spec = json.loads(Path(sys.argv[2]).read_text())
with loaded_native_document(Path(sys.argv[1])) as native:
    from veusz.document import CommandInterface
    graph = '/page1/graph1/'
    assert native.resolveSettingPath(None, graph + 'key1/hide').get() is False
    for suffix in ('MajorTicks/hide', 'MinorTicks/hide', 'TickLabels/hide'):
        assert native.resolveSettingPath(None, graph + 'y/' + suffix).get() is True
    assert len(spec['series']) == 2
    for series in spec['series']:
        for axis in ('x', 'y'):
            assert [float(v).hex() for v in native.data[series[axis + '_name']].data] == [
                float(v).hex() for v in series[axis + '_values']]
    CommandInterface(native).Export(sys.argv[3])
"""
    exported = tmp_path / "cold_export.pdf"
    child = subprocess.run([sys.executable, "-c", code, str(document_path), result["veusz_specs"][0], str(exported)],
                           capture_output=True, text=True, timeout=90, check=False)
    assert child.returncode == 0, child.stdout + child.stderr
    assert exported.stat().st_size > 0
    assert file_sha256(document_path) == document_sha
    assert file_sha256(source) == source_sha
