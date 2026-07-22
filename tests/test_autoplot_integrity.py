from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sciplot_core import autoplot
from sciplot_core._utils import existing_file_sha256
from sciplot_core.delivery import DELIVERY_PACKAGE_CONTRACT_VERSION
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
    write_delivery_launcher,
)
from sciplot_core.publish_state import build_publish_state
from sciplot_core.study_model import build_output_package_contract


def _delivery_record(delivery: Path) -> dict[str, object]:
    data_dir = delivery / "data"
    pdf_dir = delivery / "pdf"
    tiff_dir = delivery / "tiff"
    project_dir = delivery / "project"
    for directory in (data_dir, pdf_dir, tiff_dir, project_dir):
        directory.mkdir(parents=True)
    data = data_dir / "figure_plot_data.csv"
    pdf = pdf_dir / "figure.pdf"
    tiff = tiff_dir / "figure_300dpi.tiff"
    project = project_dir / "figure.vsz"
    data.write_text("x,y\n1,2\n", encoding="utf-8")
    pdf.write_bytes(b"pdf")
    tiff.write_bytes(b"tiff")
    project.write_text("# Veusz saved document\n", encoding="utf-8")
    launcher = write_delivery_launcher(delivery)
    launcher_contract = inspect_delivery_launcher_contract(delivery)
    return {
        "kind": "sciplot_user_delivery_package",
        "version": DELIVERY_PACKAGE_CONTRACT_VERSION,
        "path": str(delivery),
        "data_csvs": [
            {
                "path": str(data),
                "exists": True,
                "sha256": existing_file_sha256(data),
            }
        ],
        "figures": [
            {
                "path": str(pdf),
                "delivery_sha256": existing_file_sha256(pdf),
            },
            {
                "path": str(tiff),
                "delivery_sha256": existing_file_sha256(tiff),
            },
        ],
        "project_documents": [
            {
                "path": str(project),
                "delivery_sha256": existing_file_sha256(project),
            }
        ],
        "open_in_veusz": str(launcher),
        "open_in_veusz_sha256": launcher_contract["content_sha256"],
        "launcher_contract": launcher_contract,
        "artifacts": [
            {"id": "data", "path": str(data_dir), "exists": True},
            {"id": "pdf", "path": str(pdf_dir), "exists": True},
            {"id": "tiff", "path": str(tiff_dir), "exists": True},
            {"id": "project", "path": str(project_dir), "exists": True},
            {"id": "launcher", "path": str(launcher), "exists": True},
        ],
        "complete": True,
    }


def _ready_result(root: Path) -> dict[str, object]:
    run_output = root / "run_001"
    run_output.mkdir(parents=True)
    delivery = run_output / "delivery"
    delivery_package = _delivery_record(delivery)
    one_step = {
        "state": "ready",
        "delivery_package": delivery_package,
        "figure_qa_report": {
            "status": "passed",
            "qa_status": "passed",
            "needs_ai_intervention": False,
        },
        "render_request": {},
        "validated_envelope": {},
    }
    qa = {"status": "passed"}
    (run_output / "request_snapshot.json").write_text("{}\n", encoding="utf-8")
    (run_output / "manifest.json").write_text("{}\n", encoding="utf-8")
    (run_output / "review.html").write_text("<html></html>\n", encoding="utf-8")
    (run_output / "revision_brief.md").write_text("# Ready\n", encoding="utf-8")
    manifest_seed = {
        "figures": [
            str(item["path"])
            for item in delivery_package["figures"]
            if isinstance(item, dict)
        ],
        "qa": qa,
        "result": {},
    }
    package_contract = build_output_package_contract(
        run_output,
        manifest=manifest_seed,
    )
    publish_state = build_publish_state(
        qa=qa,
        package_contract=package_contract,
        delivery_package=one_step["delivery_package"],
        prerequisite_state=one_step["state"],
    )
    (run_output / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "sciplot_run",
                **manifest_seed,
                "qa": qa,
                "package_contract": package_contract,
                "delivery_package": one_step["delivery_package"],
                "one_step": one_step,
                **publish_state,
            }
        ),
        encoding="utf-8",
    )
    (run_output / "one_step_status.json").write_text(
        json.dumps(one_step), encoding="utf-8"
    )
    return {
        "kind": "sciplot_one_step_result",
        "status": "ready",
        "run_output": str(run_output),
        "project_dir": str(root),
        "one_step": one_step,
    }


