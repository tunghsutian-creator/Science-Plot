"""Extract a reviewable rendering contract from the established policy owners.

This is a development-time operation. Compilation reads the sealed resource;
it never reinterprets current legacy rendering code as canonical plot state.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

HOUSE_CONTRACT_ID = "sciplot-house-style-v1"
POLICY = "src/sciplot_core/policy/plot_contract.json"
FRAME = "src/sciplot_core/policy/frame_export.py"
IDENTITY = "src/sciplot_core/policy/visual_identity.py"
STUDIO = "src/sciplot_core/studio_core/"


def content_hash(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "content_hash"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def seal_contract(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "content_hash": content_hash(payload)}


class SourceReader:
    """Closed AST/JSON extraction: never execute an arbitrary source module."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.trees: dict[str, ast.Module] = {}
        self.policy: dict[str, Any] = json.loads((root / POLICY).read_text())

    def tree(self, filename: str) -> ast.Module:
        if filename not in self.trees:
            self.trees[filename] = ast.parse((self.root / filename).read_text())
        return self.trees[filename]

    def constant(self, filename: str, symbol: str) -> Any:
        for node in self.tree(filename).body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and
                                                  target.id == symbol for target in node.targets):
                return ast.literal_eval(node.value)
        raise ValueError(f"Rendering contract source constant missing: {filename}:{symbol}")

    def pointer(self, pointer: str) -> Any:
        result: Any = self.policy
        for part in pointer.split("/")[1:]:
            result = result[part]
        return result

    def set_literal(self, filename: str, function: str, setting: str) -> Any:
        owner = next(node for node in ast.walk(self.tree(filename))
                     if isinstance(node, ast.FunctionDef) and node.name == function)
        values = []
        for node in ast.walk(owner):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Set" and len(node.args) == 2
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == setting):
                values.append(ast.literal_eval(node.args[1]))
        if len(values) != 1:
            raise ValueError(f"Rendering contract setting is not one literal: {function}:{setting}")
        return values[0]

    def setting_default(self, filename: str, owner: str, setting: str) -> Any:
        cls = next(node for node in self.tree(filename).body if isinstance(node, ast.ClassDef) and node.name == owner)
        calls = [node for node in ast.walk(cls) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and len(node.args) >= 2
                 and isinstance(node.args[0], ast.Constant) and node.args[0].value == setting]
        if len(calls) != 1:
            raise ValueError(f"Native baseline setting is not one literal: {owner}:{setting}")
        return ast.literal_eval(calls[0].args[1])


def _record(value: Any, filename: str, symbol: str, notes: str = "", *,
            status: str = "specified") -> dict[str, Any]:
    return {"status": status, "value": value, "source_file": filename,
            "source_symbol": symbol, "notes": notes}


