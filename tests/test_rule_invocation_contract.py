from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.autoplot.run as autoplot_run_module
import sciplot_core.plan_preview as preview_module
from sciplot_core import cli
from sciplot_core.materials_rules import (
    SemanticRule,
    get_rule,
    iter_public_rules,
    list_rules_payload,
    show_rule_payload,
)
from sciplot_core.readiness.registry_io import load_validated_envelope_registry
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.rule_certification import (
    current_rule_invocation_contract_payload,
)
from sciplot_core.readiness.rule_contract import rule_contract_hashes


def _registry_for_status(
    rule_id: str,
    status: str,
) -> ValidatedEnvelopeRegistry:
    registry = load_validated_envelope_registry()
    rule = get_rule(rule_id)
    entry = registry.entry(rule_id)
    assert entry is not None
    hashes = rule_contract_hashes(rule)
    current_entry = replace(
        entry,
        contract_sha256=hashes.contract_sha256,
        semantic_contract_sha256=hashes.semantic_contract_sha256,
        semantic_family=rule.semantic_family,
    )
    current_registry = replace(
        registry,
        entries=tuple(
            current_entry if candidate.rule_id == rule_id else candidate
            for candidate in registry.entries
        ),
    )
    if status == "current":
        return current_registry
    if status == "stale":
        stale_entry = replace(
            current_entry,
            contract_sha256="0" * 64,
            semantic_contract_sha256="1" * 64,
        )
        return replace(
            current_registry,
            entries=tuple(
                stale_entry if candidate.rule_id == rule_id else candidate
                for candidate in current_registry.entries
            ),
        )
    if status != "missing":
        raise AssertionError(f"unsupported test status: {status}")
    source_acceptance = deepcopy(current_registry.source_acceptance)
    records = []
    for record in source_acceptance["records"]:
        retained_ids = [
            candidate for candidate in record["rule_ids"] if candidate != rule_id
        ]
        if retained_ids:
            record["rule_ids"] = retained_ids
            records.append(record)
    source_acceptance["records"] = records
    return replace(
        current_registry,
        source_acceptance=source_acceptance,
        entries=tuple(
            candidate
            for candidate in current_registry.entries
            if candidate.rule_id != rule_id
        ),
    )


def _invocation_projector(
    registry: ValidatedEnvelopeRegistry,
) -> Callable[[SemanticRule], dict[str, Any]]:
    def project(rule: SemanticRule) -> dict[str, Any]:
        return current_rule_invocation_contract_payload(
            rule=rule,
            registry=registry,
        )

    return project


def _use_cli_registry(
    monkeypatch: pytest.MonkeyPatch,
    registry: ValidatedEnvelopeRegistry,
) -> None:
    monkeypatch.setattr(
        "sciplot_core.readiness.registry_io.load_validated_envelope_registry",
        lambda: registry,
    )


def test_rule_invocation_is_derived_from_the_canonical_rule() -> None:
    rule = get_rule("impact_metric")
    registry = _registry_for_status(rule.rule_id, "current")
    invocation = show_rule_payload(
        rule.rule_id,
        invocation_projector=_invocation_projector(registry),
    )["invocation"]

    assert invocation == {
        "kind": "sciplot_rule_invocation",
        "version": 1,
        "availability": "ready",
        "reason_codes": [],
        "operations": {"preview": "plan", "render": "autoplot"},
        "required_arguments": ["input", "template"],
        "fixed_arguments": {"rule": rule.rule_id},
        "template": {
            "argument": "template",
            "default": rule.template,
            "choices": list(rule.presentation_templates),
        },
    }

    pending = replace(rule, fixture_status="pending").invocation_contract_payload()
    assert pending["availability"] == "needs_rule_repair"
    assert pending["reason_codes"] == ["fixture_backed_rule_acceptance"]
    assert show_rule_payload(rule.rule_id)["invocation"] == (
        rule.invocation_contract_payload()
    )


