from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import pytest

from distribution.macos import release, verification, welcome
from distribution.macos.identity import bundle_snapshot, content_digest, file_hash, source_snapshot


def _app(root: Path) -> Path:
    app = root / "SciPlot.app"
    resources = app / "Contents/Resources"
    source = resources / "app/src/sciplot_core/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text("# original application\n")
    (resources / "build-manifest.json").write_text(json.dumps({
        "source_file_hashes": {"src/sciplot_core/__init__.py": file_hash(source)},
        "app_version": "0.1.0",
    }))
    return app


def _ok(command, **kwargs):
    if "doctor" in command:
        payload = {"status": "ready"}
    elif "--welcome" in command:
        payload = {"doctor_status": "ready", "mcp_available": True}
    else:
        payload = {"status": "passed"}
    return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")


def _mock_runtime(monkeypatch):
    monkeypatch.setattr(verification, "audit_runtime", lambda path: {"external_non_system_dependencies": 0})
    monkeypatch.setattr(verification.subprocess, "run", _ok)
    monkeypatch.setattr(verification, "verify_mcp", lambda *args: {"status": "passed"})


def test_build_identity_covers_routing_and_distribution_source(tmp_path):
    for name in ("skill/SKILL.md", "distribution/macos/welcome.py", "src/p.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("first")
    original = source_snapshot(tmp_path)
    (tmp_path / "skill/SKILL.md").write_text("changed route")
    assert source_snapshot(tmp_path) != original
    assert "distribution/macos/welcome.py" in original


def test_bundle_identity_survives_relocation_but_detects_changes(tmp_path):
    app = _app(tmp_path)
    link = app / "Contents/current"
    link.symlink_to("Resources")
    original = bundle_snapshot(app)
    moved = tmp_path / "中文 空格" / app.name
    shutil.copytree(app, moved, symlinks=True)
    assert bundle_snapshot(moved) == original
    source = moved / "Contents/Resources/app/src/sciplot_core/__init__.py"
    source.chmod(0o755)
    assert bundle_snapshot(moved) != original
    (moved / "escaped").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        bundle_snapshot(moved)


@pytest.mark.parametrize("name,payload", [
    ("doctor", {"status": "needs_fix"}),
    ("native_window", {"status": "failed"}),
    ("runtime_smoke", {"status": "failed"}),
    ("welcome", {"doctor_status": "ready", "mcp_available": False}),
    ("doctor", []),
])
def test_successful_exit_cannot_hide_failed_or_missing_checks(name, payload):
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with pytest.raises((ValueError, RuntimeError)):
        verification.validate_command_result(name, result)


@pytest.mark.parametrize("failure", ["exit", "json", "timeout", "status"])
def test_verification_keeps_failed_check_and_durable_report(tmp_path, monkeypatch, failure):
    app = _app(tmp_path)
    _mock_runtime(monkeypatch)

    def fail(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 900)
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0,
            "not JSON" if failure == "json" else '{"status":"needs_fix"}', "actual error")

    monkeypatch.setattr(verification.subprocess, "run", fail)
    evidence = tmp_path / "failed"
    with pytest.raises((RuntimeError, ValueError, subprocess.TimeoutExpired)):
        verification.verify_app(app, evidence)
    report = json.loads((evidence / "verification.json").read_text())
    assert report["status"] == "failed"
    assert report["checks"] == [dict(report["checks"][0], name="doctor", status="failed")]
    assert report["clean_machine_test"] == "not_performed"
    if failure != "timeout":
        assert (evidence / "doctor.stderr.log").read_text() == "actual error"


def test_manifest_mismatch_stops_before_executing_bundle(tmp_path, monkeypatch):
    app = _app(tmp_path)
    (app / "Contents/Resources/app/src/sciplot_core/__init__.py").write_text("changed")
    monkeypatch.setattr(verification.subprocess, "run", lambda *a, **k: pytest.fail("must not launch modified source"))
    with pytest.raises(ValueError, match="differs"):
        verification.verify_app(app, tmp_path / "failed")
    assert json.loads((tmp_path / "failed/verification.json").read_text())["status"] == "failed"


