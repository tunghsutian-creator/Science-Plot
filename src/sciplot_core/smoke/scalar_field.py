"""Probe scalar image, contour, colorbar, and adversarial visual contracts."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.smoke.contracts import (
    EXPECTED_SCALAR_VISUAL_ATTACK_IDS,
    _inspect_veusz_document_state,
)

from sciplot_core.smoke.direct_labels import (
    _direct_label_contract_probe,
)


def _scalar_field_render_probe(run_root: Path) -> dict[str, Any]:
    """Exercise the public XYZ-to-Veusz scalar-field contract."""

    import pandas as pd

    from sciplot_core.render import render_to_dir
    from sciplot_core.source_coverage import (
        verify_rendered_mapping_source_coverage,
    )
    from sciplot_core.studio import _reference_guide_rect_contracts

    source = run_root / "scalar_field_contract" / "field_xyz.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "thickness_mm": [-2.0, 0.0, 2.0, -2.0, 0.0, 2.0],
            "in_plane_mm": [0.0, 0.0, 0.0, 20.0, 20.0, 20.0],
            "temperature_C": [125.0, 265.0, 125.0, 125.0, 265.0, 125.0],
        }
    ).to_csv(source, index=False)
    scalar_options = {
        "size": "60x55",
        "data_variables": {
            "x": "thickness_mm",
            "y": "in_plane_mm",
            "z": "temperature_C",
        },
        "z_min": 125.0,
        "z_max": 265.0,
        "z_ticks": [125.0, 195.0, 265.0],
        "z_tick_format": "%.0f",
        "contour_levels": [160.0, 230.0],
        "highlight_contour_levels": [195.0],
        "reference_guides": [
            {
                "id": "safe_temperature_transition_band",
                "kind": "band",
                "axis": "x",
                "start": -0.5,
                "end": 0.5,
                "color": "#CBD5E1",
                "transparency": 85,
            },
            {
                "id": "safe_temperature_reference_line",
                "kind": "line",
                "axis": "x",
                "value": 0.0,
                "color": "#64748B",
                "transparency": 40,
                "line_width_pt": 1.1,
                "line_style": "dash-dot",
            },
        ],
        "show_colorbar": True,
        "colorbar_width_mm": 29.5,
        "colorbar_height_mm": 2.8,
        "colorbar_foreground_color": "#223344",
        "colorbar_background_color": "#F7F7F7",
        "colorbar_background_transparency": 85,
        "colorbar_background_x_fraction": 0.52,
        "colorbar_background_y_fraction": 0.84,
        "colorbar_background_width_fraction": 0.48,
        "colorbar_background_height_fraction": 0.22,
    }
    rendered = render_to_dir(
        source,
        template="heatmap",
        output_dir=source.parent / "rendered",
        options=scalar_options,
        export_formats=("pdf",),
    )
    outputs = [Path(str(path)) for path in rendered.get("outputs") or []]
    document = Path(str((rendered.get("veusz_documents") or [""])[0]))
    spec = Path(str((rendered.get("veusz_specs") or [""])[0]))
    coverage_request = {
        "template": "heatmap",
        "render_options": dict(scalar_options),
    }
    mapping_application = {
        "proposal_id": "runtime-smoke-scalar-field-coverage",
        "mapped_outputs": [
            {
                "path": str(source.resolve()),
                "sha256": file_sha256(source),
            }
        ],
    }
    rendered_source_coverage = verify_rendered_mapping_source_coverage(
        {
            **rendered,
            "data_snapshot_source": str(source.resolve()),
        },
        mapping_application=mapping_application,
        request=coverage_request,
    )
    direct_label_contract = _direct_label_contract_probe(run_root)
    invalid_scalar_requests = {
        "explicit_zero_colorbar_width": {
            "colorbar_width_mm": 0,
        },
        "oversized_colorbar_background": {
            "colorbar_background_width_fraction": 100.0,
        },
        "opaque_colorbar_background": {
            "colorbar_background_transparency": 0,
        },
        "manual_colorbar_background": {
            "colorbar_manual_position": True,
        },
        "zero_axis_and_colorbar_font_size": {
            "font_size_pt": 0,
        },
        "opaque_reference_guide": {
            "reference_guides": [
                {
                    "kind": "band",
                    "axis": "x",
                    "start": -2.0,
                    "end": 2.0,
                    "transparency": 0,
                }
            ],
        },
        "transparent_colormap": {
            "colormap_colors": ["#00000000", "#FFFFFF00"],
        },
        "identical_colormap": {
            "colormap_colors": ["#123456", "#123456FF"],
        },
        "zero_reference_line_width": {
            "reference_guides": [
                scalar_options["reference_guides"][0],
                {
                    **scalar_options["reference_guides"][1],
                    "line_width_pt": 0,
                },
            ],
        },
    }
    invalid_scalar_request_results: dict[str, bool] = {}
    for request_id, overrides in invalid_scalar_requests.items():
        try:
            render_to_dir(
                source,
                template="heatmap",
                output_dir=source.parent / f"invalid_{request_id}",
                options={**scalar_options, **overrides},
                export_formats=("pdf",),
            )
        except (
            OSError,
            RuntimeError,
            subprocess.CalledProcessError,
            TypeError,
            ValueError,
        ):
            invalid_scalar_request_results[request_id] = True
        else:
            invalid_scalar_request_results[request_id] = False
    document_text = document.read_text(encoding="utf-8") if document.exists() else ""
    spec_text = spec.read_text(encoding="utf-8") if spec.exists() else ""
    log_x_band_contracts = _reference_guide_rect_contracts(
        {
            "axes": {
                "x": {"min": 1.0, "max": 1000.0, "scale": "log"},
                "y": {"min": 0.0, "max": 1.0, "scale": "linear"},
            },
            "reference_guides": [
                {
                    "kind": "band",
                    "axis": "x",
                    "start": 1.0,
                    "end": 100.0,
                    "color": "#CBD5E1",
                    "transparency": 86,
                }
            ],
        }
    )
    log_x_reference_guide_geometry_correct = (
        len(log_x_band_contracts) == 1
        and math.isclose(
            float(log_x_band_contracts[0]["xPos"][0]),
            10.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and math.isclose(
            float(log_x_band_contracts[0]["width"][0]),
            2.0 / 3.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
    document_only_visual_edit = document_text.replace(
        "Set('colorInvert', False)",
        "Set('colorInvert', True)",
        1,
    )
    document_only_visual_edit_materialized = document_only_visual_edit != document_text
    document_only_visual_edit_rejected = False
    if document_only_visual_edit_materialized:
        try:
            document.write_text(
                document_only_visual_edit,
                encoding="utf-8",
            )
            verify_rendered_mapping_source_coverage(
                {
                    **rendered,
                    "data_snapshot_source": str(source.resolve()),
                },
                mapping_application=mapping_application,
                request=coverage_request,
            )
        except (OSError, RuntimeError, ValueError):
            document_only_visual_edit_rejected = True
        finally:
            document.write_text(document_text, encoding="utf-8")

    coordinated_visual_forgery_materialized = False
    coordinated_visual_forgery_rejected = False
    if spec_text and document_only_visual_edit_materialized:
        forged_spec = json.loads(spec_text)
        scalar_field = forged_spec.get("scalar_field")
        if isinstance(scalar_field, dict):
            scalar_field["color_invert"] = True
            forged_spec_text = json.dumps(forged_spec, indent=2)
            coordinated_visual_forgery_materialized = forged_spec_text != spec_text
            try:
                spec.write_text(forged_spec_text, encoding="utf-8")
                document.write_text(
                    document_only_visual_edit,
                    encoding="utf-8",
                )
                verify_rendered_mapping_source_coverage(
                    {
                        **rendered,
                        "data_snapshot_source": str(source.resolve()),
                    },
                    mapping_application=mapping_application,
                    request=coverage_request,
                )
            except (OSError, RuntimeError, ValueError):
                coordinated_visual_forgery_rejected = True
            finally:
                spec.write_text(spec_text, encoding="utf-8")
                document.write_text(document_text, encoding="utf-8")
    exact_current_visual_attacks = {
        "image_transparency": (
            "To('/page1/graph1/field_image')\nSet('transparency', 100)\nTo('/')"
        ),
        "colorbar_zero_width": (
            "To('/page1/graph1/field_colorbar')\nSet('width', '0cm')\nTo('/')"
        ),
        "colorbar_label_hidden": (
            "To('/page1/graph1/field_colorbar')\nSet('Label/hide', True)\nTo('/')"
        ),
        "colorbar_ticklabels_hidden": (
            "To('/page1/graph1/field_colorbar')\nSet('TickLabels/hide', True)\nTo('/')"
        ),
        "colorbar_major_ticks_hidden": (
            "To('/page1/graph1/field_colorbar')\nSet('MajorTicks/hide', True)\nTo('/')"
        ),
        "colorbar_minor_ticks_hidden": (
            "To('/page1/graph1/field_colorbar')\nSet('MinorTicks/hide', True)\nTo('/')"
        ),
        "colorbar_line_hidden": (
            "To('/page1/graph1/field_colorbar')\nSet('Line/hide', True)\nTo('/')"
        ),
        "colorbar_border_hidden": (
            "To('/page1/graph1/field_colorbar')\nSet('Border/hide', True)\nTo('/')"
        ),
        "colorbar_label_size_zero": (
            "To('/page1/graph1/field_colorbar')\nSet('Label/size', '0pt')\nTo('/')"
        ),
        "colorbar_ticklabels_size_zero": (
            "To('/page1/graph1/field_colorbar')\nSet('TickLabels/size', '0pt')\nTo('/')"
        ),
        "colorbar_line_width_zero": (
            "To('/page1/graph1/field_colorbar')\nSet('Line/width', '0pt')\nTo('/')"
        ),
        "colorbar_border_width_zero": (
            "To('/page1/graph1/field_colorbar')\nSet('Border/width', '0pt')\nTo('/')"
        ),
        "colorbar_major_tick_width_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MajorTicks/width', '0pt')\n"
            "To('/')"
        ),
        "colorbar_major_tick_length_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MajorTicks/length', '0pt')\n"
            "To('/')"
        ),
        "colorbar_minor_tick_width_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MinorTicks/width', '0pt')\n"
            "To('/')"
        ),
        "colorbar_minor_tick_length_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MinorTicks/length', '0pt')\n"
            "To('/')"
        ),
        "colorbar_foreground_changed": (
            "To('/page1/graph1/field_colorbar')\nSet('Line/color', '#FF0000')\nTo('/')"
        ),
        "colorbar_line_transparent": (
            "To('/page1/graph1/field_colorbar')\nSet('Line/transparency', 100)\nTo('/')"
        ),
        "colorbar_border_transparent": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Border/transparency', 100)\n"
            "To('/')"
        ),
        "colorbar_ticks_transparent": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MajorTicks/transparency', 100)\n"
            "To('/')"
        ),
        "colorbar_minor_ticks_transparent": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MinorTicks/transparency', 100)\n"
            "To('/')"
        ),
        "contour_lines_hidden": (
            "To('/page1/graph1/field_contours')\nSet('Lines/hide', True)\nTo('/')"
        ),
        "reference_guide_made_opaque": (
            "To('/page1/graph1/reference_guide_1')\n"
            "Set('Fill/transparency', 0)\n"
            "To('/')"
        ),
        "reference_line_width_changed": (
            "To('/page1/graph1/reference_guide_2')\nSet('Line/width', '4pt')\nTo('/')"
        ),
        "reference_line_style_changed": (
            "To('/page1/graph1/reference_guide_2')\nSet('Line/style', 'solid')\nTo('/')"
        ),
        "reference_line_hidden": (
            "To('/page1/graph1/reference_guide_2')\nSet('Line/hide', True)\nTo('/')"
        ),
        "reference_line_geometry_changed": (
            "To('/page1/graph1/reference_guide_2')\n"
            "Set('xPos', [1.5])\n"
            "Set('xPos2', [1.5])\n"
            "To('/')"
        ),
        "colorbar_background_geometry_changed": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('width', [0.01])\n"
            "To('/')"
        ),
        "colorbar_background_fill_changed": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('Fill/color', '#000000')\n"
            "To('/')"
        ),
        "colorbar_background_hidden": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('Fill/hide', True)\n"
            "To('/')"
        ),
        "colorbar_background_transparency_changed": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('Fill/transparency', 100)\n"
            "To('/')"
        ),
        "axis_label_size_zero": (
            "To('/page1/graph1/x')\nSet('Label/size', '0pt')\nTo('/')"
        ),
        "axis_ticklabels_size_zero": (
            "To('/page1/graph1/x')\nSet('TickLabels/size', '0pt')\nTo('/')"
        ),
        "axis_line_width_zero": (
            "To('/page1/graph1/x')\nSet('Line/width', '0pt')\nTo('/')"
        ),
        "axis_major_tick_width_zero": (
            "To('/page1/graph1/x')\nSet('MajorTicks/width', '0pt')\nTo('/')"
        ),
        "axis_major_tick_length_zero": (
            "To('/page1/graph1/x')\nSet('MajorTicks/length', '0pt')\nTo('/')"
        ),
        "axis_minor_tick_width_zero": (
            "To('/page1/graph1/x')\nSet('MinorTicks/width', '0pt')\nTo('/')"
        ),
        "axis_minor_tick_length_zero": (
            "To('/page1/graph1/x')\nSet('MinorTicks/length', '0pt')\nTo('/')"
        ),
    }
    exact_current_attack_documents = {
        attack_id: document_text + "\n" + commands + "\n"
        for attack_id, commands in exact_current_visual_attacks.items()
    }
    unmanaged_overlay = (
        "Add('rect', name='unmanaged_overlay', autoadd=False)\n"
        "To('unmanaged_overlay')\n"
        "Set('positioning', 'relative')\n"
        "Set('xPos', [0.5])\n"
        "Set('yPos', [0.5])\n"
        "Set('width', [1.0])\n"
        "Set('height', [1.0])\n"
        "Set('clip', True)\n"
        "Set('Fill/color', '#FFFFFF')\n"
        "Set('Fill/hide', False)\n"
        "Set('Fill/transparency', 0)\n"
        "Set('Border/hide', True)\n"
        "To('..')\n"
    )
    image_command = "Add('image', name='field_image', autoadd=False)"
    unmanaged_overlay_document = document_text.replace(
        image_command,
        unmanaged_overlay + image_command,
        1,
    )
    exact_current_attack_documents["unmanaged_opaque_overlay"] = (
        unmanaged_overlay_document
    )
    unmanaged_line = (
        "Add('line', name='unmanaged_line_overlay', autoadd=False)\n"
        "To('unmanaged_line_overlay')\n"
        "Set('positioning', 'relative')\n"
        "Set('mode', 'point-to-point')\n"
        "Set('xPos', [0.0])\n"
        "Set('yPos', [0.0])\n"
        "Set('xPos2', [1.0])\n"
        "Set('yPos2', [1.0])\n"
        "Set('clip', True)\n"
        "Set('Line/color', '#FFFFFF')\n"
        "Set('Line/width', '20pt')\n"
        "Set('Line/transparency', 0)\n"
        "Set('Line/hide', False)\n"
        "Set('arrowleft', 'none')\n"
        "Set('arrowright', 'none')\n"
        "Set('Fill/hide', True)\n"
        "To('..')\n"
    )
    exact_current_attack_documents["unmanaged_line_overlay"] = document_text.replace(
        image_command,
        unmanaged_line + image_command,
        1,
    )
    background_command = "Add('rect', name='field_colorbar_background'"
    background_start = document_text.find(background_command)
    image_start = document_text.find(image_command)
    if 0 <= background_start < image_start:
        exact_current_attack_documents["colorbar_background_deleted"] = (
            document_text[:background_start] + document_text[image_start:]
        )
    attack_targets = {
        "image_transparency": (
            "/page1/graph1/field_image",
            "transparency",
        ),
        "colorbar_zero_width": (
            "/page1/graph1/field_colorbar",
            "width",
        ),
        "colorbar_label_hidden": (
            "/page1/graph1/field_colorbar",
            "Label/hide",
        ),
        "colorbar_ticklabels_hidden": (
            "/page1/graph1/field_colorbar",
            "TickLabels/hide",
        ),
        "colorbar_major_ticks_hidden": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/hide",
        ),
        "colorbar_minor_ticks_hidden": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/hide",
        ),
        "colorbar_line_hidden": (
            "/page1/graph1/field_colorbar",
            "Line/hide",
        ),
        "colorbar_border_hidden": (
            "/page1/graph1/field_colorbar",
            "Border/hide",
        ),
        "colorbar_label_size_zero": (
            "/page1/graph1/field_colorbar",
            "Label/size",
        ),
        "colorbar_ticklabels_size_zero": (
            "/page1/graph1/field_colorbar",
            "TickLabels/size",
        ),
        "colorbar_line_width_zero": (
            "/page1/graph1/field_colorbar",
            "Line/width",
        ),
        "colorbar_border_width_zero": (
            "/page1/graph1/field_colorbar",
            "Border/width",
        ),
        "colorbar_major_tick_width_zero": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/width",
        ),
        "colorbar_major_tick_length_zero": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/length",
        ),
        "colorbar_minor_tick_width_zero": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/width",
        ),
        "colorbar_minor_tick_length_zero": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/length",
        ),
        "colorbar_foreground_changed": (
            "/page1/graph1/field_colorbar",
            "Line/color",
        ),
        "colorbar_line_transparent": (
            "/page1/graph1/field_colorbar",
            "Line/transparency",
        ),
        "colorbar_border_transparent": (
            "/page1/graph1/field_colorbar",
            "Border/transparency",
        ),
        "colorbar_ticks_transparent": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/transparency",
        ),
        "colorbar_minor_ticks_transparent": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/transparency",
        ),
        "contour_lines_hidden": (
            "/page1/graph1/field_contours",
            "Lines/hide",
        ),
        "reference_guide_made_opaque": (
            "/page1/graph1/reference_guide_1",
            "Fill/transparency",
        ),
        "reference_line_width_changed": (
            "/page1/graph1/reference_guide_2",
            "Line/width",
        ),
        "reference_line_style_changed": (
            "/page1/graph1/reference_guide_2",
            "Line/style",
        ),
        "reference_line_hidden": (
            "/page1/graph1/reference_guide_2",
            "Line/hide",
        ),
        "reference_line_geometry_changed": (
            "/page1/graph1/reference_guide_2",
            "xPos",
        ),
        "colorbar_background_geometry_changed": (
            "/page1/graph1/field_colorbar_background",
            "width",
        ),
        "colorbar_background_fill_changed": (
            "/page1/graph1/field_colorbar_background",
            "Fill/color",
        ),
        "colorbar_background_hidden": (
            "/page1/graph1/field_colorbar_background",
            "Fill/hide",
        ),
        "colorbar_background_transparency_changed": (
            "/page1/graph1/field_colorbar_background",
            "Fill/transparency",
        ),
        "axis_label_size_zero": (
            "/page1/graph1/x",
            "Label/size",
        ),
        "axis_ticklabels_size_zero": (
            "/page1/graph1/x",
            "TickLabels/size",
        ),
        "axis_line_width_zero": (
            "/page1/graph1/x",
            "Line/width",
        ),
        "axis_major_tick_width_zero": (
            "/page1/graph1/x",
            "MajorTicks/width",
        ),
        "axis_major_tick_length_zero": (
            "/page1/graph1/x",
            "MajorTicks/length",
        ),
        "axis_minor_tick_width_zero": (
            "/page1/graph1/x",
            "MinorTicks/width",
        ),
        "axis_minor_tick_length_zero": (
            "/page1/graph1/x",
            "MinorTicks/length",
        ),
    }
    baseline_document_state = _inspect_veusz_document_state(document)
    baseline_widgets = baseline_document_state["widgets"]
    exact_current_visual_attack_materialization: dict[str, bool] = {}
    exact_current_visual_attack_results: dict[str, bool] = {}
    for attack_id, attacked_document in exact_current_attack_documents.items():
        materialized = False
        try:
            document.write_text(
                attacked_document,
                encoding="utf-8",
            )
            attacked_state = _inspect_veusz_document_state(document)
            attacked_widgets = attacked_state["widgets"]
            if attack_id == "colorbar_background_deleted":
                materialized = (
                    "/page1/graph1/field_colorbar_background" in baseline_widgets
                    and "/page1/graph1/field_colorbar_background"
                    not in attacked_widgets
                )
            elif attack_id in {
                "unmanaged_line_overlay",
                "unmanaged_opaque_overlay",
            }:
                extra_path = (
                    "/page1/graph1/unmanaged_line_overlay"
                    if attack_id == "unmanaged_line_overlay"
                    else "/page1/graph1/unmanaged_overlay"
                )
                materialized = (
                    extra_path not in baseline_widgets
                    and extra_path in attacked_widgets
                )
            else:
                target_path, setting_path = attack_targets[attack_id]
                baseline_target = baseline_widgets.get(target_path)
                attacked_target = attacked_widgets.get(target_path)
                materialized = (
                    isinstance(baseline_target, dict)
                    and isinstance(attacked_target, dict)
                    and baseline_target.get("settings", {}).get(setting_path)
                    != attacked_target.get("settings", {}).get(setting_path)
                )
            exact_current_visual_attack_materialization[attack_id] = materialized
            verify_rendered_mapping_source_coverage(
                {
                    **rendered,
                    "data_snapshot_source": str(source.resolve()),
                },
                mapping_application=mapping_application,
                request=coverage_request,
            )
        except (OSError, RuntimeError, ValueError):
            exact_current_visual_attack_results[attack_id] = True
            exact_current_visual_attack_materialization.setdefault(
                attack_id,
                False,
            )
        else:
            exact_current_visual_attack_results[attack_id] = False
        finally:
            document.write_text(document_text, encoding="utf-8")
    colorbar_index = document_text.find("Add('colorbar', name='field_colorbar'")
    colorbar_background_index = document_text.find(
        "Add('rect', name='field_colorbar_background'"
    )
    contour_index = document_text.find("Add('contour', name='field_contours'")
    image_index = document_text.find("Add('image', name='field_image'")
    qa_reports = (
        rendered.get("qa_reports")
        if isinstance(rendered.get("qa_reports"), list)
        else []
    )
    passed = (
        rendered.get("render_engine") == "veusz"
        and outputs
        and all(path.exists() and path.stat().st_size > 0 for path in outputs)
        and document.exists()
        and spec.exists()
        and rendered_source_coverage.get("status") == "passed"
        and rendered_source_coverage.get("rendered_unit_count") == 1
        and rendered_source_coverage.get("document_count") == 1
        and direct_label_contract.get("passed") is True
        and document_only_visual_edit_materialized
        and document_only_visual_edit_rejected
        and coordinated_visual_forgery_materialized
        and coordinated_visual_forgery_rejected
        and log_x_reference_guide_geometry_correct
        and invalid_scalar_request_results
        and all(invalid_scalar_request_results.values())
        and set(exact_current_attack_documents) == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
        and set(exact_current_visual_attack_materialization)
        == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
        and all(exact_current_visual_attack_materialization.values())
        and exact_current_visual_attack_results
        and set(exact_current_visual_attack_results)
        == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
        and all(exact_current_visual_attack_results.values())
        and 0 <= colorbar_index < image_index
        and 0 <= colorbar_index < colorbar_background_index < image_index
        and 0 <= contour_index < image_index
        and "Set('widgetName', 'field_image')" in document_text
        and "Add('rect', name='page_export_background'" in document_text
        and all(
            not report.get("issues")
            for report in qa_reports
            if isinstance(report, dict)
        )
    )
    return {
        "passed": bool(passed),
        "source": str(source),
        "grid_shape": [2, 3],
        "field_orientation": {
            "x": "thickness_mm",
            "y": "in_plane_mm",
            "z": "temperature_C",
        },
        "outputs": [str(path) for path in outputs],
        "document": str(document),
        "spec": str(spec),
        "rendered_source_coverage": rendered_source_coverage,
        "direct_label_contract": direct_label_contract,
        "scalar_visual_attack_regression": {
            "document_only_edit_materialized": (document_only_visual_edit_materialized),
            "document_only_edit_rejected": (document_only_visual_edit_rejected),
            "coordinated_spec_vsz_forgery_materialized": (
                coordinated_visual_forgery_materialized
            ),
            "coordinated_spec_vsz_forgery_rejected": (
                coordinated_visual_forgery_rejected
            ),
            "invalid_request_results": invalid_scalar_request_results,
            "log_x_reference_guide_geometry_correct": (
                log_x_reference_guide_geometry_correct
            ),
            "expected_exact_current_attack_ids": sorted(
                EXPECTED_SCALAR_VISUAL_ATTACK_IDS
            ),
            "expected_exact_current_attack_count": len(
                EXPECTED_SCALAR_VISUAL_ATTACK_IDS
            ),
            "exact_current_attack_id_set_matches": (
                set(exact_current_attack_documents) == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
            ),
            "exact_current_attack_materialization": (
                exact_current_visual_attack_materialization
            ),
            "exact_current_visual_attacks": (exact_current_visual_attack_results),
        },
        "overlay_order": {
            "colorbar_before_image_in_object_tree": 0 <= colorbar_index < image_index,
            "colorbar_background_between_colorbar_and_image": (
                0 <= colorbar_index < colorbar_background_index < image_index
            ),
            "contours_before_image_in_object_tree": 0 <= contour_index < image_index,
        },
        "opaque_page_background": "Add('rect', name='page_export_background'"
        in document_text,
        "real_data_evidence": False,
        "evidence_tier": "generated_synthetic_contract_fixture",
    }
