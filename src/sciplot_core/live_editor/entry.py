"""Resolve an editor entry without losing figure identity or visible-copy edits."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.policy import DELIVERY_LAUNCHER
from sciplot_core.studio_core.delivery_target import resolve_delivery_target
from sciplot_core.studio_core.project_query_paths import canonical_path


def resolve_editor_input(value: Path, *, portable_fallback: bool = False) -> tuple[Path, bool]:
    path = canonical_path(value)
    # Import lazily: the editor and delivery adapters share only launcher contracts.
    from sciplot_core.policy import DELIVERY_EDITOR_LAUNCHER
    from sciplot_core.launchers.delivery_editor_launcher import inspect_delivery_editor_launcher_contract

    if path.name == DELIVERY_EDITOR_LAUNCHER:
        if inspect_delivery_editor_launcher_contract(path.parent).get("ready") is not True:
            raise ValueError("画板启动入口已变化或不完整，请从原工程重新导出交付。")
        path = path.parent
    root = path if path.is_dir() else path.parent.parent if path.suffix.lower() == ".vsz" and path.parent.name == "project" else path.parent
    editor_launcher = root / DELIVERY_EDITOR_LAUNCHER
    if (editor_launcher.exists() or editor_launcher.is_symlink()) and inspect_delivery_editor_launcher_contract(root).get("ready") is not True:
        raise ValueError("画板启动入口已变化或不完整，请从原工程重新导出交付。")
    if (root / "project").is_dir() and (root / DELIVERY_LAUNCHER).is_file():
        resolved = resolve_delivery_target(root)
        if resolved is not None and resolved["mode"] == "vsz":
            if not portable_fallback:
                raise ValueError("此交付副本已脱离原工程。请使用 Open_in_Veusz.command 编辑便携 VSZ，或回到原交付目录打开画板。")
            document = path if path.suffix.lower() == ".vsz" else Path(resolved["document"])
            document = canonical_path(document)
            if not document.is_file():
                raise FileNotFoundError(f"便携图形文件不存在：{document}")
            return document, True
    return path, False
