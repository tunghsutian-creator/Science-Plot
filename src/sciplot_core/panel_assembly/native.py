"""Native physical panel reflow, scientific equality and actual text bounds QA."""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import io
import json
from pathlib import Path
from typing import Any
from weakref import ref

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_backends.managed_audit import content_hash, native_state
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.studio_core.persistence import atomic_save_veusz_document
from sciplot_core.task_paper_native import save_portable_copy
from sciplot_core.veusz_worker.document_edit import loaded_native_document

from .errors import AssemblyError


def _nonvisual_payload(loaded: Any) -> str:
    """Close serializer/import parameters and compatibility beyond widget values."""
    definitions = io.StringIO()
    loaded.evaluate.saveCustomDefinitions(definitions)
    datasets = {}
    for name, dataset in sorted(loaded.data.items()):
        saved = io.StringIO()
        dataset.saveToFile(saved, name)
        linked = getattr(dataset, "linked", None)
        datasets[name] = {"serialized": saved.getvalue(),
                          "linked_parameters": vars(linked.params) if linked is not None else None}
    return canonical_json_sha256({"definitions": definitions.getvalue(), "datasets": datasets,
                                 "compatlevel": loaded.compatlevel}, allow_nan=False)


def _legacy_shape(loaded: Any) -> tuple[Any, list[Any]]:
    pages = loaded.getVisiblePages()
    if list(pages) != [0] or len(loaded.basewidget.children) != 1:
        raise AssemblyError("assembly_reflow_unsupported", "Legacy physical reflow supports one visible native page.")
    page = loaded.getPage(0)
    graphs = [child for child in page.children if child.typename == "graph"]
    backgrounds = [child for child in page.children if child.typename == "rect"
                   and child.name in {"background", "page_export_background"} and child.settings.positioning == "relative"
                   and list(child.settings.xPos) == [0.5] and list(child.settings.yPos) == [0.5]
                   and list(child.settings.width) == [1.0] and list(child.settings.height) == [1.0]
                   and child.settings.clip and child.settings.Border.hide]
    if len(graphs) != 1 or len(page.children) != 1 + len(backgrounds):
        raise AssemblyError("assembly_reflow_unsupported", "Legacy reflow requires one direct Cartesian graph and an optional full-page background.")
    graph = graphs[0]
    allowed = {"axis", "xy", "key", "label"}
    if any(child.typename not in allowed or child.children for child in graph.children):
        raise AssemblyError("assembly_reflow_unsupported", "This legacy graph contains unsupported native geometry.")
    if graph.settings.aspect != "Auto":
        raise AssemblyError("assembly_reflow_unsupported", "Fixed native graph aspect needs an explicit reflow contract.")
    # Native absolute margins reflow the frame without scaling scientific text.
    import re

    for side in ("left", "right", "top", "bottom"):
        value = graph.settings.get(side + "Margin").get()
        if not isinstance(value, str) or not re.fullmatch(r"[+]?\d+(?:\.\d+)?(?:mm|cm|pt|in)", value):
            raise AssemblyError("assembly_reflow_unsupported", "Legacy graph margins must use explicit physical units.")
    return graph, [child for child in graph.children if child.typename == "axis"]


