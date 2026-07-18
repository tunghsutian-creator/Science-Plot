from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sciplot_core import studio as studio_module
from sciplot_core._utils import existing_file_sha256, json_safe
from sciplot_core.qa import _span_text_role
from sciplot_core.studio import prepare_studio_document
from sciplot_core.studio_project_probe import _copy_project_fixture


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected an object in {path}.")
    return payload


def _check(
    check_id: str,
    description: str,
    passed: bool,
    detail: object,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "description": description,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _synthetic_export(
    sample: str,
    scale: float,
    *,
    include_loss_modulus: bool = True,
) -> str:
    rows = [
        "Project:\tFrequency sweep probe",
        f"Test:\t{sample}",
        "Result:\tFrequency sweep 1",
        "Interval and data points:\t1\t4",
        (
            "Interval data:\tPoint No.\tAngular Frequency\t"
            "Storage Modulus" + ("\tLoss Modulus" if include_loss_modulus else "")
        ),
        "\t\t[rad/s]\t[Pa]" + ("\t[Pa]" if include_loss_modulus else ""),
    ]
    for index, frequency in enumerate((100.0, 10.0, 1.0, 0.1), start=1):
        storage = scale * (1000.0 / frequency**0.2)
        loss = scale * (700.0 / frequency**0.15)
        row = f"\t{index}\t{frequency:g}\t{storage:.6g}"
        if include_loss_modulus:
            row += f"\t{loss:.6g}"
        rows.append(row)
    return "\n".join(rows) + "\n"


def _registry_summary(project_dir: Path) -> dict[str, Any]:
    registry = _read_json(project_dir / "studio" / "figure_set.json")
    summaries: list[dict[str, Any]] = []
    for entry in registry.get("figures", []):
        if not isinstance(entry, dict):
            continue
        document = Path(str(entry.get("document") or ""))
        spec_path = Path(str(entry.get("spec") or ""))
        spec = _read_json(spec_path) if spec_path.is_file() else {}
        series = spec.get("series") if isinstance(spec.get("series"), list) else []
        y_axis = (
            spec.get("axes", {}).get("y", {})
            if isinstance(spec.get("axes"), dict)
            and isinstance(spec.get("axes", {}).get("y"), dict)
            else {}
        )
        summaries.append(
            {
                "figure_id": entry.get("figure_id"),
                "status": entry.get("status"),
                "metric": entry.get("metric"),
                "document": str(document),
                "document_exists": document.is_file(),
                "document_sha256": existing_file_sha256(document),
                "generated_hash": entry.get("generated_hash"),
                "size_mm": spec.get("size_mm"),
                "source_metric": (
                    spec.get("source_request", {}).get("y_metric")
                    if isinstance(spec.get("source_request"), dict)
                    else None
                ),
                "y_label": y_axis.get("label"),
                "y_scale": y_axis.get("scale"),
                "y_ticks": y_axis.get("ticks"),
                "sample_order": [
                    item.get("label") for item in series if isinstance(item, dict)
                ],
                "first_x_values": [
                    item.get("x_values", [None])[0]
                    for item in series
                    if isinstance(item, dict)
                    and isinstance(item.get("x_values"), list)
                    and item.get("x_values")
                ],
                "first_y": (
                    series[0].get("y_values", [None])[0]
                    if series
                    and isinstance(series[0], dict)
                    and isinstance(series[0].get("y_values"), list)
                    and series[0].get("y_values")
                    else None
                ),
                "unavailable": entry.get("unavailable"),
            }
        )
    return {"registry": registry, "figures": summaries}


def run_studio_figure_set_probe(
    *,
    output_root: Path,
    real_project: Path | None = None,
) -> dict[str, Any]:
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="studio_figure_set_probe_", dir=resolved_output)
    )
    checks: list[dict[str, Any]] = []

    ordinary_symbol = {
        "text": "η",
        "size": 7.0,
        "bbox": [10.0, 10.0, 15.0, 17.0],
        "origin": [10.0, 17.0],
    }
    superscript_star = {
        "text": "*",
        "size": 4.0,
        "bbox": [15.2, 8.0, 18.0, 12.0],
        "origin": [15.2, 12.0],
    }
    undersized_baseline_star = {
        "text": "*",
        "size": 4.0,
        "bbox": [15.2, 13.0, 18.0, 17.0],
        "origin": [15.2, 17.0],
    }
    checks.append(
        _check(
            "complex_viscosity_star_is_math_script",
            "Only a genuinely displaced reduced star is audited as a mathematical script; an undersized same-baseline star remains ordinary text",
            _span_text_role(
                superscript_star,
                [ordinary_symbol, superscript_star],
                line_direction=[1.0, 0.0],
            )
            == "math_script",
            {
                "ordinary_symbol": ordinary_symbol,
                "superscript_star": superscript_star,
                "classified_role": _span_text_role(
                    superscript_star,
                    [ordinary_symbol, superscript_star],
                    line_direction=[1.0, 0.0],
                ),
            },
        )
    )
    checks.append(
        _check(
            "same_baseline_small_star_is_ordinary_text",
            "A reduced star with no perpendicular baseline displacement cannot bypass the ordinary final-size text threshold",
            _span_text_role(
                undersized_baseline_star,
                [ordinary_symbol, undersized_baseline_star],
                line_direction=[1.0, 0.0],
            )
            == "ordinary",
            {
                "ordinary_symbol": ordinary_symbol,
                "undersized_baseline_star": undersized_baseline_star,
                "classified_role": _span_text_role(
                    undersized_baseline_star,
                    [ordinary_symbol, undersized_baseline_star],
                    line_direction=[1.0, 0.0],
                ),
            },
        )
    )

    synthetic_source = run_root / "synthetic_source"
    synthetic_source.mkdir(parents=True)
    (synthetic_source / "Alpha.csv").write_text(
        _synthetic_export("Alpha", 1.0), encoding="utf-8"
    )
    (synthetic_source / "Beta.csv").write_text(
        _synthetic_export("Beta", 1.5), encoding="utf-8"
    )
    synthetic_payload = prepare_studio_document(
        synthetic_source,
        output_root=run_root / "synthetic_projects",
        rule_id="rheology_frequency_sweep",
        template="point_line",
        project_name="Synthetic_Rheology_Figure_Set",
    )
    synthetic_project = Path(str(synthetic_payload["project_dir"]))
    synthetic = _registry_summary(synthetic_project)
    synthetic_figures = synthetic["figures"]
    ready_synthetic = [item for item in synthetic_figures if item["status"] == "ready"]
    unavailable_synthetic = [
        item for item in synthetic_figures if item["status"] == "unavailable"
    ]
    checks.append(
        _check(
            "synthetic_two_metric_documents",
            "A two-metric frequency sweep creates only the matching G-prime and G-double-prime independent documents",
            {item["metric"] for item in ready_synthetic}
            == {"storage_modulus", "loss_modulus"}
            and all(item["document_exists"] for item in ready_synthetic)
            and all(item["size_mm"] == [60, 55] for item in ready_synthetic)
            and all(
                item["source_metric"] == item["metric"] for item in ready_synthetic
            ),
            synthetic,
        )
    )
    checks.append(
        _check(
            "missing_metrics_are_explicitly_unavailable",
            "Missing tan-delta and complex-viscosity columns are unavailable and never fall back to another metric",
            {item["metric"] for item in unavailable_synthetic}
            == {"loss_factor", "complex_viscosity"}
            and all(not item["document_exists"] for item in unavailable_synthetic)
            and all(
                isinstance(item.get("unavailable"), dict)
                and item["unavailable"].get("reason_code")
                == "figure_metric_unavailable"
                for item in unavailable_synthetic
            ),
            unavailable_synthetic,
        )
    )
    synthetic_request = _read_json(synthetic_project / "plot_request.json")
    synthetic_registry_path = synthetic_project / "studio" / "figure_set.json"
    synthetic_registry_bytes = synthetic_registry_path.read_bytes()
    tampered_registry_results: dict[str, Any] = {}
    try:
        for attack_id, updates in (
            (
                "primary_swapped_to_loss_modulus",
                {"primary_figure_id": "loss_modulus_vs_frequency"},
            ),
            (
                "registry_rule_mismatch",
                {"rule_id": "rheology_temperature_sweep"},
            ),
        ):
            tampered_registry = json.loads(
                synthetic_registry_bytes.decode("utf-8")
            )
            tampered_registry.update(updates)
            synthetic_registry_path.write_text(
                json.dumps(tampered_registry, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            scope = studio_module._studio_figure_set_export_scope(
                synthetic_project,
                request=synthetic_request,
            )
            tampered_registry_results[attack_id] = {
                "scope": scope,
                "accepted": studio_module._is_primary_figure_set_export_scope(
                    scope
                ),
            }
    finally:
        synthetic_registry_path.write_bytes(synthetic_registry_bytes)
    restored_scope = studio_module._studio_figure_set_export_scope(
        synthetic_project,
        request=synthetic_request,
    )
    checks.append(
        _check(
            "tampered_frequency_registry_fails_closed",
            "A frequency registry whose rule or primary identity disagrees with the canonical request cannot produce a publishable project scope",
            all(
                item["scope"] is None and item["accepted"] is False
                for item in tampered_registry_results.values()
            )
            and studio_module._is_primary_figure_set_export_scope(restored_scope),
            {
                "attacks": tampered_registry_results,
                "restored_scope": restored_scope,
            },
        )
    )
    partition_attacks: dict[str, bool] = {}
    if isinstance(restored_scope, dict):
        primary_id = str(restored_scope["primary_figure_id"])
        primary_unavailable = json.loads(json.dumps(restored_scope))
        primary_unavailable["available_figure_ids"].remove(primary_id)
        primary_unavailable["unavailable_figure_ids"].append(primary_id)
        missing_blocked = json.loads(json.dumps(restored_scope))
        if missing_blocked["blocked_figure_ids"]:
            missing_blocked["blocked_figure_ids"].pop()
        orphan_planned = json.loads(json.dumps(restored_scope))
        orphan_planned["planned_figure_ids"].append("orphan_metric")
        overlap = json.loads(json.dumps(restored_scope))
        if overlap["blocked_figure_ids"]:
            overlap["unavailable_figure_ids"].append(
                overlap["blocked_figure_ids"][0]
            )
        for attack_id, scope in (
            ("primary_marked_unavailable", primary_unavailable),
            ("secondary_missing_from_blocked", missing_blocked),
            ("orphan_planned_id", orphan_planned),
            ("available_unavailable_overlap", overlap),
        ):
            partition_attacks[attack_id] = (
                studio_module._is_primary_figure_set_export_scope(scope)
            )
    checks.append(
        _check(
            "figure_set_scope_partition_is_complete",
            "A primary-only receipt requires one available primary, every ready secondary blocked, and a complete disjoint planned availability partition",
            bool(partition_attacks)
            and not any(partition_attacks.values())
            and studio_module._is_primary_figure_set_export_scope(restored_scope),
            {
                "attack_acceptance": partition_attacks,
                "restored_scope": restored_scope,
            },
        )
    )
    synthetic_loss = next(
        item for item in ready_synthetic if item["metric"] == "loss_modulus"
    )
    transactional_document = Path(str(synthetic_loss["document"]))
    transactional_spec = transactional_document.with_suffix(".spec.json")
    transactional_registry = synthetic_project / "studio" / "figure_set.json"
    transactional_document.write_bytes(
        transactional_document.read_bytes()
        + b"\n# SciPlot failed-transaction manual edit probe\n"
    )
    transactional_spec.write_bytes(transactional_spec.read_bytes() + b"\n")
    canonical_before = {
        path: path.read_bytes()
        for path in (
            transactional_document,
            transactional_spec,
            transactional_registry,
        )
    }
    history_before = {
        path.relative_to(synthetic_project)
        for path in synthetic_project.rglob("history/*")
        if path.is_file()
    }
    replace_calls: list[dict[str, str]] = []
    original_replace = studio_module._replace_studio_figure_set_path

    def _fail_second_replace(source: Path, target: Path) -> None:
        replace_calls.append({"source": str(source), "target": str(target)})
        if len(replace_calls) == 2:
            raise OSError("injected second figure-set replace failure")
        original_replace(source, target)

    transaction_error: Exception | None = None
    with patch.object(
        studio_module,
        "_replace_studio_figure_set_path",
        side_effect=_fail_second_replace,
    ):
        try:
            prepare_studio_document(
                synthetic_project,
                regenerate_generated=True,
            )
        except Exception as exc:
            transaction_error = exc
    canonical_after = {
        path: path.read_bytes()
        for path in (
            transactional_document,
            transactional_spec,
            transactional_registry,
        )
    }
    history_after = {
        path.relative_to(synthetic_project)
        for path in synthetic_project.rglob("history/*")
        if path.is_file()
    }
    transaction_residue = sorted(
        str(path.relative_to(synthetic_project))
        for path in synthetic_project.rglob(
            ".sciplot-figure-set-transaction-*"
        )
    )
    checks.append(
        _check(
            "second_replace_failure_rolls_back_secondary_transaction",
            "A failure replacing the staged secondary spec restores the prior VSZ, spec, and registry bytes without archiving or leaving transaction files",
            transaction_error is not None
            and "injected second figure-set replace failure"
            in str(transaction_error)
            and canonical_after == canonical_before
            and history_after == history_before
            and not transaction_residue
            and [item["target"] for item in replace_calls]
            == [str(transactional_document), str(transactional_spec)],
            {
                "error": str(transaction_error) if transaction_error else None,
                "replace_calls": replace_calls,
                "canonical_bytes_unchanged": canonical_after == canonical_before,
                "history_unchanged": history_after == history_before,
                "transaction_residue": transaction_residue,
            },
        )
    )
    synthetic_loss_hash = existing_file_sha256(transactional_document)
    for index, source_path in enumerate(
        sorted((synthetic_project / "source").rglob("*.csv")),
        start=1,
    ):
        source_path.write_text(
            _synthetic_export(
                source_path.stem,
                1.0 + index * 0.1,
                include_loss_modulus=False,
            ),
            encoding="utf-8",
        )
    prepare_studio_document(
        synthetic_project,
        regenerate_generated=True,
    )
    missing_after_regeneration = _registry_summary(synthetic_project)
    preserved_missing_loss = next(
        item
        for item in missing_after_regeneration["figures"]
        if item["metric"] == "loss_modulus"
    )
    checks.append(
        _check(
            "failed_secondary_regeneration_preserves_prior_document",
            "A missing metric is detected before replacement, so the last valid secondary VSZ remains intact",
            (
                synthetic_loss_hash is not None
                and preserved_missing_loss["status"] == "unavailable"
                and preserved_missing_loss["document_exists"]
                and preserved_missing_loss["document_sha256"] == synthetic_loss_hash
            ),
            {
                "prior_hash": synthetic_loss_hash,
                "after": preserved_missing_loss,
            },
        )
    )

    real_summary: dict[str, Any] | None = None
    if real_project is not None:
        copied_real = _copy_project_fixture(
            real_project.expanduser().resolve(), run_root / "real_copy"
        )
        prepare_studio_document(copied_real, regenerate_generated=True)
        real_summary = _registry_summary(copied_real)
        real_figures = real_summary["figures"]
        expected_labels = {
            "storage_modulus": "\\italic{G}′ (Pa)",
            "loss_modulus": "\\italic{G}″ (Pa)",
            "loss_factor": "tan \\delta",
            "complex_viscosity": "|\\eta^{*}| (Pa·s)",
        }
        expected_first_y = {
            "storage_modulus": 29642.0,
            "loss_modulus": 40357.0,
            "loss_factor": 1.361,
            "complex_viscosity": 500.73,
        }
        expected_sample_order = [
            "A0E6Z0",
            "A0E6Z3",
            "A10E6Z4",
            "A20E6Z5",
            "A30E6Z0",
            "A30E6Z6",
        ]
        checks.append(
            _check(
                "real_four_metric_documents",
                "The real D3 frequency sweep creates four correctly bound 60x55 independent documents with canonical labels",
                len(real_figures) == 4
                and all(item["status"] == "ready" for item in real_figures)
                and all(item["document_exists"] for item in real_figures)
                and all(item["size_mm"] == [60, 55] for item in real_figures)
                and all(
                    item["source_metric"] == item["metric"] for item in real_figures
                )
                and all(
                    item["y_label"] == expected_labels[item["metric"]]
                    for item in real_figures
                )
                and all(
                    item["sample_order"] == expected_sample_order
                    for item in real_figures
                )
                and all(item["first_x_values"] == [100.0] * 6 for item in real_figures)
                and all(
                    isinstance(item["first_y"], int | float)
                    and math.isclose(
                        float(item["first_y"]),
                        expected_first_y[item["metric"]],
                        rel_tol=0.0,
                        abs_tol=1.0e-9,
                    )
                    for item in real_figures
                )
                and next(
                    item for item in real_figures if item["metric"] == "loss_factor"
                )["y_scale"]
                == "linear"
                and len(
                    {
                        item["document_sha256"]
                        for item in real_figures
                        if item["document_sha256"]
                    }
                )
                == 4,
                real_summary,
            )
        )
        viscosity = next(
            item for item in real_figures if item["metric"] == "complex_viscosity"
        )
        checks.append(
            _check(
                "real_complex_viscosity_is_canonical_pa_s",
                "The D3 complex-viscosity figure uses converted Pa-s values rather than source mPa-s magnitudes",
                isinstance(viscosity.get("first_y"), int | float)
                and 1.0 <= float(viscosity["first_y"]) < 100000.0,
                viscosity,
            )
        )
        editable = next(
            item for item in real_figures if item["metric"] == "loss_modulus"
        )
        editable_document = Path(str(editable["document"]))
        editable_document.write_text(
            editable_document.read_text(encoding="utf-8")
            + "\n# SciPlot figure-set manual-edit probe\n",
            encoding="utf-8",
        )
        manual_hash = existing_file_sha256(editable_document)
        prepare_studio_document(copied_real)
        preserved_summary = _registry_summary(copied_real)
        preserved_entry = next(
            item
            for item in preserved_summary["figures"]
            if item["metric"] == "loss_modulus"
        )
        prepare_studio_document(copied_real, regenerate_generated=True)
        regenerated_summary = _registry_summary(copied_real)
        regenerated_entry = next(
            item
            for item in regenerated_summary["figures"]
            if item["metric"] == "loss_modulus"
        )
        archived_hashes = {
            existing_file_sha256(path)
            for path in (editable_document.parent / "history").glob(
                "loss_modulus_vs_frequency_*.vsz"
            )
        }
        checks.append(
            _check(
                "secondary_manual_edit_is_preserved_then_archived",
                "Opening a project preserves a manually edited secondary VSZ, while explicit regeneration archives it before replacing it",
                manual_hash is not None
                and preserved_entry["document_sha256"] == manual_hash
                and preserved_entry["document_sha256"]
                != preserved_entry["generated_hash"]
                and regenerated_entry["document_sha256"]
                == regenerated_entry["generated_hash"]
                and regenerated_entry["document_sha256"] != manual_hash
                and manual_hash in archived_hashes,
                {
                    "manual_hash": manual_hash,
                    "preserved": preserved_entry,
                    "regenerated": regenerated_entry,
                    "archived_hashes": sorted(
                        value for value in archived_hashes if value
                    ),
                },
            )
        )

    registry = synthetic["registry"]
    checks.append(
        _check(
            "independent_documents_never_infer_composite",
            "A multi-document figure queue remains independent and does not infer publication composition",
            registry.get("document_policy") == "independent_single_page_vsz"
            and registry.get("publication_layout_inferred") is False
            and registry.get("composite_figure") is False,
            registry,
        )
    )
    export_contract = (
        registry.get("export_contract")
        if isinstance(registry.get("export_contract"), dict)
        else {}
    )
    checks.append(
        _check(
            "secondary_publish_scope_is_explicit",
            "Until a multi-document receipt exists, secondary documents are explicitly blocked from the primary exact-current publish scope",
            export_contract.get("status") == "primary_exact_current_only"
            and export_contract.get("supported_figure_ids")
            == [registry.get("primary_figure_id")]
            and bool(export_contract.get("blocked_figure_ids"))
            and bool(export_contract.get("blocker")),
            export_contract,
        )
    )
    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": "sciplot_studio_figure_set_probe",
        "version": 1,
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "checks": checks,
        "artifacts": {
            "run_root": str(run_root),
            "synthetic_project": str(synthetic_project),
            "real_project_copy": (
                str(copied_real) if real_project is not None else None
            ),
        },
        "limitations": [
            "The synthetic inputs are contract fixtures, not real-data evidence.",
            "The real-project check uses an isolated copy and does not mutate the source project.",
        ],
    }
    summary_path = run_root / "studio_figure_set_probe.json"
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    payload["artifacts"]["summary"] = str(summary_path)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the bounded rheology frequency figure-set contract."
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--real-project", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = run_studio_figure_set_probe(
        output_root=args.out,
        real_project=args.real_project,
    )
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_studio_figure_set_probe"]
