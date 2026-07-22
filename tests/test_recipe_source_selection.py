from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_recipes import common


def test_recipe_directory_with_multiple_tables_fails_before_writing(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "a.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (source_dir / "b.csv").write_text("x,y\n3,4\n", encoding="utf-8")
    output_dir = tmp_path / "output"

    with pytest.raises(ValueError, match="Pass the intended file explicitly"):
        common.run_material_recipe(
            "spectroscopy",
            source_dir,
            output_dir=output_dir,
            default_template="curve",
        )

    assert not output_dir.exists()


def test_recipe_explicit_file_records_unambiguous_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    monkeypatch.setattr(common, "_write_source_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        common,
        "inspect_payload",
        lambda _source: {"recommendations": []},
    )
    monkeypatch.setattr(
        common,
        "render_to_dir",
        lambda *_args, **_kwargs: {
            "export_formats": ["pdf", "tiff_300"],
            "render_engine": "veusz",
            "qa_target": "veusz_export",
            "veusz_documents": [],
            "veusz_specs": [],
            "exports": [],
            "outputs": [],
            "qa_reports": [],
        },
    )

    result = common.run_material_recipe(
        "spectroscopy",
        source,
        output_dir=output_dir,
        default_template="curve",
    )

    selection = result["transform_steps"][0]
    assert selection["parameters"]["selection_policy"] == (
        "only_supported_table_or_explicit_file"
    )
    assert selection["parameters"]["candidate_count"] == 1
    assert selection["parameters"]["requires_human_confirmation"] is False
    assert json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))[
        "processed_source"
    ] == str(output_dir / "processed" / source.name)
