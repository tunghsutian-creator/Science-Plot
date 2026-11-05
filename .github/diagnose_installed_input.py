"""One-shot CI diagnostic: never produces a public-result reference."""
import json
import sys
import time
from pathlib import Path

from sciplot_core.verification.ci_public_environment import (
    UnsupportedEnvironment,
    application_environment,
    collect_environment,
)

root = Path.cwd()
started = time.monotonic()
result = {"diagnostic": "installed_input", "stage": "owned_roots"}
try:
    directory = root / ".tmp_verify/ci-public-reference"
    if (root / ".tmp_verify").is_symlink() or directory.is_symlink():
        raise UnsupportedEnvironment("owned_root_alias")
    directory.mkdir(parents=True, exist_ok=False)
    controlled = application_environment(root)
    for name in ("HOME", "TMPDIR", "PYTHONPYCACHEPREFIX"):
        path = Path(controlled[name])
        if path.is_symlink() or (path.exists() and any(path.iterdir())):
            raise UnsupportedEnvironment("owned_initial_state")
        path.mkdir(parents=True, exist_ok=True)
    result["stage"] = "collector"
    collect_environment(root)
    result["outcome"] = "collector_completed_without_refusal"
except UnsupportedEnvironment as error:
    result["outcome"] = "unsupported_environment"
    # Only the known constant is emitted; arbitrary exception text is not logged.
    if str(error) == "unsupported_installed_input_root":
        result["reason"] = "unsupported_installed_input_root"
        frames = []
        tb = error.__traceback__
        while tb:
            frames.append(tb)
            tb = tb.tb_next
        inner = frames[-1].tb_frame
        caller = frames[-2] if len(frames) >= 2 else None
        if inner.f_code.co_name == "file_identity" and caller:
            logical = inner.f_locals["logical"]
            resolved = inner.f_locals["path"]
            line = caller.tb_lineno
            collector = next((frame.tb_frame for frame in frames
                              if frame.tb_frame.f_code.co_name == "_collect_ubuntu"), None)
            if collector is not None:
                result["collector_elapsed_seconds"] = round(
                    time.monotonic() - collector.f_locals["started"], 3)
            producer = {178: "stdlib", 211: "distribution", 230: "qt_plugin",
                        240: "fontconfig", 245: "native_extension",
                        253: "native_dependency", 254: "font"}.get(line, "unknown")
            result.update(logical_path=str(logical), resolved_path=str(resolved),
                          is_file=resolved.is_file(), logical_is_symlink=logical.is_symlink(),
                          is_alias=logical != resolved, producer=producer,
                          collector_line=line)
            if producer == "distribution":
                result["distribution_name"] = caller.tb_frame.f_locals.get("name", "unknown")
    else:
        result["reason"] = "other_unsupported_environment"
except Exception:
    result["outcome"] = "unexpected_exception"
finally:
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, sort_keys=True), flush=True)
    print("INTENTIONAL_DIAGNOSTIC_STOP exit=86; no public test or origin", flush=True)
    raise SystemExit(86)