def extract_house_contract(root: Path) -> dict[str, Any]:
    """Reproduce the pinned house contract; differences require review/versioning."""
    reader = SourceReader(root)
    props: dict[str, Any] = {}
    constants = {
        "font.family": "UNIFIED_FONT_FAMILY", "font.size_pt": "UNIFIED_FONT_SIZE_PT",
        "legend.font_size_pt": "UNIFIED_LEGEND_FONT_SIZE_PT", "legend.key_length_mm": "UNIFIED_LEGEND_KEY_LENGTH_MM",
        "panel_label.font_size_pt": "UNIFIED_PANEL_LABEL_SIZE_PT", "line.width_pt": "UNIFIED_LINE_WIDTH_PT",
        "axis.line_width_pt": "UNIFIED_AXIS_LINEWIDTH_PT", "axis.major_tick_width_pt": "UNIFIED_TICK_WIDTH_PT",
        "axis.major_tick_length_pt": "UNIFIED_TICK_LENGTH_PT", "axis.minor_tick_width_pt": "UNIFIED_MINOR_TICK_WIDTH_PT",
        "axis.minor_tick_length_pt": "UNIFIED_MINOR_TICK_LENGTH_PT", "marker.size_pt": "UNIFIED_MARKER_SIZE_PT",
        "marker.line_width_pt": "UNIFIED_MARKER_LINE_WIDTH_PT", "foreground.color": "UNIFIED_FOREGROUND_COLOR",
        "frame.left_mm": "UNIFIED_LEFT_MARGIN_MM", "frame.right_mm": "UNIFIED_RIGHT_MARGIN_MM",
        "frame.top_mm": "UNIFIED_TOP_MARGIN_MM", "frame.bottom_mm": "UNIFIED_BOTTOM_MARGIN_MM",
        "line.style_sequence": "DEFAULT_CURVE_LINE_STYLE_SEQUENCE", "export.formats": "DEFAULT_EXPORT_FORMATS_POLICY",
        "axis.log_tick_format": "DEFAULT_LOG_TICK_FORMAT", "axis.log_minor_tick_count": "DEFAULT_LOG_MINOR_TICK_COUNT",
        "axis.log_minor_multipliers": "DEFAULT_LOG_MINOR_MULTIPLIERS",
        "legend.curve_clearance_mm": "DEFAULT_LEGEND_CURVE_CLEARANCE_MM",
        "legend.edge_padding_mm": "DEFAULT_LEGEND_EDGE_PADDING_MM",
    }
    for key, symbol in constants.items():
        value = reader.constant(FRAME, symbol)
        props[key] = _record(list(value) if isinstance(value, tuple) else value, FRAME, symbol)
    pointers = {
        "canvas.width_mm": "/global_frame/panel_width_mm", "canvas.height_mm": "/global_frame/panel_height_mm",
        "line.opacity": "/styles/nature/stroke/line_alpha", "marker.opacity": "/styles/nature/stroke/marker_alpha",
        "fill.opacity": "/styles/nature/stroke/fill_alpha", "fill.maximum_opacity": "/styles/nature/stroke/max_fill_alpha",
        "axis.label_padding_pt": "/styles/nature/spacing/axes_labelpad",
        "axis.x_tick_label_padding_pt": "/styles/nature/spacing/xtick_major_pad",
        "axis.y_tick_label_padding_pt": "/styles/nature/spacing/ytick_major_pad",
        "legend.inset_fraction": "/styles/nature/spacing/legend_inset_fraction",
        "legend.frame_visible": "/styles/nature/annotation/legend_frameon",
        "panel_label.weight": "/styles/nature/typography/panel_label_weight",
        "axis.frame_sides": "/styles/nature/axis_frame", "palette.id": "/defaults/palette_preset",
        "palette.colors": "/palettes/control_first_bright/categorical", "canvas.size_presets": "/size_presets",
        "axis.domain_policy": "/axis_policy", "special_layouts": "/special_layouts",
        "export.preview_dpi": "/styles/nature/export/figure_dpi",
        "export.raster_dpi": "/styles/nature/export/savefig_dpi",
        "export.color_space": "/styles/nature/export/color_space",
        "export.vector_preferred": "/styles/nature/export/vector_preferred",
        "export.matplotlib_pdf_fonttype": "/styles/nature/export/pdf_fonttype",
        "export.matplotlib_ps_fonttype": "/styles/nature/export/ps_fonttype",
    }
    for key, pointer in pointers.items():
        notes = "Policy intent; not a Veusz export option." if "fonttype" in key else ""
        props[key] = _record(reader.pointer(pointer), POLICY, pointer, notes)
    markers_file = "src/sciplot_core/studio_render/models.py"
    props["marker.sequence"] = _record(list(reader.constant(markers_file, "POINT_LINE_MARKERS")),
                                      markers_file, "POINT_LINE_MARKERS", "Point-line template sequence, not line-only spectra.")
    for key, filename, function, setting in (
        ("canvas.background", "veusz_graph_setup.py", "create_veusz_page_and_graph", "Background/color"),
        ("frame.border_hidden", "veusz_graph_setup.py", "create_veusz_page_and_graph", "Border/hide"),
        ("axis.outer_ticks", "veusz_axis_apply.py", "_add_veusz_axis", "outerticks"),
        ("axis.auto_mirror", "veusz_axis_apply.py", "_add_veusz_axis", "autoMirror"),
        ("axis.line_transparency", "veusz_axis_apply.py", "_add_veusz_axis", "Line/transparency"),
        ("legend.margin_font_fraction", "veusz_graph_setup.py", "_add_native_veusz_key", "marginSize"),
        ("line.unused_error_channel_hidden", "veusz_primitives.py", "_add_veusz_xy_series", "ErrorBarLine/hide"),
    ):
        path = STUDIO + filename
        props[key] = _record(reader.set_literal(path, function, setting), path, f"{function}:Set({setting})")
    thin_file = STUDIO + "series_request.py"
    thin_fn = next(node for node in ast.walk(reader.tree(thin_file))
                   if isinstance(node, ast.FunctionDef) and node.name == "_marker_thin_factor")
    returns = [node for node in ast.walk(thin_fn) if isinstance(node, ast.Return)]
    if len(returns) != 1 or returns[0].value is None:
        raise ValueError("Marker thinning contract is no longer one explicit return.")
    props["marker.thin_factor"] = _record(ast.literal_eval(returns[0].value), thin_file,
                                          "_marker_thin_factor:return", "Every measured point remains marked.")
    _native_adapter_baselines(reader, props)
    _mark_baselines(reader, props)
    for key, notes in {
        "title.position": "No universal title position; existing label/direct-label conventions are figure-specific.",
        "title.font_weight": "No universal title weight explicitly set by generic native creation.",
        "annotation.anchor": "Anchors and alignment belong to each annotation; no universal override.",
        "errorbar.cap_width_pt": "Old categorical caps are data-width-relative, not a universal physical pt width.",
        "export.tiff_compression": "No compression override in old interface.Export call.",
        "export.veusz_pdf_font_embedding": "No explicit old Veusz font-embedding override; PDF fonttype=42 is Matplotlib policy only.",
        "composition.multi_panel": "No generic old multi-panel rule; use the separately named composition policy.",
    }.items():
        props[key] = _record("unspecified", "", "", notes, status="unspecified")
    return seal_contract({"kind": "sciplot_rendering_style_contract", "schema_version": 1,
                          "contract_id": HOUSE_CONTRACT_ID, "authority": "legacy_source_extraction",
                          "properties": props})


