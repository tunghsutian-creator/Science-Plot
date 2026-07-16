from __future__ import annotations

import hashlib
import math
import sys
import types
from pathlib import Path
from typing import Any

from sciplot_core._paths import VEUSZ_ROOT
from sciplot_core.canvas.annotations import (
    ReviewAnnotation,
    annotation_geometry_from_points,
    annotation_geometry_points,
)
from sciplot_core.canvas.inspector import (
    SUPPORTED_INSPECTOR_TYPES,
    CanvasInspectorField,
    CanvasInspectorModel,
    CanvasInspectorObject,
    specs_for_object_type,
)
from sciplot_core.canvas.model import CanvasDataPointSelection, CanvasSession


def _load_qt_veusz() -> dict[str, Any]:
    runtime = str(VEUSZ_ROOT)
    if runtime not in sys.path:
        sys.path.insert(0, runtime)

    from sciplot_core.studio import ensure_veusz_qsettings_compat

    ensure_veusz_qsettings_compat()
    from PyQt6 import QtCore, QtGui, QtWidgets
    from veusz import dataimport, document, widgets
    from veusz.document.operations import (
        OperationMultiple,
        OperationSettingSet,
        OperationWidgetAdd,
    )
    from veusz.windows.plotwindow import PlotWindow

    _ = dataimport, widgets
    return {
        "QtCore": QtCore,
        "QtGui": QtGui,
        "QtWidgets": QtWidgets,
        "Document": document.Document,
        "OperationMultiple": OperationMultiple,
        "OperationSettingSet": OperationSettingSet,
        "OperationWidgetAdd": OperationWidgetAdd,
        "PlotWindow": PlotWindow,
    }


