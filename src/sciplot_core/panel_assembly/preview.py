"""Read-only source previews; source selection never establishes export readiness."""

from __future__ import annotations

import io
from importlib import import_module
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.veusz_runtime import veusz_worker_environment

from .errors import AssemblyError
from .sources import assert_source_current, managed_head

MAX_EDGE = 800


def _png(payload: bytes) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(payload)) as image:
        oriented = ImageOps.exif_transpose(image)
        oriented.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        oriented.save(output, format="PNG")
        return output.getvalue()


def _image_preview(source: dict[str, Any]) -> bytes:
    snapshot = stable_file_snapshot(Path(source["path"]), label="assembly image preview")
    if snapshot["sha256"] != source["binding"]["snapshot"]["sha256"]:
        raise AssemblyError("assembly_source_stale", "The selected image changed before preview.")
    if source["binding"]["media_type"] == "application/pdf":
        pymupdf: Any = import_module("pymupdf")

        with pymupdf.open(stream=snapshot["bytes"], filetype="pdf") as pdf:
            scale = min(2.0, MAX_EDGE / max(pdf[0].rect.width, pdf[0].rect.height))
            pixels = pdf[0].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            payload = pixels.tobytes("png")
    else:
        payload = snapshot["bytes"]
    result = _png(payload)
    _assert_snapshot_current(snapshot, label="assembly image preview")
    return result


def render_preview(source: dict[str, Any]) -> bytes:
    """Return a frozen source's PNG bytes (at most 800 px), never QA acceptance.

    Call from a UI worker. Qt image/pixmap construction belongs to its UI owner.
    Scientific sources render in a process main thread and temporary directory;
    no adjacent PDF, original Save, source cache write or target reflow is used.
    """
    try:
        assert_source_current(source)
        if source["kind"] == "image":
            result = _image_preview(source)
        else:
            with TemporaryDirectory(prefix="sciplot-assembly-preview-") as temporary:
                root = Path(temporary)
                request, output = root / "request.json", root / "preview.png"
                request.write_text(json.dumps(source, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                completed = subprocess.run([sys.executable, "-m", "sciplot_core.panel_assembly.preview", str(request), str(output)],
                                           env=veusz_worker_environment(), capture_output=True, text=True,
                                           check=False, timeout=120)
                if completed.returncode:
                    raise AssemblyError("assembly_preview_failed", f"Current source preview failed: {completed.stderr[-2000:]}")
                evidence = json.loads(completed.stdout)
                if (evidence.get("status") != "rendered" or evidence.get("is_export_acceptance") is not False
                        or evidence.get("target_export_readiness") != "not_evaluated"):
                    raise AssemblyError("assembly_preview_failed", "Preview returned invalid display-only evidence.")
                result = _png(output.read_bytes())
        assert_source_current(source)
        return result
    except AssemblyError:
        raise
    except Exception as exc:
        raise AssemblyError("assembly_preview_failed", f"Current source preview is unavailable: {exc}") from exc


def _native_preview(source: dict[str, Any], output: Path) -> dict[str, Any]:
    from sciplot_core.veusz_worker.document_edit import loaded_native_document, _preview

    assert_source_current(source)
    if source["kind"] == "project":
        path = Path(source["binding"]["selection"]["document"])
        with loaded_native_document(path) as loaded:
            preview = _preview(loaded, output)
        authority = "saved_vsz"
    elif source["kind"] == "managed":
        from sciplot_core.plot_backends.managed_audit import scientific_audit
        from sciplot_core.plot_engine.managed_state import resolved_ir
        from sciplot_core.veusz_worker.managed import fresh_document

        root = Path(source["project"])
        head = managed_head(root, source["plot_id"])
        ir = resolved_ir(root, head["document"])
        # Reuse the existing semantic compiler/lowering in memory. In
        # particular, source-native text clipping may still be visible here;
        # target publication QA is exclusively the export owner's decision.
        with fresh_document(ir) as loaded:
            scientific_audit(ir, loaded)
            preview = _preview(loaded, output)
        authority = "managed_document"
    else:
        raise AssemblyError("assembly_preview_failed", "The native preview worker requires a scientific source.")
    assert_source_current(source)
    return {"status": "rendered", "authority": authority, "preview": preview,
            "is_export_acceptance": False, "target_export_readiness": "not_evaluated"}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    print(json.dumps(_native_preview(source, args.output), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
