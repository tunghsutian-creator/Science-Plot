from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sciplot_core import batch, intake
from sciplot_core.semantic import (
    has_tensile_export_parent,
    is_tensile_export_dir,
    tensile_export_csv_files,
    tensile_export_sample_name,
)


def test_tensile_export_directory_recognition_is_shared_across_surfaces(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    export_dir = source_root / "Sample_A.is_tens_Exports"
    export_dir.mkdir(parents=True)
    member = export_dir / "curve.csv"
    member.write_text("strain,stress\n0,0\n1,1\n", encoding="utf-8")

    assert is_tensile_export_dir(export_dir)
    assert has_tensile_export_parent(member)
    assert intake._tensile_export_dirs(source_root) == [export_dir]
    assert batch._is_tensile_related(member)


def test_tensile_export_suffix_does_not_match_an_ordinary_file(
    tmp_path: Path,
) -> None:
    ordinary_file = tmp_path / "not_a_directory.is_tens_Exports"
    ordinary_file.write_text("not an export directory", encoding="utf-8")

    assert not is_tensile_export_dir(ordinary_file)
    assert not has_tensile_export_parent(ordinary_file)
    assert not batch._is_tensile_related(ordinary_file)


def test_tensile_export_members_and_sample_name_are_case_insensitive(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    export_dir = source_root / "Sample_A.IS_TENS_EXPORTS"
    export_dir.mkdir(parents=True)
    member = export_dir / "CURVE.CSV"
    member.write_text("strain,stress\n0,0\n1,1\n", encoding="utf-8")

    session = intake.prepare_intake_session(
        source_root,
        output_root=tmp_path / "intake",
    )

    assert tensile_export_sample_name(export_dir) == "Sample_A"
    assert tensile_export_csv_files(export_dir) == [member]
    assert session["group_order_is_explicit"] is False
    assert session["groups"][0]["sample"] == "Sample_A"
    assert [item["name"] for item in session["groups"][0]["files"]] == ["CURVE.CSV"]


def test_explicit_rule_short_circuits_source_inspection_and_auto_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.semantic_sources.classification as classification

    real_get_rule = classification.get_rule
    ready_rule = real_get_rule("tga_curve")
    catalog_versions = [ready_rule, replace(ready_rule, fixture_status="pending")]
    lookups: list[str] = []

    def lookup(rule_id: str):
        lookups.append(rule_id)
        if rule_id == ready_rule.rule_id and catalog_versions:
            return catalog_versions.pop(0)
        return real_get_rule(rule_id)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("explicit rule selection entered automatic inspection")

    monkeypatch.setattr(classification, "get_rule", lookup)
    for attribute in (
        "inspect_input_file",
        "_text_preview",
        "is_performance_comparison_source",
        "is_rheology_temperature_comparison_dir",
        "match_rule",
    ):
        monkeypatch.setattr(classification, attribute, unexpected)

    missing_source = tmp_path / "source-does-not-need-to-exist.csv"
    ready = classification.classify_source(
        missing_source,
        requested_rule_id=ready_rule.rule_id,
    )
    pending = classification.classify_source(
        missing_source,
        requested_rule_id=ready_rule.rule_id,
    )

    assert ready["rule_id"] == ready_rule.rule_id
    assert ready["confidence"] == 100.0
    assert ready["production_status"] == "ready"
    assert ready["vendor_model"] is None
    assert pending["rule_readiness"] == "pending"
    assert pending["confidence"] == 0.0
    assert pending["production_status"] == "needs_rule_repair"
    assert pending["needs_ai_intervention"] is True
    for invalid_rule_id in ("", "not_a_rule"):
        with pytest.raises(ValueError, match="Unknown material rule"):
            classification.classify_source(
                missing_source,
                requested_rule_id=invalid_rule_id,
            )
    assert lookups == [ready_rule.rule_id, ready_rule.rule_id, "", "not_a_rule"]
