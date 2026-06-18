from __future__ import annotations

import argparse
import atexit
import hashlib
import importlib.util
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _SidecarProcess:
    project_dir: Path
    request_path: Path
    fingerprint: str
    process: subprocess.Popen[str]
    info: dict[str, Any]


_SIDECARS: dict[Path, _SidecarProcess] = {}


def webagg_available() -> tuple[bool, str]:
    if importlib.util.find_spec("tornado") is None:
        return False, "Matplotlib WebAgg requires the `tornado` package."
    return True, "available"


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request_fingerprint(request_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(request_path.resolve()).encode("utf-8"))
    if request_path.exists():
        digest.update(request_path.read_bytes())
    return digest.hexdigest()[:16]


def _read_ready_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _is_running(process: subprocess.Popen[str]) -> bool:
    return process.poll() is None


def _stop_sidecar(sidecar: _SidecarProcess) -> None:
    if not _is_running(sidecar.process):
        return
    sidecar.process.terminate()
    try:
        sidecar.process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        sidecar.process.kill()


def ensure_webagg_sidecar(
    *,
    project_dir: str | Path,
    request_path: str | Path,
    host: str = "127.0.0.1",
    timeout: float = 6.0,
) -> dict[str, Any]:
    available, reason = webagg_available()
    if not available:
        return {
            "kind": "sciplot_webagg_sidecar",
            "available": False,
            "running": False,
            "reason": reason,
            "url": None,
        }

    project_path = Path(project_dir).expanduser().resolve()
    resolved_request = Path(request_path).expanduser().resolve()
    fingerprint = _request_fingerprint(resolved_request)
    existing = _SIDECARS.get(project_path)
    if existing is not None and existing.fingerprint == fingerprint and _is_running(existing.process):
        return dict(existing.info)
    if existing is not None:
        _stop_sidecar(existing)
        _SIDECARS.pop(project_path, None)

    cache_dir = project_path / "workbench_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(18)
    port = _free_local_port()
    ready_file = cache_dir / f"webagg_{fingerprint}.json"
    log_file = cache_dir / f"webagg_{fingerprint}.log"
    if ready_file.exists():
        ready_file.unlink()

    command = [
        sys.executable,
        "-m",
        "sciplot_core.workbench_webagg",
        "serve",
        "--request",
        str(resolved_request),
        "--host",
        host,
        "--port",
        str(port),
        "--token",
        token,
        "--ready-file",
        str(ready_file),
    ]
    env = os.environ.copy()
    env["SCIPLOT_MPL_BACKEND"] = "WebAgg"
    env.setdefault("MPLBACKEND", "WebAgg")
    with log_file.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=str(project_path),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    deadline = time.monotonic() + timeout
    info: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        info = _read_ready_file(ready_file)
        if info is not None:
            break
        time.sleep(0.05)

    if info is None:
        reason_text = "Matplotlib WebAgg sidecar did not become ready."
        if process.poll() is not None and log_file.exists():
            reason_text = log_file.read_text(encoding="utf-8", errors="replace")[-2000:] or reason_text
        if process.poll() is None:
            process.terminate()
        return {
            "kind": "sciplot_webagg_sidecar",
            "available": True,
            "running": False,
            "reason": reason_text,
            "url": None,
            "log": str(log_file),
        }

    info = {
        **info,
        "available": True,
        "running": True,
        "fingerprint": fingerprint,
        "request_path": str(resolved_request),
        "log": str(log_file),
    }
    _SIDECARS[project_path] = _SidecarProcess(
        project_dir=project_path,
        request_path=resolved_request,
        fingerprint=fingerprint,
        process=process,
        info=info,
    )
    return dict(info)


def stop_webagg_sidecars() -> None:
    for sidecar in list(_SIDECARS.values()):
        _stop_sidecar(sidecar)
    _SIDECARS.clear()


atexit.register(stop_webagg_sidecars)


def _serve_webagg(*, request_path: Path, host: str, port: int, token: str, ready_file: Path) -> None:
    os.environ["SCIPLOT_MPL_BACKEND"] = "WebAgg"
    os.environ.setdefault("MPLBACKEND", "WebAgg")

    from matplotlib._pylab_helpers import Gcf
    from matplotlib.backends.backend_webagg import WebAggApplication, new_figure_manager_given_figure

    from sciplot_core.workbench_preview import build_workbench_rendered_plots

    job, rendered = build_workbench_rendered_plots(request_path)
    if not rendered:
        raise RuntimeError("SciPlot request produced no rendered plots for WebAgg.")
    figure = rendered[0].figure
    manager = new_figure_manager_given_figure(1, figure)
    Gcf._set_new_active_manager(manager)
    url_prefix = f"/{token}"
    WebAggApplication.initialize(url_prefix=url_prefix, port=port, address=host)
    url = f"http://{host}:{WebAggApplication.port}{url_prefix}/1"
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.write_text(
        json.dumps(
            {
                "kind": "sciplot_webagg_sidecar",
                "url": url,
                "host": host,
                "port": WebAggApplication.port,
                "token_prefix": url_prefix,
                "template": job.template,
                "route": job.route,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    WebAggApplication.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a SciPlot Matplotlib WebAgg sidecar.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--request", required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, required=True)
    serve.add_argument("--token", required=True)
    serve.add_argument("--ready-file", required=True)
    args = parser.parse_args(argv)
    if args.command == "serve":
        _serve_webagg(
            request_path=Path(args.request).expanduser().resolve(),
            host=str(args.host),
            port=int(args.port),
            token=str(args.token),
            ready_file=Path(args.ready_file).expanduser().resolve(),
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ensure_webagg_sidecar", "main", "stop_webagg_sidecars", "webagg_available"]
