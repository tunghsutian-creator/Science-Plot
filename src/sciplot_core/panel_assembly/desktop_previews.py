"""Frozen-source preview cache; native rendering never runs on the GUI thread."""

from collections import OrderedDict

from PyQt6 import QtCore, QtGui

from sciplot_core.foundation.json_hashing import canonical_json_sha256

from .desktop_jobs import AssemblyJob


def preview_key(source):
    return canonical_json_sha256(source, allow_nan=False)


class SourcePreviews(QtCore.QObject):
    updated = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = OrderedDict()
        self._errors = {}
        self._pending = OrderedDict()
        self._job = None
        self._active = None

    @property
    def busy(self):
        return self._job is not None or bool(self._pending)

    def get(self, source):
        return self._cache.get(preview_key(source), QtGui.QPixmap())

    def error(self, source):
        return self._errors.get(preview_key(source))

    def retry(self, source):
        self._errors.pop(preview_key(source), None)

    def request_document(self, document):
        wanted = {preview_key(panel["source"]) for panel in document["panels"]}
        self._pending = OrderedDict((key, source) for key, source in self._pending.items() if key in wanted)
        for panel in document["panels"]:
            source = panel["source"]
            key = preview_key(source)
            if key not in self._cache and key not in self._errors and key != self._active:
                self._pending.setdefault(key, source)
        self._start_next()

    def _start_next(self):
        if self._job is not None or not self._pending:
            return
        from .preview import render_preview

        self._active, source = self._pending.popitem(last=False)
        self._job = AssemblyJob(lambda: render_preview(source), self)
        self._job.succeeded.connect(self._complete)
        self._job.failed.connect(self._failed)
        self._job.finished.connect(self._finished)
        self._job.start()

    def _complete(self, png_bytes):
        image = QtGui.QImage.fromData(png_bytes, "PNG")
        if image.isNull():
            self._failed("The source preview could not be decoded.")
            return
        image = image.scaled(600, 600, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                             QtCore.Qt.TransformationMode.SmoothTransformation)
        self._cache[self._active] = QtGui.QPixmap.fromImage(image)
        while len(self._cache) > 256:
            self._cache.popitem(last=False)
        self.updated.emit(self._active)

    def _failed(self, message):
        self._errors[self._active] = message
        self.failed.emit(self._active, message)
        self.updated.emit(self._active)

    def _finished(self):
        self._job.deleteLater()
        self._job = None
        self._active = None
        self._start_next()
