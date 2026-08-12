from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

import sciplot_core.intake as intake
from sciplot_core.studio import (
    StudioPreparationBlocked,
    _read_source_frame_records,
)
from sciplot_core.veusz_audit import _owner_widget


def _session_payload(source: Path, *, output_root: Path) -> dict[str, object]:
    content = source.read_bytes()
    return {
        "project_name": "session-integrity",
        "data_type_id": "unknown",
        "experiment_type_id": "unknown",
        "output_root": str(output_root),
        "groups": [
            {
                "sample": "A",
                "files": [
                    {
                        "name": source.name,
                        "source_path": str(source),
                        "size_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        ],
    }


def test_intake_session_restore_requires_original_file_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    payload = _session_payload(source, output_root=tmp_path / "outputs")
    payload["group_order_is_explicit"] = False
    captured: dict[str, object] = {}

    def fake_create_intake_project(**kwargs):
        captured.update(kwargs)
        return {"kind": "captured"}

    monkeypatch.setattr(intake, "create_intake_project", fake_create_intake_project)

    assert intake.create_intake_project_from_session(payload) == {"kind": "captured"}
    groups = captured["groups"]
    assert len(groups) == 1
    assert groups[0].files[0].content == b"x,y\n1,2\n"
    assert captured["group_order_is_explicit"] is False

    source.write_text("x,y\n1,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after the session"):
        intake.create_intake_project_from_session(payload)


def test_intake_session_restore_rejects_missing_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    payload = _session_payload(source, output_root=tmp_path / "outputs")
    source.unlink()

    with pytest.raises(FileNotFoundError, match="missing or not a file"):
        intake.create_intake_project_from_session(payload)


def test_studio_directory_read_fails_closed_on_one_unreadable_table(
    tmp_path: Path,
) -> None:
    pd.DataFrame({"x": [1, 2], "y": [3, 4]}).to_csv(
        tmp_path / "valid.csv",
        index=False,
    )
    (tmp_path / "broken.xlsx").write_bytes(b"not an Excel workbook")

    with pytest.raises(StudioPreparationBlocked) as exc_info:
        _read_source_frame_records(tmp_path)

    assert exc_info.value.reason_code == "source_table_read_failed"
    assert "broken.xlsx" in str(exc_info.value)


def test_owner_widget_finds_nearest_path_ancestor_without_global_scan() -> None:
    widgets = {
        "/page1": object(),
        "/page1/graph1": object(),
        "/page1/graph1/series_1": object(),
    }

    owner = _owner_widget(
        "/page1/graph1/series_1/PlotLine/color",
        widgets,
    )

    assert owner == (
        "/page1/graph1/series_1",
        widgets["/page1/graph1/series_1"],
    )
    assert _owner_widget("/unknown/setting", widgets) is None