def _legacy_qa(loaded: Any) -> tuple[dict[str, Any], dict[str, list[float]]]:
    """Reuse physical QA, measuring all actual native text before page clipping."""
    from sciplot_core.plot_layout import native_publication_qa

    graph, axes = _legacy_shape(loaded)
    utils = import_module("veusz.utils")
    original = utils.Renderer
    observations: list[dict[str, Any]] = []
    renderers: list[Any] = []
    dpi = 150

    def factory(*args: Any, **kwargs: Any) -> Any:
        renderer = original(*args, **kwargs)
        renderers.append(renderer)
        widget = getattr(args[0], "widget", None)
        renderer_ref, method = ref(renderer), type(renderer).render

        def measured() -> Any:
            live = renderer_ref()
            if live is None:
                raise ValueError("Native renderer expired during assembly QA.")
            result = method(live)
            if widget is not None:
                bounds = live.getBounds()
                factor = 25.4 / dpi
                role = {"axis": "axis_label", "key": "legend", "label": "annotation"}.get(widget.typename)
                if role is None:
                    raise AssemblyError("assembly_reflow_unsupported", "An unsupported native object rendered scientific text.")
                observations.append({"semantic_id": str(widget.path), "role": role, "view_id": "panel",
                    "bounds_mm": [float(bounds[0]) * factor, float(bounds[1]) * factor,
                                  float(bounds[2] - bounds[0]) * factor, float(bounds[3] - bounds[1]) * factor]})
            return result

        renderer.render = measured
        return renderer

    helper = None
    try:
        utils.Renderer = factory
        size = loaded.pageSize(0, dpi=(dpi, dpi), integer=False)
        helper = import_module("veusz.document").PaintHelper(loaded, size, dpi=(dpi, dpi))
        loaded.paintTo(helper, 0)
        states = [state for (widget, layer), state in helper.states.items() if widget is graph and layer == 0]
        if len(states) != 1:
            raise ValueError("No unique native graph bounds were measured.")
        x0, y0, x1, y1 = states[0].bounds
        factor = 25.4 / dpi
        plot = [x0 * factor, y0 * factor, (x1 - x0) * factor, (y1 - y0) * factor]
        width, height = float(size[0]) * factor, float(size[1]) * factor
        layout = {"width_mm": width, "height_mm": height,
                  "panels": [{"view_id": "panel", "row": 0, "column": 0,
                              "cell_mm": [0., 0., width, height], "plot_mm": plot}]}
        expected = [str(axis.path) for axis in axes if not axis.settings.hide
                    and (not axis.settings.Label.hide and axis.settings.label or not axis.settings.TickLabels.hide)]
        expected += [str(child.path) for child in graph.children
                     if child.typename in {"key", "label"} and not child.settings.hide]
        report = native_publication_qa(layout, observations, expected_text_ids=expected)
        # Whole key frames include their sample strokes/padding, beyond text.
        ControlKey = import_module("veusz.widgets.key").ControlKey
        for child in graph.children:
            if child.typename != "key" or child.settings.hide:
                continue
            controls = [control for control in helper.getControlGraph(child) or [] if isinstance(control, ControlKey)]
            if len(controls) != 1:
                raise ValueError("No unique complete native legend frame was measured.")
            key = controls[0]
            x, y = (value * factor for value in key.posn)
            w, h = (value * factor for value in key.dims)
            if x < -0.3 or y < -0.3 or x + w > width + 0.3 or y + h > height + 0.3:
                report["hard"].append({"code": "legend_frame_clipping", "semantic_id": str(child.path)})
        report.update(status="failed" if report["hard"] else "passed",
                      observations=observations, renderer="veusz.native-text-bounds", dpi=dpi)
        ranges = {str(axis.path): [float(value) for value in axis.plottedrange] for axis in axes}
        return report, ranges
    finally:
        utils.Renderer = original
        renderers.clear()
        if helper is not None:
            helper.states.clear()
            helper.rootstate = None


