from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.materials_rules import (
    get_rule,
    semantic_payload_from_rule,
)
from sciplot_core.studio_core import rule_readiness as readiness_module
from sciplot_core.studio_core.semantic_payloads import (
    _studio_export_semantic_payload,
)


def _document(tmp_path: Path) -> Path:
    document = tmp_path / "studio" / "document.vsz"
    document.parent.mkdir(parents=True)
    document.write_text("Add('page')\n", encoding="utf-8")
    return document


def test_canonical_request_discards_cross_rule_recognition(
    tmp_path: Path,
) -> None:
    request = {
        "rule_id": "performance_comparison",
        "template": "polar_curve",
    }
    readiness = readiness_module.resolve_studio_rule_publication_readiness(request)
    current_rule = get_rule("performance_comparison")
    expected = semantic_payload_from_rule(
        current_rule,
        confidence=100.0,
        reason="Resolved from the persisted request rule for Studio export.",
    )
    stale_recognition: dict[str, Any] = {
        "rule_id": "ftir_spectrum",
        "semantic_family": "ftir_spectrum",
        "template": "stacked_curve",
        "confidence": 0.0,
        "needs_ai_intervention": True,
        "production_status": "needs_rule_repair",
        "rule_readiness": "pending",
        "missing_requirements": ["stale"],
        "reason": "Stale FTIR recognition must not leak.",
        "axis_plan": {"x": {"label": "stale FTIR axis"}},
        "analysis_plan": [{"metric": "stale FTIR metric"}],
        "stale_only": "discard",
    }

    semantic = _studio_export_semantic_payload(
        request=request,
        intake_manifest={"recognition": stale_recognition},
        document_path=_document(tmp_path),
        rule_readiness=readiness,
    )

    assert semantic["rule_id"] == "performance_comparison"
    assert semantic["semantic_family"] == current_rule.semantic_family
    assert semantic["template"] == expected["template"]
    assert semantic["axis_plan"] == expected["axis_plan"]
    assert semantic["analysis_plan"] == expected["analysis_plan"]
    assert semantic["reason"] == expected["reason"]
    assert semantic["confidence"] == 100.0
    assert semantic["needs_ai_intervention"] is False
    assert semantic["production_status"] == "ready"
    assert semantic["rule_readiness"] == "ready"
    assert semantic["missing_requirements"] == []
    assert "stale_only" not in semantic
    assert semantic["studio_rule_publication_readiness"] == readiness.to_payload()
    assert semantic["publication_rule_ready"] is False


def test_matching_recognition_cannot_override_current_catalog_readiness(
    tmp_path: Path,
) -> None:
    request = {
        "rule_id": "performance_comparison",
        "template": "scatter",
    }
    readiness = readiness_module.resolve_studio_rule_publication_readiness(request)
    recognition = {
        "rule_id": "performance_comparison",
        "semantic_family": "performance_comparison",
        "confidence": 0.0,
        "needs_ai_intervention": True,
        "production_status": "needs_rule_repair",
        "rule_readiness": "pending",
        "fixture_status": "pending",
        "pending_rule_review": True,
        "missing_requirements": ["stale"],
        "reason": "Matching historical recognition reason.",
        "vendor_model": "historical-vendor",
        "registered_axis_plan": {"x": {"label": "historical registered axis"}},
        "historical_note": "preserve",
    }

    semantic = _studio_export_semantic_payload(
        request=request,
        intake_manifest={"recognition": recognition},
        document_path=_document(tmp_path),
        rule_readiness=readiness,
    )

    assert semantic["rule_id"] == "performance_comparison"
    assert semantic["semantic_family"] == "performance_comparison"
    assert semantic["confidence"] == 100.0
    assert semantic["needs_ai_intervention"] is False
    assert semantic["production_status"] == "ready"
    assert semantic["rule_readiness"] == "ready"
    assert semantic["missing_requirements"] == []
    assert semantic["fixture_status"] == "ready"
    assert "pending_rule_review" not in semantic
    assert semantic["reason"] == "Matching historical recognition reason."
    assert semantic["vendor_model"] == "historical-vendor"
    assert semantic["historical_note"] == "preserve"
    assert semantic["registered_axis_plan"] == {
        "x": {"label": "historical registered axis"}
    }


def test_semantic_payload_uses_inventory_current_rule_without_a_second_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = {"rule_id": "swelling_curve", "template": "point_line"}
    pending_rule = replace(get_rule("swelling_curve"), fixture_status="pending")
    monkeypatch.setattr(readiness_module, "get_rule", lambda _rule_id: pending_rule)
    readiness = readiness_module.resolve_studio_rule_publication_readiness(request)
    monkeypatch.setattr(
        readiness_module,
        "get_rule",
        lambda _rule_id: pytest.fail("semantic projection repeated the catalog lookup"),
    )

    semantic = _studio_export_semantic_payload(
        request=request,
        intake_manifest={"recognition": {"rule_id": "swelling_curve"}},
        document_path=_document(tmp_path),
        rule_readiness=readiness,
    )

    assert semantic["rule_id"] == "swelling_curve"
    assert semantic["rule_readiness"] == "pending"
    assert semantic["production_status"] == "needs_rule_repair"
    assert semantic["needs_ai_intervention"] is True
    assert semantic["pending_rule_review"] is True


@pytest.mark.parametrize(
    "request_payload",
    [
        {"pending_rule_review": True},
        {
            "rule_id": "swelling_curve",
            "template": "point_line",
            "pending_rule_review": True,
        },
    ],
)
def test_persisted_pending_evidence_always_reaches_exported_semantics(
    tmp_path: Path,
    request_payload: dict[str, Any],
) -> None:
    readiness = readiness_module.resolve_studio_rule_publication_readiness(
        request_payload
    )

    semantic = _studio_export_semantic_payload(
        request=request_payload,
        intake_manifest={},
        document_path=_document(tmp_path),
        rule_readiness=readiness,
    )

    assert semantic["rule_id"] == readiness.rule_id
    assert semantic["pending_rule_review"] is True


def test_recognition_cannot_resurrect_a_missing_canonical_rule_identity(
    tmp_path: Path,
) -> None:
    readiness = readiness_module.resolve_studio_rule_publication_readiness({})

    semantic = _studio_export_semantic_payload(
        request={},
        intake_manifest={
            "recognition": {
                "rule_id": "ftir_spectrum",
                "semantic_family": "ftir_spectrum",
                "reason": "Legacy recognition is historical, not publication identity.",
            }
        },
        document_path=_document(tmp_path),
        rule_readiness=readiness,
    )

    assert semantic["rule_id"] is None
    assert semantic["semantic_family"] == "unknown"
    assert semantic["reason"] == "Exported from the canonical SciPlot Veusz document."
