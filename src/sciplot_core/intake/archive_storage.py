"""Privately serialize archive candidates and publish their exact file capability."""

import json
import os
from pathlib import Path

def _write_zip_snapshot_unlocked(project_root: Path, zip_path: Path) -> None:
    from sciplot_core.foundation.project_archives import write_project_archive
    from sciplot_core.project_manifest import _is_private_snapshot_root, _stage_snapshot
    from sciplot_core.project_store import ResourceRoot
    from sciplot_core.project_store.adapters import project_storage_scope, publish_files

    if _is_private_snapshot_root(project_root):
        write_project_archive(project_root, zip_path)
        return
    recognized = any((project_root / name).exists() for name in
                     ("intake_manifest.json", "plot_request.json", "suite.json", ".sciplot_store/head.json"))
    recognized = recognized or bool(list(project_root.glob("*.sciplot.json")))
    if not recognized:
        # An ordinary folder archive has no project state to publish. Keep its
        # closed single-output serializer independent of the project repository.
        from contextlib import ExitStack
        from tempfile import TemporaryDirectory
        import time
        from sciplot_core.foundation.writer_lease import WriterLeaseBusy, exclusive_directory_lease
        from sciplot_core.project_manifest import _PROJECT_MANIFEST_LOCK
        from sciplot_core.project_store.io import install, read_file

        destination = zip_path.expanduser().absolute()
        if destination.is_symlink():
            raise PermissionError("Refusing to replace a symlink-backed SciPlot ZIP.")
        with _PROJECT_MANIFEST_LOCK, ExitStack() as guards:
            while True:
                try:
                    lease = guards.enter_context(exclusive_directory_lease(project_root))
                    break
                except WriterLeaseBusy:
                    time.sleep(0.01)
            parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with TemporaryDirectory(prefix="sciplot-folder-archive-") as folder:
                    staged = Path(folder) / destination.name
                    write_project_archive(project_root, staged)
                    lease.verify()
                    observed, opened = destination.parent.lstat(), os.fstat(parent)
                    if (observed.st_dev, observed.st_ino) != (opened.st_dev, opened.st_ino):
                        raise RuntimeError("The archive destination directory changed identity.")
                    if destination.is_symlink():
                        raise PermissionError("Refusing to replace a symlink-backed SciPlot ZIP.")
                    install(parent, destination.name, staged.read_bytes())
                    read_file(parent, destination.name)
            finally:
                os.close(parent)
        return
    target = zip_path.expanduser().absolute()
    if target.is_symlink():
        raise PermissionError("Refusing to replace a symlink-backed SciPlot ZIP.")
    with project_storage_scope(project_root, locations={"snapshot": ResourceRoot(target.parent, (target.name,))}) as store:
        snapshot = store.snapshot()
        manifest_entry = snapshot["files"].get("intake_manifest.json")
        payload = json.loads(store.read_bytes("intake_manifest.json")) if manifest_entry else {}
        # The declared target is selected by the host, not discovered from its parent.
        payload = {**payload, "project_slug": target.stem}
        data = _stage_snapshot(store, payload, {})
        publish_files(store, {"@snapshot/" + target.name: data}, kind="publish", result={"zip": str(target)})


