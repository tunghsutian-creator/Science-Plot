"""Loopback browser application startup for intake confirmation."""

from __future__ import annotations

import errno
import json
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote
from sciplot_core.foundation.path_names import safe_filename

from .config import _DEFAULT_OUTPUT_ROOT
from .packaging import _project_dir_fromslug
from .session import prepare_intake_session


def serve_intake(
    *,
    input_path: str | Path | None = None,
    project_slug: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    open_browser: bool = True,
) -> None:
    # Keep HTTP ownership outside the intake domain module.  The lazy import
    # avoids a cycle because the thin server adapter calls domain functions
    # defined above.
    from sciplot_core.intake_server import _IntakeServer

    requested_port = port
    try:
        server = _IntakeServer((host, port), output_root)
    except OSError as exc:
        if port and getattr(exc, "errno", None) == errno.EADDRINUSE:
            server = _IntakeServer((host, 0), output_root)
        else:
            raise
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}"
    payload: dict[str, Any] = {"url": url, "output_root": str(server.output_root)}
    if requested_port and actual_port != requested_port:
        payload.update({"requested_port": requested_port, "port_fallback": True})
    if input_path is not None:
        session = prepare_intake_session(input_path, output_root=server.output_root)
        url = f"{url}?session={quote(str(session['session_id']))}"
        payload.update(
            {
                "url": url,
                "session_path": session["session_path"],
                "session_id": session["session_id"],
            }
        )
    elif project_slug:
        safe_project = safe_filename(project_slug)
        project_dir = _project_dir_fromslug(server.output_root, safe_project)
        if not (project_dir / "intake_manifest.json").exists():
            raise FileNotFoundError(
                f"No intake project manifest found for project: {project_slug}"
            )
        url = f"{url}?project={quote(safe_project)}"
        payload.update(
            {"url": url, "project_slug": safe_project, "project_dir": str(project_dir)}
        )
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
