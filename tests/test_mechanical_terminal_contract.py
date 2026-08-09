from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from sciplot_core.figure_plan import CartesianMetricBinding, FigureTask
from sciplot_core.mechanical_figure_contract import mechanical_figure_contract
from sciplot_core.mechanical_task_sources import (
    MechanicalSummaryGroup,
    MechanicalTaskSource,
)
from sciplot_core.policy import (
    DEFAULT_PALETTE_PRESET,
    categorical_fill_color,
    categorical_keyline_color,
    categorical_slot_width_mm,
    resolve_palette_authority,
)
from sciplot_core.studio_core.series_encoding_contract import (
    series_encoding_contract_payload,
)
from sciplot_core.terminal_request import project_terminal_render_request
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding
from sciplot_core.workflow.mechanical_execution_evidence import _summary_groups
from sciplot_core.workflow.mechanical_terminal_validation import (
    _request_matches_record,
    _terminal_request_projection,
    _validate_summary_spec,
    _validate_visual_encoding,
)


def _singleton_summary_record() -> MechanicalTaskSource:
    contract = mechanical_figure_contract("compression_curve").summary_tasks[0]
    task = FigureTask.with_metric_binding(
        figure_id=contract.figure_id,
        order=2,
        title=contract.title,
        metric_binding=CartesianMetricBinding(contract.x_metric, contract.y_metric),
        template=contract.template,
        artifact_stem=contract.artifact_stem,
        document_stem=contract.document_stem,
        sample_order=("Foam",),
        replicate_counts=(("Foam", 1),),
    )
    binding = SimpleNamespace(
        rule_id="compression_curve",
        template="box_strip",
        x_metric=contract.x_metric,
        y_metric=contract.y_metric,
        sample_order=("Foam",),
    )
    return MechanicalTaskSource(
        task=task,
        source=Path("unused.csv"),
        render_options={},
        binding=cast(MaterializedTerminalSourceBinding, binding),
        task_kind="summary",
        metric=contract.y_metric,
        unit=contract.y_unit,
        groups=(MechanicalSummaryGroup("Foam", ("rep1",), (0.75,)),),
    )


def _encoding(color: str) -> dict[str, Any]:
    return {
        "kind": "sciplot_series_encoding",
        "version": 1,
        "line": {
            "visible": False,
            "color": color,
            "style": "solid",
            "width_pt": 1.2,
            "alpha": 0.92,
        },
        "marker": {
            "shape": "circle",
            "size_pt": 2.0,
            "thin_factor": 1,
            "fill_visible": True,
            "fill_color": color,
            "fill_alpha": 0.8,
            "line_visible": False,
            "line_color": color,
            "line_width_pt": 0.8,
            "line_alpha": 0.8,
        },
        "sources": {
            "line.color": "palette_shared_project_default",
            "line.style": "template_default",
            "marker.shape": "inherited_render_option",
            "marker.fill_color": "palette_shared_project_default",
            "marker.line_color": "palette_shared_project_default",
        },
        "request_bound_fields": [],
        "audit_policy": "request_bound_fields_must_match_exact_current_vsz",
    }


def _encoded_series(index: int, color: str) -> dict[str, Any]:
    encoding = _encoding(color)
    return {
        "name": f"series_{index}",
        "label": f"sample_{index}",
        "color": color,
        "line_style": "solid",
        "line_width_pt": 1.2,
        "plot_line_hide": True,
        "marker": "circle",
        "marker_size_pt": 2.0,
        "marker_thin_factor": 1,
        "marker_fill_color": color,
        "marker_alpha": 0.8,
        "marker_line_hide": True,
        "marker_line_color": color,
        "marker_line_width_pt": 0.8,
        "presentation_kind": "categorical_replicates",
        "encoding": encoding,
    }


def _singleton_spec() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    slot_width = categorical_slot_width_mm(category_count=1, figure_width_mm=60.0)
    box_fraction = 0.2
    color = "#222222"
    series = _encoded_series(1, color)
    series.update(
        {
            "label": "Foam",
            "x_name": "category_x_1",
            "y_name": "category_y_1",
            "x_values": [1.0],
            "y_values": [0.75],
            "category_position": 1.0,
            "raw_points_visible": True,
        }
    )
    spec = {
        "source_request": {"explicit_render_option_keys": []},
        "render_options": {
            "_categorical_raw_point_layout": "adaptive",
            "_categorical_box_fill_fraction": box_fraction,
            "_categorical_slot_width_mm": slot_width,
            "_categorical_box_width_mm": box_fraction * slot_width,
            "marker_size": 2.0,
            "raw_point_jitter_fraction": 0.14,
        },
        "size_mm": [60.0, 55.0],
        "axes": {
            "x": {
                "mode": "labels",
                "category_labels": ["Foam"],
                "category_positions": [1.0],
            }
        },
        "categorical": {
            "kind": "sciplot_categorical_replicate_contract",
            "presentation_kind": "box_strip",
            "summary_statistic": "median_iqr",
            "minimum_box_replicates": 2,
            "quartile_method": "linear_interpolation_at_(n_minus_1)_times_p",
            "box_whisker_mode": "1.5IQR",
            "mean_marker_visible": False,
            "raw_values_preserved": True,
            "raw_replicate_count": 1,
            "native_veusz_boxplot": False,
            "visual_style": {
                "raw_point_layout": "adaptive",
                "raw_point_position_policy": "stable_hash_shuffled_even_slots",
                "box_fill_fraction": box_fraction,
                "category_slot_width_mm": slot_width,
                "box_width_mm": box_fraction * slot_width,
                "category_count": 1,
            },
            "groups": [
                {
                    "label": "Foam",
                    "sample_label": "Foam",
                    "position": 1.0,
                    "y_name": "category_y_1",
                    "color": color,
                    "fill_color": categorical_fill_color(color),
                    "keyline_color": categorical_keyline_color(color),
                    "raw_values": [0.75],
                    "replicate_count": 1,
                    "boxplot_eligible": False,
                    "summary_status": "insufficient_replicates",
                    "raw_points_visible": True,
                    "raw_point_half_spread": 0.0,
                    "raw_point_band_fraction": 0.0,
                    "raw_point_band_width_mm": 0.0,
                    "raw_point_box_width_ratio": 0.0,
                    "raw_points_within_box_width": True,
                    "raw_marker_glyphs_within_box_width": True,
                    "descriptive_statistics": {
                        "minimum": 0.75,
                        "q1": 0.75,
                        "median": 0.75,
                        "q3": 0.75,
                        "maximum": 0.75,
                    },
                }
            ],
        },
    }
    return spec, [series]


