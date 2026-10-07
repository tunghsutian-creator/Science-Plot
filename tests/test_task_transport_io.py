"""Malformed file input must explain a local correction without starting work."""

import json
from pathlib import Path

import pytest

from sciplot_core import cli


@pytest.mark.parametrize("content,issue", [
    ('{\n  "version": 1,\n}', {"constraint": "json_syntax"}),
    ('[]', {"constraint": "type", "expected": "object"}),
])
def test_bad_request_file_reports_exact_repair_without_allocating_task(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str, issue: dict[str, object],
) -> None:
    source = tmp_path / "request.json"
    source.write_text(content)
    task = tmp_path / "task"
    assert cli.main(["task", "start", "--request", str(source), "--task-dir", str(task), "--json"]) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert captured.err == ""
    assert result["reason_code"] == "invalid_json_file"
    assert result["repair"]["file"] == str(source)
    assert result["repair"]["action"] == "correct_json_file"
    assert result["repair"]["issues"][0]["path"] == "/"
    assert issue.items() <= result["repair"]["issues"][0].items()
    if issue["constraint"] == "json_syntax":
        with pytest.raises(json.JSONDecodeError) as cause:
            json.loads(content)
        assert result["repair"]["issues"][0]["line"] == cause.value.lineno
        assert result["repair"]["issues"][0]["column"] == cause.value.colno
    assert not task.exists()
    assert source.read_text() == content
