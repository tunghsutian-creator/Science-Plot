"""Separate file/container failures from scientific interpretation questions."""

from pathlib import Path
from typing import Any


class SourceInputError(ValueError):
    def __init__(self, reason_code: str, message: str, *, repair: dict[str, Any]) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.repair = repair
        self.issues = [{"code": reason_code, "message": message}]


def require_source_file(source: Path) -> None:
    if source.is_dir():
        files = sorted(str(path) for path in source.iterdir()
                       if path.is_file() and path.suffix.casefold() in {".csv", ".tsv", ".xlsx", ".xls", ".xlsm"})
        raise SourceInputError(
            "source_is_directory", "This input is a directory; select its original data files as task sources.",
            repair={"action": "select_source_files", "source": str(source), "files": files},
        )
    if not source.is_file():
        raise SourceInputError(
            "source_file_missing", "The original input file does not exist or is not a regular file.",
            repair={"action": "locate_source_file", "source": str(source)},
        )
