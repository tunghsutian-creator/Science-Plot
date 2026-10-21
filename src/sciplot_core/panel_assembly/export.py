"""Deterministic mixed-panel PDF/TIFF packages with exclusive atomic publication."""

from __future__ import annotations

import io
from importlib import import_module
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.veusz_runtime import veusz_worker_environment

from .errors import AssemblyError
from .model import resolve_document, validate_document
from .sources import assert_source_current

POINTS_PER_MM = 72.0 / 25.4


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _scientific(source: dict[str, Any], folder: Path, width: float, height: float) -> dict[str, Any]:
    folder.mkdir(parents=True)
    request = folder / "native-request.json"
    # Qt PDF media boxes use whole points. Reflow the native canvas to the
    # largest whole-point size within its allocated mm budget, before painting.
    native_size = [math.floor(value * POINTS_PER_MM + 1e-8) / POINTS_PER_MM for value in (width, height)]
    if min(native_size) <= 0:
        raise AssemblyError("assembly_native_size_invalid", "The allocated scientific panel is smaller than one native PDF point.")
    _json(request, {"source": source, "output": str(folder), "width_mm": native_size[0], "height_mm": native_size[1]})
    try:
        result = subprocess.run([sys.executable, "-m", "sciplot_core.panel_assembly.native", str(request)],
                                env=veusz_worker_environment(), capture_output=True, text=True, timeout=240, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AssemblyError("assembly_native_timeout", "Native target-size panel export exceeded its bounded time.") from exc
    if result.returncode:
        try:
            error = json.loads(result.stdout)["error"]
        except (ValueError, KeyError, TypeError):
            error = None
        if (isinstance(error, dict) and isinstance(error.get("code"), str)
                and error["code"].startswith("assembly_") and isinstance(error.get("message"), str)):
            raw_issues = error.get("issues", [])
            issues = raw_issues if isinstance(raw_issues, list) and all(isinstance(item, dict) for item in raw_issues) else []
            raise AssemblyError(error["code"], error["message"], issues=issues)
        raise AssemblyError("assembly_native_export_failed", f"Native physical panel export failed: {result.stderr[-3000:]}")
    try:
        decoded = json.loads(result.stdout)
        if not isinstance(decoded, dict):
            raise ValueError("Native panel evidence must be an object.")
        evidence: dict[str, Any] = decoded
        if evidence["status"] != "passed" or evidence["publication_qa"]["status"] != "passed":
            raise ValueError("Target-size native evidence did not pass.")
    except (ValueError, KeyError) as exc:
        raise AssemblyError("assembly_native_export_failed", "Native panel returned invalid export evidence.") from exc
    request.unlink()
    evidence["native_reflow_mm"] = native_size
    return evidence


def _source_package(source: dict[str, Any], folder: Path) -> list[dict[str, Any]]:
    """Retain original byte snapshots as well as portable native imports."""
    if source["kind"] == "image":
        files = [Path(source["path"])]
        expected = {source["path"]: source["binding"]["snapshot"]["sha256"]}
    elif source["kind"] == "project":
        selection = source["binding"]["selection"]
        files = [Path(path) for path in selection["source_files"]]
        files += [Path(selection["project"]) / "plot_request.json"]
        expected = {**selection["source_files"],
                    str(Path(selection["project"]) / "plot_request.json"): selection["version"]["request_sha256"]}
    else:
        # Include frozen canonical history/content and actual raw inputs/scripts.
        # Executable runtimes remain external byte-pinned dependencies.
        from .sources import managed_head

        head = managed_head(Path(source["project"]), source["plot_id"])
        executables = {item["executable"] for item in head["document"]["scientific"]["provenance"]["managed"].get("executors", {}).values()}
        files = [Path(item["path"]) for item in source["binding"]["files"] if item["path"] not in executables]
        expected = {item["path"]: item["sha256"] for item in source["binding"]["files"]}
    folder.mkdir()
    records = []
    for index, path in enumerate(sorted(set(files)), 1):
        snapshot = stable_file_snapshot(path, label="assembly package source")
        if snapshot["sha256"] != expected[str(path)]:
            raise AssemblyError("assembly_source_stale", "A packaged source differs from the frozen selected bytes.")
        name = f"{index:03d}_{snapshot['sha256'][:16]}{path.suffix.lower()}"
        target = folder / name
        target.write_bytes(snapshot["bytes"])
        _assert_snapshot_current(snapshot, label="assembly package source")
        records.append({"source": str(path), "relative_path": "sources/" + name, "sha256": snapshot["sha256"]})
    _json(folder / "index.json", records)
    return records


def _fit(rectangle: list[float], width: float, height: float) -> list[float]:
    x, y, w, h = rectangle
    scale = min(w / width, h / height)
    return [x + (w - width * scale) / 2, y + (h - height * scale) / 2, width * scale, height * scale]


def _rect(rectangle: list[float]) -> Any:
    pymupdf: Any = import_module("pymupdf")

    x, y, width, height = rectangle
    return pymupdf.Rect(x, y, x + width, y + height) * POINTS_PER_MM


def _place_image(page: Any, panel: dict[str, Any], source: dict[str, Any], raw: bytes) -> dict[str, Any]:
    pymupdf: Any = import_module("pymupdf")

    crop = panel["crop"] or [0., 0., 1., 1.]
    if source["binding"]["media_type"] == "application/pdf":
        with pymupdf.open(stream=raw, filetype="pdf") as diagram:
            bounds = diagram[0].rect
            left, top, right, bottom = crop
            clip = pymupdf.Rect(bounds.x0 + left * bounds.width, bounds.y0 + top * bounds.height,
                                bounds.x0 + right * bounds.width, bounds.y0 + bottom * bounds.height)
            fitted = _fit(panel["content_mm"], clip.width, clip.height)
            page.show_pdf_page(_rect(fitted), diagram, 0, clip=clip, keep_proportion=True)
    else:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(raw)) as image:
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
            box = (math.floor(crop[0] * width), math.floor(crop[1] * height),
                   math.ceil(crop[2] * width), math.ceil(crop[3] * height))
            cropped = oriented.crop(box)
            stream = io.BytesIO()
            cropped.save(stream, format="PNG")
            fitted = _fit(panel["content_mm"], *cropped.size)
            page.insert_image(_rect(fitted), stream=stream.getvalue(), keep_proportion=True)
    return {"status": "passed", "authority": "image_bytes", "crop": crop, "placement_mm": fitted,
            "source_sha256": source["binding"]["snapshot"]["sha256"], "resampling_of_source": False}


