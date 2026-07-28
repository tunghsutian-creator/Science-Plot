"""Probe deterministic semantic parser and axis contracts."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.smoke.data_mapping import (
    _transform_parameters,
)


def _semantic_parser_probe(run_root: Path) -> dict[str, Any]:
    """Exercise promoted real-data table shapes with generated contract data."""

    import pandas as pd

    from sciplot_core.materials_rules import compute_analysis_metrics
    from sciplot_core.semantic import classify_source, prepare_semantic_source
    from sciplot_core.studio import (
        StudioPreparationBlocked,
        StudioSeries,
        StudioSourceFrame,
        _apply_series_options,
        _apply_series_domain_contract_defaults,
        _semantic_payload_with_exact_current_axes,
        _semantic_payload_with_terminal_axes,
        derive_terminal_render_data_contract,
        _series_from_frame_records,
        _validate_log_domain_series,
        _veusz_spec_path,
    )

    contracts = run_root / "semantic_contracts"

    saxs_source = contracts / "saxs_profile" / "paired_q_intensity.csv"
    saxs_source.parent.mkdir(parents=True, exist_ok=True)
    saxs_source.write_text(
        "HDPE,,2 wt% UDC 3,\n"
        "q (nm-1),Log intensity (a.u.),q (nm-1),Log intensity (a.u.)\n"
        "0.01,1000,0.01,100000\n"
        "0.02,500,0.02,50000\n"
        "0.05,100,0.05,10000\n"
        "0.10,25,0.10,2500\n",
        encoding="utf-8",
    )
    saxs_semantic = classify_source(saxs_source)
    saxs_result = prepare_semantic_source(
        saxs_source,
        output_dir=contracts / "saxs_output",
        semantic=saxs_semantic,
    )
    saxs_parameters = _transform_parameters(saxs_result)

    gpc_dir = contracts / "gpc_sec_chromatogram"
    gpc_dir.mkdir(parents=True, exist_ok=True)
    gpc_source = gpc_dir / "8.xlsx"
    pd.DataFrame(
        [
            ["SampleName", "8"],
            ["DetectorType", "DetectorUnits"],
            ["RI", "mV"],
            ["RT (mins)", "RI"],
            [1.0, 10.0],
            [1.5, 25.0],
            [2.0, 12.0],
            [2.5, 4.0],
        ]
    ).to_excel(gpc_source, sheet_name="Slice Table", header=False, index=False)
    gpc_semantic = classify_source(gpc_dir)
    gpc_result = prepare_semantic_source(
        gpc_dir,
        output_dir=contracts / "gpc_output",
        semantic=gpc_semantic,
    )
    gpc_parameters = _transform_parameters(gpc_result)

    impact_dir = contracts / "impact_metric"
    impact_dir.mkdir(parents=True, exist_ok=True)
    impact_source = impact_dir / "impact strength.xlsx"
    with pd.ExcelWriter(impact_source) as writer:
        for thickness, offset in (("2 mm", 0.0), ("4 mm", 10.0)):
            pd.DataFrame(
                [
                    ["Re", "Re"],
                    ["kJ/m2", "kJ/m2"],
                    ["V-PA", "E-PA"],
                    [1.0 + offset, 2.0 + offset],
                    [1.2 + offset, 2.2 + offset],
                    [1.4 + offset, 2.4 + offset],
                ]
            ).to_excel(writer, sheet_name=thickness, header=False, index=False)
    impact_semantic = classify_source(impact_source)
    impact_result = prepare_semantic_source(
        impact_source,
        output_dir=contracts / "impact_output",
        semantic=impact_semantic,
    )
    impact_parameters = _transform_parameters(impact_result)
    impact_metric_rows = compute_analysis_metrics(
        source_path=impact_source,
        processed_source=impact_source,
        semantic=impact_semantic,
        output_dir=contracts / "impact_metrics",
    )

    swelling_source = contracts / "explicit_rule" / "parallel_blocks.csv"
    swelling_source.parent.mkdir(parents=True, exist_ok=True)
    swelling_rows: list[list[object]] = [
        [
            "Sample Name:",
            "Fig 3 (a): SH_DI water",
            "",
            "",
            "",
            "",
            "",
            "Fig 3 (b): SH_1000 mM NaCl",
            "",
            "",
            "",
            "",
            "",
            "Fig 3 (c): SH_0.1 wt% PAA",
            "",
            "",
            "",
            "",
            "",
        ],
        ["Data Set N°", 1, "", 2, "", 3, "", 1, "", 2, "", 3, "", 1, "", 2, "", 3, ""],
        ["Axis Cordinates:", *(["Time (s)", "Ai/A0 (unitless)"] * 9)],
    ]
    for point_index in range(5):
        row: list[object] = [""]
        for series_index in range(9):
            row.extend(
                [
                    point_index * 100 + series_index * 5,
                    1.0 + point_index * 0.03 + series_index * 0.001,
                ]
            )
        swelling_rows.append(row)
    swelling_rows.extend(
        [
            [""] * 19,
            [""] * 19,
            [
                "",
                "",
                "",
                "",
                "",
                "",
                72000,
                72.6,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
            [
                "",
                "",
                "",
                "",
                "",
                "",
                73000,
                72.7,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
        ]
    )
    swelling_source.write_text(
        "\n".join(",".join(str(value) for value in row) for row in swelling_rows)
        + "\n",
        encoding="utf-8",
    )
    swelling_semantic = classify_source(
        swelling_source, requested_rule_id="swelling_curve"
    )
    swelling_result = prepare_semantic_source(
        swelling_source,
        output_dir=contracts / "swelling_output",
        semantic=swelling_semantic,
    )
    swelling_parameters = _transform_parameters(swelling_result)
    styled_swelling_series = _apply_series_options(
        [
            StudioSeries(
                label=label,
                x_name=f"x_{index}",
                y_name=f"y_{index}",
                x_values=(0.0, 1.0),
                y_values=(1.0, 1.1),
                color="#000000",
            )
            for index, label in enumerate(
                swelling_parameters.get("series_order") or [], start=1
            )
        ],
        render_options=dict(swelling_semantic.get("render_options") or {}),
        request={"template": "point_line", "rule_id": "swelling_curve"},
    )
    swelling_non_color_signatures = [
        (item.line_style, str(item.marker)) for item in styled_swelling_series
    ]
    swelling_colors = [item.color for item in styled_swelling_series]
    swelling_condition_groups = [
        styled_swelling_series[index : index + 3]
        for index in range(0, len(styled_swelling_series), 3)
    ]

    amplitude_frame = pd.DataFrame(
        {
            "Strain": ["%", "Sample A", 0.1, 1.0, 10.0],
            "Storage Modulus": ["Pa", "Sample A", 1200.0, 1100.0, 900.0],
            "Loss Modulus": ["Pa", "Sample A", 240.0, 260.0, 300.0],
            "Loss Factor": ["1", "Sample A", 0.2, 0.24, 0.33],
            "Strain.1": ["%", "Sample B", 0.1, 1.0, 10.0],
            "Storage Modulus.1": ["Pa", "Sample B", 1800.0, 1600.0, 1300.0],
            "Loss Modulus.1": ["Pa", "Sample B", 300.0, 340.0, 390.0],
            "Loss Factor.1": ["1", "Sample B", 0.17, 0.21, 0.3],
        }
    )
    amplitude_source = contracts / "rheology_strain_sweep" / "comparison.csv"
    amplitude_source.parent.mkdir(parents=True, exist_ok=True)
    amplitude_source.write_text("synthetic contract frame\n", encoding="utf-8")
    amplitude_record = StudioSourceFrame(
        label="comparison",
        path=amplitude_source,
        sha256=file_sha256(amplitude_source),
        frame=amplitude_frame,
    )
    default_amplitude_series, default_amplitude_axis = _series_from_frame_records(
        {
            "template": "point_line",
            "rule_id": "rheology_strain_sweep",
            "series_order": ["Sample A", "Sample B"],
            "render_options": {"xscale": "log", "yscale": "log"},
            "explicit_render_option_keys": [],
            "study_model": {
                "figure_queue": [{"x_metric": "x", "y_metric": "y"}],
            },
        },
        frames=[amplitude_record],
    )
    loss_factor_series, loss_factor_axis = _series_from_frame_records(
        {
            "template": "point_line",
            "rule_id": "rheology_strain_sweep",
            "y_metric": "loss_factor",
            "series_order": ["Sample A", "Sample B"],
            "render_options": {"xscale": "log", "yscale": "log"},
            "explicit_render_option_keys": [],
        },
        frames=[amplitude_record],
    )

    positive_xrd_series = [
        StudioSeries(
            label="XRD",
            x_name="xrd_x",
            y_name="xrd_y",
            x_values=(3.0, 20.0, 50.0),
            y_values=(800.0, 5000.0, 900.0),
            color="#000000",
        )
    ]
    positive_xrd_options = _apply_series_domain_contract_defaults(
        {},
        request={
            "rule_id": "xrd_pattern",
            "render_options": {},
            "explicit_render_option_keys": [],
        },
        series=positive_xrd_series,
    )
    negative_xrd_options = _apply_series_domain_contract_defaults(
        {},
        request={
            "rule_id": "xrd_pattern",
            "render_options": {},
            "explicit_render_option_keys": [],
        },
        series=[
            StudioSeries(
                label="background-subtracted XRD",
                x_name="xrd_negative_x",
                y_name="xrd_negative_y",
                x_values=(3.0, 20.0, 50.0),
                y_values=(-5.0, 5000.0, 10.0),
                color="#000000",
            )
        ],
    )
    noisy_relaxation_options = _apply_series_domain_contract_defaults(
        {
            "y_min": -0.05,
            "y_max": 1.05,
            "y_ticks": [0.0, 0.25, 0.5, 0.75, 1.0],
        },
        request={
            "rule_id": "rheology_stress_relaxation",
            "render_options": {},
            "explicit_render_option_keys": [],
        },
        series=[
            StudioSeries(
                label="noisy relaxation",
                x_name="relaxation_x",
                y_name="relaxation_y",
                x_values=(0.01, 0.1, 1.0),
                y_values=(0.9, -0.47, 0.1),
                color="#000000",
            )
        ],
    )
    xrd_terminal_source = contracts / "xrd_pattern" / "terminal.csv"
    xrd_terminal_source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "2theta": ["degree", "PDA-I", 3.0, 9.0, 20.0],
            "Intensity": ["count", "PDA-I", 2.0, 10.0, 1.0],
            "2theta.1": ["degree", "PDA-Br", 3.0, 7.0, 20.0],
            "Intensity.1": ["count", "PDA-Br", 1.0, 8.0, 2.0],
        }
    ).to_csv(xrd_terminal_source, index=False)
    xrd_terminal_contract = derive_terminal_render_data_contract(
        request={
            "template": "curve",
            "rule_id": "xrd_pattern",
            "series_order": ["pda_xrd_patterns"],
            "render_options": {},
            "explicit_render_option_keys": [],
            "study_model": {
                "sample_order": ["pda_xrd_patterns"],
                "figure_queue": [
                    {
                        "evidence_contract": {
                            "confirmation_status": "inferred",
                        }
                    }
                ],
            },
        },
        terminal_sources=[xrd_terminal_source],
    )
    xrd_terminal_labels = [
        str(unit.get("label") or "")
        for unit in xrd_terminal_contract.get("units") or []
        if isinstance(unit, dict)
    ]
    xrd_terminal_axes = (xrd_terminal_contract.get("units") or [{}])[0].get(
        "axes"
    ) or {}
    try:
        _apply_series_options(
            positive_xrd_series,
            render_options={},
            request={
                "template": "curve",
                "rule_id": "xrd_pattern",
                "series_order": ["manual typo"],
                "study_model": {
                    "sample_order": ["XRD"],
                    "figure_queue": [
                        {
                            "evidence_contract": {
                                "confirmation_status": "confirmed",
                            }
                        }
                    ],
                },
            },
        )
    except StudioPreparationBlocked as exc:
        manual_order_rejection = {
            "reason_code": exc.reason_code,
            "message": str(exc),
        }
    else:
        manual_order_rejection = None

    ftir_terminal_source = contracts / "ftir_spectrum" / "terminal.csv"
    ftir_terminal_source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "Wavenumber": ["cm^-1", "Percent T", 4000.0, 3000.0, 2000.0],
            "Transmittance": ["%", "Percent T", 90.0, 82.0, 75.0],
            "Wavenumber.1": [
                "cm^-1",
                "Hidden trace",
                4000.0,
                3000.0,
                2000.0,
            ],
            "Transmittance.1": [
                "%",
                "Hidden trace",
                88.0,
                80.0,
                72.0,
            ],
        }
    ).to_csv(ftir_terminal_source, index=False)
    ftir_terminal_contract = derive_terminal_render_data_contract(
        request={
            "template": "stacked_curve",
            "rule_id": "ftir_spectrum",
            "series_order": ["Percent T", "Hidden trace"],
            "render_options": {
                "y_label_override": "Absorbance (offset)",
                "series_include": ["Percent T"],
            },
            "explicit_render_option_keys": [],
        },
        terminal_sources=[ftir_terminal_source],
    )
    ftir_terminal_unit = (ftir_terminal_contract.get("units") or [{}])[0]
    ftir_terminal_axes = ftir_terminal_unit.get("axes") or {}

    gpc_axis_document = contracts / "axis_authority" / "gpc_document.vsz"
    gpc_axis_document.parent.mkdir(parents=True, exist_ok=True)
    gpc_axis_document.write_text(
        "# synthetic axis-authority contract\n",
        encoding="utf-8",
    )
    _veusz_spec_path(gpc_axis_document).write_text(
        json.dumps(
            {
                "axes": {
                    "x": {
                        "label": "Elution time (min)",
                        "scale": "linear",
                        "min": 1.0,
                        "max": 3.0,
                    },
                    "y": {
                        "label": "Detector response (mV)",
                        "scale": "linear",
                        "min": 0.0,
                        "max": 30.0,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    gpc_effective_semantic = _semantic_payload_with_terminal_axes(
        gpc_semantic,
        document_path=gpc_axis_document,
    )

    ftir_axis_document = contracts / "axis_authority" / "ftir_document.vsz"
    ftir_axis_document.write_text(
        "# synthetic axis-authority contract\n",
        encoding="utf-8",
    )
    ftir_axis_spec = {
        "x": {
            "label": "Wavenumber (cm^{-1})",
            "scale": "linear",
            "min": 4000.0,
            "max": 400.0,
        },
        "y": {
            "label": "Absorbance (a.u.)",
            "scale": "linear",
            "min": 0.0,
            "max": 0.5,
        },
    }
    _veusz_spec_path(ftir_axis_document).write_text(
        json.dumps({"axes": ftir_axis_spec}),
        encoding="utf-8",
    )
    ftir_absorbance_semantic = classify_source(
        ftir_terminal_source,
        requested_rule_id="ftir_spectrum",
    )
    ftir_effective_semantic = _semantic_payload_with_terminal_axes(
        ftir_absorbance_semantic,
        document_path=ftir_axis_document,
    )
    ftir_exact_semantic = _semantic_payload_with_exact_current_axes(
        ftir_effective_semantic,
        qa={
            "publication": {
                "veusz_document_audit": {
                    "documents": [
                        {
                            "path": str(ftir_axis_document.resolve()),
                            "sha256": file_sha256(ftir_axis_document),
                            "axes": [
                                {
                                    "name": axis_name,
                                    **axis_payload,
                                    "hidden": False,
                                }
                                for axis_name, axis_payload in ftir_axis_spec.items()
                            ],
                        }
                    ]
                }
            }
        },
        document_path=ftir_axis_document,
    )
    try:
        _validate_log_domain_series(
            [
                StudioSeries(
                    label="invalid log trace",
                    x_name="log_x",
                    y_name="log_y",
                    x_values=(0.01, 0.1, 1.0),
                    y_values=(10.0, 0.0, 1.0),
                    color="#000000",
                )
            ],
            render_options={"xscale": "log", "yscale": "log"},
        )
    except StudioPreparationBlocked as exc:
        log_domain_rejection = {
            "reason_code": exc.reason_code,
            "message": str(exc),
        }
    else:
        log_domain_rejection = None

    expected_saxs_order = ["HDPE", "2 wt% UDC 3"]
    expected_impact_order = ["V-PA (2 mm)", "E-PA (2 mm)", "V-PA (4 mm)", "E-PA (4 mm)"]
    expected_impact_metric_names = {
        f"impact_group_{metric}[{sample}]"
        for sample in expected_impact_order
        for metric in ("n", "median", "iqr")
    }
    impact_metric_names = {str(row.get("metric") or "") for row in impact_metric_rows}
    expected_swelling_order = [
        f"{condition} replicate {replicate}"
        for condition in ("SH DI water", "SH 1000 mM NaCl", "SH 0.1 wt% PAA")
        for replicate in range(1, 4)
    ]
    swelling_selections = swelling_parameters.get("source_selections") or []
    first_swelling_selection = swelling_selections[0] if swelling_selections else {}
    first_swelling_block = first_swelling_selection.get("source_block") or {}
    first_time_conversion = first_swelling_selection.get("time_conversion") or {}
    passed = (
        saxs_semantic.get("rule_id") == "saxs_profile"
        and saxs_parameters.get("series_order") == expected_saxs_order
        and saxs_parameters.get("source_point_counts") == [4, 4]
        and (saxs_semantic.get("axis_plan") or {}).get("x", {}).get("scale") == "log"
        and (saxs_semantic.get("axis_plan") or {}).get("y", {}).get("scale") == "log"
        and gpc_semantic.get("rule_id") == "gpc_sec_chromatogram"
        and gpc_parameters.get("series_order") == ["Sample 8"]
        and gpc_parameters.get("source_point_counts") == [4]
        and (gpc_parameters.get("source_selections") or [{}])[0].get("detector_unit")
        == "mV"
        and impact_semantic.get("rule_id") == "impact_metric"
        and impact_parameters.get("sample_order") == expected_impact_order
        and impact_parameters.get("replicate_count_total") == 12
        and impact_metric_names == expected_impact_metric_names
        and all(row.get("status") == "ok" for row in impact_metric_rows)
        and swelling_semantic.get("rule_id") == "swelling_curve"
        and swelling_semantic.get("confidence") == 100.0
        and swelling_parameters.get("series_order") == expected_swelling_order
        and swelling_parameters.get("source_point_counts") == [5] * 9
        and first_swelling_block.get("selection_policy")
        == "contiguous_labeled_swelling_block"
        and first_swelling_block.get("excluded_disconnected_rows") == 2
        and math.isclose(
            float(first_time_conversion.get("factor") or 0.0), 1.0 / 3600.0
        )
        and len(swelling_condition_groups) == 3
        and all(
            len({item.color for item in group}) == 1
            for group in swelling_condition_groups
        )
        and len({group[0].color for group in swelling_condition_groups if group}) == 3
        and all(
            len({(item.line_style, str(item.marker)) for item in group}) == 3
            for group in swelling_condition_groups
        )
        and [item.label for item in default_amplitude_series]
        == ["Sample A", "Sample B"]
        and [item.y_values for item in default_amplitude_series]
        == [(1200.0, 1100.0, 900.0), (1800.0, 1600.0, 1300.0)]
        and "G" in str(default_amplitude_axis.get("y_label") or "")
        and "Pa" in str(default_amplitude_axis.get("y_label") or "")
        and [item.label for item in loss_factor_series] == ["Sample A", "Sample B"]
        and [item.y_values for item in loss_factor_series]
        == [(0.2, 0.24, 0.33), (0.17, 0.21, 0.3)]
        and "tan" in str(loss_factor_axis.get("y_label") or "").casefold()
        and positive_xrd_options.get("x_min") == 0.0
        and positive_xrd_options.get("y_min") == 0.0
        and negative_xrd_options.get("x_min") == 0.0
        and "y_min" not in negative_xrd_options
        and "y_min" not in noisy_relaxation_options
        and "y_ticks" not in noisy_relaxation_options
        and noisy_relaxation_options.get("y_max") == 1.05
        and (xrd_terminal_axes.get("x") or {}).get("min") == 0.0
        and (xrd_terminal_axes.get("y") or {}).get("min") == 0.0
        and xrd_terminal_labels == ["PDA-I", "PDA-Br"]
        and (manual_order_rejection or {}).get("reason_code") == "unknown_series_order"
        and (
            (gpc_effective_semantic.get("axis_plan") or {})
            .get("y", {})
            .get("canonical_unit")
            == "mV"
        )
        and (
            (gpc_effective_semantic.get("registered_axis_plan") or {})
            .get("y", {})
            .get("canonical_unit")
            == "a.u."
        )
        and (
            (ftir_exact_semantic.get("axis_plan") or {})
            .get("y", {})
            .get("canonical_label")
            == "Absorbance"
        )
        and (
            (ftir_exact_semantic.get("axis_plan") or {})
            .get("y", {})
            .get("canonical_unit")
            == "a.u."
        )
        and (ftir_exact_semantic.get("axis_authority") or {}).get("status")
        == "exact_current"
        and "Transmittance"
        in str((ftir_terminal_axes.get("y") or {}).get("label") or "")
        and "Absorbance"
        not in str((ftir_terminal_axes.get("y") or {}).get("label") or "")
        and ftir_terminal_unit.get("y_values") == [90.0, 82.0, 75.0]
        and ftir_terminal_contract.get("unit_count") == 1
        and (ftir_terminal_axes.get("y") or {}).get("show_ticks") is True
        and (log_domain_rejection or {}).get("reason_code")
        == "log_axis_nonpositive_data"
    )
    return {
        "passed": passed,
        "saxs": {
            "rule_id": saxs_semantic.get("rule_id"),
            "series_order": saxs_parameters.get("series_order"),
            "point_counts": saxs_parameters.get("source_point_counts"),
            "xscale": (saxs_semantic.get("axis_plan") or {}).get("x", {}).get("scale"),
            "yscale": (saxs_semantic.get("axis_plan") or {}).get("y", {}).get("scale"),
        },
        "gpc": {
            "rule_id": gpc_semantic.get("rule_id"),
            "series_order": gpc_parameters.get("series_order"),
            "point_counts": gpc_parameters.get("source_point_counts"),
            "source_selections": gpc_parameters.get("source_selections"),
        },
        "impact": {
            "rule_id": impact_semantic.get("rule_id"),
            "sample_order": impact_parameters.get("sample_order"),
            "replicate_count_total": impact_parameters.get("replicate_count_total"),
            "analysis_metric_names": sorted(impact_metric_names),
            "analysis_metric_count": len(impact_metric_rows),
        },
        "swelling": {
            "rule_id": swelling_semantic.get("rule_id"),
            "confidence": swelling_semantic.get("confidence"),
            "series_order": swelling_parameters.get("series_order"),
            "point_counts": swelling_parameters.get("source_point_counts"),
            "first_source_selection": first_swelling_selection,
            "colors": swelling_colors,
            "non_color_signatures": swelling_non_color_signatures,
        },
        "amplitude_sweep": {
            "default_labels": [item.label for item in default_amplitude_series],
            "default_y_values": [item.y_values for item in default_amplitude_series],
            "default_axis": default_amplitude_axis,
            "loss_factor_labels": [item.label for item in loss_factor_series],
            "loss_factor_y_values": [item.y_values for item in loss_factor_series],
            "loss_factor_axis": loss_factor_axis,
        },
        "axis_domain_contracts": {
            "positive_xrd_options": positive_xrd_options,
            "negative_xrd_options": negative_xrd_options,
            "noisy_relaxation_options": noisy_relaxation_options,
            "xrd_terminal_axes": xrd_terminal_axes,
            "xrd_terminal_labels": xrd_terminal_labels,
            "manual_order_rejection": manual_order_rejection,
            "gpc_effective_axis_plan": gpc_effective_semantic.get("axis_plan"),
            "gpc_registered_axis_plan": gpc_effective_semantic.get(
                "registered_axis_plan"
            ),
            "ftir_absorbance_effective_axis_plan": ftir_exact_semantic.get("axis_plan"),
            "ftir_absorbance_axis_authority": ftir_exact_semantic.get("axis_authority"),
            "ftir_terminal_axes": ftir_terminal_axes,
            "ftir_terminal_y_values": ftir_terminal_unit.get("y_values"),
            "log_domain_rejection": log_domain_rejection,
        },
    }
