"""Keep one known categorical rejection closed despite native settings chatter."""
from collections.abc import Iterator
from contextlib import contextmanager
import json
import sys

from sciplot_core.studio_core.categorical_display_errors import CategoricalPresentationConflict
from sciplot_core.veusz_worker.persistent import _capture


@contextmanager
def categorical_rejection_frame() -> Iterator[None]:
    output_text, error_text = "", ""
    try:
        with _capture() as (output, error):
            try:
                yield
            except CategoricalPresentationConflict as exc:
                # The exception type is authoritative; never infer a conflict from stderr text.
                error.seek(0)
                error.truncate()
                print(json.dumps({"kind": "sciplot_worker_preparation_blocked", "version": 1,
                                  "reason_code": exc.reason_code, "message": str(exc)}), file=error)
                raise SystemExit(1) from None
            finally:
                output.flush()
                error.flush()
                output.seek(0)
                error.seek(0)
                output_text, error_text = output.read(), error.read()
    finally:
        sys.stdout.write(output_text)
        sys.stderr.write(error_text)
