"""Isolated project-fixture setup for native diagnostics and regression tests.

The interactive Project-dock lifecycle probe is retired. These finite helpers
retain the real figure-set diagnostic's admitted clone and source boundaries;
they do not construct a window or aggregate a second readiness state.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core._paths import resolved_path_is_within


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload


def _source_mutation_target(
    source_path: object,
    *,
    project_dir: Path,
) -> Path | None:
    if not isinstance(source_path, str) or not source_path.strip():
        return None
    if (project_dir / ".sciplot_store").exists():
        from sciplot_core.project_host_factory import project_store
        from sciplot_core.project_store.runtime import inspect_runtime_source_file, project_runtime
        from sciplot_core.studio_core.project_query_sources import current_source_files

        store = project_store(project_dir)
        with project_runtime(store):
            files, identities = current_source_files(project_dir, Path(source_path), [
                {"status": "ready", "spec": str(project_dir / "studio/spec.json")},
            ])
            for literal, digest in sorted(files.items()):
                fact = inspect_runtime_source_file(literal, expected_sha256=digest,
                                                  source_id=identities.get(literal))
                if fact.physical is not None and resolved_path_is_within(fact.physical, project_dir):
                    return fact.physical
        return None
    source = Path(source_path).expanduser().resolve()
    candidates = [source] if source.is_file() else sorted(source.rglob("*"))
    for candidate in candidates:
        if candidate.is_file() and resolved_path_is_within(candidate, project_dir):
            return candidate.resolve()
    return None


def _rebase_path_value(
    value: object,
    *,
    source_project: Path,
    copied_project: Path,
) -> object:
    if not isinstance(value, str) or not value.strip():
        return value
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return value
    try:
        relative = candidate.resolve().relative_to(source_project)
    except ValueError:
        return value
    return str((copied_project / relative).resolve())


def _rebase_project_paths(
    value: object,
    *,
    source_project: Path,
    copied_project: Path,
) -> object:
    if isinstance(value, dict):
        return {
            key: _rebase_project_paths(
                item,
                source_project=source_project,
                copied_project=copied_project,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rebase_project_paths(
                item,
                source_project=source_project,
                copied_project=copied_project,
            )
            for item in value
        ]
    return _rebase_path_value(
        value,
        source_project=source_project,
        copied_project=copied_project,
    )


def _rebase_copied_render_metadata(
    source_project: Path,
    copied_project: Path,
    *,
    preserve_stale_registry_paths: bool,
) -> None:
    from sciplot_core.foundation.source_tree import source_tree_sha256
    from sciplot_core.source_coverage.managed_documents import source_records

    for name in ("raw", "source"):
        original = source_project / name
        if original.exists() and source_tree_sha256(original) != source_tree_sha256(
            copied_project / name
        ):
            raise ValueError(f"Copied fixture {name} tree differs from its source.")
    for document in (copied_project / "studio").rglob("*.vsz"):
        original = source_project / document.relative_to(copied_project)
        if file_sha256(document) != file_sha256(original):
            raise ValueError("Copied fixture must preserve exact-current VSZ bytes.")
    for path in sorted((copied_project / "studio").rglob("*.json")):
        payload = _read_json_object(path)
        if payload.get("kind") == "sciplot_veusz_plot_spec":
            for original, digest in source_records(payload).items():
                try:
                    relative = original.relative_to(source_project)
                except ValueError as exc:
                    raise ValueError(
                        "Fixture specification cites a source outside its project."
                    ) from exc
                copied_source = copied_project / relative
                if (
                    file_sha256(original) != digest
                    or file_sha256(copied_source) != digest
                ):
                    raise ValueError(
                        "Copied fixture source does not match its specification hash."
                    )
        rebound = _rebase_project_paths(
            payload, source_project=source_project, copied_project=copied_project
        )
        if not isinstance(rebound, dict):
            raise ValueError("Copied fixture render metadata must remain an object.")
        if (
            preserve_stale_registry_paths
            and path == copied_project / "studio" / "figure_set.json"
        ):
            # Keep every persisted projection, including outcome artifacts, in
            # one coherent old registry. The independent reader probe checks
            # path relocation; export probes use fully rebound metadata.
            rebound = payload
        path.write_text(
            json.dumps(json_safe(rebound), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _copy_project_fixture(
    source_project: Path,
    run_root: Path,
    *,
    preserve_stale_registry_paths: bool = False,
) -> Path:
    source_project = source_project.expanduser().resolve()
    copied_project = run_root / "project"
    if (source_project / ".sciplot_store").exists():
        from sciplot_core.project_host_factory import project_store
        from sciplot_core.project_store import FileProjectStore, ProjectConflict

        # This is an explicit isolated clone, not a raw directory move. Keep
        # admitted scientific locators, source UUIDs/history and native bytes;
        # the existing import owns registration of the new physical roots.
        original = project_store(source_project)
        before = original.snapshot()
        if before["projection_status"] != "current":
            raise ProjectConflict("The probe cannot clone unadmitted project changes.")
        run_root.mkdir(parents=True, exist_ok=True)
        bundle = original.export_bundle(run_root / "project.bundle")
        after = original.snapshot()
        if after["generation"] != before["generation"] or after["projection_status"] != "current":
            raise ProjectConflict("The probe cannot clone unadmitted project changes.")
        clone = FileProjectStore.import_bundle(bundle, copied_project)
        if clone.snapshot()["generation"] != before["generation"]:
            raise ProjectConflict("The probe clone differs from its selected generation.")
        return clone.root
    shutil.copytree(
        source_project,
        copied_project,
        ignore=shutil.ignore_patterns(
            "runs",
            "delivery",
            "exports",
            "*.zip",
        ),
    )
    _rebase_copied_render_metadata(
        source_project,
        copied_project.resolve(),
        preserve_stale_registry_paths=preserve_stale_registry_paths,
    )
    request_path = copied_project / "plot_request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Copied plot_request.json must contain an object.")
    request = _rebase_project_paths(
        request,
        source_project=source_project,
        copied_project=copied_project,
    )
    request_path.write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    for manifest_path in [
        copied_project / "intake_manifest.json",
        *sorted(copied_project.glob("*.sciplot.json")),
    ]:
        if not manifest_path.is_file():
            continue
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        # Rebasing path leaves preserves the dictionary admitted above.
        payload = cast(dict[str, Any], _rebase_project_paths(
            payload,
            source_project=source_project,
            copied_project=copied_project,
        ))
        for key in (
            "last_run",
            "package_contract",
            "delivery_package",
            "layout_quality",
        ):
            payload.pop(key, None)
        studio_value = payload.get("studio")
        studio = studio_value if isinstance(studio_value, dict) else {}
        for key in ("exports", "last_export_run"):
            studio.pop(key, None)
        studio["document"] = str((copied_project / "studio" / "document.vsz").resolve())
        studio["generated_from"] = str(request_path.resolve())
        payload["studio"] = studio
        manifest_path.write_text(
            json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return copied_project.resolve()


def _publish_fixture_setup(project: Path, writes: dict[Path, bytes | None], *,
                           modes: dict[Path, int] | None = None) -> None:
    """Publish the probe's intentional producer state through the sole writer.

    Deliberate outside-edit refusal controls do not use this helper. Scientific
    inputs and native user edits retain their existing source/save owners.
    """
    from sciplot_core.project_commands.resources import PreparedFile
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store.adapters import publish_files

    legacy = not (project / ".sciplot_store").exists()
    store = project_store(project)
    snapshot = store.snapshot(import_legacy=legacy)
    logical = {store.logical_path(path): data for path, data in writes.items()}
    permissions = {store.logical_path(path): mode for path, mode in (modes or {}).items()}
    observed = {name: entry["sha256"] for name, entry in snapshot["files"].items()}
    for name in logical:
        observed.setdefault(name, None)
    publish_files(store, {
        name: PreparedFile(data, permissions.get(name, snapshot["files"].get(name, {}).get("mode", 0o600)))
        if data is not None else None for name, data in logical.items()
    }, kind="publish", result={"probe": "studio_project_fixture_setup"}, baseline={
        "project_id": snapshot["project_id"], "generation": snapshot["generation"], "files": observed,
    })


if __name__ == "__main__":
    raise SystemExit(
        "studio_project_probe_retired: The Project-dock diagnostic is retired. "
        "Use the existing headless project/figure-set verification routes; no target was opened."
    )
