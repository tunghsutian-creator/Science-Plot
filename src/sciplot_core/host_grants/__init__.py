"""Explicit host authorization, separate from sealed scientific identities."""
from .authorization import admit_document_executors, admit_registration, authorize_external
from .context import execution_context, using_host_registry
from .models import EXECUTE_TRANSFORM, SourceScope
from .registry import HostRegistry

__all__ = ["EXECUTE_TRANSFORM", "HostRegistry", "SourceScope", "admit_document_executors",
           "admit_registration", "authorize_external", "execution_context", "using_host_registry"]
