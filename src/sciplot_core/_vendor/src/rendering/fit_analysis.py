from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import curve_fit

from src.data_loader import CurveSeries
from src.rendering.expression_engine import ExpressionError, evaluate_expression

SUPPORTED_FIT_MODEL_IDS = (
    "linear",
    "polynomial_2",
    "polynomial_3",
    "exponential",
    "logarithmic",
    "power_law",
    "gaussian",
    "logistic",
    "custom_function",
)


@dataclass(frozen=True)
class FitOptions:
    enabled: bool = False
    model_id: str = "linear"
    custom_function: object = None


@dataclass(frozen=True)
class FitDerivedRow:
    row_index: int
    x: float
    y: float
    y_fit: float
    residual: float


@dataclass(frozen=True)
class FitSeriesResult:
    series_id: str
    series_label: str
    model_id: str
    x_label: str
    y_label: str
    coefficients: tuple[float, ...]
    r_squared: float
    rmse: float
    point_count: int
    derived_rows: tuple[FitDerivedRow, ...]
    custom_expression: str | None = None
    custom_parameter_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def degree(self) -> int:
        if self.model_id == "linear":
            return 1
        if self.model_id == "polynomial_2":
            return 2
        if self.model_id == "polynomial_3":
            return 3
        raise ValueError(f"Fit model `{self.model_id}` is not a polynomial.")

    @property
    def slope(self) -> float | None:
        if self.model_id != "linear":
            return None
        return self.coefficients[0]

    @property
    def intercept(self) -> float | None:
        if self.model_id != "linear":
            return None
        return self.coefficients[1]

    @property
    def equation_display(self) -> str:
        if self.model_id == "linear":
            slope = self.slope or 0.0
            intercept = self.intercept or 0.0
            sign = "+" if intercept >= 0 else "-"
            return f"y = {slope:.3g}x {sign} {abs(intercept):.3g}"
        if self.model_id == "exponential":
            a, b, c = self.coefficients
            return f"y = {a:.3g} exp({b:.3g}x) + {c:.3g}"
        if self.model_id == "logarithmic":
            a, b = self.coefficients
            return f"y = {a:.3g} log(x) + {b:.3g}"
        if self.model_id == "power_law":
            a, b, c = self.coefficients
            return f"y = {a:.3g} x^{b:.3g} + {c:.3g}"
        if self.model_id == "gaussian":
            a, mu, sigma, c = self.coefficients
            return f"y = {a:.3g} exp(-((x-{mu:.3g})^2)/(2*{sigma:.3g}^2)) + {c:.3g}"
        if self.model_id == "logistic":
            l_value, k_value, x0_value, c_value = self.coefficients
            return f"y = {l_value:.3g} / (1 + exp(-{k_value:.3g}(x-{x0_value:.3g}))) + {c_value:.3g}"
        if self.model_id == "custom_function":
            return "y = custom function"
        terms: list[tuple[str, str]] = []
        degree = self.degree
        for index, coefficient in enumerate(self.coefficients):
            power = degree - index
            magnitude = abs(coefficient)
            if power == 0:
                token = f"{magnitude:.3g}"
            elif power == 1:
                token = f"{magnitude:.3g}x"
            else:
                token = f"{magnitude:.3g}x^{power}"
            sign = "-" if coefficient < 0 else "+"
            terms.append((sign, token))
        if not terms:
            return "y = 0"
        first_sign, first_token = terms[0]
        expression = f"-{first_token}" if first_sign == "-" else first_token
        for sign, token in terms[1:]:
            expression += f" {sign} {token}"
        return f"y = {expression}"

    @property
    def legend_label(self) -> str:
        if self.model_id == "linear":
            return f"fit: {self.equation_display}"
        return f"{self.series_label} fit"

    def predict(self, x_values: np.ndarray) -> np.ndarray:
        if self.model_id == "linear":
            slope = self.slope or 0.0
            intercept = self.intercept or 0.0
            return slope * x_values + intercept
        if self.model_id in {"polynomial_2", "polynomial_3"}:
            return np.polyval(np.asarray(self.coefficients, dtype=float), x_values)
        return _predict_model(
            self.model_id,
            x_values,
            self.coefficients,
            expression=self.custom_expression,
            parameter_names=self.custom_parameter_names,
        )

    @property
    def x_line(self) -> np.ndarray:
        if not self.derived_rows:
            return np.asarray([], dtype=float)
        x_values = np.asarray([row.x for row in self.derived_rows], dtype=float)
        return np.linspace(float(np.min(x_values)), float(np.max(x_values)), 120, dtype=float)

    @property
    def y_line(self) -> np.ndarray:
        return self.predict(self.x_line)


