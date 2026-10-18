"""The public CLI forwards exact source selection into the ordinary task owner."""

import pytest

from sciplot_core.cli.dispatch.tasks import dispatch_task
from sciplot_core.cli.parsers.builder import build_parser
from sciplot_core.task_contract import TaskControlError


def test_selection_flags_reach_the_existing_task_owner(monkeypatch, capsys):
    calls = []

    def create(source, **kwargs):
        calls.append((source, kwargs))
        return {"status": "needs_review"}

    monkeypatch.setattr("sciplot_core.task_shortcuts.create_task", create)
    args = build_parser().parse_args([
        "task", "create", "/original.csv", "--x", "angular_frequency",
        "--y", "complex_viscosity", "--y-unit", "mPa s",
        "--test-name", "HDPE-Control", "--test-name", "Exact Case",
        "--source-block", "source:0/table:0/block:1",
        "--source-block", "source:1/table:2/block:3", "--full", "--json",
    ])
    assert dispatch_task(args) == 0
    assert len(calls) == 1
    source, options = calls[0]
    assert str(source) == "/original.csv"
    assert options["intent"]["selection"] == {
        "test_names": ["HDPE-Control", "Exact Case"],
        "blocks": [
            {"source_id": "source:0", "table_id": "table:0", "block_id": "block:1"},
            {"source_id": "source:1", "table_id": "table:2", "block_id": "block:3"},
        ],
    }
    assert options["intent"]["y"] == {"quantity": "complex_viscosity", "unit": "mPa s"}
    assert "needs_review" in capsys.readouterr().out


@pytest.mark.parametrize("selection", [
    ["--source-block", "block:1"],
    ["--source-block", "source:0/table:0/block:1/extra"],
    ["--source-block", "source:-1/table:0/block:1"],
    ["--intent", "/intent.json", "--test-name", "HDPE-Control"],
])
def test_invalid_selection_flags_fail_before_task_creation(monkeypatch, selection):
    def unexpected(*args, **kwargs):
        pytest.fail("A rejected CLI selection must not create a task.")

    monkeypatch.setattr("sciplot_core.task_shortcuts.create_task", unexpected)
    args = build_parser().parse_args([
        "task", "create", "/original.csv", "--x", "angular_frequency",
        "--y", "complex_viscosity", *selection, "--json",
    ])
    with pytest.raises(TaskControlError) as error:
        dispatch_task(args)
    assert error.value.reason_code == "invalid_semantic_intent"


def test_selection_alone_requires_scientific_coordinates_before_creation(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Selection alone must not silently run the source-only route.")

    monkeypatch.setattr("sciplot_core.task_shortcuts.create_task", unexpected)
    args = build_parser().parse_args(["task", "create", "/original.csv", "--test-name", "HDPE-Control"])
    with pytest.raises(TaskControlError) as error:
        dispatch_task(args)
    assert error.value.reason_code == "invalid_semantic_intent"