def test_verification_binds_actual_bundle_and_detects_runtime_writes(tmp_path, monkeypatch):
    app = _app(tmp_path)
    _mock_runtime(monkeypatch)
    report = verification.verify_app(app, tmp_path / "passed", smoke=True)
    assert report["status"] == "passed"
    assert report["bundle_sha256"] == content_digest(bundle_snapshot(app))
    assert [item["name"] for item in report["checks"]][-1] == "runtime_smoke"
    assert report["developer_id_signed"] is None

    def writes_to_app(*args):
        (app / "unexpected.pyc").write_bytes(b"cache")
        return {"status": "passed"}

    monkeypatch.setattr(verification, "verify_mcp", writes_to_app)
    with pytest.raises(RuntimeError, match="changed during verification"):
        verification.verify_app(app, tmp_path / "changed")


def test_public_release_cannot_package_unsigned_app_or_overwrite_output(tmp_path, monkeypatch):
    app = _app(tmp_path)
    original = bundle_snapshot(app)

    def copy(command, **kwargs):
        assert command[0] == "/usr/bin/ditto" and len(command) == 3
        shutil.copytree(command[1], command[2], symlinks=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release.subprocess, "run", copy)
    monkeypatch.setattr(release, "assess_distribution", lambda *args: {"passed": False, "checks": {}})
    monkeypatch.setattr(release, "verify_app", lambda *a, **k: pytest.fail("public gate must block first"))
    out = tmp_path / "release"
    with pytest.raises(ValueError, match="Developer ID"):
        release.prepare_release(app, out, public=True)
    report = json.loads((out / "release.json").read_text())
    assert report["status"] == "failed" and report["public_distribution_ready"] is False
    assert not list(out.glob("*.zip"))
    assert bundle_snapshot(app) == original
    with pytest.raises(FileExistsError):
        release.prepare_release(app, out)


def test_public_gate_requires_developer_identity_and_all_apple_checks(tmp_path, monkeypatch):
    def fake(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "", "Signature=adhoc\nTeamIdentifier=not set\n")

    monkeypatch.setattr(release.subprocess, "run", fake)
    assessment = release.assess_distribution(tmp_path / "App.app", tmp_path / "signing")
    assert assessment["passed"] is False
    assert assessment["checks"]["identity"]["passed"] is False


def test_feedback_omits_private_paths_measurements_and_arbitrary_error_text():
    secret = "/Users/private/secret-experiment-token-123"
    report = welcome.feedback_report({
        "status": "needs_fix", "error": secret, "repo_root": secret,
        "checks": [{"id": "veusz_qt_runtime", "status": "failed", "detail": secret},
                   {"id": secret, "status": "failed"}],
    }, {"app_version": "0.1.0", "python": secret, "dependencies": secret}, True)
    assert secret not in json.dumps(report)
    assert report["checks"] == [{"id": "veusz_qt_runtime", "status": "failed"}]
    assert report["build"]["app_version"] == "0.1.0"


def test_welcome_timeout_and_nonzero_ready_are_failures(monkeypatch):
    monkeypatch.setattr(welcome.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, '{"status":"ready"}', "failed"))
    assert welcome.run_json(["doctor"], timeout=1)["status"] == "needs_fix"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("doctor", 1)

    monkeypatch.setattr(welcome.subprocess, "run", timeout)
    assert welcome.run_json(["doctor"], timeout=1)["status"] == "needs_fix"


def test_welcome_downloads_embed_exact_contents_for_local_file_pages(tmp_path):
    class Downloads(HTMLParser):
        def __init__(self):
            super().__init__()
            self.files = {}

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "a" and values.get("download"):
                self.files[values["download"]] = values["href"]

    command = tmp_path / '有空格 "name"/sciplot'
    page = welcome.render_page(command, {"status": "ready"}, True, tmp_path / "check.json")
    parser = Downloads()
    parser.feed(page)
    expected = welcome.connection_files(command) | {
        "SciPlot-feedback.json": json.dumps(welcome.feedback_report({"status": "ready"}, {}, True), ensure_ascii=False, indent=2) + "\n",
    }
    assert set(parser.files) == set(expected)
    for filename, text in expected.items():
        assert parser.files[filename].startswith("data:")
        assert unquote(parser.files[filename].split(",", 1)[1]) == text