@dataclass(frozen=True)
class FitAnalysisResult:
    model_id: str
    x_label: str
    y_label: str
    series_results: tuple[FitSeriesResult, ...]
    warnings: tuple[str, ...] = ()

    def selected_series(self, series_id: str | None = None) -> FitSeriesResult:
        if not self.series_results:
            raise ValueError("No fit series results are available.")
        if series_id:
            for result in self.series_results:
                if result.series_id == series_id:
                    return result
            raise ValueError(f"Unknown fit series: {series_id}")
        return self.series_results[0]


def normalize_fit_options_payload(value: object) -> dict[str, object]:
    if isinstance(value, FitOptions):
        return {"enabled": value.enabled, "model_id": value.model_id, "custom_function": value.custom_function}
    if not isinstance(value, dict):
        return {"enabled": False, "model_id": "linear"}
    enabled = bool(value.get("enabled", False))
    model_id = str(value.get("model_id", "linear")).strip() or "linear"
    if model_id not in SUPPORTED_FIT_MODEL_IDS:
        model_id = "linear"
    custom_function = value.get("custom_function") if isinstance(value.get("custom_function"), dict) else None
    return {"enabled": enabled, "model_id": model_id, "custom_function": custom_function}


def fit_options_from_payload(value: object) -> FitOptions:
    payload = normalize_fit_options_payload(value)
    return FitOptions(
        enabled=bool(payload.get("enabled", False)),
        model_id=str(payload.get("model_id", "linear")),
        custom_function=payload.get("custom_function"),
    )


def _finite_points_for_series(series: CurveSeries) -> tuple[np.ndarray, np.ndarray, str, str]:
    frame = series.data.dropna(subset=["x", "y"])
    if frame.empty:
        raise ValueError("No valid X/Y points found.")
    x_values = frame["x"].to_numpy(dtype=float)
    y_values = frame["y"].to_numpy(dtype=float)
    valid = np.isfinite(x_values) & np.isfinite(y_values)
    if not np.any(valid):
        raise ValueError("No finite X/Y points found.")
    x_all = x_values[valid]
    y_all = y_values[valid]
    if x_all.size < 2:
        raise ValueError("At least two points are required to compute a fit.")
    if np.allclose(x_all, x_all[0]):
        raise ValueError("Fit cannot be computed when all x values are identical.")
    x_label = str(series.x_label or "x")
    y_label = str(series.y_label or "y")
    return x_all, y_all, x_label, y_label


def _series_identifier(series: CurveSeries, *, index: int, seen: set[str]) -> tuple[str, str]:
    label = str(series.sample or f"Series {index + 1}").strip() or f"Series {index + 1}"
    identifier = label
    suffix = 2
    while identifier in seen:
        identifier = f"{label} ({suffix})"
        suffix += 1
    seen.add(identifier)
    return identifier, label


def _linear_fit(x_all: np.ndarray, y_all: np.ndarray) -> tuple[tuple[float, ...], np.ndarray, float]:
    design_matrix = sm.add_constant(x_all, has_constant="add")
    model = sm.OLS(y_all, design_matrix).fit()
    intercept = float(model.params[0])
    slope = float(model.params[1])
    predicted = slope * x_all + intercept
    return (slope, intercept), predicted, float(model.rsquared)


