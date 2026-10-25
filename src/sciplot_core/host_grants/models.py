"""Host permissions are separate from scientific identities and OS isolation."""
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, NoReturn

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document.errors import fail

EXECUTE_TRANSFORM = "transform.execute"


def denied(code: str, message: str) -> NoReturn:
    fail(code, message, "/executor", "explicit_host_grant")


@dataclass(frozen=True)
class SourceScope:
    source_id: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        path = Path(self.path)
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", self.source_id)
                or not path.is_absolute() or str(path) != str(path.resolve())
                or not re.fullmatch(r"[0-9a-f]{64}", self.sha256)):
            denied("host_source_scope_invalid", "A host source scope needs an exact ID, physical absolute path and SHA-256.")

    def to_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "path": self.path, "sha256": self.sha256}

    @classmethod
    def of(cls, value: dict[str, Any]) -> "SourceScope":
        return cls(value["source_id"], value["path"], value["sha256"])

    @classmethod
    def local_file(cls, source_id: str, path: Path) -> "SourceScope":
        physical = path.resolve(strict=True)
        return cls(source_id, str(physical), file_sha256(physical))
