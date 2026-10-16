"""The diagnostic identifies loaded source separately from a supplied runtime."""

from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from sciplot_core.doctor import execution_identity as identity


@pytest.mark.parametrize("git_available", [True, False])
def test_execution_identity_preserves_distinct_source_and_runtime(tmp_path, monkeypatch, git_available):
    checkout = tmp_path / "checkout"
    package = checkout / "src/sciplot_core"
    package.mkdir(parents=True)
    wrapper = checkout / "skill/scripts/sciplot"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("owned source wrapper")
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(identity, "PACKAGE_ROOT", package)
    monkeypatch.setattr(identity, "REPO_ROOT", checkout)
    monkeypatch.setattr(identity, "RUNTIME_REPO_ROOT", runtime)
    monkeypatch.setattr(identity, "VEUSZ_ROOT", runtime / "third_party/veusz")

    def git(argv, **kwargs):
        assert argv == ["git", "--no-optional-locks", "-C", str(checkout),
                        "rev-parse", "--show-toplevel", "HEAD"]
        assert kwargs["timeout"] == 2 and kwargs["check"] is False
        if not git_available:
            raise subprocess.TimeoutExpired(argv, 2)
        return SimpleNamespace(returncode=0, stdout=f"{checkout}\n{'a' * 40}\n")

    monkeypatch.setattr(identity.subprocess, "run", git)
    result = identity.execution_identity()
    assert result["source_package_root"] == str(package)
    assert result["configured_repo_root"] == str(checkout)
    assert result["runtime_repo_root"] == str(runtime)
    assert result["source_runtime_separate"] is True
    assert result["native_execution_verified"] is False
    assert result["source_git_head"] == ("a" * 40 if git_available else None)
    prefix = result["continuation"]["command_prefix"]
    assert prefix == ([str(wrapper)] if git_available else [identity.sys.executable, "-m", "sciplot_core.cli"])
    assert result["continuation"]["existing_documents_migrated"] is False
    assert result["continuation"]["environment"] == {
        "SCIPLOT_REPO": str(checkout), "SCIPLOT_RUNTIME_REPO": str(runtime),
        "SCIPLOT_SOURCE_ROOT": str(package.parent), "SCIPLOT_VEUSZ_ROOT": str(runtime / "third_party/veusz"),
    }
    assert wrapper.read_text() == "owned source wrapper"
    assert not runtime.exists()


def test_execution_identity_does_not_call_a_failed_git_probe_a_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "PACKAGE_ROOT", tmp_path / "src/sciplot_core")
    monkeypatch.setattr(identity.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=128, stdout="fatal: unavailable\n"))
    result = identity.execution_identity()
    assert result["source_checkout_root"] is None and result["source_git_head"] is None
    assert Path(result["python_binary"]).is_absolute()
