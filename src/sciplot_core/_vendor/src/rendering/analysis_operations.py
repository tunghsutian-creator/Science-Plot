from __future__ import annotations

# ruff: noqa: E501
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
from scipy import interpolate, signal, stats
from scipy.optimize import curve_fit

from src.rendering.cache import read_raw_table_cached
from src.rendering.data_containers import table_container_from_frame

SUPPORTED_OPERATION_IDS = {
    "analysis.smoothing",
    "analysis.interpolation",
    "analysis.differentiation",
    "analysis.integration",
    "analysis.fft",
    "analysis.fourier_filter",
    "analysis.correlation",
    "analysis.convolution",
    "analysis.baseline",
    "analysis.peak_detection",
    "analysis.kde",
    "analysis.statistical_tests",
    "analysis.distribution_fitting",
    "analysis.peak_fitting",
    "analysis.growth_models",
}


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _looks_numeric(value: object) -> bool:
    try:
        numeric = float(_cell_text(value))
    except ValueError:
        return False
    return np.isfinite(numeric)


def _column_frame(path: Path, sheet: str | int) -> pd.DataFrame:
    raw = read_raw_table_cached(path, sheet)
    if raw.empty:
        raise ValueError("Analysis source table is empty.")
    headers = [_cell_text(value) or f"Column {index + 1}" for index, value in enumerate(raw.iloc[0].tolist())]
    data_start = 1
    for index in range(1, raw.shape[0]):
        if sum(1 for value in raw.iloc[index].tolist() if _looks_numeric(value)) >= 2:
            data_start = index
            break
    data = raw.iloc[data_start:].reset_index(drop=True)
    data.columns = headers[: data.shape[1]]
    return data