def _place_scientific(page: Any, pdf_path: Path, content: list[float], cell: list[float]) -> dict[str, Any]:
    pymupdf: Any = import_module("pymupdf")

    with pymupdf.open(pdf_path) as native:
        if len(native) != 1:
            raise AssemblyError("assembly_native_size_invalid", "A scientific panel must export exactly one PDF page.")
        size = [native[0].rect.width / POINTS_PER_MM, native[0].rect.height / POINTS_PER_MM]
        target = [math.floor(value * POINTS_PER_MM + 1e-8) / POINTS_PER_MM for value in content[2:]]
        slack = [budget - actual for budget, actual in zip(content[2:], size, strict=True)]
        if (any(abs(actual - requested) > 1e-4 for actual, requested in zip(size, target, strict=True))
                or any(value < -1e-4 or value * POINTS_PER_MM > 1.0001 for value in slack)):
            raise AssemblyError("assembly_native_size_invalid", "Native PDF physical size differs from the requested reflow size.")
        # Place at the actual exported size: show_pdf_page therefore uses a 1:1
        # physical mapping, never a fitted/scaled scientific panel.
        placement = [content[0], content[1], *size]
        if (placement[0] < cell[0] or placement[1] < cell[1]
                or placement[0] + placement[2] > cell[0] + cell[2]
                or placement[1] + placement[3] > cell[1] + cell[3]):
            raise AssemblyError("assembly_native_size_invalid", "The actual native PDF page exceeds its non-overlapping assembly cell.")
        page.show_pdf_page(_rect(placement), native, 0, keep_proportion=True)
    return {"allocated_budget_mm": content[2:], "native_reflow_mm": target, "actual_mm": size,
            "placement_mm": placement, "scale": 1.0, "rounding_slack_mm": slack,
            "quantization_policy": "native_canvas_floor_to_whole_pdf_point", "maximum_underfill_pt": 1.0,
            "actual_page_within_content": True, "actual_page_within_cell": True}


