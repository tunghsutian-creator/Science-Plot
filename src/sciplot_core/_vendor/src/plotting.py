from __future__ import annotations

from collections.abc import Sequence

import matplotlib.pyplot as plt

from src.data_loader import CurveSeries, ReplicateGroup
from src.plotting_curve_support import INSIDE_LEGEND_INSET_FRACTION, compute_shared_curve_x_layout
from src.plotting_curves import plot_curve_template, plot_curves, plot_scatter
from src.plotting_heatmap import plot_heatmap
from src.plotting_primitives import _cap_visible_major_ticks, _format_axis_label
from src.plotting_stats import plot_bar, plot_box, plot_box_bar_plots, plot_violin
from src.plotting_wide_nmr import plot_wide_nmr
from src.wide_nmr import WideNMRConfig


def plot_frequency_sweep(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("frequency_sweep", series_list, **overrides)


def plot_temperature_sweep(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("temperature_sweep", series_list, **overrides)


def plot_stress_relaxation(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("stress_relaxation", series_list, **overrides)


def plot_tensile_curve(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("tensile_curve", series_list, **overrides)


def plot_ftir(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("ftir", series_list, **overrides)


def plot_nmr(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("nmr", series_list, **overrides)


def plot_xrd(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("xrd", series_list, **overrides)


def plot_dsc(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("dsc", series_list, **overrides)


def plot_tga(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("tga", series_list, **overrides)


def plot_dma(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("dma", series_list, **overrides)


__all__ = [
    "INSIDE_LEGEND_INSET_FRACTION",
    "_cap_visible_major_ticks",
    "_format_axis_label",
    "compute_shared_curve_x_layout",
    "plot_bar",
    "plot_box",
    "plot_box_bar_plots",
    "plot_curve_template",
    "plot_curves",
    "plot_dma",
    "plot_dsc",
    "plot_frequency_sweep",
    "plot_heatmap",
    "plot_ftir",
    "plot_nmr",
    "plot_scatter",
    "plot_stress_relaxation",
    "plot_temperature_sweep",
    "plot_tensile_curve",
    "plot_tga",
    "plot_violin",
    "plot_wide_nmr",
    "plot_xrd",
    "WideNMRConfig",
    "CurveSeries",
    "ReplicateGroup",
]
