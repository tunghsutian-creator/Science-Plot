"""Report the loaded source and runtime locations without changing either checkout."""

from pathlib import Path
import subprocess
import sys
from typing import Any

from sciplot_core._paths import PACKAGE_ROOT, REPO_ROOT, RUNTIME_REPO_ROOT, VEUSZ_ROOT


def execution_identity() -> dict[str, Any]:
    """Expose checkout context; Git metadata is not a source-byte or native audit."""
    source_root = PACKAGE_ROOT.parents[1]
    checkout: str | None = None
    head: str | None = None
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(source_root), "rev-parse", "--show-toplevel", "HEAD"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        lines = result.stdout.splitlines()
        if result.returncode == 0 and len(lines) == 2:
            checkout, head = lines
    except (OSError, subprocess.TimeoutExpired):
        pass  # A packaged install, missing Git or unavailable checkout stays explicit.
    wrapper = source_root / "skill/scripts/sciplot"
    command = ([str(wrapper)] if checkout and wrapper.is_file()
               else [sys.executable, "-m", "sciplot_core.cli"])
    return {
        "kind": "sciplot_execution_identity", "version": 1,
        "source_package_root": str(PACKAGE_ROOT),
        "source_checkout_root": checkout, "source_git_head": head,
        "configured_repo_root": str(REPO_ROOT),
        "runtime_repo_root": str(RUNTIME_REPO_ROOT), "veusz_root": str(VEUSZ_ROOT),
        "python_executable": sys.executable,
        "python_binary": str(Path(sys.executable).resolve()),
        "python_version": sys.version.split()[0],
        "source_runtime_separate": source_root.resolve() != RUNTIME_REPO_ROOT.resolve(),
        "git_scope": "checkout_metadata_only; uncommitted source and loaded native bytes are not certified",
        "native_execution_verified": False,
        "continuation": {"command_prefix": command,
                         "environment": {"SCIPLOT_REPO": str(REPO_ROOT),
                                         "SCIPLOT_RUNTIME_REPO": str(RUNTIME_REPO_ROOT),
                                         "SCIPLOT_SOURCE_ROOT": str(PACKAGE_ROOT.parent),
                                         "SCIPLOT_VEUSZ_ROOT": str(VEUSZ_ROOT)},
                         "scope": "new_cli_call_using_reported_roots; existing_sessions_not_rebound",
                         "existing_documents_migrated": False},
    }
