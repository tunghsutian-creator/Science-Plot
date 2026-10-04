"""Shared presentation helpers for source-bound rheology figure plans."""

import math

from sciplot_core.policy import DEFAULT_FIGURE_SIZE, DEFAULT_PALETTE_COLORS, WIDE_FIGURE_SIZE
from sciplot_core.studio_render.value_parsing import _size_mm

COLORS = dict(zip((0, 2, 4, 6), DEFAULT_PALETTE_COLORS[:4], strict=True))
OMEGA = "Angular frequency, ω (rad s^{-1})"
REDUCED = "Reduced frequency, a_{T}ω (rad s^{-1})"
INV_T = "1000/T (K^{-1})"


def _color(sample: dict) -> str:
    return COLORS[float(sample["udc_wt_percent"])]


def curve(label: str, x: list, y: list, color: str, **kwargs) -> dict:
    return {"label": label, "x": x, "y": y, "color": color, **kwargs}


def panel(identifier: str, title: str, x: str, y: str, series: list, **kwargs) -> dict:
    for axis in ("x", "y"):
        values = [value for entry in series for value in entry[axis]]
        lo, hi = min(values), max(values)
        if kwargs.get(f"{axis}scale") == "log":
            bounds = (lo / 1.3, hi * 1.3)
        else:
            padding = .06 * (hi - lo or abs(hi) or 1)
            bounds = (lo - padding, hi + padding)
        kwargs.setdefault(f"{axis}_min", bounds[0])
        kwargs.setdefault(f"{axis}_max", bounds[1])
    return {"id": identifier, "title": title, "rect_mm": [0, 0, 80, 80],
            "x_label": x, "y_label": y, "series": series, "legend": "upper_left", **kwargs}


def frequency_panel(samples: list, polymer: str, identifier: str, *, viscosity=False) -> dict:
    curves = []
    for sample in samples:
        if sample["polymer"] != polymer:
            continue
        points = sample["block"]["points"]
        x = [p["omega_rad_s"] for p in points]
        label = "Control" if sample["udc_wt_percent"] == 0 else f'{sample["udc_wt_percent"]:g} wt% UDC'
        metrics = (("complex_viscosity_Pa_s", "solid"),) if viscosity else (("storage_modulus_Pa", "solid"), ("loss_modulus_Pa", "dash"))
        for metric, style in metrics:
            curves.append(curve(label if style == "solid" else "", x, [p[metric] for p in points],
                                _color(sample), line_style=style, marker="none"))
    return panel(identifier, f'{identifier}  {polymer}, 210 °C', OMEGA,
        "Complex viscosity, η* (Pa s)" if viscosity else "G′, G″ (Pa)", curves,
        xscale="log", yscale="log", x_min=0.08, x_max=130,
        y_min=300 if viscosity else 5, y_max=500000 if viscosity else 200000,
        notes=[] if viscosity else [{"text": "Solid: G′   Dashed: G″", "x": .04, "y": .04}])


def master_panel(samples: list, identifier: str, title: str) -> dict:
    curves = []
    for sample in samples:
        for i, block in enumerate(sample["master_curves"]):
            points = block["points"]
            curves.append(curve(sample["sample_id"] if i == 0 else "",
                [p["omega_reduced_rad_s"] for p in points], [p["storage_modulus_Pa"] for p in points],
                _color(sample), line_style="none", marker="circle" if sample["polymer"] == "HDPE" else "diamond",
                marker_fill=_color(sample) if sample["polymer"] == "HDPE" else "none", marker_size=2.0))
    return panel(identifier, title, REDUCED, "G′ (Pa)", curves, xscale="log", yscale="log",
        x_min=.008, x_max=5000, y_min=5, y_max=200000,
        notes=[{"text": "T_{ref} = 210 °C; b_{T} = 1", "x": .43, "y": .04}])


def arrhenius_panel(samples: list, identifier: str, title: str) -> dict:
    curves = []
    for sample in samples:
        rows = sample["arrhenius"]["rows"]
        x = [row["inverse_temperature_1000_K"] for row in rows]
        color = _color(sample)
        curves.append(curve(sample["sample_id"], x, [r["ln_aT"] for r in rows], color,
            line_style="none", marker="circle" if sample["polymer"] == "HDPE" else "diamond",
            marker_fill=color if sample["polymer"] == "HDPE" else "none", marker_size=3.0))
        curves.append(curve("", x, [r["ln_aT_fit"] for r in rows], color,
            line_style="solid" if sample["polymer"] == "HDPE" else "dash", marker="none"))
    return panel(identifier, title, INV_T, "ln a_{T}", curves,
                 x_min=1.92, x_max=2.45, y_min=-1.5, y_max=3.5)