def _native_adapter_baselines(reader: SourceReader, props: dict[str, Any]) -> None:
    """Label inherited backend behaviour separately from the old house rules."""
    join_file = STUDIO + "veusz_line_joins.py"
    calls = [node for node in ast.walk(reader.tree(join_file)) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "Choice"
             and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "joinStyle"]
    if len(calls) != 1:
        raise ValueError("Native line join baseline changed structure.")
    props["line.join"] = _record(ast.literal_eval(calls[0].args[2]), join_file, "ensure_veusz_line_joins:Choice(joinStyle)",
                                 "Explicit SciPlot adapter default preserves old native joins.", status="adapter_baseline")
    export_file = STUDIO + "export_execution.py"
    assignments = [node for node in ast.walk(reader.tree(export_file)) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                           and target.slice.value == "pdfdpi" for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError("PDF native export baseline changed structure.")
    props["export.veusz_pdf_dpi"] = _record(ast.literal_eval(assignments[0].value), export_file,
                                            "export_studio_document:kwargs[pdfdpi]")
    color_file = "third_party/veusz/veusz/document/colors.py"
    colors = [node for node in ast.walk(reader.tree(color_file)) if isinstance(node, ast.Dict)
              and any(isinstance(key, ast.Constant) and key.value == "foreground" for key in node.keys)]
    if len(colors) != 1:
        raise ValueError("Native foreground baseline changed structure.")
    props["legend.color"] = _record(ast.literal_eval(colors[0])["foreground"], color_file, "Colors.wipe:foreground",
                                    "Old house rule unspecified; old key inherits backend foreground.", status="adapter_baseline")
    collections = "third_party/veusz/veusz/setting/collections.py"
    text = next(node for node in reader.tree(collections).body if isinstance(node, ast.ClassDef) and node.name == "Text")
    bold = [node for node in ast.walk(text) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Bool" and node.args and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "bold"]
    props["font.weight"] = _record("bold" if ast.literal_eval(bold[0].args[1]) else "normal", collections,
                                   "Text.__init__:Bool(bold)", "Old house rule unspecified; pin inherited native weight.",
                                   status="adapter_baseline")
    axis_file = "third_party/veusz/veusz/widgets/axis.py"
    minor = next(node for node in reader.tree(axis_file).body if isinstance(node, ast.ClassDef) and node.name == "MinorTick")
    number = next(node for node in ast.walk(minor) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "Int" and node.args and isinstance(node.args[0], ast.Constant)
                  and node.args[0].value == "number")
    props["axis.linear_minor_tick_count"] = _record(ast.literal_eval(number.args[1]), axis_file,
                                                   "MinorTick.__init__:Int(number)",
                                                   "Matches explicit old _add_veusz_axis fallback of 20.", status="adapter_baseline")
    props["axis.tick_color"] = _record(props["legend.color"]["value"], collections,
        "Line.__init__:color -> StyleSheet/Line/color -> Colors.foreground",
        "Old major/minor ticks inherit backend foreground independently from the #111111 axis spine.", status="adapter_baseline")
    props["axis.minor_ticks_visible"] = _record(not reader.setting_default(collections, "Line", "hide"),
        collections, "Line.__init__:hide", "MinorTick inherits Line.hide=false unless explicitly hidden.", status="adapter_baseline")
    for key, cls_name in (("axis.grid_visible", "GridLine"), ("axis.minor_grid_visible", "MinorGridLine")):
        owner = next(node for node in reader.tree(axis_file).body if isinstance(node, ast.ClassDef) and node.name == cls_name)
        call = next(node for node in ast.walk(owner) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "newDefault" and isinstance(node.func.value, ast.Call)
                    and node.func.value.args and isinstance(node.func.value.args[0], ast.Constant)
                    and node.func.value.args[0].value == "hide")
        props[key] = _record(not ast.literal_eval(call.args[0]), axis_file, f"{cls_name}.__init__:hide.newDefault",
                             "Old native default; no generic house override.", status="adapter_baseline")


def _mark_baselines(reader: SourceReader, props: dict[str, Any]) -> None:
    collections = "third_party/veusz/veusz/setting/collections.py"
    label = "third_party/veusz/veusz/widgets/textlabel.py"
    for key, setting in (("text.align_h", "alignHorz"), ("text.align_v", "alignVert")):
        props[key] = _record(reader.setting_default(label, "TextLabel", setting), label,
                             f"TextLabel.addSettings:{setting}", "Old house rule unspecified; pin native label default.",
                             status="adapter_baseline")
    foreground = props["legend.color"]["value"]
    fill = reader.setting_default(collections, "BrushExtended", "color")
    transparency = reader.setting_default(collections, "BrushExtended", "transparency")
    props["band.fill_color"] = _record(foreground if fill == "foreground" else fill, collections,
                                       "BrushExtended.__init__:color -> Colors.foreground",
                                       "No old scientific-band house rule; pinned polygon adapter baseline.", status="adapter_baseline")
    props["band.fill_opacity"] = _record((100 - transparency) / 100, collections,
                                         "BrushExtended.__init__:transparency", "Opacity = (100 - transparency) / 100.",
                                         status="adapter_baseline")
    props["band.border_color"] = _record(foreground, collections, "Line.__init__:color -> StyleSheet/Line/color -> foreground",
                                         "Inherited native polygon outline; not an old band-specific house rule.", status="adapter_baseline")
    props["band.border_width_pt"] = _record(props["line.width_pt"]["value"], STUDIO + "veusz_graph_setup.py",
                                            "create_veusz_page_and_graph:StyleSheet/Line/width",
                                            "Native polygon Line inherits explicit document line width.", status="adapter_baseline")
    categorical = "src/sciplot_core/policy/categorical.py"
    for key, symbol in (("bar.fill_colors", "CATEGORICAL_FILL_COLORS_BY_BASE"),
                        ("bar.border_colors", "CATEGORICAL_KEYLINE_COLORS_BY_BASE"),
                        ("bar.border_width_pt", "CATEGORICAL_KEYLINE_WIDTH_PT"),
                        ("bar.fill_transparency", "CATEGORICAL_BAR_FILL_TRANSPARENCY"),
                        ("errorbar.cap_to_bar_ratio", "CATEGORICAL_ERROR_CAP_TO_BAR_RATIO"),
                        ("bar.width_fraction", "CATEGORICAL_BAR_WIDTH_FRACTION")):
        props[key] = _record(reader.constant(categorical, symbol), categorical, symbol,
                             "Old categorical family convention; differs from generic stroke.fill_alpha policy.")
    endsize = reader.setting_default(collections, "ErrorBarLine", "endsize")
    props["errorbar.adapter_cap_width_pt"] = _record(2 * props["marker.size_pt"]["value"] * endsize, collections,
        "ErrorBarLine.__init__:endsize", "Old categorical physical cap unspecified; native XY cap spans +/- markerSize * endsize. "
        "Project markerSize comes from UNIFIED_MARKER_SIZE_PT. Actual categorical data-relative caps need explicit conversion.",
        status="adapter_baseline")
