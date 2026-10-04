"""Source-bound rheology figures using native Veusz and shared exact export."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_spec import compile_tts_spec
from sciplot_core.veusz_runtime import (
    needs_veusz_worker_process,
    veusz_worker_environment,
)


def render_tts_figures(spec: dict[str, Any], out: Path, *, resume: bool = False) -> dict[str, Any]:
    """Save editable native figures and export their exact bytes in three formats."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

    if not isinstance(resume, bool):
        raise ValueError("Native creation resume must be a boolean.")
    reject_symlink_path(out)
    compiled = compile_tts_spec(spec)
    return _dispatch({"action": "render", "spec": compiled, "out": str(out.resolve()), "resume": resume})


def audit_tts_document(
    path: Path, figure_spec: dict[str, Any], *, check_presentation: bool = False
) -> dict[str, Any]:
    """Audit the saved native arrays against a compiled immutable figure spec."""
    return _dispatch(
        {
            "action": "audit",
            "path": str(path.resolve()),
            "figure": figure_spec,
            "check_presentation": check_presentation,
        }
    )


def restyle_tts_document(
    path: Path,
    out_path: Path,
    old_figure: dict[str, Any],
    new_figure: dict[str, Any],
    expected_sha256: str,
) -> dict[str, Any]:
    """Create a native candidate containing only requested resolved style changes."""
    return _dispatch(
        {
            "action": "restyle",
            "path": str(path.resolve()),
            "out_path": str(out_path.resolve()),
            "old_figure": old_figure,
            "new_figure": new_figure,
            "expected_sha256": expected_sha256,
        }
    )


def export_tts_document(
    path: Path, out_base: Path, figure_spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Audit and export a saved VSZ without regenerating it after native edits."""
    if out_base.name != path.stem:
        raise ValueError("Export base name must equal the saved document stem.")
    if figure_spec is None:
        sidecar = path.with_suffix(".spec.json")
        figure_spec = json.loads(sidecar.read_text(encoding="utf-8"))["figure"]
    return _dispatch(
        {
            "action": "export",
            "path": str(path.resolve()),
            "out": str(out_base.parent.resolve()),
            "figure": figure_spec,
        }
    )


def export_tts_documents(
    documents: list[tuple[Path, Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Exact-export (VSZ, output base, compiled figure) entries in one worker.

    The caller owns staging and whole-suite publication; this function never
    saves or regenerates native documents and returns receipts in input order.
    """
    if not isinstance(documents, list) or not documents:
        raise ValueError("Batch export requires a nonempty document list.")
    entries = []
    for entry in documents:
        if not isinstance(entry, (tuple, list)) or len(entry) != 3:
            raise ValueError("Each batch export requires path, output base and compiled figure.")
        path, out_base, figure = entry
        if not isinstance(path, Path) or not isinstance(out_base, Path):
            raise ValueError("Batch document and output base must be paths.")
        entries.append({"path": str(path.resolve()), "out_base": str(out_base.resolve()), "figure": figure})
    request = {"action": "export_batch", "documents": entries}
    _validate_export_batch(request)
    return _dispatch(request)["results"]


def _validate_export_batch(request: dict[str, Any]) -> list[tuple[Path, Path, dict[str, Any]]]:
    """Validate the transport and target set before any native side effects."""
    from sciplot_core.studio_core.runtime import _export_suffix

    if set(request) != {"action", "documents"} or request["action"] != "export_batch":
        raise ValueError("Invalid native batch export request.")
    entries = request["documents"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Batch export requires a nonempty document list.")
    documents, paths, stems, targets = [], set(), set(), set()
    target_paths = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "out_base", "figure"}:
            raise ValueError("Invalid native batch export entry.")
        if any(not isinstance(entry[key], str) or not Path(entry[key]).is_absolute()
               for key in ("path", "out_base")):
            raise ValueError("Batch export paths must be absolute strings.")
        path, out_base = Path(entry["path"]).resolve(), Path(entry["out_base"]).resolve()
        figure = entry["figure"]
        if (not isinstance(figure, dict) or figure.get("id") != path.stem
                or not isinstance(figure.get("panels"), list) or not figure["panels"]
                or any(not isinstance(panel, dict) for panel in figure["panels"])):
            raise ValueError("Batch export requires a document-bound compiled figure.")
        if path.suffix.lower() != ".vsz" or not path.is_file() or out_base.name != path.stem:
            raise ValueError("Batch export requires a saved VSZ and matching output base stem.")
        path_key, stem_key = str(path).casefold(), path.stem.casefold()
        if path_key in paths or stem_key in stems:
            raise ValueError("Batch export document paths and stems must be unique.")
        paths.add(path_key)
        stems.add(stem_key)
        suffixes = [_export_suffix(fmt)[0] for fmt in ("pdf", "tiff_300", "png_300")]
        for suffix in [*suffixes, ".native-audit.json"]:
            target = out_base.parent / f"{out_base.name}{suffix}"
            target_key = str(target.resolve()).casefold()
            if target.is_symlink() or target_key in targets:
                raise ValueError("Batch export targets must be unique ordinary files.")
            targets.add(target_key)
            target_paths.append(target)
        documents.append((path, out_base.parent, figure))
    if paths & targets:
        raise ValueError("Batch export targets must not replace saved documents.")
    input_identities = set()
    for path, _, _ in documents:
        stat = path.stat()
        input_identities.add((stat.st_dev, stat.st_ino))
    target_identities = set()
    for target in target_paths:
        if target.exists():
            stat = target.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity in input_identities:
                raise ValueError("Batch export targets must not hard-link saved documents.")
            if identity in target_identities:
                raise ValueError("Batch export targets must not hard-link each other.")
            target_identities.add(identity)
    return documents


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    if not needs_veusz_worker_process():
        return _run_native(request)
    with tempfile.TemporaryDirectory(prefix="sciplot-tts-native-") as temporary:
        request_path = Path(temporary) / "request.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False), encoding="utf-8"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.rheology_tts_render",
                "--worker",
                str(request_path),
            ],
            env=veusz_worker_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            failure = RuntimeError(f"Native TTS figure operation failed:\n{result.stderr}")
            try:
                evidence = json.loads(result.stdout)
            except (TypeError, ValueError):
                evidence = None
            if (isinstance(evidence, dict) and set(evidence) == {"kind", "version", "native_reason_code"}
                    and evidence["kind"] == "sciplot_tts_native_failure" and type(evidence["version"]) is int
                    and evidence["version"] == 1 and evidence["native_reason_code"] == "project_busy"):
                failure.native_reason_code = "project_busy"
            raise failure
        return json.loads(result.stdout)