def _polynomial_fit(
    x_all: np.ndarray,
    y_all: np.ndarray,
    *,
    degree: int,
) -> tuple[tuple[float, ...], np.ndarray, float]:
    if x_all.size < degree + 1:
        raise ValueError(f"At least {degree + 1} points are required to fit a polynomial of degree {degree}.")
    coefficients = np.polyfit(x_all, y_all, deg=degree)
    predicted = np.polyval(coefficients, x_all)
    residuals = y_all - predicted
    total_variance = float(np.sum(np.square(y_all - np.mean(y_all))))
    residual_variance = float(np.sum(np.square(residuals)))
    if math.isclose(total_variance, 0.0):
        r_squared = 1.0 if math.isclose(residual_variance, 0.0) else 0.0
    else:
        r_squared = max(0.0, 1.0 - residual_variance / total_variance)
    return tuple(float(value) for value in coefficients), predicted, r_squared


def _r_squared(y_all: np.ndarray, predicted: np.ndarray) -> float:
    residuals = y_all - predicted
    total_variance = float(np.sum(np.square(y_all - np.mean(y_all))))
    residual_variance = float(np.sum(np.square(residuals)))
    if math.isclose(total_variance, 0.0):
        return 1.0 if math.isclose(residual_variance, 0.0) else 0.0
    return max(0.0, 1.0 - residual_variance / total_variance)


def _builtin_model_function(model_id: str):
    if model_id == "exponential":
        return lambda x, a, b, c: a * np.exp(b * x) + c
    if model_id == "logarithmic":
        return lambda x, a, b: a * np.log(x) + b
    if model_id == "power_law":
        return lambda x, a, b, c: a * np.power(x, b) + c
    if model_id == "gaussian":
        return lambda x, a, mu, sigma, c: a * np.exp(-np.square(x - mu) / (2 * np.square(sigma))) + c
    if model_id == "logistic":
        return lambda x, l_value, k_value, x0_value, c_value: (
            l_value / (1 + np.exp(-k_value * (x - x0_value))) + c_value
        )
    raise ValueError(f"Unsupported fit model: {model_id}")


def _initial_guess(model_id: str, x_all: np.ndarray, y_all: np.ndarray) -> tuple[float, ...]:
    span_y = float(np.max(y_all) - np.min(y_all)) or 1.0
    if model_id == "exponential":
        return (span_y, 0.1, float(np.min(y_all)))
    if model_id == "logarithmic":
        return (span_y, float(np.mean(y_all)))
    if model_id == "power_law":
        return (1.0, 1.0, 0.0)
    if model_id == "gaussian":
        return (span_y, float(x_all[np.argmax(y_all)]), float(np.std(x_all)) or 1.0, float(np.min(y_all)))
    if model_id == "logistic":
        return (span_y, 1.0, float(np.median(x_all)), float(np.min(y_all)))
    raise ValueError(f"Unsupported fit model: {model_id}")


