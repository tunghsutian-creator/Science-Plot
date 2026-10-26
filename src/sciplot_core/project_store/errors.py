"""Explicit project-store conflict and recovery outcomes."""

from sciplot_core.foundation.source_errors import SourceVersionMismatch


class ProjectStoreError(ValueError):
    reason_code = "project_store_invalid"


class ProjectConflict(ProjectStoreError):
    reason_code = "project_generation_conflict"


class ProjectSourceVersionMismatch(ProjectConflict, SourceVersionMismatch):
    """A concrete byte conflict retains the existing project conflict contract."""


class ProjectRecoveryRequired(ProjectStoreError):
    reason_code = "project_recovery_required"


class ProjectCommandConflict(ProjectConflict):
    reason_code = "project_command_conflict"
