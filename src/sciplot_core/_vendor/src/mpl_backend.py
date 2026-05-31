from __future__ import annotations

import matplotlib

# All rendering in SciPlot is file/preview oriented, so a non-interactive
# backend avoids macOS GUI backend crashes inside FastAPI worker threads.
matplotlib.use("Agg", force=True)