def test_autoplot_ready_requires_current_manifest_status_and_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )

    summary = autoplot.build_autoplot_summary(_ready_result(tmp_path))

    assert summary["ready_to_use"] is True
    assert summary["delivery_complete"] is True
    assert summary["integrity"]["reasons"] == []


@pytest.mark.parametrize(
    ("missing", "reason", "integrity_key"),
    [
        ("manifest.json", "manifest_missing", "manifest_exists"),
        (
            "one_step_status.json",
            "one_step_status_missing",
            "one_step_status_exists",
        ),
        ("delivery", "delivery_path_missing", "delivery_path_exists"),
    ],
)
def test_autoplot_rejects_missing_persisted_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    reason: str,
    integrity_key: str,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    target = Path(str(result["run_output"])) / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    summary = autoplot.build_autoplot_summary(result)

    assert summary["ready_to_use"] is False
    assert summary["integrity"][integrity_key] is False
    assert reason in summary["integrity"]["reasons"]
    assert summary["codex_handoff"]["required"] is True
    if missing == "delivery":
        assert summary["delivery_complete"] is False


def test_autoplot_rejects_deleted_delivery_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    run_output = Path(str(result["run_output"]))
    (run_output / "delivery" / "pdf" / "figure.pdf").unlink()

    summary = autoplot.build_autoplot_summary(result)

    assert summary["ready_to_use"] is False
    assert summary["delivery_complete"] is False
    assert "delivery_package_verification_failed" in summary["integrity"]["reasons"]
    assert "pdf_files_current" in summary["integrity"]["delivery_verification"][
        "failed_checks"
    ]


@pytest.mark.parametrize("stale_launcher", ["exit_zero", "retired_advanced_editor"])
def test_autoplot_rejects_noncanonical_delivery_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_launcher: str,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    run_output = Path(str(result["run_output"]))
    launcher = run_output / "delivery" / "Open_in_Veusz.command"
    if stale_launcher == "exit_zero":
        launcher.write_text("#!/bin/zsh\nexit 0\n", encoding="utf-8")
    else:
        content = launcher.read_text(encoding="utf-8")
        canonical_command = 'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}"\n'
        assert canonical_command in content
        launcher.write_text(
            content.replace(
                canonical_command,
                'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --advanced-editor\n',
            ),
            encoding="utf-8",
        )
    launcher.chmod(0o755)

    summary = autoplot.build_autoplot_summary(result)

    assert summary["ready_to_use"] is False
    assert summary["delivery_complete"] is False
    assert "delivery_package_verification_failed" in summary["integrity"]["reasons"]
    verification = summary["integrity"]["delivery_verification"]
    assert "launcher_hash_current" in verification["failed_checks"]
    assert "launcher_structure_current" in verification["failed_checks"]
    assert verification["launcher"]["canonical_structure"] is False


def test_autoplot_rejects_deleted_output_package_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    run_output = Path(str(result["run_output"]))
    (run_output / "request_snapshot.json").unlink()

    summary = autoplot.build_autoplot_summary(result)

    assert summary["ready_to_use"] is False
    assert "package_contract_verification_failed" in summary["integrity"]["reasons"]
    assert "live_complete" in summary["integrity"][
        "package_contract_verification"
    ]["failed_checks"]


