from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core import workflow


def _write_request(path: Path, *, input_path: Path, output_dir: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(input_path),
                "output": str(output_dir),
            }
        ),
        encoding="utf-8",
    )
    return path


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _raise_after_output_setup(*_args: object, **_kwargs: object) -> dict[str, object]:
    raise RuntimeError("synthetic failure after managed output setup")


def test_existing_managed_output_is_restored_after_run_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.csv"
    input_path.write_text("x,y\n0,1\n", encoding="utf-8")
    output_dir = tmp_path / "existing_output"
    (output_dir / "figures").mkdir(parents=True)
    (output_dir / "figures" / "old.pdf").write_bytes(b"old-pdf")
    (output_dir / "delivery").mkdir()
    (output_dir / "delivery" / "old.txt").write_text("old delivery", encoding="utf-8")
    (output_dir / "raw").mkdir()
    (output_dir / "raw" / "old.csv").write_text("old raw", encoding="utf-8")
    (output_dir / "manifest.json").write_text('{"state":"ready"}', encoding="utf-8")
    (output_dir / "one_step_status.json").write_text(
        '{"state":"ready"}', encoding="utf-8"
    )
    (output_dir / "autoplot_summary.json").write_text(
        '{"ready_to_use":true}', encoding="utf-8"
    )
    (output_dir / "unrelated-notes.txt").write_text(
        "keep me", encoding="utf-8"
    )
    before = _file_snapshot(output_dir)
    request_path = _write_request(
        tmp_path / "plot_request.json",
        input_path=input_path,
        output_dir=output_dir,
    )
    monkeypatch.setattr(workflow, "classify_source", _raise_after_output_setup)

    with pytest.raises(RuntimeError, match="synthetic failure"):
        workflow.run_request(request_path)

    assert _file_snapshot(output_dir) == before
    assert not list(
        output_dir.parent.glob(f".{output_dir.name}.sciplot-managed-backup-*")
    )


def test_new_output_keeps_partial_failure_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.csv"
    input_path.write_text("x,y\n0,1\n", encoding="utf-8")
    output_dir = tmp_path / "new_output"
    request_path = _write_request(
        tmp_path / "plot_request.json",
        input_path=input_path,
        output_dir=output_dir,
    )
    monkeypatch.setattr(workflow, "classify_source", _raise_after_output_setup)

    with pytest.raises(RuntimeError, match="synthetic failure"):
        workflow.run_request(request_path)

    assert (output_dir / "request_snapshot.json").is_file()
    assert (output_dir / "raw" / input_path.name).is_file()


def test_successful_managed_transaction_discards_backup_and_keeps_unrelated_files(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text("old", encoding="utf-8")
    unrelated = output_dir / "notes.txt"
    unrelated.write_text("unchanged", encoding="utf-8")

    with workflow._managed_output_transaction(output_dir):
        assert not (output_dir / "manifest.json").exists()
        assert unrelated.read_text(encoding="utf-8") == "unchanged"
        (output_dir / "manifest.json").write_text("new", encoding="utf-8")

    assert (output_dir / "manifest.json").read_text(encoding="utf-8") == "new"
    assert unrelated.read_text(encoding="utf-8") == "unchanged"
    assert not list(
        output_dir.parent.glob(f".{output_dir.name}.sciplot-managed-backup-*")
    )


def test_next_run_dir_atomically_reserves_each_run(tmp_path: Path) -> None:
    project = tmp_path / "project"

    first = workflow._next_run_dir(project)
    second = workflow._next_run_dir(project)

    assert first.name == "run_001"
    assert second.name == "run_002"
    assert first.is_dir()
    assert second.is_dir()
