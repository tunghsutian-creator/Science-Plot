"""Isolated non-executable capability data for descriptor-only tests.

This never changes the canonical runtime adapter or the actual platform. The
generated Mac controls are the sole execution proof for sandbox capability.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Iterator
from uuid import uuid4

from sciplot_core.verification import process_private_exclusion as runtime


@contextmanager
def descriptor_boundary(directory: Path) -> Iterator[ModuleType]:
    canonical_identity = runtime._identity
    name = "_sciplot_synthetic_descriptor_" + uuid4().hex
    spec = importlib.util.spec_from_file_location(name, runtime.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        tools = directory / "synthetic-capability-descriptors"
        tools.mkdir()
        for attribute in ("SANDBOX", "ENV", "SYSTEM", "DESCRIPTOR_TARGET"):
            path = tools / attribute.lower()
            path.write_bytes(b"synthetic descriptor data; never an executable\n")
            path.chmod(0o600)
            setattr(module, attribute, path)

        def synthetic_identity() -> dict[str, object]:
            return {"adapter": "synthetic descriptor data, not native admission",
                "sandbox": module._tool(module.SANDBOX), "env": module._tool(module.ENV),
                "system": module._tool(module.SYSTEM), "interpreter": module._tool(module.DESCRIPTOR_TARGET),
                "os": {"kind": "synthetic descriptor-only facts"},
                "sources": [module._tool(Path(runtime.__file__)), module._tool(Path(__file__))]}

        module.__dict__["_identity"] = synthetic_identity
        assert runtime._identity is canonical_identity
        yield module
    finally:
        assert runtime._identity is canonical_identity
        sys.modules.pop(name, None)
