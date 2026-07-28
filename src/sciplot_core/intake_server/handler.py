"""Serve intake assets and JSON endpoints over localhost."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import stat
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import safe_filename
from sciplot_core.intake.catalog import intake_catalog_payload
from sciplot_core.intake.packaging import _project_dir_fromslug
from sciplot_core.intake.path_security import _resolve_path_within_root
from sciplot_core.intake.payloads import _decode_group_payload
from sciplot_core.intake.application import create_intake_project
from sciplot_core.intake.run import create_and_run_intake_project
from sciplot_core.intake.status import (
    _resolve_project_artifact,
    intake_project_status,
    list_intake_projects,
)
from sciplot_core.intake.table_preview import preview_table_payload

from sciplot_core.intake_server.request_security import (
    _STATIC_DIR,
    _MAX_JSON_BODY_BYTES,
    _is_loopback_host,
    _authorized_source_path,
)


class _IntakeServerContext(Protocol):
    output_root: Path
    server_port: int


class _IntakeHandler(BaseHTTPRequestHandler):
    server: _IntakeServerContext

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, *, authorized_root: Path) -> None:
        try:
            safe_path = _resolve_path_within_root(
                path,
                root=authorized_root,
                require_regular_file=True,
            )
            open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            file_descriptor = os.open(safe_path, open_flags)
            handle = os.fdopen(file_descriptor, "rb")
            file_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                handle.close()
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        except PermissionError as exc:
            self.send_error(HTTPStatus.FORBIDDEN, str(exc))
            return
        except (FileNotFoundError, OSError):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = (
            mimetypes.guess_type(safe_path.name)[0] or "application/octet-stream"
        )
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(file_stat.st_size))
            self.end_headers()
            while chunk := handle.read(64 * 1024):
                self.wfile.write(chunk)
        finally:
            handle.close()

    def _project_dir_from_request(self, project_slug: str) -> Path:
        return _project_dir_fromslug(self.server.output_root, unquote(project_slug))

    def _validate_local_request(self) -> None:
        host_header = str(self.headers.get("Host") or "").strip()
        parsed_host = urlparse(f"//{host_header}")
        if not parsed_host.hostname or not _is_loopback_host(parsed_host.hostname):
            raise PermissionError("SciPlot browser requests require a loopback Host.")
        try:
            host_port = parsed_host.port or 80
        except ValueError as exc:
            raise PermissionError(
                "SciPlot browser request has an invalid Host port."
            ) from exc
        if host_port != self.server.server_port:
            raise PermissionError(
                "SciPlot browser request port does not match this server."
            )
        origin_header = str(self.headers.get("Origin") or "").strip()
        if not origin_header:
            return
        parsed_origin = urlparse(origin_header)
        try:
            origin_port = parsed_origin.port or 80
        except ValueError as exc:
            raise PermissionError(
                "SciPlot browser request has an invalid Origin port."
            ) from exc
        if (
            parsed_origin.scheme != "http"
            or not parsed_origin.hostname
            or not _is_loopback_host(parsed_origin.hostname)
            or parsed_origin.hostname.casefold() != parsed_host.hostname.casefold()
            or origin_port != self.server.server_port
        ):
            raise PermissionError(
                "SciPlot browser POSTs require a loopback same-origin request."
            )

    def _read_json_body(self) -> dict[str, object]:
        content_type = str(self.headers.get("Content-Type") or "")
        if content_type.partition(";")[0].strip().casefold() != "application/json":
            raise ValueError(
                "SciPlot browser POSTs require Content-Type application/json."
            )
        try:
            length = int(str(self.headers.get("Content-Length") or ""))
        except ValueError as exc:
            raise ValueError("A valid Content-Length header is required.") from exc
        if length <= 0 or length > _MAX_JSON_BODY_BYTES:
            raise ValueError(
                "JSON request body must contain between 1 byte and "
                f"{_MAX_JSON_BODY_BYTES} bytes."
            )
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object.")
        return payload

    def _validate_group_source_paths(self, payload: dict[str, object]) -> None:
        groups = (
            payload.get("groups") if isinstance(payload.get("groups"), list) else []
        )
        for group in groups:
            if not isinstance(group, dict):
                continue
            files = group.get("files") if isinstance(group.get("files"), list) else []
            for item in files:
                if not isinstance(item, dict) or not item.get("source_path"):
                    continue
                item["source_path"] = str(
                    _authorized_source_path(
                        item["source_path"],
                        output_root=self.server.output_root,
                        session_id=payload.get("session_id"),
                    )
                )

    def _respond_error(self, exc: Exception) -> None:
        detail = str(exc) or type(exc).__name__
        if isinstance(exc, FileNotFoundError):
            self._send_json(
                {
                    "error": detail,
                    "code": "not_found",
                    "hint": "The requested resource was not found.",
                },
                status=HTTPStatus.NOT_FOUND,
            )
        elif isinstance(exc, PermissionError):
            self._send_json(
                {"error": detail, "code": "forbidden"},
                status=HTTPStatus.FORBIDDEN,
            )
        elif isinstance(exc, (ValueError, TypeError)):
            self._send_json(
                {"error": detail, "code": "invalid_input"},
                status=HTTPStatus.BAD_REQUEST,
            )
        elif isinstance(exc, OSError):
            self._send_json(
                {"error": detail, "code": "io_error"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        else:
            self._send_json(
                {"error": detail, "code": "internal_error"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_GET(self) -> None:
        try:
            self._validate_local_request()
        except PermissionError as exc:
            self.send_error(HTTPStatus.FORBIDDEN, str(exc))
            return
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(_STATIC_DIR / "index.html", authorized_root=_STATIC_DIR)
            return
        if parsed.path == "/api/catalog":
            query = parse_qs(parsed.query)
            include_pending = query.get("all", ["0"])[0] in {"1", "true", "yes"}
            self._send_json(intake_catalog_payload(include_pending=include_pending))
            return
        if parsed.path.startswith("/api/session/"):
            session_id = safe_filename(unquote(parsed.path.rsplit("/", 1)[-1]))
            session_root = self.server.output_root / "sessions"
            self._send_file(
                session_root / f"{session_id}.json",
                authorized_root=session_root,
            )
            return
        if parsed.path == "/api/session":
            query = parse_qs(parsed.query)
            session_id = safe_filename(query.get("id", [""])[0])
            session_root = self.server.output_root / "sessions"
            self._send_file(
                session_root / f"{session_id}.json",
                authorized_root=session_root,
            )
            return
        if parsed.path == "/api/projects":
            query = parse_qs(parsed.query)
            search = str(query.get("search", [""])[0]).strip().lower()
            all_projects = list_intake_projects(self.server.output_root)
            if search:
                all_projects = [
                    project
                    for project in all_projects
                    if search in project["slug"].lower()
                    or search in str(project.get("project_name", "")).lower()
                ]
            self._send_json({"kind": "sciplot_project_list", "projects": all_projects})
            return
        if parsed.path.startswith("/api/download/"):
            filename = safe_filename(unquote(parsed.path.rsplit("/", 1)[-1]))
            self._send_file(
                self.server.output_root / filename,
                authorized_root=self.server.output_root,
            )
            return
        if parsed.path.startswith("/api/projects/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 4 and parts[0] == "api" and parts[1] == "projects":
                project_dir = self._project_dir_from_request(parts[2])
                try:
                    if parts[3] == "status":
                        self._send_json(intake_project_status(project_dir))
                        return
                    if parts[3] == "artifact":
                        query = parse_qs(parsed.query)
                        artifact_path = query.get("path", [""])[0]
                        artifact = _resolve_project_artifact(project_dir, artifact_path)
                        self._send_file(artifact, authorized_root=project_dir)
                        return
                except PermissionError as exc:
                    self.send_error(HTTPStatus.FORBIDDEN, str(exc))
                    return
                except FileNotFoundError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                except ValueError as exc:
                    self._respond_error(exc)
                    return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            self._validate_local_request()
        except PermissionError as exc:
            self.send_error(HTTPStatus.FORBIDDEN, str(exc))
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/table-preview":
            try:
                payload = self._read_json_body()
                source_path = str(payload.get("source_path") or "").strip()
                content_base64 = str(payload.get("content_base64") or "")
                content: bytes | None = None
                authorized_path: Path | None = None
                if source_path:
                    authorized_path = _authorized_source_path(
                        source_path,
                        output_root=self.server.output_root,
                        session_id=payload.get("session_id"),
                    )
                if content_base64:
                    if "," in content_base64:
                        content_base64 = content_base64.split(",", 1)[1]
                    content = base64.b64decode(content_base64, validate=True)
                preview = preview_table_payload(
                    name=str(payload.get("name") or Path(source_path).name or "table"),
                    content=content,
                    source_path=str(authorized_path) if authorized_path else None,
                )
            except Exception as exc:
                self._respond_error(exc)
                return
            self._send_json(preview)
            return
        if parsed.path != "/api/projects":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json_body()
            self._validate_group_source_paths(payload)
            create_project = (
                create_and_run_intake_project
                if payload.get("run_after_create")
                else create_intake_project
            )
            project = create_project(
                project_name=str(payload.get("project_name") or ""),
                data_type_id=str(payload.get("data_type_id") or ""),
                experiment_type_id=str(payload.get("experiment_type_id") or ""),
                groups=_decode_group_payload(payload),
                output_root=self.server.output_root,
                plot_output=payload.get("plot_output"),
                exports=payload.get("exports"),
                render_options=payload.get("render_options"),
                column_confirmations=payload.get("column_confirmations"),
                replicate_mode=payload.get("replicate_mode"),
            )
        except Exception as exc:
            self._respond_error(exc)
            return
        self._send_json(project)