class VeuszCanvasAdapter:
    """The sole SciPlot boundary around Veusz Document and PlotWindow."""

    def __init__(
        self,
        document_path: Path,
        *,
        parent: Any = None,
        visible: bool = False,
    ) -> None:
        runtime = _load_qt_veusz()
        self._QtCore = runtime["QtCore"]
        self._QtGui = runtime["QtGui"]
        self._QtWidgets = runtime["QtWidgets"]
        self._OperationMultiple = runtime["OperationMultiple"]
        self._OperationSettingSet = runtime["OperationSettingSet"]
        self._OperationWidgetAdd = runtime["OperationWidgetAdd"]

        self.document_path = document_path.expanduser().resolve()
        if not self.document_path.is_file():
            raise FileNotFoundError(self.document_path)

        application = self._QtWidgets.QApplication.instance()
        self.owns_application = application is None
        self.application = application or self._QtWidgets.QApplication([])
        self.assert_gui_thread()

        self.document = runtime["Document"]()
        self.document.load(str(self.document_path))
        self.plot_window = runtime["PlotWindow"](self.document, parent)
        self._paper_item = self._QtWidgets.QGraphicsRectItem()
        self._paper_item.setPen(
            self._QtGui.QPen(self._QtCore.Qt.PenStyle.NoPen)
        )
        self._paper_item.setBrush(
            self._QtGui.QBrush(self._QtGui.QColor("#ffffff"))
        )
        self._paper_item.setAcceptedMouseButtons(
            self._QtCore.Qt.MouseButton.NoButton
        )
        self._paper_item.setZValue(-1.0)
        self.plot_window.scene.addItem(self._paper_item)
        self._selection_overlay: Any = None
        self._selection_path: str | None = None
        self._direct_widget: Any = None
        self._direct_widget_had_override = False
        self._direct_widget_override: Any = None
        self._direct_manipulation_supported = False
        self._data_point_selection: CanvasDataPointSelection | None = None
        self._data_point_session: CanvasSession | None = None
        self.plot_window.rendercontrol.updateNumberThreads(num=0)
        self.plot_window.setTimeout(-1)
        width, height = self.document.docSize()
        self.plot_window.resize(max(int(width) + 16, 320), max(int(height) + 16, 240))
        if visible:
            self.plot_window.show()
        self.force_redraw()

    def assert_gui_thread(self) -> None:
        application = self._QtWidgets.QApplication.instance()
        if application is None:
            raise RuntimeError("A QApplication is required for the live canvas.")
        if self._QtCore.QThread.currentThread() is not application.thread():
            raise RuntimeError(
                "Veusz Document mutations must run on the Qt GUI thread."
            )

    def force_redraw(self) -> str:
        self.assert_gui_thread()
        self.plot_window.actionForceUpdate()
        self.application.processEvents()
        fingerprint = self.render_fingerprint()
        if not fingerprint:
            raise RuntimeError("Embedded PlotWindow did not produce a rendered pixmap.")
        self._sync_display_paper()
        self._restore_persisted_data_point()
        return fingerprint

    def _sync_display_paper(self) -> None:
        self._paper_item.setRect(self.plot_window.pixmapitem.boundingRect())

    def set_display_surface(
        self,
        *,
        canvas_color: str,
        paper_color: str = "#ffffff",
    ) -> None:
        """Set display-only Canvas surfaces without changing the Veusz document."""

        self.assert_gui_thread()
        self.plot_window.setBackgroundBrush(
            self._QtGui.QColor(str(canvas_color))
        )
        self._paper_item.setBrush(
            self._QtGui.QBrush(self._QtGui.QColor(str(paper_color)))
        )
        self._sync_display_paper()

    def render_fingerprint(self) -> str:
        pixmap = self.plot_window.pixmapitem.pixmap()
        if pixmap.isNull() or pixmap.width() <= 1 or pixmap.height() <= 1:
            return ""
        byte_array = self._QtCore.QByteArray()
        buffer = self._QtCore.QBuffer(byte_array)
        buffer.open(self._QtCore.QIODevice.OpenModeFlag.WriteOnly)
        try:
            if not pixmap.save(buffer, "PNG"):
                raise RuntimeError("Could not serialize the live canvas pixmap.")
        finally:
            buffer.close()
        return hashlib.sha256(bytes(byte_array)).hexdigest()

    def bind_object_registry(self, session: CanvasSession) -> list[dict[str, Any]]:
        self.assert_gui_thread()
        self._active_session = session
        objects: list[tuple[str, str, str, str]] = []

        def walk(parent: Any, parent_key: str) -> None:
            type_counts: dict[str, int] = {}
            for child in parent.children:
                object_type = str(child.typename)
                type_index = type_counts.get(object_type, 0)
                type_counts[object_type] = type_index + 1
                structural_key = f"{parent_key}/{object_type}[{type_index}]"
                objects.append(
                    (
                        structural_key,
                        str(child.path),
                        object_type,
                        str(child.name),
                    )
                )
                walk(child, structural_key)

        walk(self.document.basewidget, "root")
        records = session.object_registry.reconcile(
            [
                (structural_key, path, object_type)
                for structural_key, path, object_type, _ in objects
            ],
            revision=session.revision,
        )
        return [
            {
                "object_id": record.object_id,
                "structural_key": structural_key,
                "path": path,
                "object_type": object_type,
                "display_name": display_name,
            }
            for (
                structural_key,
                path,
                object_type,
                display_name,
            ), record in zip(objects, records, strict=True)
        ]

    def _widget(self, widget_path: str) -> Any:
        self.assert_gui_thread()
        return self.document.resolveWidgetPath(None, str(widget_path))

    def _object_item(
        self,
        session: CanvasSession,
        object_id: str,
    ) -> dict[str, Any]:
        inventory = self.bind_object_registry(session)
        item = next(
            (
                candidate
                for candidate in inventory
                if candidate.get("object_id") == object_id
            ),
            None,
        )
        if item is None:
            raise ValueError(f"Unknown Canvas object: {object_id}")
        return item

    def _object_record_path(
        self,
        session: CanvasSession,
        object_id: str,
    ) -> str:
        record = session.object_registry.by_id(object_id)
        if record is None:
            self.bind_object_registry(session)
            record = session.object_registry.by_id(object_id)
        if record is None:
            raise ValueError(f"Unknown Canvas object: {object_id}")
        return str(record.current_path)

    def _page_scene_rect(self) -> Any:
        rect = self.plot_window.pixmapitem.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            raise RuntimeError("The live Canvas page has no drawable bounds.")
        return rect

    def _widget_scene_rect(self, widget: Any) -> Any:
        helper = self.plot_window.painthelper
        if helper is None:
            raise RuntimeError("The live Canvas has no rendered geometry.")
        bounds = helper.widgetBounds(widget)
        scale = float(helper.cgscale)
        return self._QtCore.QRectF(
            self._QtCore.QPointF(
                float(bounds[0]) * scale,
                float(bounds[1]) * scale,
            ),
            self._QtCore.QPointF(
                float(bounds[2]) * scale,
                float(bounds[3]) * scale,
            ),
        ).normalized()

    def _graph_widget_for(self, widget: Any) -> Any | None:
        candidate = widget
        while candidate is not None:
            if str(getattr(candidate, "typename", "")) == "graph":
                return candidate
            candidate = getattr(candidate, "parent", None)
        return None

    def _first_graph_on_current_page(self) -> Any | None:
        page = self._widget(self.current_page_path)
        stack = list(page.children)
        while stack:
            candidate = stack.pop(0)
            if str(candidate.typename) == "graph":
                return candidate
            stack[0:0] = list(candidate.children)
        return None

    def _annotation_target_widget(
        self,
        annotation: ReviewAnnotation,
        session: CanvasSession,
    ) -> Any:
        if annotation.target_object_id is None:
            raise ValueError(
                f"{annotation.coordinate_space}-space annotation has no target."
            )
        return self._widget(
            self._object_record_path(session, annotation.target_object_id)
        )

    def _data_axes_context(
        self,
        *,
        target_object_id: str,
        session: CanvasSession,
    ) -> tuple[Any, tuple[Any, Any], Any]:
        widget = self._widget(
            self._object_record_path(session, target_object_id)
        )
        graph = self._graph_widget_for(widget)
        if graph is None:
            raise ValueError("Data-space review marks require a graph-bound target.")
        axes: tuple[Any, Any] | None = None
        if hasattr(widget, "fetchAxes"):
            fetched = widget.fetchAxes()
            if (
                isinstance(fetched, (tuple, list))
                and len(fetched) >= 2
                and fetched[0] is not None
                and fetched[1] is not None
            ):
                axes = (fetched[0], fetched[1])
        if axes is None and hasattr(graph, "getAxes"):
            fetched = graph.getAxes(("x", "y"))
            if (
                isinstance(fetched, (tuple, list))
                and len(fetched) >= 2
                and fetched[0] is not None
                and fetched[1] is not None
            ):
                axes = (fetched[0], fetched[1])
        if axes is None:
            raise ValueError(
                "The selected target does not expose a complete X/Y axis pair."
            )
        helper = self.plot_window.painthelper
        if helper is None:
            raise RuntimeError("The live Canvas has no rendered geometry.")
        bounds = helper.widgetBounds(graph)
        return graph, axes, bounds

    def review_anchor_target_id(
        self,
        session: CanvasSession,
        coordinate_space: str,
    ) -> str | None:
        """Resolve the current selection to a valid review-anchor target."""

        if coordinate_space in {"page", "normalized_page"}:
            return None
        selected_id = session.selection.primary_object_id
        if coordinate_space == "object":
            if selected_id is None:
                raise ValueError("Select a Canvas object before using an object anchor.")
            return selected_id
        inventory = self.bind_object_registry(session)
        selected_item = next(
            (
                item
                for item in inventory
                if item.get("object_id") == selected_id
            ),
            None,
        )
        selected_widget = (
            self._widget(str(selected_item["path"]))
            if selected_item is not None
            else None
        )
        if coordinate_space == "graph":
            graph = (
                self._graph_widget_for(selected_widget)
                if selected_widget is not None
                else None
            ) or self._first_graph_on_current_page()
            if graph is None:
                raise ValueError("The current page does not contain a graph anchor.")
            item = next(
                (value for value in inventory if value.get("path") == str(graph.path)),
                None,
            )
            if item is None:
                raise RuntimeError("The graph anchor is outside the object registry.")
            return str(item["object_id"])
        if coordinate_space == "data":
            candidates: list[str] = []
            if session.selection.data_point is not None:
                candidates.append(session.selection.data_point.target_object_id)
            if selected_id is not None:
                candidates.append(selected_id)
            candidates.extend(
                str(item["object_id"])
                for item in inventory
                if item.get("object_type")
                in {"xy", "boxplot", "image", "contour"}
                and (
                    str(item.get("path")) == self.current_page_path
                    or str(item.get("path")).startswith(
                        f"{self.current_page_path}/"
                    )
                )
            )
            for object_id in dict.fromkeys(candidates):
                try:
                    self._data_axes_context(
                        target_object_id=object_id,
                        session=session,
                    )
                except (RuntimeError, ValueError):
                    continue
                return object_id
            raise ValueError(
                "Select a graph series or data point before using a data anchor."
            )
        raise ValueError(f"Unsupported review coordinate space: {coordinate_space!r}")

    def review_geometry_to_scene(
        self,
        annotation: ReviewAnnotation,
        session: CanvasSession,
    ) -> dict[str, Any]:
        if annotation.page_index != self.current_page:
            raise ValueError("Review annotation is not on the current page.")
        points = annotation_geometry_points(annotation.shape, annotation.geometry)
        page_rect = self._page_scene_rect()

        if annotation.coordinate_space == "page":
            scale = float(self.plot_window.painthelper.cgscale)
            transformed = [
                (
                    page_rect.left() + x * scale,
                    page_rect.top() + y * scale,
                )
                for x, y in points
            ]
        elif annotation.coordinate_space == "normalized_page":
            transformed = [
                (
                    page_rect.left() + x * page_rect.width(),
                    page_rect.top() + y * page_rect.height(),
                )
                for x, y in points
            ]
        elif annotation.coordinate_space in {"graph", "object"}:
            target = self._annotation_target_widget(annotation, session)
            if annotation.coordinate_space == "graph":
                target = self._graph_widget_for(target)
                if target is None:
                    raise ValueError("The review graph anchor no longer resolves.")
            rect = self._widget_scene_rect(target)
            transformed = [
                (
                    rect.left() + x * rect.width(),
                    rect.top() + y * rect.height(),
                )
                for x, y in points
            ]
        elif annotation.coordinate_space == "data":
            if annotation.target_object_id is None:
                raise ValueError("Data-space review annotation has no target.")
            import numpy as np

            _, axes, bounds = self._data_axes_context(
                target_object_id=annotation.target_object_id,
                session=session,
            )
            scale = float(self.plot_window.painthelper.cgscale)
            transformed = [
                (
                    float(
                        axes[0].dataToPlotterCoords(
                            bounds,
                            np.asarray([x], dtype=float),
                        )[0]
                    )
                    * scale,
                    float(
                        axes[1].dataToPlotterCoords(
                            bounds,
                            np.asarray([y], dtype=float),
                        )[0]
                    )
                    * scale,
                )
                for x, y in points
            ]
        else:
            raise ValueError(
                f"Unsupported review coordinate space: {annotation.coordinate_space!r}"
            )
        return annotation_geometry_from_points(annotation.shape, transformed)

    def review_geometry_from_scene(
        self,
        *,
        shape: str,
        scene_geometry: dict[str, Any],
        coordinate_space: str,
        target_object_id: str | None,
        page_index: int,
        session: CanvasSession,
    ) -> dict[str, Any]:
        if int(page_index) != self.current_page:
            raise ValueError("Review annotations can only be created on the active page.")
        points = annotation_geometry_points(shape, scene_geometry)
        page_rect = self._page_scene_rect()

        if coordinate_space == "page":
            scale = float(self.plot_window.painthelper.cgscale)
            transformed = [
                (
                    (x - page_rect.left()) / scale,
                    (y - page_rect.top()) / scale,
                )
                for x, y in points
            ]
        elif coordinate_space == "normalized_page":
            transformed = [
                (
                    min(max((x - page_rect.left()) / page_rect.width(), 0.0), 1.0),
                    min(max((y - page_rect.top()) / page_rect.height(), 0.0), 1.0),
                )
                for x, y in points
            ]
        elif coordinate_space in {"graph", "object"}:
            if target_object_id is None:
                raise ValueError(
                    f"{coordinate_space}-space review marks require a target."
                )
            target = self._widget(
                self._object_record_path(session, target_object_id)
            )
            if coordinate_space == "graph":
                target = self._graph_widget_for(target)
                if target is None:
                    raise ValueError("The graph review target no longer resolves.")
            rect = self._widget_scene_rect(target)
            transformed = [
                (
                    min(max((x - rect.left()) / rect.width(), 0.0), 1.0),
                    min(max((y - rect.top()) / rect.height(), 0.0), 1.0),
                )
                for x, y in points
            ]
        elif coordinate_space == "data":
            if target_object_id is None:
                raise ValueError("Data-space review marks require a target.")
            import numpy as np

            _, axes, bounds = self._data_axes_context(
                target_object_id=target_object_id,
                session=session,
            )
            scale = float(self.plot_window.painthelper.cgscale)
            transformed = [
                (
                    float(
                        axes[0].plotterToDataCoords(
                            bounds,
                            np.asarray([x / scale], dtype=float),
                        )[0]
                    ),
                    float(
                        axes[1].plotterToDataCoords(
                            bounds,
                            np.asarray([y / scale], dtype=float),
                        )[0]
                    ),
                )
                for x, y in points
            ]
        else:
            raise ValueError(f"Unsupported review coordinate space: {coordinate_space!r}")
        return annotation_geometry_from_points(shape, transformed)

    def native_annotation_spec(
        self,
        annotation: ReviewAnnotation,
        session: CanvasSession,
    ) -> dict[str, Any]:
        """Compile one review mark into a bounded native Veusz widget spec."""

        if not annotation.promotable:
            raise ValueError(
                f"{annotation.shape!r} review annotation cannot be promoted."
            )
        inventory = self.bind_object_registry(session)
        page_widget = self._widget(self.current_page_path)
        target_widget = (
            self._annotation_target_widget(annotation, session)
            if annotation.target_object_id is not None
            else page_widget
        )
        parent_widget = self._graph_widget_for(target_widget) or page_widget
        if str(parent_widget.typename) not in {"page", "graph"}:
            raise ValueError("Native annotations require a page or graph parent.")
        parent_item = next(
            (
                item
                for item in inventory
                if str(item.get("path")) == str(parent_widget.path)
            ),
            None,
        )
        if parent_item is None:
            raise RuntimeError("Native annotation parent is outside the object registry.")

        scene_geometry = self.review_geometry_to_scene(annotation, session)
        scene_points = annotation_geometry_points(
            annotation.shape,
            scene_geometry,
        )
        parent_rect = self._widget_scene_rect(parent_widget)

        def relative(point: tuple[float, float]) -> tuple[float, float]:
            return (
                min(
                    max(
                        (point[0] - parent_rect.left()) / parent_rect.width(),
                        0.0,
                    ),
                    1.0,
                ),
                min(
                    max(
                        (parent_rect.bottom() - point[1]) / parent_rect.height(),
                        0.0,
                    ),
                    1.0,
                ),
            )

        positioning = "relative"
        native_points = [relative(point) for point in scene_points]
        x_axis_name = "x"
        y_axis_name = "y"
        if (
            annotation.coordinate_space == "data"
            and annotation.target_object_id is not None
            and str(parent_widget.typename) == "graph"
        ):
            _, axes, _ = self._data_axes_context(
                target_object_id=annotation.target_object_id,
                session=session,
            )
            positioning = "axes"
            x_axis_name = str(getattr(axes[0], "name", "x") or "x")
            y_axis_name = str(getattr(axes[1], "name", "y") or "y")
            native_points = annotation_geometry_points(
                annotation.shape,
                annotation.geometry,
            )

        style = annotation.style
        common: dict[str, Any] = {
            "positioning": positioning,
            "xAxis": x_axis_name,
            "yAxis": y_axis_name,
            "clip": False,
        }
        name = f"review_{annotation.annotation_id.replace('-', '')[:12]}"
        if annotation.shape == "text":
            point = native_points[0]
            settings = {
                **common,
                "xPos": [point[0]],
                "yPos": [point[1]],
                "label": annotation.text,
                "alignHorz": "left",
                "alignVert": "top",
                "Text__color": style.color,
                "Text__size": f"{style.font_size:g}pt",
            }
            widget_type = "label"
        elif annotation.shape == "arrow":
            start, end = native_points
            settings = {
                **common,
                "mode": "point-to-point",
                "xPos": [start[0]],
                "yPos": [start[1]],
                "xPos2": [end[0]],
                "yPos2": [end[1]],
                "arrowright": "arrow",
                "arrowleft": "none",
                "arrowSize": f"{max(style.line_width * 3.0, 5.0):g}pt",
                "Line__color": style.color,
                "Line__width": f"{style.line_width:g}pt",
                "Fill__color": style.color,
            }
            widget_type = "line"
        else:
            first_scene, second_scene = scene_points
            center_scene = (
                (first_scene[0] + second_scene[0]) / 2.0,
                (first_scene[1] + second_scene[1]) / 2.0,
            )
            if positioning == "axes" and annotation.target_object_id is not None:
                center_geometry = self.review_geometry_from_scene(
                    shape="text",
                    scene_geometry={"position": list(center_scene)},
                    coordinate_space="data",
                    target_object_id=annotation.target_object_id,
                    page_index=annotation.page_index,
                    session=session,
                )
                center = annotation_geometry_points(
                    "text",
                    center_geometry,
                )[0]
            else:
                center = relative(center_scene)
            width = abs(second_scene[0] - first_scene[0]) / parent_rect.width()
            height = abs(second_scene[1] - first_scene[1]) / parent_rect.height()
            settings = {
                **common,
                "xPos": [center[0]],
                "yPos": [center[1]],
                "width": [width],
                "height": [height],
                "Border__color": style.color,
                "Border__width": f"{style.line_width:g}pt",
                "Fill__color": style.fill_color,
                "Fill__transparency": round(
                    (1.0 - min(style.opacity * 0.34, 0.42)) * 100.0
                ),
                "Fill__hide": False,
            }
            widget_type = "rect" if annotation.shape == "rectangle" else "ellipse"

        return {
            "target_id": str(parent_item["object_id"]),
            "parent_path": str(parent_widget.path),
            "widget_type": widget_type,
            "name": name,
            # Page children are drawn in reverse order by Veusz. Insert native
            # page annotations at the front so the graph cannot cover them.
            "index": 0 if str(parent_widget.typename) == "page" else -1,
            "settings": settings,
        }

    def _object_role(self, item: dict[str, Any]) -> str:
        object_type = str(item["object_type"])
        name = str(item.get("display_name") or object_type)
        path = str(item["path"])
        widget = self._widget(path)
        if object_type == "page":
            return "Figure page"
        if object_type == "graph":
            return "Plot area"
        if object_type == "axis":
            if name.casefold() == "x":
                return "X axis"
            if name.casefold() == "y":
                return "Y axis"
            return f"Axis · {name}"
        if object_type == "xy":
            key = str(widget.settings.key or "").strip()
            return f"Series · {key or name}"
        if object_type == "boxplot":
            return f"Box plot · {name}"
        if object_type == "key":
            return "Legend"
        if object_type == "image":
            return f"Field image · {name}"
        if object_type == "contour":
            return f"Contours · {name}"
        if object_type == "colorbar":
            return "Color scale"
        if object_type == "label":
            label = str(widget.settings.label or "").strip()
            if len(label) > 36:
                label = f"{label[:33]}…"
            return f"Annotation · {label or name}"
        return f"{object_type} · {name}"

    def _inspector_object(
        self,
        item: dict[str, Any],
    ) -> CanvasInspectorObject:
        return CanvasInspectorObject(
            object_id=str(item["object_id"]),
            object_type=str(item["object_type"]),
            display_name=str(item.get("display_name") or item["object_type"]),
            role_label=self._object_role(item),
            path=str(item["path"]),
        )

    def default_inspector_object_id(
        self,
        session: CanvasSession,
    ) -> str | None:
        inventory = self.bind_object_registry(session)
        page_prefix = self.current_page_path
        supported = [
            item
            for item in inventory
            if item.get("object_type") in SUPPORTED_INSPECTOR_TYPES
            and (
                str(item.get("path")) == page_prefix
                or str(item.get("path")).startswith(f"{page_prefix}/")
            )
        ]
        for preferred_type in ("graph", "page", "axis", "xy", "image"):
            item = next(
                (
                    candidate
                    for candidate in supported
                    if candidate.get("object_type") == preferred_type
                ),
                None,
            )
            if item is not None:
                return str(item["object_id"])
        return str(supported[0]["object_id"]) if supported else None

    def nearest_inspector_object_id(
        self,
        session: CanvasSession,
        widget_path: str,
    ) -> str | None:
        """Resolve a clicked Veusz object to the nearest bounded Canvas editor."""

        inventory = self.bind_object_registry(session)
        by_path = {
            str(item["path"]): item
            for item in inventory
            if item.get("object_type") in SUPPORTED_INSPECTOR_TYPES
        }
        candidate = str(widget_path).rstrip("/")
        while candidate:
            item = by_path.get(candidate)
            if item is not None:
                return str(item["object_id"])
            candidate = candidate.rsplit("/", 1)[0]
        return self.default_inspector_object_id(session)

    def contextual_inspector(
        self,
        session: CanvasSession,
        object_id: str,
    ) -> CanvasInspectorModel:
        item = self._object_item(session, object_id)
        object_type = str(item["object_type"])
        specs = specs_for_object_type(object_type)
        if not specs:
            raise ValueError(
                f"SciPlot has no bounded inspector for {object_type!r}."
            )
        widget_path = str(item["path"])
        fields: list[CanvasInspectorField] = []
        for spec in specs:
            setting_path = f"{widget_path}/{spec.suffix}"
            try:
                setting = self.document.resolveSettingPath(None, setting_path)
            except ValueError:
                continue
            choices = tuple(
                str(choice) for choice in getattr(setting, "vallist", ())
            )
            help_text = spec.help_text or str(getattr(setting, "descr", "") or "")
            fields.append(
                CanvasInspectorField(
                    field_id=spec.field_id,
                    section=spec.section,
                    label=spec.label,
                    setting_path=setting_path,
                    setting_type=str(getattr(setting, "typename", "setting")),
                    editor=spec.editor,
                    value=setting.get(),
                    immediate=spec.immediate,
                    read_only=spec.read_only,
                    choices=choices,
                    minimum=spec.minimum,
                    maximum=spec.maximum,
                    step=spec.step,
                    decimals=spec.decimals,
                    help_text=help_text,
                )
            )

        inventory = self.bind_object_registry(session)
        page_path = f"/{widget_path.strip('/').split('/')[0]}"
        related_items = [
            candidate
            for candidate in inventory
            if candidate.get("object_type") in SUPPORTED_INSPECTOR_TYPES
            and (
                str(candidate.get("path")) == page_path
                or str(candidate.get("path")).startswith(f"{page_path}/")
            )
        ]
        type_order = {
            "page": 0,
            "graph": 1,
            "axis": 2,
            "key": 3,
            "xy": 4,
            "boxplot": 5,
            "image": 6,
            "contour": 7,
            "colorbar": 8,
            "label": 9,
        }
        related_items.sort(
            key=lambda candidate: (
                type_order.get(str(candidate.get("object_type")), 99),
                str(candidate.get("path")),
            )
        )
        breadcrumb: list[str] = []
        parts = widget_path.strip("/").split("/")
        for index in range(len(parts)):
            prefix = f"/{'/'.join(parts[: index + 1])}"
            candidate = next(
                (
                    value
                    for value in inventory
                    if str(value.get("path")) == prefix
                ),
                None,
            )
            if candidate is not None:
                breadcrumb.append(
                    str(candidate.get("display_name") or candidate["object_type"])
                )
        point = session.selection.data_point
        point_payload = (
            point.to_dict()
            if point is not None and point.target_object_id == object_id
            else None
        )
        return CanvasInspectorModel(
            target=self._inspector_object(item),
            breadcrumb=tuple(breadcrumb),
            fields=tuple(fields),
            related_objects=tuple(
                self._inspector_object(candidate) for candidate in related_items
            ),
            point_selection=point_payload,
            direct_manipulation=(
                "drag_annotation_on_canvas" if object_type == "label" else None
            ),
        )

    def point_selection_from_pick(
        self,
        session: CanvasSession,
        pickinfo: Any,
    ) -> CanvasDataPointSelection:
        self.assert_gui_thread()
        widget = getattr(pickinfo, "widget", None)
        coords = getattr(pickinfo, "coords", None)
        graphpos = getattr(pickinfo, "graphpos", None)
        if (
            widget is None
            or not isinstance(coords, (tuple, list))
            or len(coords) != 2
            or not isinstance(graphpos, (tuple, list))
            or len(graphpos) != 2
        ):
            raise ValueError("Veusz did not return a complete data-point selection.")
        inventory = self.bind_object_registry(session)
        item = next(
            (
                candidate
                for candidate in inventory
                if str(candidate.get("path")) == str(widget.path)
            ),
            None,
        )
        if item is None:
            raise ValueError("Picked data point does not resolve to a Canvas object.")
        labels = getattr(pickinfo, "labels", ("x", "y"))
        if not isinstance(labels, (tuple, list)) or len(labels) != 2:
            labels = ("x", "y")
        display_type = getattr(pickinfo, "displaytype", ("numeric", "numeric"))
        if not isinstance(display_type, (tuple, list)) or len(display_type) != 2:
            display_type = ("numeric", "numeric")
        index_text = str(getattr(pickinfo, "index", "") or "").strip() or None
        return CanvasDataPointSelection(
            target_object_id=str(item["object_id"]),
            x=float(coords[0]),
            y=float(coords[1]),
            graph_x=float(graphpos[0]),
            graph_y=float(graphpos[1]),
            x_label=str(labels[0] or "x"),
            y_label=str(labels[1] or "y"),
            index=index_text,
            display_type=(str(display_type[0]), str(display_type[1])),
        )

    def set_interaction_mode(self, mode: str) -> str:
        self.assert_gui_thread()
        if mode not in {"select", "pick"}:
            raise ValueError(f"Unsupported Canvas interaction mode: {mode!r}")
        self.plot_window.clickmode = mode
        if mode == "pick":
            self.plot_window.pixmapitem.setCursor(
                self._QtCore.Qt.CursorShape.CrossCursor
            )
        else:
            self.plot_window.pixmapitem.unsetCursor()
        return mode

    def restore_data_point_selection(
        self,
        selection: CanvasDataPointSelection | None,
        session: CanvasSession,
    ) -> bool:
        self.assert_gui_thread()
        self._data_point_selection = selection
        self._data_point_session = session if selection is not None else None
        return self._restore_persisted_data_point()

    def _restore_persisted_data_point(self) -> bool:
        selection = self._data_point_selection
        session = self._data_point_session
        if selection is None or self.plot_window.painthelper is None:
            self.plot_window.pickeritem.hide()
            return False
        graph_x = selection.graph_x
        graph_y = selection.graph_y
        try:
            import numpy as np

            record_path = next(
                (
                    record.current_path
                    for record in session.object_registry.records.values()
                    if record.object_id == selection.target_object_id
                ),
                None,
            )
            if record_path:
                widget = self._widget(record_path)
                axes = widget.fetchAxes()
                bounds = self.plot_window.painthelper.widgetBounds(widget)
                if axes and bounds:
                    graph_x = float(
                        axes[0].dataToPlotterCoords(
                            bounds, np.asarray([selection.x], dtype=float)
                        )[0]
                    )
                    graph_y = float(
                        axes[1].dataToPlotterCoords(
                            bounds, np.asarray([selection.y], dtype=float)
                        )[0]
                    )
        except Exception:
            graph_x = selection.graph_x
            graph_y = selection.graph_y
        scale = self.plot_window.painthelper.cgscale
        self.plot_window.pickeritem.setPos(graph_x * scale, graph_y * scale)
        self.plot_window.pickeritem.show()
        return True

    def clear_selection_visual(self) -> None:
        self.assert_gui_thread()
        self.plot_window.selectedWidgets([])
        if self._selection_overlay is not None:
            try:
                self.plot_window.scene.removeItem(self._selection_overlay)
            except RuntimeError:
                pass
            self._selection_overlay = None
        if self._direct_widget is not None:
            if self._direct_widget_had_override:
                self._direct_widget.updateControlItem = self._direct_widget_override
            elif "updateControlItem" in self._direct_widget.__dict__:
                delattr(self._direct_widget, "updateControlItem")
        self._direct_widget = None
        self._direct_widget_had_override = False
        self._direct_widget_override = None
        self._direct_manipulation_supported = False
        self._selection_path = None

    def _install_label_direct_manipulation(
        self,
        widget: Any,
        callback: Any,
    ) -> bool:
        x_setting = widget.settings.get("xPos")
        y_setting = widget.settings.get("yPos")
        if x_setting.isDataset(self.document) or y_setting.isDataset(self.document):
            return False
        controls = self.plot_window.painthelper.getControlGraph(widget)
        if not controls:
            return False
        self._direct_widget = widget
        self._direct_widget_had_override = "updateControlItem" in widget.__dict__
        self._direct_widget_override = widget.__dict__.get("updateControlItem")

        def routed_update(label_widget: Any, control: Any) -> None:
            points_x = list(label_widget.settings.xPos)
            points_y = list(label_widget.settings.yPos)
            index = int(control.index)
            x_value, y_value = label_widget._getGraphCoords(
                control.widgetposn,
                control.deltacrosspos[0] + control.posn[0],
                control.deltacrosspos[1] + control.posn[1],
            )
            if x_value is None or y_value is None:
                raise RuntimeError(
                    "The annotation drag could not be mapped to document coordinates."
                )
            points_x[index] = float(x_value)
            points_y[index] = float(y_value)
            callback(
                str(label_widget.path),
                [
                    {
                        "setting_path": f"{label_widget.path}/xPos",
                        "value": points_x,
                    },
                    {
                        "setting_path": f"{label_widget.path}/yPos",
                        "value": points_y,
                    },
                ],
                "Move a native annotation from the SciPlot Canvas.",
            )

        widget.updateControlItem = types.MethodType(routed_update, widget)
        self.plot_window.selectedWidgets([widget])
        self._direct_manipulation_supported = True
        return True

    def show_selection_visual(
        self,
        widget_path: str | None,
        *,
        color: str = "#308cc6",
        direct_callback: Any = None,
    ) -> dict[str, Any]:
        self.assert_gui_thread()
        self.clear_selection_visual()
        if not widget_path or self.plot_window.painthelper is None:
            return {"visible": False, "direct_manipulation": False}
        widget = self._widget(widget_path)
        self._selection_path = str(widget.path)
        if (
            widget.typename == "label"
            and direct_callback is not None
            and self._install_label_direct_manipulation(widget, direct_callback)
        ):
            return {
                "visible": True,
                "path": str(widget.path),
                "direct_manipulation": True,
            }
        bounds = self.plot_window.painthelper.widgetBounds(widget)
        if not bounds:
            return {
                "visible": False,
                "path": str(widget.path),
                "direct_manipulation": False,
            }
        scale = self.plot_window.painthelper.cgscale
        rect = self._QtCore.QRectF(
            self._QtCore.QPointF(float(bounds[0]) * scale, float(bounds[1]) * scale),
            self._QtCore.QPointF(float(bounds[2]) * scale, float(bounds[3]) * scale),
        ).normalized()
        pen = self._QtGui.QPen(
            self._QtGui.QColor(color),
            1.5,
            self._QtCore.Qt.PenStyle.DashLine,
        )
        pen.setCosmetic(True)
        overlay = self._QtWidgets.QGraphicsRectItem(rect)
        overlay.setPen(pen)
        overlay.setBrush(
            self._QtGui.QBrush(self._QtCore.Qt.BrushStyle.NoBrush)
        )
        overlay.setAcceptedMouseButtons(self._QtCore.Qt.MouseButton.NoButton)
        overlay.setZValue(3.0)
        self.plot_window.scene.addItem(overlay)
        self._selection_overlay = overlay
        return {
            "visible": True,
            "path": str(widget.path),
            "direct_manipulation": False,
            "bounds": [
                rect.left(),
                rect.top(),
                rect.right(),
                rect.bottom(),
            ],
        }

    @property
    def selection_overlay_visible(self) -> bool:
        return bool(
            self._selection_overlay is not None
            and self._selection_overlay.isVisible()
        )

    @property
    def direct_manipulation_supported(self) -> bool:
        return self._direct_manipulation_supported

    def structural_qa(self, session: CanvasSession) -> dict[str, Any]:
        """Run fast, non-exporting checks against the exact in-memory document."""

        self.assert_gui_thread()
        render_hash = self.force_redraw()
        checks: list[dict[str, Any]] = []

        def add(
            check_id: str,
            label: str,
            passed: bool,
            detail: Any,
            *,
            severity: str = "error",
        ) -> None:
            checks.append(
                {
                    "id": check_id,
                    "label": label,
                    "status": (
                        "passed"
                        if passed
                        else ("warning" if severity == "warning" else "failed")
                    ),
                    "severity": severity,
                    "detail": detail,
                }
            )

        add(
            "live_render",
            "The exact in-memory document has a visible render",
            bool(render_hash),
            {"render_sha256": render_hash},
        )
        page_size = tuple(float(value) for value in self.document.docSize())
        add(
            "page_geometry",
            "The current document has a positive page geometry",
            self.page_count > 0
            and len(page_size) == 2
            and all(math.isfinite(value) and value > 0 for value in page_size),
            {"page_count": self.page_count, "document_size": list(page_size)},
        )

        widgets: list[Any] = []

        def walk(parent: Any) -> None:
            for child in parent.children:
                widgets.append(child)
                walk(child)

        walk(self.document.basewidget)
        data_fields = {
            "xy": ("xData", "yData"),
            "image": ("data",),
            "contour": ("data",),
            "boxplot": ("values",),
        }
        missing_data: list[dict[str, Any]] = []
        visible_data_objects = 0
        for widget in widgets:
            field_names = data_fields.get(str(widget.typename))
            if field_names is None or bool(widget.settings.hide):
                continue
            visible_data_objects += 1
            for field_name in field_names:
                setting = widget.settings.get(field_name)
                try:
                    resolved = setting.getData(self.document)
                except Exception as exc:
                    missing_data.append(
                        {
                            "path": str(widget.path),
                            "field": field_name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                available = (
                    bool(resolved)
                    if isinstance(resolved, (list, tuple))
                    else resolved is not None
                )
                if not available:
                    missing_data.append(
                        {
                            "path": str(widget.path),
                            "field": field_name,
                            "value": setting.get(),
                        }
                    )
        add(
            "plot_data_resolves",
            "Every visible supported plot object resolves its source datasets",
            visible_data_objects > 0 and not missing_data,
            {
                "visible_data_objects": visible_data_objects,
                "missing": missing_data,
            },
        )

        invalid_axes: list[dict[str, Any]] = []
        for widget in widgets:
            if widget.typename not in {"axis", "colorbar"} or bool(
                widget.settings.hide
            ):
                continue
            plotted = tuple(float(value) for value in widget.plottedrange)
            valid = (
                len(plotted) == 2
                and all(math.isfinite(value) for value in plotted)
                and plotted[0] != plotted[1]
                and (not bool(widget.settings.log) or min(plotted) > 0)
            )
            if not valid:
                invalid_axes.append(
                    {
                        "path": str(widget.path),
                        "range": list(plotted),
                        "log": bool(widget.settings.log),
                    }
                )
        add(
            "axis_ranges_valid",
            "Visible axes have finite, non-degenerate ranges",
            not invalid_axes,
            {"invalid_axes": invalid_axes},
        )

        selected_id = session.selection.primary_object_id
        selected_record = (
            session.object_registry.by_id(selected_id) if selected_id else None
        )
        selection_valid = selected_id is None or (
            selected_record is not None
            and any(
                str(widget.path) == selected_record.current_path for widget in widgets
            )
        )
        add(
            "selection_resolves",
            "The persisted Canvas selection resolves to the current object tree",
            selection_valid,
            {
                "selected_object_id": selected_id,
                "selected_path": (
                    selected_record.current_path if selected_record else None
                ),
            },
        )
        add(
            "document_conflict_free",
            "The Canvas document has no unresolved external VSZ conflict",
            session.state != "conflict",
            {"state": session.state},
        )
        export_current = (
            session.exported_revision == session.revision
            and session.qa_summary.get("ready_to_use") is True
        )
        add(
            "artifact_qa_current",
            "The current revision has a passing artifact export",
            export_current,
            {
                "revision": session.revision,
                "exported_revision": session.exported_revision,
            },
            severity="warning",
        )
        failed_ids = [
            item["id"] for item in checks if item["status"] == "failed"
        ]
        warning_ids = [
            item["id"] for item in checks if item["status"] == "warning"
        ]
        status = "failed" if failed_ids else ("warning" if warning_ids else "passed")
        return {
            "kind": "sciplot_canvas_structural_qa",
            "version": 1,
            "status": status,
            "revision": session.revision,
            "ready_for_artifact_qa": not failed_ids,
            "summary": {
                "check_count": len(checks),
                "passed_count": sum(
                    item["status"] == "passed" for item in checks
                ),
                "failed_ids": failed_ids,
                "warning_ids": warning_ids,
            },
            "checks": checks,
        }

    def visible_text_targets(
        self,
        session: CanvasSession,
    ) -> list[dict[str, Any]]:
        candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
        for item in self.bind_object_registry(session):
            object_type = item["object_type"]
            if object_type not in {"axis", "label", "colorbar"}:
                continue
            setting_path = f"{item['path']}/label"
            try:
                setting = self.document.resolveSettingPath(None, setting_path)
            except ValueError:
                continue
            value = setting.get()
            widget_hidden = self._optional_bool_setting(f"{item['path']}/hide", False)
            label_hidden = (
                self._optional_bool_setting(f"{item['path']}/Label/hide", False)
                if object_type in {"axis", "colorbar"}
                else False
            )
            visible = not widget_hidden and not label_hidden
            auxiliary = "colorbar" in str(item["path"]).casefold()
            score = (
                0 if visible else 1,
                0 if str(value).strip() else 1,
                1 if auxiliary else 0,
                0 if object_type == "axis" else 1,
            )
            candidates.append(
                (
                    score,
                    {
                        **item,
                        "setting_path": setting_path,
                        "value": value,
                        "target_role": (
                            "axis_label"
                            if object_type == "axis"
                            else "visible_text_label"
                        ),
                        "visible": visible,
                    },
                )
            )
        if not candidates:
            return []
        candidates.sort(key=lambda item: item[0])
        return [target for _, target in candidates if target["visible"] is True]

    def first_visible_text_target(
        self,
        session: CanvasSession,
    ) -> dict[str, Any]:
        targets = self.visible_text_targets(session)
        if not targets:
            raise RuntimeError(
                "The document does not contain a visible editable text setting."
            )
        return targets[0]

    def first_axis_label_target(
        self,
        session: CanvasSession,
    ) -> dict[str, Any]:
        """Compatibility alias for the broader visible-text characterization seam."""

        return self.first_visible_text_target(session)

    def _optional_bool_setting(self, setting_path: str, default: bool) -> bool:
        try:
            return bool(self.document.resolveSettingPath(None, setting_path).get())
        except ValueError:
            return default

    def setting_value(self, setting_path: str) -> Any:
        self.assert_gui_thread()
        return self.document.resolveSettingPath(None, setting_path).get()

    @property
    def page_count(self) -> int:
        return int(self.document.getNumberPages())

    @property
    def current_page(self) -> int:
        return int(self.plot_window.getPageNumber())

    @property
    def current_page_path(self) -> str:
        pages = [
            child
            for child in self.document.basewidget.children
            if child.typename == "page"
        ]
        if not pages:
            raise RuntimeError("The Veusz document does not contain a page.")
        page_index = min(max(self.current_page, 0), len(pages) - 1)
        return str(pages[page_index].path)

    def set_page(self, page_index: int) -> int:
        self.assert_gui_thread()
        self.plot_window.setPageNumber(int(page_index))
        self.application.processEvents()
        self._sync_display_paper()
        self._restore_persisted_data_point()
        return self.current_page

    @property
    def zoom_factor(self) -> float:
        return float(self.plot_window.zoomfactor)

    def set_zoom_factor(self, zoom: float) -> float:
        self.assert_gui_thread()
        self.plot_window.setZoomFactor(float(zoom))
        self.application.processEvents()
        self._sync_display_paper()
        self._restore_persisted_data_point()
        return self.zoom_factor

    def zoom_to_page(self) -> float:
        self.assert_gui_thread()
        self.plot_window.slotViewZoomPage()
        self.application.processEvents()
        self._sync_display_paper()
        self._restore_persisted_data_point()
        return self.zoom_factor

    def validate_setting_value(self, setting_path: str, value: Any) -> Any:
        self.assert_gui_thread()
        setting = self.document.resolveSettingPath(None, setting_path)
        return setting.normalize(value)

    def apply_setting_batch(
        self,
        changes: list[dict[str, Any]],
        *,
        description: str,
    ) -> list[dict[str, Any]]:
        prepared = [
            {
                **change,
                "operation_type": "set_setting",
            }
            for change in changes
        ]
        return self.apply_operation_batch(prepared, description=description)

    def apply_operation_batch(
        self,
        operations_payload: list[dict[str, Any]],
        *,
        description: str,
    ) -> list[dict[str, Any]]:
        self.assert_gui_thread()
        prepared: list[dict[str, Any]] = []
        operations: list[Any] = []
        widget_operations: list[tuple[dict[str, Any], Any]] = []
        for payload in operations_payload:
            operation_type = str(payload.get("operation_type") or "set_setting")
            if operation_type == "set_setting":
                setting_path = str(payload["setting_path"])
                normalized = self.validate_setting_value(
                    setting_path,
                    payload["value"],
                )
                old_value = self.setting_value(setting_path)
                prepared.append(
                    {
                        "operation_type": operation_type,
                        "operation_id": payload.get("operation_id"),
                        "target_id": payload.get("target_id"),
                        "setting_path": setting_path,
                        "old_value": old_value,
                        "new_value": normalized,
                    }
                )
                operations.append(
                    self._OperationSettingSet(setting_path, normalized)
                )
                continue
            if operation_type == "add_widget":
                parent_path = str(payload["parent_path"])
                parent = self._widget(parent_path)
                index = int(payload.get("index", -1))
                widget_operation = self._OperationWidgetAdd(
                    parent,
                    str(payload["widget_type"]),
                    name=str(payload["name"]),
                    index=index,
                    **dict(payload["settings"]),
                )
                record = {
                    "operation_type": operation_type,
                    "operation_id": payload.get("operation_id"),
                    "target_id": payload.get("target_id"),
                    "parent_path": parent_path,
                    "widget_type": str(payload["widget_type"]),
                    "name": str(payload["name"]),
                    "index": index,
                    "settings": dict(payload["settings"]),
                }
                prepared.append(record)
                operations.append(widget_operation)
                widget_operations.append((record, widget_operation))
                continue
            raise ValueError(f"Unsupported Canvas operation: {operation_type!r}")
        self.document.applyOperation(
            self._OperationMultiple(
                operations, descr=description or "SciPlot canvas edit"
            )
        )
        for record, widget_operation in widget_operations:
            created_name = str(widget_operation.createdname)
            parent_path = str(record["parent_path"]).rstrip("/")
            record["created_path"] = f"{parent_path}/{created_name}"
        self.force_redraw()
        return prepared

    @property
    def can_undo(self) -> bool:
        return bool(self.document.canUndo())

    @property
    def can_redo(self) -> bool:
        return bool(self.document.canRedo())

    def undo(self) -> str:
        self.assert_gui_thread()
        if not self.can_undo:
            raise RuntimeError("The live canvas has no operation to undo.")
        self.document.undoOperation()
        return self.force_redraw()

    def redo(self) -> str:
        self.assert_gui_thread()
        if not self.can_redo:
            raise RuntimeError("The live canvas has no operation to redo.")
        self.document.redoOperation()
        return self.force_redraw()

    def save(self, path: Path | None = None) -> Path:
        self.assert_gui_thread()
        target = (path or self.document_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.document.save(str(target))
        self.document_path = target
        return target

    def save_recovery_snapshot(self, path: Path) -> Path:
        """Serialize current in-memory state without changing canonical authority."""

        self.assert_gui_thread()
        target = path.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        previous_filename = self.document.filename
        was_modified = self.document.isModified()
        try:
            self.document.save(str(target))
        finally:
            self.document.filename = previous_filename
            self.document.modified = was_modified
        return target

    def interaction_characterization(self) -> dict[str, Any]:
        """Exercise PlotWindow's selection and axis-coordinate seams."""

        self.assert_gui_thread()
        helper = self.plot_window.painthelper
        if helper is None:
            raise RuntimeError("PlotWindow has no PaintHelper after redraw.")

        bounds_items = list(helper.widgetBoundsIterator())
        graph_item = next(
            (
                (widget, bounds)
                for widget, bounds in bounds_items
                if widget.typename == "graph"
            ),
            None,
        )
        if graph_item is None:
            raise RuntimeError(
                "The document does not contain a graph interaction surface."
            )
        _, bounds = graph_item
        scene_x = ((float(bounds[0]) + float(bounds[2])) / 2.0) * helper.cgscale
        scene_y = ((float(bounds[1]) + float(bounds[3])) / 2.0) * helper.cgscale
        scene_point = self._QtCore.QPointF(scene_x, scene_y)
        viewport_point = self.plot_window.mapFromScene(scene_point)

        selected: list[dict[str, str]] = []

        def on_selected(widget: Any, mode: str) -> None:
            selected.append({"path": str(widget.path), "mode": str(mode)})

        self.plot_window.sigWidgetClicked.connect(on_selected)
        try:
            self.plot_window.identifyAndClickWidget(
                scene_x,
                scene_y,
                self._QtCore.Qt.KeyboardModifier.NoModifier,
            )
        finally:
            self.plot_window.sigWidgetClicked.disconnect(on_selected)

        axis_values = {
            str(axis.name): float(value)
            for axis, value in self.plot_window.axesForPoint(viewport_point).items()
        }
        return {
            "selection_signal_received": bool(selected),
            "selection": selected[-1] if selected else None,
            "axis_coordinates_reported": bool(axis_values),
            "axis_values": axis_values,
            "scene_point": [scene_x, scene_y],
        }

    def first_data_point_pick(self) -> Any:
        """Return a real PickInfo from the first visible pickable XY series."""

        self.assert_gui_thread()
        helper = self.plot_window.painthelper
        if helper is None:
            raise RuntimeError("PlotWindow has no PaintHelper after redraw.")
        for widget, bounds in helper.widgetBoundsIterator():
            if widget.typename != "xy" or bool(widget.settings.hide):
                continue
            center_x = (float(bounds[0]) + float(bounds[2])) / 2.0
            center_y = (float(bounds[1]) + float(bounds[3])) / 2.0
            pickinfo = widget.pickPoint(center_x, center_y, bounds)
            if getattr(pickinfo, "coords", None) is not None:
                return pickinfo
        raise RuntimeError(
            "The current page does not contain a visible pickable XY series."
        )

    def close(self) -> None:
        self.assert_gui_thread()
        self.clear_selection_visual()
        self.plot_window.rendercontrol.exitThreads()
        self.plot_window.close()
        self.application.processEvents()


__all__ = ["VeuszCanvasAdapter"]