def test_singleton_summary_is_raw_only_with_exact_terminal_geometry() -> None:
    record = _singleton_summary_record()
    spec, series = _singleton_spec()

    _validate_summary_spec(spec, series=series, record=record)
    evidence = _summary_groups(spec, record=record, series=series)
    assert evidence[0]["summary_status"] == "insufficient_replicates"
    assert evidence[0]["boxplot_visible"] is False
    assert evidence[0]["raw_points_visible"] is True

    for field, value in (("summary_status", "boxplot"),):
        forged = deepcopy(spec)
        forged["categorical"]["groups"][0][field] = value
        with pytest.raises(ValueError, match="mechanical_terminal_evidence_mismatch"):
            _validate_summary_spec(forged, series=series, record=record)
    hidden = deepcopy(series)
    hidden[0]["raw_points_visible"] = False
    with pytest.raises(ValueError, match="mechanical_terminal_evidence_mismatch"):
        _validate_summary_spec(spec, series=hidden, record=record)
    shifted = deepcopy(series)
    shifted[0]["x_values"] = [999.0]
    with pytest.raises(ValueError, match="mechanical_terminal_evidence_mismatch"):
        _validate_summary_spec(spec, series=shifted, record=record)


def test_terminal_palette_requires_closed_encoding_and_exact_series_order() -> None:
    source_request = {
        "render_options": {"palette_preset": DEFAULT_PALETTE_PRESET},
        "explicit_render_option_keys": [],
    }
    render_options = {"palette_preset": DEFAULT_PALETTE_PRESET}
    palette = resolve_palette_authority(
        source_request,
        template_id="box_strip",
        resolved_render_options=render_options,
    ).to_payload()
    series = [_encoded_series(index, palette["colors"][index - 1]) for index in (1, 2)]
    spec = {
        "template": "box_strip",
        "source_request": source_request,
        "render_options": render_options,
        "palette_resolution": palette,
        "style": {},
        "series": series,
        "series_encoding_contract": series_encoding_contract_payload(series),
    }

    _validate_visual_encoding(spec, series=series)
    wrong_palette = deepcopy(spec)
    wrong_palette["palette_resolution"]["palette_id"] = "jama_editorial"
    with pytest.raises(ValueError, match="public palette resolution"):
        _validate_visual_encoding(wrong_palette, series=series)
    duplicate_color = deepcopy(spec)
    first = palette["colors"][0]
    duplicate_color["series"][1] = _encoded_series(2, first)
    duplicate_color["series_encoding_contract"] = series_encoding_contract_payload(
        duplicate_color["series"]
    )
    with pytest.raises(ValueError, match="exact palette order"):
        _validate_visual_encoding(duplicate_color, series=duplicate_color["series"])
    malformed = deepcopy(spec)
    malformed["series"][0]["encoding"].pop("sources")
    with pytest.raises(ValueError, match="series encoding is invalid"):
        _validate_visual_encoding(malformed, series=malformed["series"])


@pytest.mark.parametrize("field", ["palette_preset", "style_preset", "size"])
def test_terminal_request_options_and_spec_projection_are_exact(
    field: str,
) -> None:
    base = _singleton_summary_record()
    options = {
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "style_preset": "nature",
        "size": "60x55",
        "x_metric": "sample",
        "y_metric": "compressive_strength_MPa",
    }
    record = replace(
        base,
        render_options=options,
        explicit_render_option_keys=("palette_preset", "size", "style_preset"),
    )
    terminal = project_terminal_render_request(
        template="box_strip",
        render_options=options,
        request_context={
            "rule_id": "compression_curve",
            "resolved_figure_task": record.task.to_payload(),
            "explicit_render_option_keys": list(record.explicit_render_option_keys),
        },
    )
    assert _request_matches_record(terminal, record, canonical=True)
    altered = deepcopy(terminal)
    altered["render_options"][field] = "forged"
    assert not _request_matches_record(altered, record, canonical=False)
    source_request = {"input": "/terminal.csv", **terminal}
    assert _terminal_request_projection(source_request) == terminal
    source_request["render_options"] = altered["render_options"]
    assert _terminal_request_projection(source_request) != terminal
