"""Place generated AF_UNIX fixtures in the audit's fresh finite input scope."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile

import pytest

from sciplot_core.verification.private_audit_runtime import ACTOR, reserve_socket_fixture


@contextmanager
def socket_directory(*, prefix, dir="/tmp", endpoints=("engine.sock",)):
    scoped = reserve_socket_fixture(tuple(endpoints))
    if scoped is None:
        with tempfile.TemporaryDirectory(prefix=prefix, dir=dir) as temporary:
            yield temporary
        return
    # Explicit generated fixtures retain their existing cross-client lifetime.
    # Only the audit's default-actor holder consumes this audit-only marker.
    previous = os.environ.pop(ACTOR, None)
    try:
        yield str(scoped)
    finally:
        if previous is not None:
            os.environ[ACTOR] = previous
        for name in endpoints:
            for path in scoped.glob(name + "*"):
                if path.is_dir() and not path.is_symlink():
                    raise ValueError("Unexpected directory in a generated socket fixture.")
                path.unlink(missing_ok=True)


@pytest.fixture
def audited_socket_directory():
    with socket_directory(prefix="sp-observer-fixture-", endpoints=("engine.sock",)) as temporary:
        yield Path(temporary)
