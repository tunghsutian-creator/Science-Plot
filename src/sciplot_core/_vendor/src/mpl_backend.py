from __future__ import annotations

import os

import matplotlib

# All rendering in SciPlot is file/preview oriented, so a non-interactive
# backend avoids macOS GUI backend crashes inside FastAPI worker threads.
matplotlib.use(os.environ.get("SCIPLOT_MPL_BACKEND", "Agg"), force=True)
