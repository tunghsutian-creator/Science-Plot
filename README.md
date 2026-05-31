# SciPlot Codex Core

Self-contained headless SciPlot core for Codex-driven scientific plotting and materials data cleanup.

This repo replaces the retired local `codegod` app workflow. It must remain usable without Xcode, the macOS app, the sidecar server, or the old `codegod` checkout.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m sciplot_core.cli inspect examples/curve_table.csv --json
.venv/bin/python -m sciplot_core.cli render examples/curve_table.csv --template curve --out /tmp/sciplot-render
.venv/bin/python -m sciplot_core.cli qa /tmp/sciplot-render --goldens tests/goldens
```

The installed Codex skill calls the same CLI through:

```bash
/Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot
```

## Rules

- Keep `plot_contract.json`, the renderer, layout policy, tick policy, and QA as the source of visual truth.
- Do not hand-copy Matplotlib style constants into recipe scripts.
- Recipes prepare data and analysis artifacts, then render through `sciplot_core.render_to_dir`.
- If a new dataset needs custom handling, patch the matching recipe, add a fixture, and add a QA or golden assertion.
