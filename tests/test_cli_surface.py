from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

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
    assert "plan" in help_text
    assert "verify" in help_text
    assert "one-step" not in help_text
    assert "workbench" not in help_text
    assert "readiness-probe" not in help_text
    assert "--advanced-editor" not in help_text
    studio_help = (
        cli._build_parser()
        ._subparsers._group_actions[0]
        .choices["studio"]
        .format_help()
    )
    assert "--prepare-only" not in studio_help
    assert "--qt-smoke" not in studio_help


def test_specialized_figure_route_is_not_a_cli_command() -> None:
    assert "figure" not in _command_choices()
    assert "figure" not in _visible_command_choices()


def test_plan_parser_accepts_explicit_rule_and_template() -> None:
    args = cli._build_parser().parse_args(
        [
            "plan",
            "source.csv",
            "--rule",
            "tensile_curve",
            "--template",
            "curve",
            "--json",
        ]
    )

    assert args.command == "plan"
    assert args.input == Path("source.csv")
    assert args.rule == "tensile_curve"
    assert args.template == "curve"
    assert args.json is True


def test_verify_parser_requires_changed_worktree_scope() -> None:
    args = cli._build_parser().parse_args(["verify", "--changed", "--json"])

    assert args.command == "verify"
    assert args.changed is True
    assert args.json is True
    with pytest.raises(SystemExit) as excinfo:
        cli._build_parser().parse_args(["verify", "--json"])
    assert excinfo.value.code == 2


def test_readiness_merge_parser_accepts_base_summary_and_output() -> None:
    args = cli._build_parser().parse_args(
        [
            "readiness",
            "merge",
            "base.json",
            "acceptance_summary.json",
            "--out",
            "candidate.json",
            "--json",
        ]
    )

    assert args.command == "readiness"
    assert args.readiness_command == "merge"
    assert args.base_registry == Path("base.json")
    assert args.acceptance_summary == Path("acceptance_summary.json")
    assert args.out == Path("candidate.json")
    assert args.json is True


def test_readiness_merge_cli_writes_the_same_registry_and_reports_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_path = tmp_path / "base.json"
    summary_path = tmp_path / "acceptance_summary.json"
    output_path = tmp_path / "candidate.json"
    base_path.write_text("{}", encoding="utf-8")
    summary_path.write_text("{}", encoding="utf-8")
    base_registry = object()
    merged_registry = SimpleNamespace(
        source_acceptance={
            "records": [{"rule_ids": ["uvvis_spectrum", "xrd_pattern"]}]
        }
    )
    captured: dict[str, object] = {}
    import sciplot_core.readiness as readiness

    def fake_load(path):
        captured["base_path"] = path
        return base_registry

    monkeypatch.setattr(readiness, "load_validated_envelope_registry", fake_load)

    def fake_merge(base, summary):
        captured["base"] = base
        captured["summary"] = summary
        return merged_registry

    def fake_write(path, registry):
        captured["output"] = path
        captured["registry"] = registry
        return path.resolve()

    monkeypatch.setattr(readiness, "merge_validated_envelope_registry", fake_merge)
    monkeypatch.setattr(readiness, "write_validated_envelope_registry", fake_write)

    exit_code = cli.main(
        [
            "readiness",
            "merge",
            str(base_path),
            str(summary_path),
            "--out",
            str(output_path),
            "--json",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "base_path": base_path.resolve(),
        "base": base_registry,
        "summary": summary_path.resolve(),
        "output": output_path,
        "registry": merged_registry,
    }
    assert json.loads(capsys.readouterr().out) == {
        "kind": "sciplot_validated_envelope_scoped_merge",
        "version": 1,
        "status": "ready",
        "selected_rule_ids": ["uvvis_spectrum", "xrd_pattern"],
        "base_registry": str(base_path.resolve()),
        "acceptance_summary": str(summary_path.resolve()),
        "registry": str(output_path.resolve()),
    }


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [("passed", 0), ("failed", 1)],
)
def test_verify_cli_emits_owner_payload_and_status_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    expected_exit: int,
) -> None:
    payload = {
        "kind": "sciplot_changed_verification",
        "version": 1,
        "status": status,
        "comparison": {"base": "HEAD"},
        "changed_paths": [],
        "owners": [],
        "unowned_paths": [],
        "checks": [],
        "required_later": {
            "handoff": [],
            "final_milestone": [],
            "release": [],
        },
    }
    import sciplot_core.verification as verification

    monkeypatch.setattr(
        verification,
        "run_changed_verification",
        lambda: payload,
    )

    assert cli.main(["verify", "--changed", "--json"]) == expected_exit
    assert json.loads(capsys.readouterr().out) == payload


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [("planned", 0), ("not_applicable", 0), ("blocked", 1)],
)
def test_plan_cli_emits_owner_payload_and_status_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    expected_exit: int,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    payload = {
        "kind": "sciplot_figure_plan_preview",
        "version": 1,
        "status": status,
        "source": str(source),
        "rule_id": "tensile_curve",
        "template": "curve",
        "resolved_figure_plan": None,
        "scientific_transform": None,
        "blocker": (
            {"reason_code": "fixture_blocked", "message": "Blocked fixture."}
            if status == "blocked"
            else None
        ),
    }
    captured: dict[str, object] = {}
    import sciplot_core.plan_preview as preview_module

    def fake_preview(
        input_path: Path,
        *,
        request: dict[str, object],
    ) -> dict[str, object]:
        captured["input_path"] = input_path
        captured["request"] = request
        return payload

    monkeypatch.setattr(preview_module, "build_plan_preview", fake_preview)

    exit_code = cli.main(
        [
            "plan",
            str(source),
            "--rule",
            "tensile_curve",
            "--template",
            "curve",
            "--json",
        ]
    )

    assert exit_code == expected_exit
    assert captured == {
        "input_path": source,
        "request": {
            "rule_id": "tensile_curve",
            "template": "curve",
            "explicit_template_selection": True,
        },
    }
    assert json.loads(capsys.readouterr().out) == payload


