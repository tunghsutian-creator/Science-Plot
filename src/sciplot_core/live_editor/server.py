"""Loopback-only, session-authorized HTTP presentation of a native editor."""

from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
import webbrowser
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from sciplot_core.live_editor.session import LiveSession


ASSETS = Path(__file__).resolve().parents[1] / "live_editor_assets"
MAX_BODY = 128 * 1024


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, session: LiveSession, port: int = 0):
        self.session = session
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), EditorHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.cookie_name = f"sciplot_editor_{self.server_port}"


class EditorHandler(BaseHTTPRequestHandler):
    server: EditorServer

    def log_message(self, format: str, *args: Any) -> None:
        # Keep JSON CLI startup and the native stderr evidence separate.
        pass

    def _authorized(self, *, api: bool = False, image: bool = False) -> bool:
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            return False
        if api:
            return hmac.compare_digest(self.headers.get("X-SciPlot-Token", ""), self.server.token)
        if image:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                return False
            value = cookie.get(self.server.cookie_name)
            return value is not None and hmac.compare_digest(value.value, self.server.token)
        return True

    def _send(self, body: bytes, content_type: str, status: int = 200, *, page: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if page:
            self.send_header("Set-Cookie", f"{self.server.cookie_name}={self.server.token}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: dict[str, Any], status: int = 200) -> None:
        self._send(json.dumps(value, ensure_ascii=False, allow_nan=False).encode(),
                   "application/json; charset=utf-8", status)

    def _error(self, exc: Exception, status: int = 409) -> None:
        payload: dict[str, Any] = {"error": {"code": type(exc).__name__, "message": str(exc)}}
        try:
            payload["state"] = self.server.session.state()
        except Exception:
            pass  # The primary failure remains visible if the session is no longer readable.
        self._json(payload, status)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if not self._authorized(api=parsed.path == "/api/state", image=parsed.path == "/api/preview"):
            self._json({"error": {"code": "forbidden", "message": "编辑器会话身份不匹配。"}}, 403)
            return
        try:
            if parsed.path == "/api/state":
                self._json(self.server.session.state())
                return
            if parsed.path == "/api/preview":
                values = parse_qs(parsed.query)
                revision = int(values.get("revision", [""])[0])
                path = self.server.session.preview_path(revision)
                self._send(path.read_bytes(), "image/png")
                return
            if parsed.path.startswith("/api/"):
                self._json({"error": {"message": "未知的编辑器接口。"}}, 404)
                return
            relative = unquote(parsed.path).lstrip("/") or "index.html"
            path = (ASSETS / relative).resolve()
            if not path.is_relative_to(ASSETS.resolve()) or not path.is_file():
                self._json({"error": {"message": "未找到界面资源。"}}, 404)
                return
            data = path.read_bytes()
            if relative == "index.html":
                marker = f'<meta name="sciplot-token" content="{escape(self.server.token, quote=True)}">'
                data = data.replace(b"</head>", marker.encode() + b"</head>")
            self._send(data, mimetypes.guess_type(path)[0] or "application/octet-stream",
                       page=relative == "index.html")
        except (ValueError, OSError, RuntimeError) as exc:
            self._error(exc)

    def do_POST(self) -> None:
        if not self._authorized(api=True):
            self._json({"error": {"message": "编辑器会话身份不匹配。"}}, 403)
            return
        if self.path != "/api/command":
            self._json({"error": {"message": "未知的编辑器接口。"}}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                raise ValueError("无效或过大的编辑请求。")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("编辑请求需要 JSON。")
            request = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(request, dict):
                raise ValueError("编辑请求需要对象。")
            self._json(self.server.session.command(request))
        except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
            self._error(exc)


def serve_editor(project: Path, *, figure_id: str | None = None, port: int = 0,
                 output: Path | None = None, open_browser: bool = True) -> None:
    if not (ASSETS / "index.html").is_file():
        raise ValueError("缺少编辑器界面资源，请重新构建或安装 SciPlot。")
    session = LiveSession(project, figure_id=figure_id, output=output)
    try:
        server = EditorServer(session, port)
        print(json.dumps({"url": server.origin, "session_id": session.session_id,
                          "project": str(session.project), "figure_id": session.figure_id,
                          "session_dir": str(session.output)}, ensure_ascii=False), flush=True)
        if open_browser:
            webbrowser.open(server.origin)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    finally:
        session.close()