def test_rules_list_and_show_publish_one_invocation_contract(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_id = "impact_metric"
    registry = _registry_for_status(rule_id, "current")
    projector = _invocation_projector(registry)
    _use_cli_registry(monkeypatch, registry)

    assert cli.main(["rules", "list", "--json"]) == 0
    listed_payload = json.loads(capsys.readouterr().out)
    assert cli.main(["rules", "show", rule_id, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    listed = next(
        item for item in listed_payload["rules"] if item["rule_id"] == rule_id
    )
    assert shown == show_rule_payload(
        rule_id,
        invocation_projector=projector,
    )
    assert listed["invocation"] == shown["invocation"]


@pytest.mark.parametrize(
    ("status", "availability", "reason_codes"),
    [
        ("current", "ready", []),
        ("missing", "needs_rule_repair", ["validated_envelope_missing"]),
        (
            "stale",
            "needs_rule_repair",
            [
                "certified_rule_contract_sha256_mismatch",
                "certified_rule_semantic_contract_sha256_mismatch",
            ],
        ),
    ],
)
def test_rules_list_and_show_share_current_certification_projection(
    status: str,
    availability: str,
    reason_codes: list[str],
) -> None:
    rule_id = "impact_metric"
    registry = _registry_for_status(rule_id, status)
    projector = _invocation_projector(registry)

    listed = next(
        item
        for item in list_rules_payload(invocation_projector=projector)["rules"]
        if item["rule_id"] == rule_id
    )
    shown = show_rule_payload(
        rule_id,
        invocation_projector=projector,
    )

    assert listed["invocation"] == shown["invocation"]
    assert shown["invocation"]["availability"] == availability
    assert shown["invocation"]["reason_codes"] == reason_codes


def test_rules_plan_and_autoplot_share_one_stale_rule_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule("impact_metric")
    registry = _registry_for_status(rule.rule_id, "stale")
    invocation = show_rule_payload(
        rule.rule_id,
        invocation_projector=_invocation_projector(registry),
    )["invocation"]
    reasons = invocation["reason_codes"]
    source = tmp_path / "source-does-not-exist.csv"
    output_root = tmp_path / "outputs"

    monkeypatch.setattr(
        preview_module,
        "load_validated_envelope_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        autoplot_run_module,
        "load_validated_envelope_registry",
        lambda: registry,
    )

    def forbidden_work(*_args: object, **_kwargs: object) -> None:
        pytest.fail("stale rule reached source or project work")

    monkeypatch.setattr(preview_module, "classify_source", forbidden_work)
    monkeypatch.setattr(autoplot_run_module, "run_one_step", forbidden_work)

    plan = preview_module.build_plan_preview(
        source,
        request={"rule_id": rule.rule_id, "template": rule.template},
    )
    autoplot = autoplot_run_module.run_autoplot(
        source,
        output_root=output_root,
        rule_id=rule.rule_id,
        template=rule.template,
    )

    assert invocation["availability"] == "needs_rule_repair"
    assert plan["status"] == "blocked"
    assert plan["blocker"]["reason_code"] == reasons[0]
    assert all(reason in plan["blocker"]["message"] for reason in reasons)
    assert autoplot["state"] == "needs_rule_repair"
    assert autoplot["validated_envelope"]["repair_reasons"] == reasons
    assert autoplot["summary_path"] is None
    assert not output_root.exists()


def test_advertised_invocation_calls_the_existing_autoplot_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "impact.xlsx"
    source.write_bytes(b"fixture")
    invocation = show_rule_payload(
        "impact_metric",
        invocation_projector=_invocation_projector(
            _registry_for_status("impact_metric", "current")
        ),
    )["invocation"]
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
    fixed_arguments = [
        item
        for name, value in invocation["fixed_arguments"].items()
        for item in (f"--{name}", str(value))
    ]
    assert (
        cli.main(
            [
                str(invocation["operations"]["render"]),
                str(source),
                *fixed_arguments,
                "--template",
                str(invocation["template"]["default"]),
                "--json",
            ]
        )
        == 0
    )
    assert captured["rule_id"] == "impact_metric"
    assert captured["template"] == get_rule("impact_metric").template


def test_every_ready_rule_advertises_parseable_preview_and_render_calls() -> None:
    parser = cli._build_parser()

    for rule in iter_public_rules():
        invocation = rule.invocation_contract_payload()
        fixed_arguments = [
            item
            for name, value in invocation["fixed_arguments"].items()
            for item in (f"--{name}", str(value))
        ]
        for operation in invocation["operations"].values():
            args = parser.parse_args(
                [
                    str(operation),
                    "source-path",
                    *fixed_arguments,
                    "--template",
                    str(invocation["template"]["default"]),
                    "--json",
                ]
            )
            assert args.rule == rule.rule_id
            assert args.template == rule.template
