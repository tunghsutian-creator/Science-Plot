"""Backend compatibility profile data; no backend implementation import."""
from typing import Any

# The existing compatibility facade advertises this bounded grammar contract.
# Pure applications can instead inject their backend's own explicit profile.
COMPATIBILITY_CAPABILITIES: dict[str, Any] = {
    "marks": ["line", "point", "bar", "errorbar", "band", "rule", "text"],
    "scale_transforms": ["linear", "log"], "multi_view": True, "multiple_scales": True,
}
