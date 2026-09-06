from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pandas as pd
import pytest

from sciplot_core.semantic_sources.models import RheologySweepSample
from sciplot_core.semantic_sources import rheology_workbooks as workbooks


def _sample(root: Path, name: str = "Sample A") -> RheologySweepSample:
    return RheologySweepSample(
        sample=name,
        source=root / "raw.csv",
        x_label="Angular Frequency",
        x_unit="rad/s",
        metric_units={"storage_modulus": "Pa", "loss_modulus": "Pa"},
        rows=(
            {"x": 1.0, "storage_modulus": 100.0, "loss_modulus": 40.0},
            {"x": 10.0, "storage_modulus": 80.0, "loss_modulus": 30.0},
        ),
    )


def _write(path: Path, samples: list[RheologySweepSample], **options) -> None:
    workbooks._write_rheology_sweep_comparison_workbook(
        samples, path, comparison_sheet="Frequency_Comparison", **options
    )


def _old_save_timestamps(path: Path) -> None:
    """Make the next real writer differ in both ZIP and core-property dates."""
    with ZipFile(path) as archive:
        parts = [(entry, archive.read(entry)) for entry in archive.infolist()]
    with ZipFile(path, "w") as archive:
        for entry, original_content in parts:
            content = original_content
            entry.date_time = (2000, 1, 1, 0, 0, 0)
            if entry.filename == "docProps/core.xml":
                properties = ElementTree.fromstring(content)
                for name in ("created", "modified"):
                    timestamp = properties.find(f"{{http://purl.org/dc/terms/}}{name}")
                    assert timestamp is not None
                    timestamp.text = "2000-01-01T00:00:00Z"
                content = ElementTree.tostring(properties)
            archive.writestr(entry, content)


def test_repeated_frequency_preparation_preserves_already_bound_workbook_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "frequency.xlsx"
    sample = _sample(tmp_path)
    _write(path, [sample], source_replicates=[sample])
    _old_save_timestamps(path)
    before, stat = path.read_bytes(), path.stat()

    _write(path, [sample], source_replicates=[sample])

    assert path.read_bytes() == before
    assert path.stat().st_ino == stat.st_ino
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "change", ["value", "unit", "sample", "order", "raw_replicate"]
)
def test_scientific_workbook_changes_are_materialized_instead_of_reusing_old_bytes(
    tmp_path: Path,
    change: str,
) -> None:
    path = tmp_path / "frequency.xlsx"
    first, second = _sample(tmp_path), _sample(tmp_path, "Sample B")
    _write(path, [first, second], source_replicates=[first])
    before = path.read_bytes()
    samples, replicates = [first, second], [first]
    if change == "value":
        samples[0] = replace(first, rows=({**first.rows[0], "storage_modulus": 111.0},))
    elif change == "unit":
        samples[0] = replace(first, metric_units={"storage_modulus": "kPa"})
    elif change == "sample":
        samples[0] = replace(first, sample="Renamed sample")
    elif change == "order":
        samples.reverse()
    else:
        replicates.append(second)

    _write(path, samples, source_replicates=replicates)

    assert path.read_bytes() != before
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    comparison = sheets["Frequency_Comparison"]
    assert comparison.iat[1, 0] == samples[0].sample
    assert comparison.iat[2, 1] == samples[0].metric_units["storage_modulus"]
    assert comparison.iat[3, 1] == samples[0].rows[0]["storage_modulus"]
    assert len(sheets) == 1 + len(samples) + len(replicates)
    assert not list(tmp_path.glob(".frequency-*.xlsx"))


def test_failed_candidate_write_preserves_previous_workbook_and_removes_partial_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "frequency.xlsx"
    sample = _sample(tmp_path)
    _write(path, [sample])
    before = path.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("sample sheet write failed")

    monkeypatch.setattr(workbooks, "_sample_sweep_frame", fail)
    with pytest.raises(OSError, match="sample sheet write failed"):
        _write(path, [sample])
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
