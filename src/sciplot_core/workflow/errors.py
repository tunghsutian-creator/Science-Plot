"""Known pre-render outcomes, distinct from unknown native execution failures."""


class WorkflowIntervention(ValueError):
    """Preparation stopped before rendering and wrote an assisted-repair request."""