def reflow_legacy(source: dict[str, Any], output: Path, width_mm: float, height_mm: float) -> dict[str, Any]:
    from sciplot_core.veusz_worker.spec_audit import audit_spec_data

    selection = source["binding"]["selection"]
    selected, spec = Path(selection["document"]), Path(selection["spec"])
    for key, path, name in (("document_sha256", selected, "source.vsz"), ("spec_sha256", spec, "source.spec.json")):
        snapshot = stable_file_snapshot(path, label="assembly legacy authority")
        if snapshot["sha256"] != selection["version"][key]:
            raise AssemblyError("assembly_source_stale", "The native authority changed before it could be frozen for export.")
        (output / name).write_bytes(snapshot["bytes"])
        _assert_snapshot_current(snapshot, label="assembly legacy authority")
    spec = output / "source.spec.json"
    before_audit = audit_spec_data(selected, spec, check_presentation=False)
    original = output / "original/document.vsz"
    portable = save_portable_copy(selected, original, imports=output / "original/imports")
    if portable["original_sha256"] != selection["version"]["document_sha256"]:
        raise AssemblyError("assembly_source_stale", "Portable Save read a different selected native version.")
    target = output / "reflowed/document.vsz"
    copied = save_portable_copy(original, target, imports=output / "reflowed/imports")
    with loaded_native_document(target) as loaded:
        _legacy_shape(loaded)
        _, ranges_before = _legacy_qa(loaded)
        expected = native_state(loaded)
        payload_hash = _nonvisual_payload(loaded)
        page = loaded.getPage(0)
        for widget in (loaded.basewidget, page):
            for field, value in (("width", width_mm), ("height", height_mm)):
                widget.settings.get(field).set(f"{value:.12g}mm")
                expected["widgets"][str(widget.path)]["settings"][field] = f"{value:.12g}mm"
        after = native_state(loaded)
        # Veusz's page stylesheet dimensions are references to the root canvas.
        # Their resolved values follow that native setting while the original
        # reference bindings themselves remain part of the equality guard.
        for field in ("width", "height"):
            path = "StyleSheet/page/" + field
            setting = loaded.basewidget.settings.get("StyleSheet").get("page").get(field)
            if setting.isReference() and setting.getReference().getPaths() == ["/" + field]:
                expected["widgets"]["/"]["settings"][path] = after["widgets"]["/"]["settings"][path]
        if expected != after:
            raise ValueError("Native resize changed state outside the physical page dimensions.")
        qa, ranges_after = _legacy_qa(loaded)
        if ranges_before != ranges_after:
            raise AssemblyError("assembly_reflow_unsupported", "Target dimensions changed automatic native axis ranges.")
        if qa["status"] != "passed":
            raise AssemblyError("assembly_native_qa_failed", f"Target-size native bounds failed: {qa['hard']}")
        saved = atomic_save_veusz_document(loaded, target)
        if not saved["ready_for_export"]:
            raise ValueError("Reflowed native document could not be securely reopened.")
        state_hash = content_hash(after)
    with loaded_native_document(target) as reopened:
        if content_hash(native_state(reopened)) != state_hash:
            raise ValueError("Native Save changed reflowed scientific or opaque state.")
        if _nonvisual_payload(reopened) != payload_hash:
            raise ValueError("Native Save changed dataset serialization, import parameters or opaque compatibility state.")
        qa, reopened_ranges = _legacy_qa(reopened)
        if qa["status"] != "passed" or reopened_ranges != ranges_before:
            raise ValueError("Reopened target-size native QA failed.")
        import_module("veusz.document").CommandInterface(reopened).Export(str(output / "panel.pdf"), page=[0], pdfdpi=72)
    after_audit = audit_spec_data(target, spec, check_presentation=False)
    science = canonical_json_sha256(before_audit["units"], allow_nan=False)
    if canonical_json_sha256(after_audit["units"], allow_nan=False) != science:
        raise ValueError("Native physical reflow changed scientific dataset evidence.")
    final_portable = {"status": "passed", "portable_sha256": file_sha256(target),
                      "native_state_sha256": state_hash, "reopened_native_state_sha256": state_hash,
                      "imports": copied["imports"], "reflow_input_sha256": copied["original_sha256"]}
    return {"status": "passed", "authority": "saved_vsz", "scientific_hash": science,
            "native_state_hash": state_hash, "nonvisual_payload_sha256": payload_hash,
            "axis_ranges": ranges_before, "publication_qa": qa,
            "portable_original": portable, "portable_reflowed": final_portable,
            "pdf": "panel.pdf", "original": "original/document.vsz", "reflowed": "reflowed/document.vsz"}


