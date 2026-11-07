"""Decode only the inert binding comment in a historical v1 launcher."""

from __future__ import annotations

import json
from sciplot_core.delivery_binding import DeliveryBinding, delivery_binding_from_payload

DELIVERY_BINDING_PREFIX = "# SCIPLOT_DELIVERY_BINDING_V1 "


def delivery_binding_from_content(content: str) -> DeliveryBinding | None:
    lines = [line for line in content.splitlines() if line.startswith(DELIVERY_BINDING_PREFIX)]
    if not lines:
        return None
    if len(lines) != 1:
        raise ValueError("The delivery launcher contains multiple identity records.")
    return delivery_binding_from_payload(json.loads(lines[0][len(DELIVERY_BINDING_PREFIX):]))
