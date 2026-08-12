from __future__ import annotations

import json
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from sciplot_core import intake, intake_server


def test_browser_surface_keeps_first_project_creation_and_read_only_review() -> None:
    html_path = Path(intake.__file__).with_name("intake_static") / "index.html"
    html = html_path.read_text(encoding="utf-8")

    assert 'fetch("/api/projects",' in html
    assert "run_after_create: true" in html
    assert "render_options: { size: S.figureSize }" in html
    assert "Result Review is read-only" in html
    assert "renderScientificTransformReview(scientificReview)" in html
    assert '<div class="section-title">Scientific Review</div>' in html
    assert "Open_in_Veusz.command" in html
    assert "canonical_figure_stem" in html
    assert '.replace(/_\\d+dpi$/i, "")' in html

    forbidden_mutation_tokens = (
        "data-refine",
        "data-series",
        "/workbench/apply",
        "/rerun",
        "applyProject",
        "exportProject",
        "workbenchPayload",
        "renderAxesInspector",
        "renderAppearanceInspector",
        "renderLegendInspector",
        "renderSeriesInspector",
    )
    for token in forbidden_mutation_tokens:
        assert token not in html


def test_removed_browser_mutation_and_execution_routes_return_not_found() -> None:
    handler = object.__new__(intake_server._IntakeHandler)
    statuses: list[int] = []
    headers = Message()
    headers["Host"] = "127.0.0.1:8765"
    handler.headers = headers
    handler.server = SimpleNamespace(server_port=8765)
    handler.send_error = lambda status, *_args, **_kwargs: statuses.append(int(status))

    for path in (
        "/api/projects/demo/workbench/apply",
        "/api/projects/demo/rerun",
        "/api/codex/jobs",
    ):
        handler.path = path
        handler.do_POST()

    for path in (
        "/api/codex/jobs/demo?project=demo",
        "/api/reveal?path=/tmp",
    ):
        handler.path = path
        handler.do_GET()

    assert statuses == [HTTPStatus.NOT_FOUND] * 5


def test_removed_browser_mutation_helpers_are_not_public() -> None:
    assert not hasattr(intake, "apply_intake_project")
    assert not hasattr(intake, "rerun_intake_project")
    assert "apply_intake_project" not in intake.__all__
    assert "rerun_intake_project" not in intake.__all__


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.25", "example.com"])
def test_browser_server_rejects_non_loopback_bindings(
    tmp_path: Path,
    host: str,
) -> None:
    with pytest.raises(ValueError, match="loopback"):
        intake_server._IntakeServer((host, 0), tmp_path / "output")


def test_browser_source_paths_are_bound_to_output_or_active_session(
    tmp_path: Path,
) -> None:
    output_root = (tmp_path / "output").resolve()
    output_root.mkdir()
    inside = output_root / "project" / "source.csv"
    inside.parent.mkdir()
    inside.write_text("x,y\n0,1\n", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    outside.write_text("x,y\n0,2\n", encoding="utf-8")

    assert (
        intake_server._authorized_source_path(
            inside,
            output_root=output_root,
        )
        == inside.resolve()
    )
    with pytest.raises(PermissionError, match="active CLI-created session"):
        intake_server._authorized_source_path(
            outside,
            output_root=output_root,
        )

    sessions = output_root / "sessions"
    sessions.mkdir()
    (sessions / "session-1.json").write_text(
        json.dumps(
            {
                "output_root": str(output_root),
                "groups": [
                    {
                        "files": [
                            {"source_path": str(outside)},
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        intake_server._authorized_source_path(
            outside,
            output_root=output_root,
            session_id="session-1",
        )
        == outside.resolve()
    )


def test_project_artifacts_ignore_manifest_supplied_external_roots(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "output" / "project"
    project_dir.mkdir(parents=True)
    internal = project_dir / "runs" / "run_001" / "figure.pdf"
    internal.parent.mkdir(parents=True)
    internal.write_bytes(b"%PDF-safe")
    external = tmp_path / "secret.txt"
    external.write_text("secret", encoding="utf-8")
    (project_dir / "intake_manifest.json").write_text(
        json.dumps(
            {
                "project_slug": "project",
                "outputs_dir": str(tmp_path),
                "last_run": {
                    "output": str(tmp_path),
                    "figures": [str(external)],
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        intake._resolve_project_artifact(
            project_dir,
            str(internal),
        )
        == internal.resolve()
    )
    with pytest.raises(PermissionError, match="outside this SciPlot project"):
        intake._resolve_project_artifact(project_dir, str(external))

    status = intake.intake_project_status(project_dir)
    assert status["outputs_dir"] == str((project_dir / "runs" / "run_001").resolve())
    assert status["figures"] == []
    assert status["preview_figure"]["exists"] is False


def test_project_artifact_and_download_paths_reject_symlinks(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "output" / "project"
    project_dir.mkdir(parents=True)
    target = project_dir / "artifact.txt"
    target.write_text("artifact", encoding="utf-8")
    symlink = project_dir / "artifact-link.txt"
    symlink.symlink_to(target)

    with pytest.raises(PermissionError):
        intake._resolve_project_artifact(project_dir, str(symlink))

    handler = object.__new__(intake_server._IntakeHandler)
    statuses: list[int] = []
    handler.send_error = lambda status, *_args, **_kwargs: statuses.append(int(status))
    handler._send_file(symlink, authorized_root=project_dir)
    assert statuses == [HTTPStatus.FORBIDDEN]


def test_intake_zip_refuses_symlink_entries(tmp_path: Path) -> None:
    project_dir = tmp_path / "output" / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "manifest.json").write_text("{}", encoding="utf-8")
    external = tmp_path / "external.txt"
    external.write_text("external", encoding="utf-8")
    (project_dir / "external-link.txt").symlink_to(external)
    zip_path = project_dir.parent / "project.zip"

    with pytest.raises(PermissionError, match="symlink-backed project entry"):
        intake._write_zip(project_dir, zip_path)

    assert not zip_path.exists()


def test_browser_requests_require_matching_loopback_host_and_origin() -> None:
    handler = object.__new__(intake_server._IntakeHandler)
    handler.server = SimpleNamespace(server_port=8765)
    headers = Message()
    headers["Host"] = "127.0.0.1:8765"
    headers["Origin"] = "http://localhost:8765"
    handler.headers = headers

    with pytest.raises(PermissionError, match="same-origin"):
        handler._validate_local_request()

    headers.replace_header("Origin", "http://127.0.0.1:8765")
    handler._validate_local_request()


def test_browser_posts_require_bounded_json_objects() -> None:
    handler = object.__new__(intake_server._IntakeHandler)
    headers = Message()
    headers["Content-Type"] = "text/plain"
    headers["Content-Length"] = "2"
    handler.headers = headers
    handler.rfile = BytesIO(b"{}")

    with pytest.raises(ValueError, match="application/json"):
        handler._read_json_body()

    headers.replace_header("Content-Type", "application/json")
    headers.replace_header(
        "Content-Length",
        str(intake_server._MAX_JSON_BODY_BYTES + 1),
    )
    with pytest.raises(ValueError, match="between 1 byte"):
        handler._read_json_body()

    headers.replace_header("Content-Length", "2")
    handler.rfile = BytesIO(b"[]")
    with pytest.raises(ValueError, match="must be an object"):
        handler._read_json_body()
