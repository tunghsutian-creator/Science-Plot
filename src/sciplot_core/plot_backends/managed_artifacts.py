"""Capture the Managed adapter's finite native IO without scientific path grants."""
from contextlib import AbstractContextManager, nullcontext
import os
from pathlib import Path

from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_store.io import read_file, sha


def artifact_scope(arguments: list[str], *, inputs: dict[str, Path],
                   outputs: dict[str, Path] | None = None) -> AbstractContextManager[None]:
    if selected_source_resolver() is None:
        return nullcontext()
    from sciplot_core.project_store.native_artifacts import (
        NativeArtifactInput, NativeArtifactOutput, native_artifact_runtime,
    )

    captured = []
    for role, path in inputs.items():
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            data, mode = read_file(descriptor, path.name, owned=True)
        finally:
            os.close(descriptor)
        captured.append(NativeArtifactInput(role, path, sha(data), mode))
    return native_artifact_runtime(arguments, inputs=tuple(captured),
        outputs=tuple(NativeArtifactOutput(role, path) for role, path in (outputs or {}).items()))
