"""Compatibility import for the project lifecycle owner; no parallel implementation."""
import sys
from sciplot_core.project_lifecycle import exports as _owner

sys.modules[__name__] = _owner
