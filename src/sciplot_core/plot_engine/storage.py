"""Compatibility names for the single project repository; no storage implementation."""
from sciplot_core.project_lifecycle.context import (
    active, commit, digest, document_root, load_head, persist, read, reserve,
    transaction_path, write,
)

__all__ = ["active", "commit", "digest", "document_root", "load_head", "persist", "read", "reserve",
           "transaction_path", "write"]
