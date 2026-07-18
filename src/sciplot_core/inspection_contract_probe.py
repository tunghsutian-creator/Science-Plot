from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sciplot_core import render
from sciplot_core._utils import json_safe

INSPECTION_CONTRACT_PROBE_KIND = "sciplot_inspection_contract_probe"
INSPECTION_CONTRACT_PROBE_VERSION = 2


def _check(
    check_id: str,
    label: str,
    passed: bool,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "evidence": json_safe(evidence),
    }


def _ready_semantics() -> dict[str, Any]:
    return {
        "rule_id": "dma_temperature_sweep",
        "semantic_family": "dma_temperature_sweep",
        "recommended_recipe": "rheology_dma",
        "template": "point_line",
        "confidence": 100.0,
        "reason": "Explicit ready rule selected.",
        "production_status": "ready",
        "render_options": {"size": "60x55"},
        "axis_plan": {
            "x": {"canonical_label": "Temperature"},
            "y": {"canonical_label": "Storage modulus"},
        },
    }


def _generic_payload() -> dict[str, Any]:
    return {
        "source": "fixture.csv",
        "model": "replicate_table",
        "model_label": "Replicate wide table",
        "recommendations": [
            {
                "template_id": "violin",
                "default_render_overrides": {"size": "60x55"},
            }
        ],
        "canonical_templates": [],
        "advanced_templates": [],
        "recommendation_confidence": 84.0,
        "recommendation_summary": "Generic shape match.",
        "warnings": [
            "There are many groups, so x-axis labels may wrap or shrink.",
            "Non-finite values were dropped from 3 rows.",
        ],
    }