MODULI = (
    ("Gprime", "storage_modulus_Pa", "storage_modulus_reduced_Pa", "G′"),
    ("Gdoubleprime", "loss_modulus_Pa", "loss_modulus_reduced_Pa", "G″"),
)


def content_label(sample: dict) -> str:
    return "Control" if sample["udc_wt_percent"] == 0 else f'{sample["udc_wt_percent"]:g} wt% UDC'


def sample_stem(sample: dict) -> str:
    content = "Control" if sample["udc_wt_percent"] == 0 else f'{sample["udc_wt_percent"]:g}UDC'
    return f'{sample["polymer"]}_{content}'


def independent_figure(identifier: str, item: dict, polymer: str, quantity: str,
                       data_basis: str, *, wide: bool = False) -> dict:
    """One graph, one polymer and explicit metric identity on the policy frame."""
    width, height = _size_mm(WIDE_FIGURE_SIZE if wide else DEFAULT_FIGURE_SIZE)
    item = {**item, "rect_mm": [0, 0, width, height], "standard_frame": True}
    return {"id": identifier, "width_mm": width, "height_mm": height, "panels": [item],
            "polymer": polymer, "quantity": quantity, "data_basis": data_basis}


def separate_frequency_panel(samples: list, polymer: str, metric: str, symbol: str) -> dict:
    curves = []
    for sample in samples:
        points = sample["block"]["points"]
        curves.append(curve(content_label(sample), [p["omega_rad_s"] for p in points],
            [p[metric] for p in points], _color(sample)))
    return panel("graph1", f"{polymer}: {symbol} at 210 °C", OMEGA,
        f"{symbol} (Pa)" if metric != "complex_viscosity_Pa_s" else "η* (Pa s)",
        curves, xscale="log", yscale="log",
        legend="upper_right" if metric == "complex_viscosity_Pa_s" else "lower_right")


def separate_master_panel(samples: list, polymer: str, metric: str, symbol: str) -> dict:
    curves = []
    for sample in samples:
        for index, block in enumerate(sample["master_curves"]):
            points = block["points"]
            curves.append(curve(content_label(sample) if index == 0 else "",
                [p["omega_reduced_rad_s"] for p in points], [p[metric] for p in points],
                _color(sample)))
    return panel("graph1", f"{polymer}: reduced {symbol}", REDUCED, f"{symbol}_{{red}} (Pa)",
                 curves, xscale="log", yscale="log")


def separate_arrhenius_panel(samples: list, polymer: str) -> dict:
    curves = []
    for sample in samples:
        rows = sample["arrhenius"]["rows"]
        x = [r["inverse_temperature_1000_K"] for r in rows]
        curves.append(curve(content_label(sample), x, [r["ln_aT"] for r in rows],
            _color(sample)))
        curves.append(curve("", x, [r["ln_aT_fit"] for r in rows], _color(sample)))
    return panel("graph1", f"{polymer}: Arrhenius", INV_T, "ln a_{T}", curves)


def separate_energy_panel(samples: list, polymer: str) -> dict:
    amounts = [s["udc_wt_percent"] for s in samples]
    energies = [s["arrhenius"]["Ea_app_kJ_mol"] for s in samples]
    bar_width = min(b - a for a, b in zip(amounts[:-1], amounts[1:], strict=True)) * .45
    xmin, xmax = min(amounts) - bar_width, max(amounts) + bar_width
    ymin = min(0.0, min(energies) * 1.15)
    ymax = math.ceil(max(energies) * 1.22 / 10) * 10
    curves, notes = [], []
    for sample, amount, ea in zip(samples, amounts, energies, strict=True):
        curves.append(curve("", [amount], [ea], _color(sample), kind="bar", bar_width=bar_width))
        notes.append({"text": f"{ea:.1f}", "x": (amount - xmin) / (xmax - xmin) - .04,
                      "y": (ea - ymin) / (ymax - ymin) + .025})
    return panel("graph1", f"{polymer}: apparent E_{{a}}", "UDC content (wt%)",
        "E_{a,app} (kJ mol^{-1})", curves, x_min=xmin, x_max=xmax,
        y_min=ymin, y_max=ymax, y_ticks=list(range(0, int(ymax) + 1, 20)),
        x_ticks=amounts, legend=False, notes=notes)
