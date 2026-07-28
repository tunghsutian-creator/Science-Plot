"""Probe exact direct-label geometry and style contracts."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.smoke.contracts import (
    _inspect_veusz_document_state,
)


def _direct_label_contract_probe(run_root: Path) -> dict[str, Any]:
    """Exercise source-bound direct-label geometry and overlay controls."""

    import pandas as pd

    from sciplot_core.render import render_to_dir
    from sciplot_core.source_coverage import (
        verify_rendered_mapping_source_coverage,
    )

    root = run_root / "direct_label_contract"
    source = root / "stacked_curves.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "wavenumber": [1000.0, 1500.0, 2000.0, 2500.0],
            "sample_a": [0.2, 0.8, 0.5, 0.3],
            "sample_b": [0.4, 0.3, 0.9, 0.6],
        }
    ).to_csv(source, index=False)
    render_options = {
        "size": "60x55",
        "series_label_mode": "inline",
        "legend_position": "none",
    }
    rendered = render_to_dir(
        source,
        template="stacked_curve",
        output_dir=root / "rendered",
        options=render_options,
        export_formats=("pdf",),
    )
    document = Path(str((rendered.get("veusz_documents") or [""])[0]))
    spec = Path(str((rendered.get("veusz_specs") or [""])[0]))
    coverage_request = {
        "template": "stacked_curve",
        "render_options": dict(render_options),
    }
    mapping_application = {
        "proposal_id": "runtime-smoke-direct-label-coverage",
        "mapped_outputs": [
            {
                "path": str(source.resolve()),
                "sha256": file_sha256(source),
            }
        ],
    }
    coverage_input = {
        **rendered,
        "data_snapshot_source": str(source.resolve()),
    }
    baseline_coverage = verify_rendered_mapping_source_coverage(
        coverage_input,
        mapping_application=mapping_application,
        request=coverage_request,
    )
    document_text = document.read_text(encoding="utf-8")
    spec_text = spec.read_text(encoding="utf-8")
    baseline_spec = json.loads(spec_text)
    baseline_labels = baseline_spec.get("direct_labels")
    baseline_widgets = _inspect_veusz_document_state(document)["widgets"]
    attacks = {
        "position_changed": (
            "Set('xPos', [0.5])",
            "xPos",
        ),
        "size_inflated": (
            "Set('Text/size', '1000pt')",
            "Text/size",
        ),
        "text_color_changed": (
            "Set('Text/color', '#FFFFFF')",
            "Text/color",
        ),
        "background_unhidden": (
            "Set('Background/hide', False)",
            "Background/hide",
        ),
        "border_unhidden": (
            "Set('Border/hide', False)",
            "Border/hide",
        ),
    }
    target_path = "/page1/graph1/label_1"
    materialization_results: dict[str, bool] = {}
    rejection_results: dict[str, bool] = {}
    for attack_id, (command, setting_path) in attacks.items():
        attacked_document = (
            document_text + f"\nTo('{target_path}')\n" + command + "\nTo('/')\n"
        )
        try:
            document.write_text(attacked_document, encoding="utf-8")
            attacked_widgets = _inspect_veusz_document_state(document)["widgets"]
            materialization_results[attack_id] = baseline_widgets.get(
                target_path, {}
            ).get("settings", {}).get(setting_path) != attacked_widgets.get(
                target_path, {}
            ).get("settings", {}).get(setting_path)
            verify_rendered_mapping_source_coverage(
                coverage_input,
                mapping_application=mapping_application,
                request=coverage_request,
            )
        except (OSError, RuntimeError, ValueError):
            rejection_results[attack_id] = True
            materialization_results.setdefault(attack_id, False)
        else:
            rejection_results[attack_id] = False
        finally:
            document.write_text(document_text, encoding="utf-8")

    coordinated_materialized = False
    coordinated_rejected = False
    if isinstance(baseline_labels, list) and baseline_labels:
        forged_spec = json.loads(spec_text)
        forged_labels = forged_spec.get("direct_labels")
        if isinstance(forged_labels, list) and forged_labels:
            original_x = float(forged_labels[0]["x"])
            replacement_x = 0.5 if not math.isclose(original_x, 0.5) else 0.25
            forged_labels[0]["x"] = replacement_x
            forged_spec_text = json.dumps(
                forged_spec,
                indent=2,
                ensure_ascii=False,
            )
            forged_document_text = (
                document_text
                + f"\nTo('{target_path}')\n"
                + f"Set('xPos', [{replacement_x!r}])\n"
                + "To('/')\n"
            )
            try:
                spec.write_text(forged_spec_text, encoding="utf-8")
                document.write_text(
                    forged_document_text,
                    encoding="utf-8",
                )
                forged_x = (
                    _inspect_veusz_document_state(document)["widgets"]
                    .get(target_path, {})
                    .get("settings", {})
                    .get("xPos")
                )
                baseline_x = (
                    baseline_widgets.get(target_path, {})
                    .get("settings", {})
                    .get("xPos")
                )
                coordinated_materialized = (
                    forged_spec_text != spec_text and forged_x != baseline_x
                )
                verify_rendered_mapping_source_coverage(
                    coverage_input,
                    mapping_application=mapping_application,
                    request=coverage_request,
                )
            except (OSError, RuntimeError, ValueError):
                coordinated_rejected = True
            finally:
                spec.write_text(spec_text, encoding="utf-8")
                document.write_text(document_text, encoding="utf-8")

    expected_attack_ids = frozenset(attacks)
    passed = (
        baseline_coverage.get("status") == "passed"
        and isinstance(baseline_labels, list)
        and len(baseline_labels) == 2
        and set(materialization_results) == expected_attack_ids
        and all(materialization_results.values())
        and set(rejection_results) == expected_attack_ids
        and all(rejection_results.values())
        and coordinated_materialized
        and coordinated_rejected
    )
    return {
        "passed": bool(passed),
        "source": str(source),
        "document": str(document),
        "spec": str(spec),
        "baseline_status": baseline_coverage.get("status"),
        "direct_label_count": (
            len(baseline_labels) if isinstance(baseline_labels, list) else 0
        ),
        "expected_attack_ids": sorted(expected_attack_ids),
        "materialization_results": materialization_results,
        "rejection_results": rejection_results,
        "coordinated_spec_vsz_forgery_materialized": (coordinated_materialized),
        "coordinated_spec_vsz_forgery_rejected": coordinated_rejected,
        "real_data_evidence": False,
        "evidence_tier": "generated_synthetic_contract_fixture",
    }