def _label(page: Any, label: str, position: list[float] | None, cell: list[float], content: list[float]) -> dict[str, Any]:
    pymupdf: Any = import_module("pymupdf")
    from sciplot_core.rendering_contract import contract_value

    if not label:
        return {"visible": False, "text": ""}
    if position is None or any(not 32 <= ord(character) <= 126 for character in label):
        raise AssemblyError("assembly_label_unsupported", "Outer panel labels require printable ASCII characters.")
    family = contract_value("font.family")
    size = float(contract_value("panel_label.font_size_pt"))
    weight = contract_value("panel_label.weight")
    fontname = "hebo" if weight == "bold" else "helv"
    font = pymupdf.Font(fontname)
    width = font.text_length(label, fontsize=size)
    x, y = (value * POINTS_PER_MM for value in position)
    if width > (cell[0] + cell[2] - position[0]) * POINTS_PER_MM:
        raise AssemblyError("assembly_label_clipping", "Panel label exceeds its reserved physical cell width.")
    # The solver anchor is the vertical center of the six-mm label band.
    baseline = y + (font.ascender + font.descender) * size / 2
    page.insert_text((x, baseline), label, fontname=fontname, fontsize=size, color=(0, 0, 0))
    spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block
             for line in block["lines"] for span in line["spans"]
             if span["text"] == label and abs(span["size"] - size) < 1e-4
             and abs(span["origin"][0] - x) < 1e-3 and abs(span["origin"][1] - baseline) < 1e-3]
    if len(spans) != 1:
        raise AssemblyError("assembly_label_qa_failed", "The exported panel label has no unique measured PDF text bounds.")
    bounds = [float(value) / POINTS_PER_MM for value in spans[0]["bbox"]]
    band = [cell[0], cell[1], cell[2], min(2 * (position[1] - cell[1]), content[1] - cell[1])]
    if (bounds[0] < band[0] - 1e-4 or bounds[1] < band[1] - 1e-4
            or bounds[2] > band[0] + band[2] + 1e-4 or bounds[3] > band[1] + band[3] + 1e-4):
        raise AssemblyError("assembly_label_clipping", "The measured PDF panel label exceeds its reserved physical band.")
    return {"visible": True, "text": label, "font_size_pt": size, "font_weight": weight,
            "requested_font_family": family, "actual_font": spans[0]["font"],
            "font_policy": "Explicit PDF Base14 Helvetica fallback for outer labels only.",
            "bounds_mm": [bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]],
            "allowed_band_mm": band, "anchor_mm": position, "native_text_scaled": False}


