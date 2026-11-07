from __future__ import annotations

import subprocess
import sys
import pytest

from sciplot_core.studio_core import project_session as sessions


def test_native_lease_blocks_external_process_until_closed(tmp_path):
    project = tmp_path / "managed"
    project.mkdir()
    lease = sessions.ProjectSessionLease(project, native=True)
    code = "from pathlib import Path; from sciplot_core.studio_core.project_session import ProjectSessionLease; import sys; ProjectSessionLease(Path(sys.argv[1]), native=False).close()"

    def attempt():
        return subprocess.run(
            [sys.executable, "-c", code, str(project)],
            capture_output=True,
            text=True,
            timeout=20,
        )

    try:
        assert "writable Veusz session" in attempt().stderr
    finally:
        lease.close()
    assert attempt().returncode == 0


def test_failed_core_scope_releases_its_lease_without_releasing_another_project(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    with sessions.ProjectSessionLease(first, native=True):
        with pytest.raises(OSError, match="controlled Core failure"):
            with sessions.external_project_session(second):
                raise OSError("controlled Core failure")
        with sessions.external_project_session(second):
            pass
        with pytest.raises(sessions.ProjectSessionBusy):
            with sessions.external_project_session(first):
                pytest.fail("The native lease was lost by another project's failure")
    with sessions.external_project_session(first):
        pass
