import json
import sys

from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.veusz_worker import main

try:
    raise SystemExit(main())
except StudioPreparationBlocked as exc:
    # Domain rejection is distinct from a crashed worker. Keep stdout reserved
    # for successful export results and expose one closed failure envelope.
    print(json.dumps({"kind": "sciplot_worker_preparation_blocked", "version": 1,
                      "reason_code": exc.reason_code, "message": str(exc)}), file=sys.stderr)
    raise SystemExit(1) from None