def test_autoplot_records_incomplete_delivery_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    one_step = result["one_step"]
    assert isinstance(one_step, dict)
    delivery = one_step["delivery_package"]
    assert isinstance(delivery, dict)
    delivery["complete"] = False
    run_output = Path(str(result["run_output"]))
    (run_output / "one_step_status.json").write_text(
        json.dumps(one_step), encoding="utf-8"
    )
    manifest = json.loads(
        (run_output / "manifest.json").read_text(encoding="utf-8")
    )
    manifest["one_step"] = one_step
    manifest["delivery_package"] = delivery
    manifest.update(
        build_publish_state(
            qa=manifest["qa"],
            package_contract=manifest["package_contract"],
            delivery_package=delivery,
            prerequisite_state=one_step["state"],
        )
    )
    (run_output / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    result["status"] = manifest["state"]

    summary = autoplot.build_autoplot_summary(result)

    assert summary["ready_to_use"] is False
    assert summary["delivery_recorded_complete"] is False
    assert "delivery_package_incomplete" in summary["integrity"]["reasons"]


def test_autoplot_rejects_incomplete_package_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    run_output = Path(str(result["run_output"]))
    manifest = json.loads((run_output / "manifest.json").read_text(encoding="utf-8"))
    manifest["package_contract"]["complete"] = False
    manifest.update(
        build_publish_state(
            qa=manifest["qa"],
            package_contract=manifest["package_contract"],
            delivery_package=manifest["delivery_package"],
            prerequisite_state=manifest["one_step"]["state"],
        )
    )
    (run_output / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    result["status"] = manifest["state"]

    summary = autoplot.build_autoplot_summary(result)

    assert summary["state"] == "needs_rule_repair"
    assert summary["ready_to_use"] is False
    assert summary["integrity"]["publish_state_valid"] is True
    assert "package_contract_incomplete" in summary["integrity"]["reasons"]


def test_autoplot_rejects_forged_publish_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    run_output = Path(str(result["run_output"]))
    manifest = json.loads((run_output / "manifest.json").read_text(encoding="utf-8"))
    manifest["package_contract"]["complete"] = False
    (run_output / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    summary = autoplot.build_autoplot_summary(result)

    assert summary["state"] == "needs_rule_repair"
    assert summary["ready_to_use"] is False
    assert summary["integrity"]["publish_state_valid"] is False
    assert "publish_state_missing_or_mismatch" in summary["integrity"]["reasons"]
    assert "package_contract_incomplete" in summary["integrity"]["reasons"]


def test_autoplot_rejects_noncanonical_delivery_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    run_output = Path(str(result["run_output"]))
    outside = tmp_path / "outside_delivery"
    outside.mkdir()
    one_step = result["one_step"]
    assert isinstance(one_step, dict)
    one_step["delivery_package"]["path"] = str(outside)
    manifest = json.loads((run_output / "manifest.json").read_text(encoding="utf-8"))
    manifest["one_step"] = one_step
    manifest["delivery_package"] = one_step["delivery_package"]
    manifest.update(
        build_publish_state(
            qa=manifest["qa"],
            package_contract=manifest["package_contract"],
            delivery_package=manifest["delivery_package"],
            prerequisite_state=one_step["state"],
        )
    )
    (run_output / "one_step_status.json").write_text(
        json.dumps(one_step), encoding="utf-8"
    )
    (run_output / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    summary = autoplot.build_autoplot_summary(result)

    assert summary["ready_to_use"] is False
    assert summary["integrity"]["delivery_path_canonical"] is False
    assert "delivery_path_noncanonical" in summary["integrity"]["reasons"]


@pytest.mark.parametrize(
    ("artifact", "reason", "integrity_key"),
    [
        ("manifest.json", "manifest_invalid", "manifest_valid"),
        (
            "one_step_status.json",
            "one_step_status_invalid",
            "one_step_status_valid",
        ),
    ],
)
def test_autoplot_rejects_present_but_invalid_persisted_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
    reason: str,
    integrity_key: str,
) -> None:
    monkeypatch.setattr(
        autoplot,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )
    result = _ready_result(tmp_path)
    run_output = Path(str(result["run_output"]))
    (run_output / artifact).write_text("{}", encoding="utf-8")

    summary = autoplot.build_autoplot_summary(result)

    assert summary["ready_to_use"] is False
    assert summary["integrity"][integrity_key] is False
    assert reason in summary["integrity"]["reasons"]
    assert summary["codex_handoff"]["required"] is True