def export_document(document: dict[str, Any], out: str | Path, *, dpi: int = 300) -> dict[str, Any]:
    """Export a new complete package; failed staging never replaces an output."""
    if type(dpi) is not int or not 72 <= dpi <= 1200:
        raise AssemblyError("assembly_dpi_invalid", "Use an integer TIFF resolution from 72 to 1200 dpi.")
    validated = validate_document(document)
    solved = resolve_document(validated)
    if not solved["panels"]:
        raise AssemblyError("assembly_empty", "Add at least one panel before exporting.")
    destination = Path(out).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise AssemblyError("assembly_output_exists", "The output destination already exists; choose a new directory.")
    for panel in validated["panels"]:
        assert_source_current(panel["source"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.assembly-", dir=destination.parent))
    try:
        pymupdf: Any = import_module("pymupdf")
        from PIL import Image

        receipts = []
        originals = {panel["id"]: panel for panel in validated["panels"]}
        with pymupdf.open() as composite:
            composite.set_metadata({"producer": "SciPlot panel assembly", "creator": "SciPlot", "title": "Panel assembly"})
            page = composite.new_page(width=solved["width_mm"] * POINTS_PER_MM, height=solved["height_mm"] * POINTS_PER_MM)
            page.draw_rect(page.rect, color=None, fill=(1, 1, 1), overlay=False)
            (stage / "panels").mkdir()
            for index, placement in enumerate(solved["panels"], 1):
                panel = {**originals[placement["id"]], **placement}
                source = panel["source"]
                folder = stage / "panels" / f"{index:03d}"
                folder.mkdir()
                assert_source_current(source)
                if source["kind"] == "image":
                    snapshot = stable_file_snapshot(Path(source["path"]), label="assembly image composition")
                    if snapshot["sha256"] != source["binding"]["snapshot"]["sha256"]:
                        raise AssemblyError("assembly_source_stale", "The image changed before composition.")
                    evidence = _place_image(page, panel, source, snapshot["bytes"])
                    _assert_snapshot_current(snapshot, label="assembly image composition")
                else:
                    try:
                        evidence = _scientific(source, folder / "native", *panel["content_mm"][2:])
                        evidence["physical_size"] = _place_scientific(page, folder / "native/panel.pdf", panel["content_mm"], panel["cell_mm"])
                    except AssemblyError as exc:
                        issues = [{**issue, "panel_id": panel["id"], "panel_label": panel["label"]} for issue in exc.issues]
                        raise AssemblyError(exc.code, f"Panel {panel['label'] or panel['id']} ({panel['id']}): {exc}", issues=issues) from exc
                records = _source_package(source, folder / "sources")
                evidence["panel_label"] = _label(page, panel["label"], panel["label_mm"], panel["cell_mm"], panel["content_mm"])
                assert_source_current(source)
                receipts.append({"id": panel["id"], "label": panel["label"], "cell_mm": panel["cell_mm"],
                                 "content_mm": panel["content_mm"], "package_path": f"panels/{index:03d}",
                                 "source_package": records, "evidence": evidence})
            composite.save(stage / "assembly.pdf", garbage=4, deflate=True, no_new_id=True)
        with pymupdf.open(stage / "assembly.pdf") as pdf:
            pixmap = pdf[0].get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            image.save(stage / "assembly.tiff", compression="tiff_lzw", dpi=(dpi, dpi))
            pixel_size = list(image.size)
        _json(stage / "layout.json", validated)
        for panel in validated["panels"]:
            assert_source_current(panel["source"])
        receipt = {"kind": "sciplot_panel_assembly_export", "version": 1, "status": "complete",
                   "dpi": dpi, "width_mm": solved["width_mm"], "height_mm": solved["height_mm"],
                   "tiff_pixels": pixel_size, "panels": receipts, "source_currentness": "passed",
                   "tiff_physical_size_mm": [value / dpi * 25.4 for value in pixel_size],
                   "layout_source_policy": "Frozen references require their original current source roots; replace explicitly after relocation.",
                   "native_editing_policy": "Original and reflowed portable VSZ/import packages support relocated manual native editing.",
                   "journal_acceptance_evaluated": False, "font_portability_evaluated": False}
        # Strip private staging names from human-facing evidence; byte content
        # seals remain separate from native source-state and science identities.
        receipt = json.loads(json.dumps(receipt).replace(str(stage), str(destination)))
        receipt["files"] = {str(path.relative_to(stage)): file_sha256(path) for path in sorted(stage.rglob("*")) if path.is_file()}
        _json(stage / "manifest.json", receipt)
        install_new_delivery(stage, destination)
        return {**receipt, "out": str(destination), "pdf": str(destination / "assembly.pdf"),
                "tiff": str(destination / "assembly.tiff"), "layout": str(destination / "layout.json"),
                "manifest": str(destination / "manifest.json")}
    except AssemblyError:
        raise
    except Exception as exc:
        raise AssemblyError("assembly_export_failed", f"Assembly export failed: {exc}") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage)