def _resolve_xy(
    *,
    path: Path,
    sheet: str | int,
    x_column: str | None,
    y_column: str | None,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, str, str]:
    frame = _column_frame(path, sheet)
    x_name = x_column or str(frame.columns[0])
    y_name = y_column or str(frame.columns[1] if frame.shape[1] > 1 else frame.columns[0])
    if x_name not in frame.columns:
        raise ValueError(f"Unknown x_column `{x_name}`.")
    if y_name not in frame.columns:
        raise ValueError(f"Unknown y_column `{y_name}`.")
    x_values = pd.to_numeric(frame[x_name], errors="coerce").to_numpy(dtype=float)
    y_values = pd.to_numeric(frame[y_name], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(x_values) & np.isfinite(y_values)
    if mask.sum() < 2:
        raise ValueError("At least two finite X/Y points are required.")
    return frame, x_values[mask], y_values[mask], x_name, y_name


def _spacing(x_values: np.ndarray) -> float:
    if x_values.size < 2:
        return 1.0
    diffs = np.diff(np.sort(x_values))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    return float(np.median(diffs)) if diffs.size else 1.0


def _stable_analysis_suffix(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def _operation_kind(operation_id: str) -> str:
    return operation_id.split(".", 1)[1] if "." in operation_id else operation_id


def _analysis_ids(
    *,
    operation_id: str,
    module: str,
    input_path: Path,
    sheet: str | int,
    x_column: str | None,
    y_column: str | None,
    parameters: dict[str, Any],
    operation_instance_id: str | None,
) -> tuple[str, str, str]:
    operation_kind = _operation_kind(operation_id)
    if operation_instance_id:
        instance_id = operation_instance_id
        suffix = operation_instance_id.rsplit(":", 1)[-1].strip() or _stable_analysis_suffix({"id": operation_instance_id})
    else:
        suffix = _stable_analysis_suffix(
            {
                "operation_id": operation_id,
                "module": module,
                "input_path": str(input_path),
                "sheet": sheet,
                "x_column": x_column,
                "y_column": y_column,
                "parameters": parameters,
            }
        )
        instance_id = f"analysis:{module}:{operation_kind}:{suffix}"
    graph_prefix = "data_studio" if module == "data_studio" else "plot"
    graph_node_id = f"{graph_prefix}:analysis_operation:{suffix}"
    return instance_id, operation_kind, graph_node_id


def _result(
    *,
    operation_id: str,
    operation_instance_id: str,
    operation_kind: str,
    graph_node_id: str,
    recalculate_policy: str,
    input_path: Path,
    sheet: str | int,
    frame: pd.DataFrame,
    message: str,
    metrics: dict[str, Any] | None = None,
    overlays: list[dict[str, Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
    source_binding: dict[str, Any] | None = None,
    input_points: int | None = None,
    started_at: float | None = None,
) -> dict[str, Any]:
    result_node_id = f"{graph_node_id}:result"
    container = table_container_from_frame(
        frame,
        input_path=input_path,
        sheet=sheet,
        container_id=f"{operation_instance_id}:result",
        label=f"{operation_kind.replace('_', ' ').title()} result",
        status="enabled",
        kind="transformed_view",
        help_text="Analysis result table generated by /analysis-operation.",
    )
    overlay_refs_payload = overlays or []
    return {
        "operation_id": operation_id,
        "operation_instance_id": operation_instance_id,
        "operation_kind": operation_kind,
        "available": True,
        "valid": True,
        "status_code": "ok",
        "message": message,
        "diagnostics": diagnostics or [],
        "metrics": metrics or {},
        "tables": [
            {
                "id": f"{operation_id}:table",
                "row_count": int(frame.shape[0]),
                "columns": [str(column) for column in frame.columns],
                "rows": frame.replace({np.nan: None}).values.tolist()[:200],
            }
        ],
        "overlays": overlay_refs_payload,
        "data_containers": [container],
        "settings": settings or {},
        "source_binding": source_binding or {},
        "prepared_arrays": {
            "input_points": int(input_points if input_points is not None else frame.shape[0]),
            "output_points": int(frame.shape[0]),
        },
        "elapsed_ms": max(0.0, (perf_counter() - started_at) * 1000.0) if started_at is not None else 0.0,
        "lineage": {
            "invalidates_on": ["source_revision", "settings_revision"],
            "output_container_ids": [container["id"]],
            "operation_instance_id": operation_instance_id,
            "graph_node_id": graph_node_id,
            "result_node_id": result_node_id,
        },
        "artifact_refs": [],
        "graph_node_id": graph_node_id,
        "result_node_id": result_node_id,
        "result_container_ids": [container["id"]],
        "overlay_refs": overlay_refs_payload,
        "recalculate_policy": recalculate_policy,
    }


def run_analysis_operation(
    *,
    operation_id: str,
    input_path: str | Path,
    sheet: str | int,
    operation_instance_id: str | None = None,
    module: str = "plot",
    x_column: str | None = None,
    y_column: str | None = None,
    parameters: dict[str, Any] | None = None,
    source_binding: dict[str, Any] | None = None,
    recalculate_policy: str = "manual",
    graph_revision: int | None = None,
) -> dict[str, Any]:
    started_at = perf_counter()
    params = parameters or {}
    path = Path(input_path)
    if operation_id not in SUPPORTED_OPERATION_IDS:
        raise ValueError(f"Unsupported analysis operation `{operation_id}`.")
    module_name = module if module in {"plot", "data_studio"} else "plot"
    instance_id, operation_kind, graph_node_id = _analysis_ids(
        operation_id=operation_id,
        module=module_name,
        input_path=path,
        sheet=sheet,
        x_column=x_column,
        y_column=y_column,
        parameters=params,
        operation_instance_id=operation_instance_id,
    )
    source_frame, x_values, y_values, x_name, y_name = _resolve_xy(
        path=path,
        sheet=sheet,
        x_column=x_column,
        y_column=y_column,
    )
    column_names = [str(column) for column in source_frame.columns]
    x_index = column_names.index(x_name) if x_name in column_names else 0
    y_index = column_names.index(y_name) if y_name in column_names else 1
    source_binding_payload = {
        "input_path": str(path),
        "sheet": sheet,
        "x_column": x_name,
        "y_column": y_name,
        "x_column_id": f"col-{x_index}",
        "y_column_id": f"col-{y_index}",
        "module": module_name,
    }
    source_binding_payload.update(source_binding or {})
    if graph_revision is not None:
        source_binding_payload["graph_revision"] = int(graph_revision)

    def operation_result(
        *,
        frame: pd.DataFrame,
        message: str,
        metrics: dict[str, Any] | None = None,
        overlays: list[dict[str, Any]] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _result(
            operation_id=operation_id,
            operation_instance_id=instance_id,
            operation_kind=operation_kind,
            graph_node_id=graph_node_id,
            recalculate_policy=recalculate_policy if recalculate_policy in {"manual", "auto", "on_open"} else "manual",
            input_path=path,
            sheet=sheet,
            frame=frame,
            message=message,
            metrics=metrics,
            overlays=overlays,
            diagnostics=diagnostics,
            settings=settings or {"operation_id": operation_id, **params},
            source_binding=source_binding_payload,
            input_points=int(y_values.size),
            started_at=started_at,
        )

    if operation_id == "analysis.smoothing":
        method = str(params.get("method") or "rolling_mean")
        window = max(2, int(params.get("window") or 3))
        series = pd.Series(y_values)
        if method == "rolling_median":
            y_out = series.rolling(window, center=True, min_periods=1).median().to_numpy(dtype=float)
        elif method == "savitzky_golay":
            if window % 2 == 0:
                window += 1
            window = min(window, y_values.size if y_values.size % 2 == 1 else y_values.size - 1)
            polyorder = min(int(params.get("polyorder") or 2), max(1, window - 1))
            y_out = signal.savgol_filter(y_values, window_length=max(3, window), polyorder=polyorder)
        else:
            y_out = series.rolling(window, center=True, min_periods=1).mean().to_numpy(dtype=float)
        frame = pd.DataFrame({x_name: x_values, y_name: y_values, "smoothed": y_out})
        return operation_result(frame=frame, message="Smoothing complete.", metrics={"window": window, "point_count": int(y_values.size)})

    if operation_id == "analysis.interpolation":
        method = str(params.get("method") or "linear")
        sample_count = max(2, int(params.get("sample_count") or y_values.size))
        x_new = np.linspace(float(np.min(x_values)), float(np.max(x_values)), sample_count)
        kind = "cubic" if method == "cubic" and y_values.size >= 4 else "linear"
        fn = interpolate.interp1d(x_values, y_values, kind=kind, fill_value="extrapolate")
        frame = pd.DataFrame({x_name: x_new, "interpolated": fn(x_new)})
        return operation_result(frame=frame, message="Interpolation complete.", metrics={"method": kind, "point_count": sample_count})

    if operation_id == "analysis.differentiation":
        derivative = np.gradient(y_values, x_values)
        frame = pd.DataFrame({x_name: x_values, y_name: y_values, "derivative": derivative})
        return operation_result(frame=frame, message="Differentiation complete.", metrics={"point_count": int(y_values.size)})

    if operation_id == "analysis.integration":
        cumulative = np.asarray(
            [np.trapezoid(y_values[: index + 1], x_values[: index + 1]) for index in range(y_values.size)]
        )
        frame = pd.DataFrame({x_name: x_values, y_name: y_values, "cumulative_area": cumulative})
        return operation_result(
            frame=frame,
            message="Integration complete.",
            metrics={"total_area": float(np.trapezoid(y_values, x_values))},
        )

    if operation_id == "analysis.fft":
        centered = y_values - np.mean(y_values)
        frequencies = np.fft.rfftfreq(y_values.size, d=_spacing(x_values))
        magnitudes = np.abs(np.fft.rfft(centered))
        dominant_index = int(np.argmax(magnitudes[1:]) + 1) if magnitudes.size > 1 else 0
        frame = pd.DataFrame({"frequency": frequencies, "magnitude": magnitudes})
        return operation_result(frame=frame, message="FFT complete.", metrics={"dominant_frequency": float(frequencies[dominant_index]), "dominant_magnitude": float(magnitudes[dominant_index])})

    if operation_id == "analysis.fourier_filter":
        mode = str(params.get("mode") or "lowpass")
        cutoff = float(params.get("cutoff") or 0.25)
        frequencies = np.fft.rfftfreq(y_values.size, d=_spacing(x_values))
        spectrum = np.fft.rfft(y_values)
        mask = frequencies <= cutoff if mode == "lowpass" else frequencies >= cutoff
        filtered = np.fft.irfft(spectrum * mask, n=y_values.size)
        frame = pd.DataFrame({x_name: x_values, y_name: y_values, "filtered": filtered})
        return operation_result(frame=frame, message="Fourier filter complete.", metrics={"cutoff": cutoff, "mode": mode})

    if operation_id == "analysis.correlation":
        corr = signal.correlate(y_values - np.mean(y_values), y_values - np.mean(y_values), mode="full")
        lags = signal.correlation_lags(y_values.size, y_values.size, mode="full")
        frame = pd.DataFrame({"lag": lags, "correlation": corr})
        return operation_result(frame=frame, message="Correlation complete.", metrics={"max_correlation": float(np.max(corr))})

    if operation_id == "analysis.convolution":
        kernel = np.asarray(params.get("kernel") or [1.0, 1.0, 1.0], dtype=float)
        convolved = np.convolve(y_values, kernel / np.sum(kernel), mode="same")
        frame = pd.DataFrame({x_name: x_values, y_name: y_values, "convolved": convolved})
        return operation_result(frame=frame, message="Convolution complete.", metrics={"kernel_size": int(kernel.size)})

    if operation_id == "analysis.baseline":
        degree = max(0, int(params.get("degree") or 1))
        coefficients = np.polyfit(x_values, y_values, deg=min(degree, y_values.size - 1))
        baseline = np.polyval(coefficients, x_values)
        corrected = y_values - baseline
        frame = pd.DataFrame({x_name: x_values, y_name: y_values, "baseline": baseline, "corrected": corrected})
        return operation_result(frame=frame, message="Baseline correction complete.", metrics={"degree": degree})

    if operation_id == "analysis.peak_detection":
        peaks, properties = signal.find_peaks(y_values, height=params.get("height"))
        frame = pd.DataFrame({"peak_index": peaks, x_name: x_values[peaks], y_name: y_values[peaks]})
        return operation_result(
            frame=frame,
            message="Peak detection complete.",
            metrics={"peak_count": int(peaks.size)},
            overlays=[{"kind": "peak_markers", "x": x_values[peaks].tolist(), "y": y_values[peaks].tolist(), "properties": {key: value.tolist() for key, value in properties.items()}}],
        )

    if operation_id == "analysis.kde":
        kde = stats.gaussian_kde(y_values)
        samples = np.linspace(float(np.min(y_values)), float(np.max(y_values)), max(32, y_values.size * 4))
        density = kde(samples)
        frame = pd.DataFrame({"value": samples, "density": density})
        return operation_result(frame=frame, message="KDE complete.", metrics={"sample_count": int(samples.size)})

    if operation_id == "analysis.statistical_tests":
        zero = np.zeros_like(y_values)
        ttest = stats.ttest_1samp(y_values, popmean=0.0)
        shapiro = stats.shapiro(y_values) if y_values.size >= 3 else None
        mann = stats.mannwhitneyu(y_values, zero, alternative="two-sided")
        frame = pd.DataFrame(
            [
                {"test": "t_test_1samp", "statistic": float(ttest.statistic), "p_value": float(ttest.pvalue)},
                {"test": "mann_whitney", "statistic": float(mann.statistic), "p_value": float(mann.pvalue)},
                {
                    "test": "shapiro",
                    "statistic": float(shapiro.statistic) if shapiro is not None else None,
                    "p_value": float(shapiro.pvalue) if shapiro is not None else None,
                },
            ]
        )
        return operation_result(frame=frame, message="Statistical tests complete.")

    if operation_id == "analysis.distribution_fitting":
        distribution = str(params.get("distribution") or "normal")
        if distribution == "lognormal":
            shape, loc, scale = stats.lognorm.fit(y_values[y_values > 0])
            statistic, p_value = stats.kstest(y_values[y_values > 0], "lognorm", args=(shape, loc, scale))
            metrics = {"shape": float(shape), "loc": float(loc), "scale": float(scale)}
        elif distribution == "exponential":
            loc, scale = stats.expon.fit(y_values)
            statistic, p_value = stats.kstest(y_values, "expon", args=(loc, scale))
            metrics = {"loc": float(loc), "scale": float(scale)}
        else:
            mu, sigma = stats.norm.fit(y_values)
            statistic, p_value = stats.kstest(y_values, "norm", args=(mu, sigma))
            metrics = {"mu": float(mu), "sigma": float(sigma)}
        frame = pd.DataFrame([{**metrics, "ks_statistic": float(statistic), "ks_p_value": float(p_value)}])
        return operation_result(frame=frame, message="Distribution fitting complete.", metrics={**metrics, "ks_statistic": float(statistic), "ks_p_value": float(p_value)})

    if operation_id == "analysis.peak_fitting":
        def gaussian(x: np.ndarray, amplitude: float, center: float, sigma: float, offset: float) -> np.ndarray:
            return amplitude * np.exp(-np.square(x - center) / (2 * sigma * sigma)) + offset

        initial = [float(np.max(y_values) - np.min(y_values)), float(x_values[np.argmax(y_values)]), _spacing(x_values), float(np.min(y_values))]
        coefficients, _ = curve_fit(gaussian, x_values, y_values, p0=initial, maxfev=10000)
        y_fit = gaussian(x_values, *coefficients)
        frame = pd.DataFrame({x_name: x_values, y_name: y_values, "y_fit": y_fit, "residual": y_values - y_fit})
        metrics = {"amplitude": float(coefficients[0]), "center": float(coefficients[1]), "sigma": abs(float(coefficients[2])), "offset": float(coefficients[3])}
        return operation_result(frame=frame, message="Peak fitting complete.", metrics=metrics, overlays=[{"kind": "fit_overlay", "model_id": "gaussian_peak"}])

    def logistic(x: np.ndarray, l_value: float, k_value: float, x0_value: float, c_value: float) -> np.ndarray:
        return l_value / (1 + np.exp(-k_value * (x - x0_value))) + c_value

    model = str(params.get("model") or "exponential")
    if model == "logistic":
        initial = [float(np.max(y_values) - np.min(y_values)), 1.0, float(np.median(x_values)), float(np.min(y_values))]
        coefficients, _ = curve_fit(logistic, x_values, y_values, p0=initial, maxfev=10000)
        y_fit = logistic(x_values, *coefficients)
        metrics = {"l": float(coefficients[0]), "k": float(coefficients[1]), "x0": float(coefficients[2]), "c": float(coefficients[3])}
    else:
        positive = np.maximum(y_values, np.finfo(float).eps)
        slope, intercept = np.polyfit(x_values, np.log(positive), deg=1)
        y_fit = np.exp(intercept + slope * x_values)
        amplitude = float(np.exp(intercept))
        rate = float(slope)
        metrics = {"a": amplitude, "b": rate, "amplitude": amplitude, "rate": rate}
    frame = pd.DataFrame({x_name: x_values, y_name: y_values, "y_fit": y_fit, "residual": y_values - y_fit})
    return operation_result(frame=frame, message="Growth model fitting complete.", metrics=metrics, overlays=[{"kind": "fit_overlay", "model_id": model}])


__all__ = ["SUPPORTED_OPERATION_IDS", "run_analysis_operation"]
