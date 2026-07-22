from __future__ import annotations

from pathlib import Path

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
    assert session["groups"][0]["sample"] == "Sample_A"
    assert [item["name"] for item in session["groups"][0]["files"]] == ["CURVE.CSV"]