def _worker_result(request: dict[str, Any]) -> dict[str, Any]:
    """Preserve worker exceptions and expose only a closed, private busy marker."""
    try:
        return _run_native(request)
    except Exception as exc:
        if getattr(exc, "reason_code", None) == "project_busy":
            print(json.dumps({"kind": "sciplot_tts_native_failure", "version": 1,
                              "native_reason_code": "project_busy"}))
        raise


def _run_native(request: dict[str, Any]) -> dict[str, Any]:
    action = request.get("action")
    batch = _validate_export_batch(request) if action == "export_batch" else None
    if action not in {"audit", "export", "export_batch", "restyle", "render"}:
        raise ValueError("Unknown native TTS operation.")
    from sciplot_core.studio_core.runtime import _ensure_veusz_on_path

    _ensure_veusz_on_path()
    from sciplot_core.studio_core.qt_compat import (
        ensure_veusz_loader_compat,
        ensure_veusz_qsettings_compat,
    )

    ensure_veusz_qsettings_compat()
    ensure_veusz_loader_compat()
    from veusz import dataimport, widgets

    _ = dataimport, widgets
    from PyQt6 import QtWidgets
    from sciplot_core.rheology_tts_native import audit_native_figure

    existing = QtWidgets.QApplication.instance()
    app = existing or QtWidgets.QApplication([])
    try:
        if batch is not None:
            return {"status": "completed", "results": _export_batch(batch)}
        if action == "audit":
            path = Path(request["path"])
            before = file_sha256(path)
            audit = audit_native_figure(
                path,
                request["figure"],
                check_presentation=request.get("check_presentation", False),
            )
            if before != file_sha256(path):
                raise ValueError("Saved document changed during native numeric audit.")
            return {**audit, "document": str(path), "document_sha256": before}
        if action == "export":
            return _export(
                Path(request["path"]), Path(request["out"]), request["figure"]
            )
        if action == "restyle":
            from sciplot_core.rheology_tts_native_edit import restyle_native_document

            return restyle_native_document(
                Path(request["path"]),
                Path(request["out_path"]),
                request["old_figure"],
                request["new_figure"],
                request["expected_sha256"],
            )
        if action != "render":
            raise ValueError("Unknown native TTS operation.")
        from sciplot_core.rheology_tts_render_creation import render_native_creation

        return render_native_creation(request["spec"], Path(request["out"]),
                                      resume=request.get("resume", False), export_figure=_export)
    finally:
        if existing is None:
            app.quit()


def _export_batch(documents: list[tuple[Path, Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    from sciplot_core.rheology_tts_native import audit_native_figure

    baseline = {path: file_sha256(path) for path, _, _ in documents}

    def check_documents() -> None:
        for path, digest in baseline.items():
            if file_sha256(path) != digest:
                raise ValueError(f"Saved document changed during native batch export: {path}")

    # No output is created until every saved document has passed the same audit.
    for path, _, figure in documents:
        audit_native_figure(path, figure, check_presentation=False)
    check_documents()
    results = []
    for path, out, figure in documents:
        result = _export(path, out, figure)
        if result["document_sha256"] != baseline[path]:
            raise ValueError(f"Native batch export revision changed: {path}")
        results.append(result)
    check_documents()
    return results


def _export(
    path: Path, out: Path, figure: dict[str, Any], *, check_presentation: bool = False
) -> dict[str, Any]:
    from sciplot_core.rheology_tts_native import audit_native_figure
    from sciplot_core.studio_core.export_execution import export_studio_document

    before = file_sha256(path)
    audit = audit_native_figure(path, figure, check_presentation=check_presentation)
    if file_sha256(path) != before:
        raise ValueError("Saved document changed during native numeric audit.")
    result = export_studio_document(
        path, formats=["pdf", "tiff_300", "png_300"], output_dir=out
    )
    if result["document_sha256"] != before:
        raise ValueError("Native document changed between audit and export.")
    audit["document"] = str(path)
    audit["document_sha256"] = before
    audit_path = out / f"{path.stem}.native-audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {**result, "native_audit": audit, "native_audit_path": str(audit_path)}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker":
        raise SystemExit("Internal native worker; use the public rheology tts command.")
    print(
        json.dumps(
            _worker_result(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
        )
    )