def _domain_filter(model_id: str, x_all: np.ndarray, y_all: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if model_id in {"logarithmic", "power_law"}:
        mask = x_all > 0
        if np.count_nonzero(mask) < 2:
            raise ValueError(f"{model_id} fit requires at least two positive x values.")
        return x_all[mask], y_all[mask]
    return x_all, y_all


def _nonlinear_fit(
    x_all: np.ndarray,
    y_all: np.ndarray,
    *,
    model_id: str,
) -> tuple[tuple[float, ...], np.ndarray, float]:
    x_fit, y_fit_source = _domain_filter(model_id, x_all, y_all)
    function = _builtin_model_function(model_id)
    try:
        params, _covariance = curve_fit(
            function,
            x_fit,
            y_fit_source,
            p0=_initial_guess(model_id, x_fit, y_fit_source),
            maxfev=20000,
        )
    except Exception as exc:
        raise ValueError(f"{model_id} fit failed to converge.") from exc
    predicted = function(x_all, *params)
    if not np.isfinite(predicted).all():
        raise ValueError(f"{model_id} fit produced non-finite predictions.")
    return tuple(float(value) for value in params), predicted, _r_squared(y_all, predicted)


def _custom_function_details(
    custom_function: object,
) -> tuple[str, tuple[str, ...], tuple[float, ...], tuple[tuple[float, ...], tuple[float, ...]]]:
    if not isinstance(custom_function, dict):
        raise ValueError("custom_function fit requires an expression and parameter list.")
    expression = str(custom_function.get("expression") or "").strip()
    raw_parameters = custom_function.get("parameters")
    if not expression:
        raise ValueError("custom_function.expression must not be empty.")
    if not isinstance(raw_parameters, list) or not raw_parameters:
        raise ValueError("custom_function.parameters must be a non-empty list.")
    names: list[str] = []
    initial: list[float] = []
    lower_bounds: list[float] = []
    upper_bounds: list[float] = []
    for index, item in enumerate(raw_parameters):
        if not isinstance(item, dict):
            raise ValueError(f"custom_function.parameters[{index}] must be a mapping.")
        name = str(item.get("name") or "").strip()
        if not name.isidentifier():
            raise ValueError(f"custom_function parameter `{name}` must be a valid identifier.")
        if name in {"x", "y"} or name in names:
            raise ValueError(f"custom_function parameter `{name}` is reserved or duplicated.")
        names.append(name)
        initial.append(float(item.get("initial", 1.0)))
        lower = item.get("lower", -np.inf)
        upper = item.get("upper", np.inf)
        lower_value = float(lower) if lower is not None else -np.inf
        upper_value = float(upper) if upper is not None else np.inf
        if lower_value > upper_value:
            raise ValueError(f"custom_function parameter `{name}` lower bound exceeds upper bound.")
        lower_bounds.append(lower_value)
        upper_bounds.append(upper_value)
    return expression, tuple(names), tuple(initial), (tuple(lower_bounds), tuple(upper_bounds))


def _custom_fit(
    x_all: np.ndarray,
    y_all: np.ndarray,
    *,
    custom_function: object,
) -> tuple[tuple[float, ...], np.ndarray, float, str, tuple[str, ...]]:
    expression, parameter_names, initial, bounds = _custom_function_details(custom_function)

    def function(x_values: np.ndarray, *params: float) -> np.ndarray:
        names = {"x": x_values, **dict(zip(parameter_names, params, strict=True))}
        try:
            return evaluate_expression(
                expression,
                frame=pd.DataFrame({"x": x_values}),
                names=names,
                expect="numeric",
                label="custom_function",
            ).to_numpy(dtype=float)
        except ExpressionError as exc:
            raise ValueError(str(exc)) from exc

    try:
        params, _covariance = curve_fit(function, x_all, y_all, p0=initial, bounds=bounds, maxfev=20000)
    except Exception as exc:
        raise ValueError("custom_function fit failed to converge.") from exc
    predicted = function(x_all, *params)
    if not np.isfinite(predicted).all():
        raise ValueError("custom_function fit produced non-finite predictions.")
    return tuple(float(value) for value in params), predicted, _r_squared(y_all, predicted), expression, parameter_names


def _predict_model(
    model_id: str,
    x_values: np.ndarray,
    coefficients: tuple[float, ...],
    *,
    expression: str | None = None,
    parameter_names: tuple[str, ...] = (),
) -> np.ndarray:
    if model_id == "custom_function":
        if not expression or not parameter_names:
            raise ValueError("custom_function prediction requires the original expression and parameter names.")
        names = {"x": x_values, **dict(zip(parameter_names, coefficients, strict=True))}
        try:
            return evaluate_expression(
                expression,
                frame=pd.DataFrame({"x": x_values}),
                names=names,
                expect="numeric",
                label="custom_function",
            ).to_numpy(dtype=float)
        except ExpressionError as exc:
            raise ValueError(str(exc)) from exc
    return _builtin_model_function(model_id)(x_values, *coefficients)


def fit_series(
    series: CurveSeries,
    *,
    model_id: str,
    series_id: str,
    series_label: str,
    custom_function: object = None,
) -> FitSeriesResult:
    if model_id not in SUPPORTED_FIT_MODEL_IDS:
        raise ValueError(f"Unsupported fit model: {model_id}")
    x_all, y_all, x_label, y_label = _finite_points_for_series(series)
    custom_expression = None
    custom_parameter_names: tuple[str, ...] = ()
    if model_id == "linear":
        coefficients, predicted, r_squared = _linear_fit(x_all, y_all)
    elif model_id == "polynomial_2":
        coefficients, predicted, r_squared = _polynomial_fit(x_all, y_all, degree=2)
    elif model_id == "polynomial_3":
        coefficients, predicted, r_squared = _polynomial_fit(x_all, y_all, degree=3)
    elif model_id == "custom_function":
        coefficients, predicted, r_squared, custom_expression, custom_parameter_names = _custom_fit(
            x_all,
            y_all,
            custom_function=custom_function,
        )
    else:
        coefficients, predicted, r_squared = _nonlinear_fit(x_all, y_all, model_id=model_id)
    residuals = y_all - predicted
    rmse = math.sqrt(float(np.mean(np.square(residuals))))
    derived_rows = tuple(
        FitDerivedRow(
            row_index=index,
            x=float(x_value),
            y=float(y_value),
            y_fit=float(y_fit),
            residual=float(residual),
        )
        for index, (x_value, y_value, y_fit, residual) in enumerate(
            zip(x_all, y_all, predicted, residuals, strict=True)
        )
    )
    return FitSeriesResult(
        series_id=series_id,
        series_label=series_label,
        model_id=model_id,
        x_label=x_label,
        y_label=y_label,
        coefficients=coefficients,
        r_squared=r_squared,
        rmse=rmse,
        point_count=int(x_all.size),
        derived_rows=derived_rows,
        custom_expression=custom_expression,
        custom_parameter_names=custom_parameter_names,
    )


def fit_series_list(
    series_list: list[CurveSeries],
    *,
    model_id: str,
    custom_function: object = None,
) -> FitAnalysisResult:
    if model_id not in SUPPORTED_FIT_MODEL_IDS:
        raise ValueError(f"Unsupported fit model: {model_id}")
    seen_ids: set[str] = set()
    warnings: list[str] = []
    results: list[FitSeriesResult] = []
    for index, series in enumerate(series_list):
        series_id, series_label = _series_identifier(series, index=index, seen=seen_ids)
        try:
            results.append(
                fit_series(
                    series,
                    model_id=model_id,
                    series_id=series_id,
                    series_label=series_label,
                    custom_function=custom_function,
                )
            )
        except ValueError as exc:
            warnings.append(f"{series_label}: {exc}")
    if not results:
        if warnings:
            raise ValueError(" ".join(warnings))
        raise ValueError("No valid X/Y series found.")
    first = results[0]
    return FitAnalysisResult(
        model_id=model_id,
        x_label=first.x_label,
        y_label=first.y_label,
        series_results=tuple(results),
        warnings=tuple(warnings),
    )


def fit_linear_series_list(series_list: list[CurveSeries]) -> FitSeriesResult:
    return fit_series_list(series_list, model_id="linear").selected_series()


__all__ = [
    "FitAnalysisResult",
    "FitDerivedRow",
    "FitOptions",
    "FitSeriesResult",
    "SUPPORTED_FIT_MODEL_IDS",
    "fit_linear_series_list",
    "fit_options_from_payload",
    "fit_series",
    "fit_series_list",
    "normalize_fit_options_payload",
]
