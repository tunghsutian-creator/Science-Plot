from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY
from sciplot_core.project_manifest import read_intake_project_manifest
from sciplot_core.intake import session as intake_session
from sciplot_core.intake.project import project_builder
from sciplot_core.materials_rules import get_rule
from sciplot_core.studio_core import prepare_generated, studio_prepare
from sciplot_core.studio_core.rule_contract_binding import (
    STUDIO_RULE_CONTRACT_BINDING_KEY,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)
RULE_ID = "performance_comparison"
TEMPLATE = "polar_curve"
PROJECT_NAME = "Explicit Project"


def _raw_source(tmp_path: Path, source_kind: str) -> Path:
    if source_kind == "file":
        source = tmp_path / "performance.csv"
        source.write_bytes(FIXTURE.read_bytes())
        return source
    source_dir = tmp_path / "performance_source"
    source_dir.mkdir()
    (source_dir / "performance.csv").write_bytes(FIXTURE.read_bytes())
    return source_dir


def _ready_prepare_payload(*, project_dir: Path, request_path: Path) -> dict[str, Any]:
    document = project_dir / "studio" / "document.vsz"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("# fake generated Studio document\n", encoding="utf-8")
    return {
        "kind": "sciplot_studio_prepare",
        "mode": "generated",
        "project_dir": str(project_dir),
        "request": str(request_path),
        "document": str(document),
        "studio": {
            "kind": "sciplot_studio_document",
            "engine": "veusz",
            "status": "ready",
        },
    }


