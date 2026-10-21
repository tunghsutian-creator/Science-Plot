"""Owned startup for public enforcement, composed with opt-in observation."""
import os
import hashlib
import json
import importlib.util
from importlib.machinery import PathFinder
from pathlib import Path
import sys

try:
    wrapper_bootstrap = os.environ.pop("SCIPLOT_PUBLIC_GUARD_WRAPPER_BOOTSTRAP", None)
    if wrapper_bootstrap:
        actual = Path(__file__).resolve()
        if actual != Path(wrapper_bootstrap).resolve():
            raise ValueError("Unknown public wrapper startup.")
        os.environ["SCIPLOT_PUBLIC_GUARD_BOOTSTRAP"] = json.dumps({
            "path": str(actual), "sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
        })
    # Every owned startup pins its adjacent dependencies, even when the
    # caller deliberately omits the package path from PYTHONPATH.
    source = Path(__file__).resolve().parents[3]
    owner = source / "sciplot_core/__init__.py"
    locations = [os.curdir, *os.environ.get("PYTHONPATH", "").split(os.pathsep)]
    explicit = PathFinder.find_spec("sciplot_core", locations)
    if explicit is not None and explicit.origin is not None and Path(explicit.origin).resolve() != owner:
        raise ValueError("Public startup has an unknown explicit source owner.")
    sys.path.insert(0, str(source))
    import sciplot_core
    if Path(sciplot_core.__file__).resolve() != owner:
        raise ValueError("Public startup has an unknown loaded source owner.")
    if os.environ.get("SCIPLOT_PRIVATE_AUDIT_DIR") and os.environ.get("SCIPLOT_PRIVATE_AUDIT_ROOTS"):
        from sciplot_core.verification.private_observer import install as install_observer

        install_observer()
    # Import from this owned file so an intentionally isolated bootstrap-control
    # package cannot mask enforcement by shadowing sciplot_core on sys.path.
    spec = importlib.util.spec_from_file_location("_sciplot_public_input_guard", Path(__file__).parents[1] / "public_input_guard.py")
    if spec is None or spec.loader is None:
        raise ValueError("Owned public enforcement source is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install()
except Exception as error:
    print(f"Public verification startup BLOCKED: {error}", file=sys.stderr)
    # Python otherwise catches a sitecustomize error and executes the body.
    os._exit(78)