def reflow_managed(source: dict[str, Any], output: Path, width_mm: float, height_mm: float) -> dict[str, Any]:
    from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
    from sciplot_core.plot_document import seal_document
    from sciplot_core.plot_engine.content_store import resolve_document_content
    from sciplot_core.plot_engine.managed_state import resolved_ir
    from sciplot_core.plot_ir import compile_document
    from sciplot_core.plot_ir.figure_document import figure_spec, is_figure, store_spec

    from .sources import managed_head

    root = Path(source["project"])
    head = managed_head(root, source["plot_id"])
    document = head["document"]
    original_ir = resolved_ir(root, document)
    candidate = deepcopy(document)
    if is_figure(document):
        spec = figure_spec(document)
        spec["layout"].update(width_mm=width_mm, height_mm=height_mm)
        # House minimum frame height is an explicit physical policy; retaining it
        # can correctly refuse small target cells rather than shrink the frame.
        candidate = store_spec(candidate, spec)
    else:
        candidate["presentation"]["layout"]["dimensions"] = {"width_mm": width_mm, "height_mm": height_mm}
        candidate = seal_document(candidate)
    if candidate["scientific_hash"] != document["scientific_hash"]:
        raise ValueError("Assembly reflow changed the canonical scientific projection.")
    datasets = resolve_document_content(root, document)["scientific"]["provenance"]["datasets"]
    reflowed_ir = compile_document(candidate, datasets)
    if original_ir["datasets"] != reflowed_ir["datasets"]:
        raise ValueError("Assembly reflow changed canonical datasets.")
    compiler = ManagedVeuszCompiler(warm=False)
    try:
        native = Path(head["binding"]["document"])
        if native.exists():
            compiler._require_exact(original_ir, native)
            portable = save_portable_copy(native, output / "original/document.vsz", imports=output / "original/imports")
            (output / "source.vsz").write_bytes(native.read_bytes())
        else:
            built = compiler.compile_ir(original_ir, output / "original")
            portable = {"status": "compiled_from_canonical", "native_state_hash": built["native_state_hash"]}
        built = compiler.compile_ir(reflowed_ir, output / "reflowed")
        exported = compiler.export_ir(reflowed_ir, Path(built["document"]), output / "reflowed/exports")
        qa = exported.get("publication_qa")
        if qa is None:
            with loaded_native_document(Path(built["document"])) as loaded:
                qa, _ranges = _legacy_qa(loaded)
            if qa["status"] != "passed":
                raise AssemblyError("assembly_native_qa_failed", "Managed target-size native text bounds failed.")
        pdf = next(item for item in exported["exports"] if item["format"] == "pdf")
        (output / "panel.pdf").write_bytes(Path(pdf["path"]).read_bytes())
        (output / "canonical-document.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        (output / "reflowed-document.json").write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
        (output / "resolved-datasets.json").write_text(json.dumps(datasets, indent=2) + "\n", encoding="utf-8")
        return {"status": "passed", "authority": "managed_document", "scientific_hash": document["scientific_hash"],
                "source_ir_hash": original_ir["ir_hash"], "reflowed_ir_hash": reflowed_ir["ir_hash"],
                "scientific_audit": exported["scientific_audit"], "publication_qa": qa,
                "portable_original": portable, "native_state_hash": built["native_state_hash"],
                "pdf": "panel.pdf", "original": "original/document.vsz", "reflowed": "reflowed/document.vsz"}
    finally:
        compiler.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    from .sources import assert_source_current

    source, output = request["source"], Path(request["output"])
    assert_source_current(source)
    output.mkdir(parents=True, exist_ok=True)
    operation = reflow_legacy if source["kind"] == "project" else reflow_managed
    try:
        result = operation(source, output, request["width_mm"], request["height_mm"])
        assert_source_current(source)
    except Exception as exc:
        code = exc.code if isinstance(exc, AssemblyError) else "assembly_native_export_failed"
        message = str(exc)
        if getattr(exc, "stderr", None):
            message += "\n" + str(exc.stderr)[-2000:]
        print(json.dumps({"status": "failed", "error": {"code": code, "message": message[-3000:]}}))
        return 2
    result["pdf_sha256"] = file_sha256(output / "panel.pdf")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