@pytest.mark.parametrize("source_kind", ("file", "directory"))
def test_raw_source_canonicalizes_once_before_studio_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
) -> None:
    source = _raw_source(tmp_path, source_kind)
    output_root = tmp_path / "projects"
    delivery_root = tmp_path / "delivery"
    calls: list[dict[str, Any]] = []

    def generate(
        *,
        project_dir: Path,
        request_path: Path,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(
            {
                "project_dir": project_dir,
                "request": json.loads(request_path.read_text(encoding="utf-8")),
            }
        )
        return _ready_prepare_payload(
            project_dir=project_dir,
            request_path=request_path,
        )

    monkeypatch.setattr(studio_prepare, "generate_studio_document", generate)

    prepared = studio_prepare.prepare_studio_document(
        source,
        output_root=output_root,
        delivery_root=delivery_root,
        rule_id=RULE_ID,
        template=TEMPLATE,
        project_name=PROJECT_NAME,
    )

    assert len(calls) == 1
    generation = calls[0]
    request = generation["request"]
    assert request["rule_id"] == RULE_ID
    assert request["template"] == TEMPLATE
    assert request["study_model"]["experiment"]["template"] == TEMPLATE
    assert request[REQUEST_DELIVERY_ROOT_KEY] == str(delivery_root.resolve())
    project_dir = Path(prepared["project_dir"])
    assert generation["project_dir"] == project_dir
    assert project_dir.name == "Explicit_Project"
    manifest = read_intake_project_manifest(project_dir)
    assert manifest is not None
    assert manifest["project_name"] == PROJECT_NAME
    assert manifest["experiment"]["template"] == TEMPLATE
    assert manifest["study_model"]["experiment"]["template"] == TEMPLATE
    mirror = json.loads(
        (project_dir / f"{project_dir.name}.sciplot.json").read_text(encoding="utf-8")
    )
    assert mirror == manifest
    with zipfile.ZipFile(project_dir.parent / f"{project_dir.name}.zip") as archive:
        archived_manifest = json.loads(
            archive.read(f"{project_dir.name}/intake_manifest.json").decode("utf-8")
        )
        archived_request = json.loads(
            archive.read(f"{project_dir.name}/plot_request.json").decode("utf-8")
        )
    assert archived_manifest == manifest
    assert archived_request == request


def _run_failure_after_noncanonical_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], Path]:
    source = _raw_source(tmp_path, "file")
    output_root = tmp_path / "projects"
    delivery_root = tmp_path / "delivery"
    calls: list[dict[str, Any]] = []
    fake_binding = {
        "kind": "test_fake_ready_rule_contract_binding",
        "version": 1,
    }
    injected_error = RuntimeError("injected canonical Studio generation failure")

    def generate(
        *,
        project_dir: Path,
        request_path: Path,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        calls.append(request)
        if request.get(REQUEST_DELIVERY_ROOT_KEY) != str(delivery_root.resolve()):
            request[STUDIO_RULE_CONTRACT_BINDING_KEY] = fake_binding
            request_path.write_text(
                json.dumps(request, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            payload = _ready_prepare_payload(
                project_dir=project_dir,
                request_path=request_path,
            )
            payload["studio"][STUDIO_RULE_CONTRACT_BINDING_KEY] = fake_binding
            return payload
        raise injected_error

    monkeypatch.setattr(studio_prepare, "generate_studio_document", generate)

    try:
        studio_prepare.prepare_studio_document(
            source,
            output_root=output_root,
            delivery_root=delivery_root,
            rule_id=RULE_ID,
            template=TEMPLATE,
            project_name=PROJECT_NAME,
        )
    except RuntimeError as exc:
        assert exc is injected_error
        assert str(exc) == "injected canonical Studio generation failure"
        assert any(
            "retained the blocked intake project" in note
            for note in getattr(exc, "__notes__", ())
        )

    project_requests = sorted(output_root.glob("*/plot_request.json"))
    assert len(project_requests) == 1
    return calls, project_requests[0].parent


def test_failed_raw_source_studio_generation_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _project_dir = _run_failure_after_noncanonical_prepare(
        tmp_path,
        monkeypatch,
    )

    assert len(calls) == 1


def test_pending_review_marker_reaches_the_only_raw_source_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _raw_source(tmp_path, "file")
    output_root = tmp_path / "projects"
    pending_rule = replace(
        get_rule(RULE_ID),
        fixture_status="pending",
    )
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        intake_session,
        "get_rule",
        lambda _rule_id: pending_rule,
    )
    monkeypatch.setattr(
        project_builder,
        "get_rule",
        lambda _rule_id: pending_rule,
    )

    def generate(
        *,
        project_dir: Path,
        request_path: Path,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(json.loads(request_path.read_text(encoding="utf-8")))
        return _ready_prepare_payload(
            project_dir=project_dir,
            request_path=request_path,
        )

    monkeypatch.setattr(studio_prepare, "generate_studio_document", generate)

    prepared = studio_prepare.prepare_studio_document(
        source,
        output_root=output_root,
        rule_id=RULE_ID,
        template=TEMPLATE,
    )

    assert len(calls) == 1
    assert calls[0]["pending_rule_review"] is True
    manifest = read_intake_project_manifest(Path(prepared["project_dir"]))
    assert manifest is not None
    assert manifest["recognition"]["pending_rule_review"] is True


def test_pending_raw_source_rule_requires_an_explicit_template_before_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _raw_source(tmp_path, "file")
    output_root = tmp_path / "projects"
    pending_rule = replace(
        get_rule(RULE_ID),
        fixture_status="pending",
    )
    generate_calls = 0

    monkeypatch.setattr(
        intake_session,
        "get_rule",
        lambda _rule_id: pending_rule,
    )

    def generate(**_kwargs: Any) -> dict[str, Any]:
        nonlocal generate_calls
        generate_calls += 1
        raise AssertionError("Pending input must be rejected before generation.")

    monkeypatch.setattr(studio_prepare, "generate_studio_document", generate)

    with pytest.raises(
        ValueError,
        match="an explicit rule plus template is required",
    ):
        studio_prepare.prepare_studio_document(
            source,
            output_root=output_root,
            rule_id=RULE_ID,
        )

    assert generate_calls == 0
    assert not tuple(output_root.glob("*/plot_request.json"))
    assert not tuple(output_root.glob("*.zip"))


def test_invalid_raw_source_template_is_rejected_before_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _raw_source(tmp_path, "file")
    output_root = tmp_path / "projects"
    generate_calls = 0

    def generate(**_kwargs: Any) -> dict[str, Any]:
        nonlocal generate_calls
        generate_calls += 1
        raise AssertionError("Invalid input must not reach Studio generation.")

    monkeypatch.setattr(studio_prepare, "generate_studio_document", generate)

    with pytest.raises(ValueError, match="is not supported by material rule"):
        studio_prepare.prepare_studio_document(
            source,
            output_root=output_root,
            rule_id=RULE_ID,
            template="bar",
        )

    assert generate_calls == 0
    assert not tuple(output_root.glob("*/plot_request.json"))
    assert not tuple(output_root.glob("*.zip"))


def test_post_generation_projection_failure_cannot_return_captured_ready_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _raw_source(tmp_path, "file")
    output_root = tmp_path / "projects"
    profile_calls = 0
    real_profile = project_builder.get_publication_profile

    def profile(profile_id: str) -> dict[str, Any]:
        nonlocal profile_calls
        profile_calls += 1
        if profile_calls == 2:
            raise RuntimeError("injected manifest projection failure")
        return real_profile(profile_id)

    def generate(
        *,
        project_dir: Path,
        request_path: Path,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return _ready_prepare_payload(
            project_dir=project_dir,
            request_path=request_path,
        )

    monkeypatch.setattr(project_builder, "get_publication_profile", profile)
    monkeypatch.setattr(studio_prepare, "generate_studio_document", generate)

    with pytest.raises(RuntimeError, match="injected manifest projection failure"):
        studio_prepare.prepare_studio_document(
            source,
            output_root=output_root,
            rule_id=RULE_ID,
            template=TEMPLATE,
        )

    assert profile_calls == 2
    assert not tuple(output_root.glob("*/plot_request.json"))
    assert not tuple(output_root.glob("*.zip"))


@pytest.mark.comprehensive
def test_raw_source_takes_one_rule_certification_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _raw_source(tmp_path, "file")
    calls = 0
    real_snapshot = prepare_generated.current_certified_rule_contract_snapshot

    def snapshot(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return real_snapshot(**kwargs)

    monkeypatch.setattr(
        prepare_generated,
        "current_certified_rule_contract_snapshot",
        snapshot,
    )

    prepared = studio_prepare.prepare_studio_document(
        source,
        output_root=tmp_path / "projects",
        rule_id=RULE_ID,
        template=TEMPLATE,
    )

    assert calls == 1
    assert Path(prepared["document"]).is_file()


def test_failed_raw_source_generation_keeps_only_blocked_project_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calls, project_dir = _run_failure_after_noncanonical_prepare(
        tmp_path,
        monkeypatch,
    )

    request = json.loads(
        (project_dir / "plot_request.json").read_text(encoding="utf-8")
    )
    assert STUDIO_RULE_CONTRACT_BINDING_KEY not in request

    manifest = read_intake_project_manifest(project_dir)
    assert manifest is not None
    assert manifest["studio"]["status"] == "blocked"
    assert STUDIO_RULE_CONTRACT_BINDING_KEY not in manifest["studio"]

    zip_path = project_dir.parent / f"{project_dir.name}.zip"
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as archive:
        archived_manifest = json.loads(
            archive.read(f"{project_dir.name}/intake_manifest.json").decode("utf-8")
        )
        archived_request = json.loads(
            archive.read(f"{project_dir.name}/plot_request.json").decode("utf-8")
        )
    assert archived_manifest["studio"]["status"] == "blocked"
    assert STUDIO_RULE_CONTRACT_BINDING_KEY not in archived_manifest["studio"]
    assert STUDIO_RULE_CONTRACT_BINDING_KEY not in archived_request


def test_existing_request_and_vsz_control_paths_keep_generation_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"generate": 0, "reuse": 0}

    def generate(
        *,
        project_dir: Path,
        request_path: Path,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls["generate"] += 1
        return _ready_prepare_payload(
            project_dir=project_dir,
            request_path=request_path,
        )

    def reuse(
        *,
        project_dir: Path,
        request_path: Path,
        document_path: Path,
    ) -> dict[str, Any]:
        calls["reuse"] += 1
        return {
            "mode": "project",
            "project_dir": str(project_dir),
            "request": str(request_path),
            "document": str(document_path),
        }

    monkeypatch.setattr(studio_prepare, "generate_studio_document", generate)
    monkeypatch.setattr(studio_prepare, "reuse_existing_studio_document", reuse)

    existing_project = tmp_path / "existing_project"
    existing_project.mkdir()
    existing_request = existing_project / "plot_request.json"
    existing_request.write_text("{}", encoding="utf-8")
    existing_document = existing_project / "studio" / "document.vsz"
    existing_document.parent.mkdir()
    existing_document.write_text("# existing\n", encoding="utf-8")
    studio_prepare.prepare_studio_document(existing_project)
    assert calls == {"generate": 0, "reuse": 1}

    request_project = tmp_path / "request_project"
    request_project.mkdir()
    request_path = request_project / "plot_request.json"
    request_path.write_text("{}", encoding="utf-8")
    studio_prepare.prepare_studio_document(request_path)
    assert calls == {"generate": 1, "reuse": 1}

    standalone = tmp_path / "standalone.vsz"
    standalone.write_text("# standalone\n", encoding="utf-8")
    studio_prepare.prepare_studio_document(standalone)
    assert calls == {"generate": 1, "reuse": 1}
