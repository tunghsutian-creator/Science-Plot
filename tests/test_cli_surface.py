from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sciplot_core import cli


def _command_choices() -> set[str]:
    parser = cli._build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return set(subparsers.choices)


def _visible_command_choices() -> set[str]:
    parser = cli._build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return {str(action.dest) for action in subparsers._choices_actions}


def test_retired_user_commands_are_not_parseable() -> None:
    retired = {"one-step", "quick", "prepare", "intake", "workbench"}
    assert retired.isdisjoint(_command_choices())


@pytest.mark.parametrize("option", ["--catalog", "--all", "--json"])
def test_app_has_no_hidden_catalog_submode(option: str) -> None:
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(["app", option])


def test_help_exposes_one_studio_family_and_hides_internal_probes() -> None:
    help_text = cli._build_parser().format_help()
    assert "studio" in help_text
    assert "autoplot" in help_text
    assert "one-step" not in help_text
    assert "workbench" not in help_text
    assert "readiness-probe" not in help_text
    assert "--advanced-editor" not in help_text
    studio_help = cli._build_parser()._subparsers._group_actions[0].choices[
        "studio"
    ].format_help()
    assert "--prepare-only" not in studio_help
    assert "--qt-smoke" not in studio_help


def test_specialized_figure_route_is_not_a_cli_command() -> None:
    assert "figure" not in _command_choices()
    assert "figure" not in _visible_command_choices()


def test_batch_regression_runner_is_parseable_but_not_public_automation() -> None:
    assert "batch" in _command_choices()
    assert "batch" not in _visible_command_choices()


def test_retired_advanced_editor_flag_is_not_parseable(tmp_path: Path) -> None:
    document = tmp_path / "figure.vsz"
    document.write_text("# Veusz saved document\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(
            ["studio", str(document), "--advanced-editor"]
        )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"state": "ready", "ready_to_use": True, "qa": {"status": "passed"}}, 0),
        ({"state": "ready", "qa": {"status": "passed"}}, 1),
        (
            {
                "state": "ready",
                "ready_to_use": 1,
                "qa": {"status": "passed"},
            },
            1,
        ),
        (
            {
                "one_step": {"state": "needs_human_confirmation"},
                "qa": {"status": "passed"},
            },
            1,
        ),
        (
            {
                "one_step": {"state": "needs_rule_repair"},
                "qa": {"status": "failed"},
            },
            1,
        ),
    ],
)
def test_run_exit_code_tracks_lifecycle_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    expected: int,
) -> None:
    request = tmp_path / "plot_request.json"
    request.write_text("{}\n", encoding="utf-8")
    import sciplot_core.workflow as workflow

    monkeypatch.setattr(workflow, "run_request", lambda _path: payload)
    assert cli.main(["run", str(request)]) == expected


@pytest.mark.parametrize("ready_to_use", [None, False, 1, "yes"])
def test_autoplot_exit_code_fails_closed_on_ready_to_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ready_to_use: object,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    payload = {
        "state": "ready",
        "ready_to_use": ready_to_use,
        "delivery": None,
        "run_output": str(tmp_path / "run"),
    }
    monkeypatch.setattr(cli, "run_autoplot", lambda *_args, **_kwargs: payload)

    assert cli.main(["autoplot", str(source), "--json"]) == 1


def test_autoplot_cli_forwards_explicit_presentation_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "impact.xlsx"
    source.write_bytes(b"fixture")
    captured: dict[str, object] = {}

    def fake_run_autoplot(*_args: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "state": "ready",
            "ready_to_use": True,
            "delivery": str(tmp_path / "delivery"),
            "run_output": str(tmp_path / "run"),
        }

    monkeypatch.setattr(cli, "run_autoplot", fake_run_autoplot)

    assert (
        cli.main(
            [
                "autoplot",
                str(source),
                "--template",
                "bar",
                "--json",
            ]
        )
        == 0
    )
    assert captured["template"] == "bar"