def run_inspection_contract_probe(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / "fixture.csv"
    source.write_text("Temperature,Storage modulus\n25,100\n50,80\n", encoding="utf-8")
    directory_source = root / "dma_temperature_sweep_directory"
    directory_source.mkdir(parents=True, exist_ok=True)
    empty_source = root / "dma_temperature_sweep" / "empty.csv"
    empty_source.parent.mkdir(parents=True, exist_ok=True)
    empty_source.write_bytes(b"")
    corrupt_sources = {
        "dma": root / "dma_temperature_sweep" / "corrupt.csv",
        "rheology": root / "rheology_frequency_sweep" / "corrupt.csv",
        "ftir": root / "ftir_spectrum" / "corrupt.csv",
        "saxs": root / "saxs_profile" / "corrupt.csv",
    }
    for corrupt_source in corrupt_sources.values():
        corrupt_source.parent.mkdir(parents=True, exist_ok=True)
        corrupt_source.write_text(
            "not,a,usable,table\nthis is non-empty gibberish\n",
            encoding="utf-8",
        )

    original_inspect = render.inspect_input_file
    original_classify = render.classify_source
    try:
        render.inspect_input_file = lambda _source, _sheet: _generic_payload()
        render.classify_source = lambda _source, **_kwargs: _ready_semantics()
        ready_payload = render.inspect_payload(source)

        same_model_payload_source = _generic_payload()
        same_model_payload_source["model"] = "dma_temperature_sweep"
        same_model_payload_source["recommendations"] = [
            {
                "template_id": "point_line",
                "default_render_overrides": {"size": "60x55"},
            }
        ]
        same_model_payload_source["warnings"] = [
            "Missing axis labels; add labels before export.",
            "Missing values were dropped from 2 rows.",
            "Missing axis labels and non-finite values were found.",
        ]
        render.inspect_input_file = lambda _source, _sheet: same_model_payload_source
        same_model_payload = render.inspect_payload(source)

        render.inspect_input_file = lambda _source, _sheet: (_ for _ in ()).throw(
            ValueError("Generic reader cannot parse this instrument container.")
        )
        semantic_candidate_payload = render.inspect_payload(directory_source)

        render.inspect_input_file = lambda _source, _sheet: _generic_payload()
        render.classify_source = lambda _source, **_kwargs: {
            "rule_id": None,
            "semantic_family": "unknown",
            "template": "curve",
            "production_status": "unknown",
        }
        generic_payload = render.inspect_payload(source)
        try:
            render.inspect_payload(empty_source)
        except ValueError as exc:
            empty_source_error = str(exc)
        else:
            empty_source_error = ""
    finally:
        render.inspect_input_file = original_inspect
        render.classify_source = original_classify

    corrupt_errors: dict[str, dict[str, str]] = {}
    for family, corrupt_source in corrupt_sources.items():
        try:
            render.inspect_payload(corrupt_source)
        except Exception as exc:
            corrupt_errors[family] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        else:
            corrupt_errors[family] = {"type": "", "message": ""}

    ready_provenance = ready_payload.get("inspection_warning_provenance")
    if not isinstance(ready_provenance, list):
        ready_provenance = []
    checks = [
        _check(
            "ready_rule_selects_authoritative_model",
            "A ready material rule replaces the generic model and recommendation",
            ready_payload.get("model") == "dma_temperature_sweep"
            and (ready_payload.get("recommendations") or [{}])[0].get("template_id")
            == "point_line"
            and ready_payload.get("inspection_resolution", {}).get("status")
            == "ready_rule_authoritative",
            {
                "model": ready_payload.get("model"),
                "template": (ready_payload.get("recommendations") or [{}])[0].get(
                    "template_id"
                ),
                "resolution": ready_payload.get("inspection_resolution"),
            },
        ),
        _check(
            "superseded_shape_warning_hidden",
            "Generic shape and presentation warnings do not leak into user warnings",
            ready_payload.get("warnings")
            == [
                "[generic_table_inspection] Non-finite values were dropped from 3 rows."
            ],
            {"warnings": ready_payload.get("warnings")},
        ),
        _check(
            "unresolved_risk_keeps_source",
            "An unresolved generic data risk remains visible with its source",
            any(
                item.get("source") == "generic_table_inspection"
                and item.get("disposition") == "preserved_for_review"
                and "Non-finite" in str(item.get("message"))
                for item in ready_provenance
                if isinstance(item, dict)
            ),
            {"warning_provenance": ready_provenance},
        ),
        _check(
            "superseded_warning_remains_auditable",
            "A hidden generic presentation warning remains auditable as superseded",
            any(
                item.get("source") == "generic_table_inspection"
                and item.get("disposition") == "superseded_by_ready_rule"
                and "many groups" in str(item.get("message"))
                for item in ready_provenance
                if isinstance(item, dict)
            ),
            {"warning_provenance": ready_provenance},
        ),
        _check(
            "unreadable_directory_rule_is_candidate_only",
            "A directory that generic inspection cannot read keeps an explicit non-executable candidate and cannot populate automatic recommendation surfaces",
            bool(semantic_candidate_payload.get("warnings"))
            and semantic_candidate_payload.get("recommendation_confidence") == 0.0
            and semantic_candidate_payload.get("recommendations") == []
            and semantic_candidate_payload.get("canonical_templates") == []
            and semantic_candidate_payload.get("unverified_candidate", {}).get(
                "score"
            )
            == 0.0
            and semantic_candidate_payload.get("unverified_candidate", {}).get(
                "lifecycle_policy"
            )
            == "candidate_only"
            and semantic_candidate_payload.get("unverified_candidate", {}).get(
                "recommended_action"
            )
            == "inspect_source"
            and semantic_candidate_payload.get("inspection_resolution", {}).get(
                "status"
            )
            == "generic_inspection_failed"
            and semantic_candidate_payload.get("inspection_resolution", {}).get(
                "authoritative_source"
            )
            is None
            and semantic_candidate_payload.get("inspection_resolution", {}).get(
                "generic_inspection_status"
            )
            == "failed"
            and any(
                item.get("disposition") == "preserved_for_review"
                for item in semantic_candidate_payload.get(
                    "inspection_warning_provenance", []
                )
                if isinstance(item, dict)
            ),
            {
                "warnings": semantic_candidate_payload.get("warnings"),
                "recommendation_confidence": semantic_candidate_payload.get(
                    "recommendation_confidence"
                ),
                "recommendations": semantic_candidate_payload.get("recommendations"),
                "candidate": semantic_candidate_payload.get("unverified_candidate"),
                "resolution": semantic_candidate_payload.get(
                    "inspection_resolution"
                ),
                "warning_provenance": semantic_candidate_payload.get(
                    "inspection_warning_provenance"
                ),
            },
        ),
        _check(
            "same_model_ready_rule_still_owns_warnings",
            "Ready-rule warning ownership does not depend on a model or template mismatch",
            (
                same_model_payload.get("warnings")
                == [
                    "[generic_table_inspection] Missing values were dropped from 2 rows.",
                    "[generic_table_inspection] Missing axis labels and non-finite values were found.",
                ]
                and same_model_payload.get("inspection_resolution", {}).get(
                    "generic_inspection_status"
                )
                == "confirmed"
                and any(
                    item.get("message")
                    == "Missing axis labels; add labels before export."
                    and item.get("disposition") == "superseded_by_ready_rule"
                    for item in same_model_payload.get(
                        "inspection_warning_provenance", []
                    )
                    if isinstance(item, dict)
                )
            ),
            {
                "warnings": same_model_payload.get("warnings"),
                "resolution": same_model_payload.get("inspection_resolution"),
                "warning_provenance": same_model_payload.get(
                    "inspection_warning_provenance"
                ),
            },
        ),
        _check(
            "mixed_presentation_and_data_risk_stays_visible",
            "A warning that combines presentation wording with a data risk is not suppressed",
            any(
                item.get("message")
                == "Missing axis labels and non-finite values were found."
                and item.get("disposition") == "preserved_for_review"
                for item in same_model_payload.get("inspection_warning_provenance", [])
                if isinstance(item, dict)
            ),
            {
                "warnings": same_model_payload.get("warnings"),
                "warning_provenance": same_model_payload.get(
                    "inspection_warning_provenance"
                ),
            },
        ),
        _check(
            "generic_path_unchanged_without_ready_rule",
            "Generic warnings stay unchanged when no ready rule is authoritative",
            generic_payload.get("warnings") == _generic_payload()["warnings"]
            and "inspection_resolution" not in generic_payload,
            {
                "warnings": generic_payload.get("warnings"),
                "has_resolution": "inspection_resolution" in generic_payload,
            },
        ),
        _check(
            "empty_source_cannot_be_ready_by_path",
            "An empty source fails before a path keyword can make a ready rule authoritative",
            "Input file is empty" in empty_source_error,
            {"error": empty_source_error},
        ),
        *[
            _check(
                f"unreadable_{family}_file_fails_closed",
                f"A non-empty unreadable {family} file cannot become authoritative from its path",
                bool(corrupt_errors[family]["type"])
                and "Could not recognize this file"
                in corrupt_errors[family]["message"],
                {
                    "source": str(corrupt_sources[family]),
                    "error": corrupt_errors[family],
                },
            )
            for family in ("dma", "rheology", "ftir", "saxs")
        ],
    ]
    failed = [item for item in checks if item["status"] != "passed"]
    payload = {
        "kind": INSPECTION_CONTRACT_PROBE_KIND,
        "version": INSPECTION_CONTRACT_PROBE_VERSION,
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "summary": {
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "total": len(checks),
        },
    }
    artifact = root / "inspection_contract_probe.json"
    artifact.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    payload["artifact"] = str(artifact)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe SciPlot inspection warning ownership."
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = run_inspection_contract_probe(args.out)
    if args.json:
        print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    else:
        print(
            "SciPlot inspection contract probe: "
            f"{payload['status']} ({payload['summary']['passed']}/{payload['summary']['total']})"
        )
        print(payload["artifact"])
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
