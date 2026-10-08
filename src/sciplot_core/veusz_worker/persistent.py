"""Serial internal command loop; retain Qt, reopen native documents on every call."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import gc
import os
import sys
import tempfile
import traceback
from typing import Any, Iterator, TextIO

from sciplot_core.native_process.protocol import (MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES, decode, encode, validate_request)


@contextmanager
def _capture() -> Iterator[tuple[TextIO, TextIO]]:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error:
        sys.stdout.flush()
        sys.stderr.flush()
        old_out, old_err = os.dup(1), os.dup(2)
        try:
            os.dup2(output.fileno(), 1)
            os.dup2(error.fileno(), 2)
            with redirect_stdout(output), redirect_stderr(error):
                yield output, error
        finally:
            output.flush()
            error.flush()
            os.dup2(old_out, 1)
            os.dup2(old_err, 2)
            os.close(old_out)
            os.close(old_err)


def _application() -> Any:
    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat

    ensure_veusz_runtime_path()
    ensure_veusz_loader_compat()
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def serve() -> int:
    app: Any = None
    try:
        while True:
            raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if not raw:
                return 0
            if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                return 2
            try:
                request_id, argv = validate_request(decode(raw))
            except (ValueError, UnicodeError):
                return 2
            with _capture() as (output, error):
                try:
                    if app is None:
                        app = _application()
                    from sciplot_core.veusz_worker.cli import main

                    code = main(argv)
                except SystemExit as exc:
                    code = exc.code if type(exc.code) is int else 1
                except Exception:
                    traceback.print_exc()
                    code = 1
                finally:
                    gc.collect()
                output.seek(0)
                error.seek(0)
                stdout, stderr = output.read(MAX_STDOUT_BYTES + 1), error.read(MAX_STDERR_BYTES + 1)
                if len(stdout.encode()) > MAX_STDOUT_BYTES or len(stderr.encode()) > MAX_STDERR_BYTES:
                    return 2
            response = encode({"id": request_id, "returncode": code, "stdout": stdout, "stderr": stderr, "pid": os.getpid()})
            if len(response) > MAX_RESPONSE_BYTES:
                return 2
            sys.stdout.buffer.write(response)
            sys.stdout.buffer.flush()
    finally:
        if app is not None:
            app.quit()


if __name__ == "__main__":
    raise SystemExit(serve())
