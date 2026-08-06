from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sciplot_core.materials_rules import get_rule
from sciplot_core.readiness import load_validated_envelope_registry
from sciplot_core.readiness.rule_certification import (
    current_certified_rule_contract_snapshot,
)
from sciplot_core.studio_core.figure_set_state import (
    _replace_studio_figure_set_path,
)
from sciplot_core.studio_core.prepare_existing import (
    reuse_existing_studio_document,
)
from sciplot_core.studio_core.prepare_generated import (
    generate_studio_document,
)
from sciplot_core.studio_core.request_overrides import (
    _apply_studio_request_overrides,
)
from sciplot_core.studio_core.rule_contract_binding import (
    STUDIO_RULE_CONTRACT_BINDING_KEY,
    StudioRuleContractBinding,
)


PERFORMANCE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _current_binding(rule_id: str) -> dict[str, Any]:
    snapshot = current_certified_rule_contract_snapshot(
        rule=get_rule(rule_id),
        registry=load_validated_envelope_registry(),
    )
    assert snapshot.certification_status == "current"
    return StudioRuleContractBinding.from_snapshot(snapshot).to_payload()


def _generate_rule_bearing_project(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "performance.csv"
    shutil.copyfile(PERFORMANCE_FIXTURE, source)
    request_path = project_dir / "plot_request.json"
    _write_json(
        request_path,
        {
            "input": str(source),
            "rule_id": "performance_comparison",
            "template": "scatter",
        },
    )
    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )
    return project_dir, request_path, prepared


