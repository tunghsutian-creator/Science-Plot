"""Create and save a Veusz document from an already validated plot specification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe

from sciplot_core.studio_core.runtime import (
    _ensure_veusz_on_path,
    _capture_process_stderr,
)

from sciplot_core.studio_core.launchers import (
    _prefer_offscreen_export_platform,
)

from sciplot_core.studio_core.veusz_apply import (
    _apply_veusz_spec,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_path,
)


def _save_veusz_document_from_spec(
    path: Path,
    spec: dict[str, Any],
    *,
    spec_path: Path | None = None,
) -> None:
    from sciplot_core.veusz_runtime import (
        needs_veusz_worker_process,
        veusz_worker_environment,
    )

    if needs_veusz_worker_process():
        resolved_spec = spec_path or _veusz_spec_path(path)
        if not resolved_spec.exists():
            resolved_spec.parent.mkdir(parents=True, exist_ok=True)
            resolved_spec.write_text(
                json.dumps(json_safe(spec), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.veusz_worker",
                "save-spec",
                str(path),
                str(resolved_spec),
            ],
            text=True,
            capture_output=True,
            check=True,
            env=veusz_worker_environment(),
        )
        return
    stderr_log = path.parent / "logs" / "veusz_generate_stderr.log"
    with _capture_process_stderr(stderr_log):
        _prefer_offscreen_export_platform()
        _ensure_veusz_on_path()
        from PyQt6 import QtWidgets
        from veusz import dataimport, document, widgets
        from veusz.document import CommandInterface

        _ = dataimport, widgets
        app = QtWidgets.QApplication.instance()
        created_app = app is None
        if app is None:
            app = QtWidgets.QApplication([])
        try:
            doc = document.Document()
            interface = CommandInterface(doc)
            _apply_veusz_spec(interface, spec)
            path.parent.mkdir(parents=True, exist_ok=True)
            interface.Save(str(path))
            load_test = document.Document()
            load_test.load(str(path))
        finally:
            if created_app:
                app.quit()