@pytest.mark.parametrize(
    ("arguments", "reason_code"),
    [
        (["--rule", ""], "plan_rule_invalid"),
        (["--rule", "not_a_rule"], "plan_rule_unknown"),
        (
            ["--rule", "tensile_curve", "--template", "polar_curve"],
            "plan_template_unsupported",
        ),
    ],
)
def test_plan_cli_returns_blocked_json_for_expected_invocation_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    reason_code: str,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")

    exit_code = cli.main(["plan", str(source), *arguments, "--json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["kind"] == "sciplot_figure_plan_preview"
    assert payload["version"] == 1
    assert payload["status"] == "blocked"
    assert payload["blocker"]["reason_code"] == reason_code


def test_plan_cli_returns_blocked_json_for_missing_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "missing.csv"

    exit_code = cli.main(
        [
            "plan",
            str(source),
            "--rule",
            "tensile_curve",
            "--template",
            "curve",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "blocked"
    assert payload["blocker"]["reason_code"] == "plan_source_not_found"


def test_plan_cli_returns_blocked_json_for_source_inspection_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "unreadable.csv"
    source.write_text("", encoding="utf-8")

    exit_code = cli.main(["plan", str(source), "--json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "blocked"
    assert payload["blocker"]["reason_code"] == "plan_source_inspection_failed"


def test_plan_cli_explicit_performance_template_selects_the_same_single_task(
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = (
        Path(__file__).parent
        / "fixtures"
        / "performance_comparison"
        / "material_performance_long.csv"
    )

    assert (
        cli.main(
            [
                "plan",
                str(source),
                "--rule",
                "performance_comparison",
                "--template",
                "polar_curve",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    plan = payload["resolved_figure_plan"]
    assert plan["selected_figure_ids"] == ["performance_polar_curve"]
    assert plan["primary_figure_id"] == "performance_polar_curve"


def test_plan_cli_human_output_reports_resolved_scientific_transform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    import sciplot_core.plan_preview as preview_module

    monkeypatch.setattr(
        preview_module,
        "build_plan_preview",
        lambda *_args, **_kwargs: {
            "status": "not_applicable",
            "scientific_transform": {
                "semantic_family": "rheology_stress_relaxation",
                "output": {"series_order": ["E3", "E4", "E2"]},
            },
        },
    )

    assert cli.main(["plan", str(source)]) == 0
    assert capsys.readouterr().out == (
        "SciPlot plan: not_applicable\n"
        "Scientific transform: rheology_stress_relaxation (3 series)\n"
    )


def test_batch_regression_runner_is_parseable_but_not_public_automation() -> None:
    assert "batch" in _command_choices()
    assert "batch" not in _visible_command_choices()


def test_retired_advanced_editor_flag_is_not_parseable(tmp_path: Path) -> None:
    document = tmp_path / "figure.vsz"
    document.write_text("# Veusz saved document\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(["studio", str(document), "--advanced-editor"])


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


def test_autoplot_cli_forwards_explicit_rule_and_presentation_template(
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
                "--rule",
                "impact_metric",
                "--template",
                "bar",
                "--json",
            ]
        )
        == 0
    )
    assert captured["rule_id"] == "impact_metric"
    assert captured["template"] == "bar"


@pytest.mark.parametrize(
    "reason_codes",
    [
        ["validated_envelope_missing"],
        [
            "certified_rule_contract_sha256_mismatch",
            "certified_rule_semantic_contract_sha256_mismatch",
        ],
    ],
)
def test_autoplot_cli_reaches_rule_preflight_before_missing_source_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reason_codes: list[str],
) -> None:
    source = tmp_path / "source-does-not-exist.csv"
    captured: dict[str, object] = {}
    payload = {
        "kind": "sciplot_autoplot_result",
        "version": 2,
        "state": "needs_rule_repair",
        "ready_to_use": False,
        "delivery": None,
        "run_output": None,
        "validated_envelope": {"repair_reasons": reason_codes},
    }

    def fake_run_autoplot(
        input_path: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        captured["input_path"] = input_path
        captured.update(kwargs)
        return payload

    monkeypatch.setattr(cli, "run_autoplot", fake_run_autoplot)

    exit_code = cli.main(
        [
            "autoplot",
            str(source),
            "--rule",
            "impact_metric",
            "--template",
            "bar",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert captured["input_path"] == source
    assert captured["rule_id"] == "impact_metric"
    assert captured["template"] == "bar"
    assert output.err == ""
    assert json.loads(output.out) == payload
