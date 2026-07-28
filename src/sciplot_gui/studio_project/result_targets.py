"""Open or reveal verified project result targets."""

from __future__ import annotations

from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core._paths import resolved_path_is_within


class ResultTargetsMixin:
    def _open_local_path(self, path: Path) -> bool:
        return bool(
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
        )

    def _open_result_target(
        self,
        key: str,
        *,
        reveal: bool = False,
    ) -> bool:
        results = (
            self.status_snapshot.get("results")
            if isinstance(self.status_snapshot.get("results"), dict)
            else {}
        )
        target = results.get(key) if isinstance(results.get(key), dict) else {}
        value = target.get("reveal_path") if reveal else target.get("path")
        if target.get("available") is not True or not isinstance(value, str):
            QtWidgets.QMessageBox.warning(
                self.window,
                "SciPlot result unavailable",
                "This result is not current and available yet.",
            )
            return False
        try:
            path = Path(value).expanduser().resolve()
            root_value = target.get("evidence_root")
            evidence_root = (
                Path(str(root_value)).expanduser().resolve()
                if isinstance(root_value, str) and root_value.strip()
                else None
            )
            within_root = bool(
                evidence_root is not None
                and resolved_path_is_within(path, evidence_root)
            )
            exists = path.is_dir() if reveal or key == "delivery" else path.is_file()
            expected_sha256 = str(target.get("sha256") or "").strip()
            hash_current = bool(
                not expected_sha256 or existing_file_sha256(path) == expected_sha256
            )
        except (OSError, RuntimeError, ValueError):
            exists = False
            within_root = False
            hash_current = False
            path = Path(value)
        if not (exists and within_root and hash_current):
            QtWidgets.QMessageBox.warning(
                self.window,
                "SciPlot result unavailable",
                "The result path is missing, changed, or outside its "
                f"validated root:\n{path}",
            )
            return False
        if self._open_local_path(path):
            return True
        QtWidgets.QMessageBox.warning(
            self.window,
            "SciPlot could not open the result",
            f"The operating system did not open:\n{path}",
        )
        return False

    def open_current_pdf(self) -> bool:
        return self._open_result_target("pdf")

    def show_current_delivery(self) -> bool:
        return self._open_result_target("delivery")

    def reveal_current_vsz(self) -> bool:
        return self._open_result_target("vsz", reveal=True)
