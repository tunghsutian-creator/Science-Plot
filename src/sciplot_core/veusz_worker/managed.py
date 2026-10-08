"""Compile/audit complete PlotIR using fresh native documents, never legacy state."""

from contextlib import contextmanager
from importlib import import_module
import json
from pathlib import Path
from typing import Any, Iterator

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed_audit import compare_native, native_state, content_hash, scientific_audit
from sciplot_core.plot_backends.managed_plan import apply_plan, validate_capabilities
from sciplot_core.veusz_worker.document_edit import loaded_native_document, _preview


def _read_ir(path: Path) -> dict[str, Any]:
    from sciplot_core.plot_ir import validate_ir

    ir = json.loads(path.read_text(encoding="utf-8"))
    validated = validate_ir(ir)
    validate_capabilities(validated)
    return validated


@contextmanager
def fresh_document(ir: dict[str, Any]) -> Iterator[Any]:
    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
    from sciplot_core.studio_core.veusz_numeric_persistence import ensure_veusz_numeric_precision
    from sciplot_core.studio_core.veusz_line_joins import ensure_veusz_line_joins

    ensure_veusz_runtime_path()
    ensure_veusz_loader_compat()
    from PyQt6.QtWidgets import QApplication
    import_module("veusz.dataimport")
    import_module("veusz.widgets")
    document = import_module("veusz.document")
    ensure_veusz_numeric_precision()
    ensure_veusz_line_joins()
    existing = QApplication.instance()
    app = existing or QApplication([])
    try:
        loaded = document.Document()
        loaded._sciplot_write_full_precision = True
        apply_plan(document.CommandInterface(loaded), ir)
        yield loaded
    finally:
        if existing is None:
            app.quit()


def compile_plot_ir(ir_path: Path, document: Path, preview: Path) -> dict[str, Any]:
    ir = _read_ir(ir_path)
    if document.exists():
        raise ValueError("Managed compilation requires a new artifact path; existing native bytes are never replaced.")
    document.parent.mkdir(parents=True, exist_ok=True)
    with fresh_document(ir) as expected:
        import_module("veusz.document").CommandInterface(expected).Save(str(document))
        expected_hash = content_hash(native_state(expected))
    result = inspect_plot_ir(ir_path, document)
    if result["status"] != "unchanged" or result["scientific_audit"]["status"] != "passed":
        raise ValueError(f"Saved managed artifact failed native fidelity: {result}")
    if result.get("publication_qa", {}).get("status", "passed") != "passed":
        raise ValueError(f"Managed Figure publication QA failed: {result['publication_qa']}")
    audited_hash = result["document_sha256"]
    if file_sha256(document) != audited_hash:
        raise ValueError("Managed native document changed after its compilation audit.")
    with loaded_native_document(document) as loaded:
        image = _preview(loaded, preview)
    if file_sha256(document) != audited_hash:
        raise ValueError("Managed native document changed between its compilation audit and preview.")
    return {"kind": "sciplot_managed_compile", "document": str(document),
            "document_sha256": audited_hash, "ir_path": str(ir_path),
            "ir_hash": ir["ir_hash"], "scientific_hash": ir["scientific_hash"],
            "native_state_hash": expected_hash, "scientific_audit": result["scientific_audit"],
            "preview": image, **({"publication_qa": result["publication_qa"]} if "publication_qa" in result else {})}


def inspect_plot_ir(ir_path: Path, document: Path) -> dict[str, Any]:
    ir = _read_ir(ir_path)
    before = file_sha256(document)
    qa: dict[str, Any] | None = None
    with fresh_document(ir) as expected, loaded_native_document(document) as actual:
        comparison = compare_native(ir, expected, actual)
        try:
            audit = scientific_audit(ir, actual)
        except (ValueError, KeyError) as exc:
            audit = {"status": "failed", "reason": str(exc)}
        if ir.get("schema_version") == 2:
            from sciplot_core.plot_backends.figure_qa import native_publication_qa
            qa = native_publication_qa(ir, actual)
    if file_sha256(document) != before:
        raise ValueError("Managed native document changed during inspection.")
    return {"kind": "sciplot_external_mutation", **comparison, "scientific_audit": audit,
            "document": str(document), "document_sha256": before, "ir_hash": ir["ir_hash"],
            **({"publication_qa": qa} if qa is not None else {})}