def _existing_rule_project(
    tmp_path: Path,
    *,
    binding: dict[str, Any] | None,
) -> tuple[Path, Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "source.csv"
    source.write_text("x,y\n0,1\n1,2\n", encoding="utf-8")
    request: dict[str, Any] = {
        "input": str(source),
        "rule_id": "swelling_curve",
        "template": "point_line",
    }
    if binding is not None:
        request[STUDIO_RULE_CONTRACT_BINDING_KEY] = binding
    request_path = project_dir / "plot_request.json"
    _write_json(request_path, request)
    document_path = project_dir / "studio" / "document.vsz"
    document_path.parent.mkdir()
    document_path.write_text(
        "Add('xy', name='series_1')\n",
        encoding="utf-8",
    )
    return project_dir, request_path, document_path


def test_generated_rule_bearing_request_persists_current_contract_binding(
    tmp_path: Path,
) -> None:
    _project_dir, request_path, prepared = _generate_rule_bearing_project(tmp_path)

    request = json.loads(request_path.read_text(encoding="utf-8"))
    binding_payload = request[STUDIO_RULE_CONTRACT_BINDING_KEY]
    binding = StudioRuleContractBinding.from_payload(binding_payload)
    current = current_certified_rule_contract_snapshot(
        rule=get_rule("performance_comparison"),
        registry=load_validated_envelope_registry(),
    )

    assert binding.matches_current_snapshot(current)
    assert prepared["rule_contract_binding"] == binding_payload
    assert prepared["studio"]["rule_contract_binding"] == binding_payload


def test_generated_ruleless_request_removes_stale_contract_binding(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "source.csv"
    source.write_text("x,y\n0,1\n1,2\n", encoding="utf-8")
    request_path = project_dir / "plot_request.json"
    _write_json(
        request_path,
        {
            "input": str(source),
            "template": "curve",
            STUDIO_RULE_CONTRACT_BINDING_KEY: _current_binding(
                "performance_comparison"
            ),
        },
    )

    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert STUDIO_RULE_CONTRACT_BINDING_KEY not in request
    assert prepared["rule_contract_binding"] is None
    assert "rule_contract_binding" not in prepared["studio"]


def test_reusing_existing_document_preserves_contract_binding_exactly(
    tmp_path: Path,
) -> None:
    expected_binding = _current_binding("swelling_curve")
    project_dir, request_path, document_path = _existing_rule_project(
        tmp_path,
        binding=expected_binding,
    )
    before = request_path.read_bytes()

    prepared = reuse_existing_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request_path.read_bytes() == before
    assert request[STUDIO_RULE_CONTRACT_BINDING_KEY] == expected_binding
    assert prepared["studio"]["rule_contract_binding"] == expected_binding
    assert prepared["publication_rule_blocked"] is False


def test_reusing_legacy_rule_bearing_document_does_not_mint_binding(
    tmp_path: Path,
) -> None:
    project_dir, request_path, document_path = _existing_rule_project(
        tmp_path,
        binding=None,
    )
    before = request_path.read_bytes()

    prepared = reuse_existing_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request_path.read_bytes() == before
    assert STUDIO_RULE_CONTRACT_BINDING_KEY not in request
    assert "rule_contract_binding" not in prepared["studio"]
    assert prepared["publication_rule_blocked"] is True


@pytest.mark.parametrize(
    ("initial_rule", "initial_template", "overrides"),
    [
        (
            "swelling_curve",
            "point_line",
            {"rule_id": "performance_comparison", "template": "scatter"},
        ),
        (
            "performance_comparison",
            "scatter",
            {"template": "polar_curve"},
        ),
    ],
)
def test_rule_or_template_change_clears_contract_binding(
    tmp_path: Path,
    initial_rule: str,
    initial_template: str,
    overrides: dict[str, str],
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "source.csv"
    source.write_text("x,y\n0,1\n1,2\n", encoding="utf-8")
    request_path = project_dir / "plot_request.json"
    _write_json(
        request_path,
        {
            "input": str(source),
            "rule_id": initial_rule,
            "template": initial_template,
            STUDIO_RULE_CONTRACT_BINDING_KEY: _current_binding(initial_rule),
        },
    )

    _apply_studio_request_overrides(
        project_dir,
        request_path=request_path,
        **overrides,
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert STUDIO_RULE_CONTRACT_BINDING_KEY not in request


def test_project_name_only_override_preserves_contract_binding(
    tmp_path: Path,
) -> None:
    binding = _current_binding("swelling_curve")
    project_dir, request_path, _document_path = _existing_rule_project(
        tmp_path,
        binding=binding,
    )

    _apply_studio_request_overrides(
        project_dir,
        request_path=request_path,
        project_name="Renamed locally",
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request[STUDIO_RULE_CONTRACT_BINDING_KEY] == binding


def test_failed_generated_transaction_preserves_prior_request_and_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.studio_core.prepare_generated as generated_module

    project_dir, request_path, prepared = _generate_rule_bearing_project(tmp_path)
    document_path = Path(prepared["document"])
    spec_path = document_path.with_name("spec.json")
    before = {
        path: path.read_bytes() for path in (request_path, document_path, spec_path)
    }
    prior_binding = json.loads(request_path.read_text(encoding="utf-8"))[
        STUDIO_RULE_CONTRACT_BINDING_KEY
    ]
    monkeypatch.setattr(
        generated_module,
        "load_validated_envelope_registry",
        lambda: SimpleNamespace(entry=lambda _rule_id: None),
    )

    def fail_request_replace(staged: Path, target: Path) -> None:
        if target == request_path:
            raise OSError("injected request replacement failure")
        _replace_studio_figure_set_path(staged, target)

    with pytest.raises(OSError, match="injected request replacement failure"):
        generate_studio_document(
            project_dir=project_dir,
            request_path=request_path,
            rule_id=None,
            template=None,
            project_name=None,
            figure_set_path_replacer=fail_request_replace,
        )

    assert {
        path: path.read_bytes() for path in (request_path, document_path, spec_path)
    } == before
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request[STUDIO_RULE_CONTRACT_BINDING_KEY] == prior_binding
    assert not list(project_dir.rglob(".sciplot-studio-prepare-*"))
    assert not list(project_dir.rglob(".sciplot-figure-set-transaction-*"))
