"""Capture private publication outputs while retaining scientific literals."""
from pathlib import Path
from typing import Any
import json
from sciplot_core.project_commands.resources import PreparedFile


def relocate_candidate(value: Any, roots: dict[Path, Path]) -> Any:
    """Relocate only private output paths, leaving scientific source literals intact."""
    if isinstance(value, dict):
        return {relocate_candidate(key, roots): relocate_candidate(item, roots) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate_candidate(item, roots) for item in value]
    if isinstance(value, str):
        for old, new in roots.items():
            if value == str(old) or value.startswith(str(old) + "/"):
                return str(new) + value[len(str(old)):]
    return value


def _stage_tree(root: Path, destination: str, writes: dict[str, bytes | Path | PreparedFile | None],
                roots: dict[Path, Path]) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("A private publication candidate cannot contain symlinks")
        if not path.is_file():
            continue
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            relocated = relocate_candidate(data, roots)
            if relocated != data:
                path.write_text(json.dumps(relocated, ensure_ascii=False, indent=2), encoding="utf-8")
        elif path.suffix in {".html", ".md"}:
            content = path.read_text(encoding="utf-8")
            for old, new in roots.items():
                content = content.replace(str(old), str(new))
            path.write_text(content, encoding="utf-8")
        writes[(destination + "/" if destination else "") + path.relative_to(root).as_posix()] = path
