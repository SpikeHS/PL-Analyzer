"""Parametric peak fitting for photoluminescence spectra.

The module is intentionally independent from Qt and plotting. It accepts array-like
spectral data, can use a Savitzky-Golay trace for initialization, jointly fits a
baseline and one or more peaks to the original observations, and returns immutable
numerical results suitable for the UI, project persistence, and export layers.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import least_squares
from scipy.signal import find_peaks, peak_widths, savgol_filter
from scipy.special import voigt_profile

from core.errors import AnalysisError

FloatArray = NDArray[np.float64]
PeakCount = int | Literal["auto"]


class FitModel(StrEnum):
    """Peak line-shape models supported by the v1.1 fitting engine."""

    AUTO = "auto"
    GAUSSIAN = "gaussian"
    LORENTZIAN = "lorentzian"
    VOIGT = "voigt"
    PSEUDO_VOIGT = "pseudo_voigt"


class BaselineMode(StrEnum):
    """Baseline models that can be fitted jointly with spectral peaks."""

    NONE = "none"
    CONSTANT = "constant"
    LINEAR = "linear"


@dataclass(frozen=True, slots=True)
class FitConfig:
    """Operator-controlled settings for one fitting window."""

    search_min_nm: float | None = None
    search_max_nm: float | None = None
    model: FitModel | str = FitModel.AUTO
    peak_count: PeakCount = "auto"
    max_peaks: int = 3
    baseline: BaselineMode | str = BaselineMode.LINEAR
    savgol_enabled: bool = False
    savgol_window_length: int = 11
    savgol_polyorder: int = 3
    min_peak_distance_nm: float = 0.0
    max_nfev: int = 10_000

    def validate(self) -> None:
        """Raise a stable error when the configuration is not usable."""

        self.resolved_model()
        self.resolved_baseline()

        for bound in (self.search_min_nm, self.search_max_nm):
            if bound is not None and (
                isinstance(bound, bool)
                or not isinstance(bound, Real)
                or not math.isfinite(float(bound))
            ):
                raise AnalysisError(
                    "Fit window bounds must be finite real numbers.",
                    code="E_FIT_INVALID_WINDOW",
                )
        if (
            self.search_min_nm is not None
            and self.search_max_nm is not None
            and float(self.search_min_nm) >= float(self.search_max_nm)
        ):
            raise AnalysisError(
                "Fit window minimum must be smaller than its maximum.",
                code="E_FIT_INVALID_WINDOW",
            )

        if isinstance(self.peak_count, str):
            peak_count_is_valid = self.peak_count == "auto"
        else:
            peak_count_is_valid = (
                not isinstance(self.peak_count, bool)
                and isinstance(self.peak_count, int)
                and self.peak_count >= 1
            )
        if not peak_count_is_valid:
            raise AnalysisError(
                "Peak count must be 'auto' or a positive integer.",
                code="E_FIT_INVALID_PEAK_COUNT",
            )
        if (
            isinstance(self.max_peaks, bool)
            or not isinstance(self.max_peaks, int)
            or self.max_peaks < 1
            or self.max_peaks > 20
        ):
            raise AnalysisError(
                "Maximum peak count must be between 1 and 20.",
                code="E_FIT_INVALID_PEAK_COUNT",
            )
        if isinstance(self.peak_count, int) and self.peak_count > 20:
            raise AnalysisError(
                "Peak count cannot exceed 20.",
                code="E_FIT_INVALID_PEAK_COUNT",
            )
        if (
            isinstance(self.min_peak_distance_nm, bool)
            or not isinstance(self.min_peak_distance_nm, Real)
            or not math.isfinite(float(self.min_peak_distance_nm))
            or float(self.min_peak_distance_nm) < 0
        ):
            raise AnalysisError(
                "Minimum peak distance must be a finite non-negative number.",
                code="E_FIT_INVALID_CONFIG",
            )
        if (
            isinstance(self.max_nfev, bool)
            or not isinstance(self.max_nfev, int)
            or self.max_nfev < 100
        ):
            raise AnalysisError(
                "Maximum optimizer evaluations must be an integer of at least 100.",
                code="E_FIT_INVALID_CONFIG",
            )
        if not isinstance(self.savgol_enabled, bool):
            raise AnalysisError(
                "Savitzky-Golay enabled state must be a boolean.",
                code="E_FIT_INVALID_CONFIG",
            )
        if self.savgol_enabled and (
            isinstance(self.savgol_window_length, bool)
            or not isinstance(self.savgol_window_length, int)
            or self.savgol_window_length < 3
            or self.savgol_window_length % 2 == 0
            or isinstance(self.savgol_polyorder, bool)
            or not isinstance(self.savgol_polyorder, int)
            or self.savgol_polyorder < 0
            or self.savgol_polyorder >= self.savgol_window_length
        ):
            raise AnalysisError(
                "Savitzky-Golay requires an odd window and a lower polynomial order.",
                code="E_FIT_INVALID_SAVGOL",
            )

    def resolved_model(self) -> FitModel:
        """Return the normalized model enum."""

        value = (
            self.model.value
            if isinstance(self.model, FitModel)
            else str(self.model).strip().lower().replace("-", "_").replace(" ", "_")
        )
        try:
            return FitModel(value)
        except ValueError as exc:
            raise AnalysisError(
                f"Unsupported fit model: {self.model!s}.",
                code="E_FIT_INVALID_MODEL",
            ) from exc

    def resolved_baseline(self) -> BaselineMode:
        """Return the normalized baseline enum."""

        value = (
            self.baseline.value
            if isinstance(self.baseline, BaselineMode)
            else str(self.baseline).strip().lower().replace("-", "_").replace(" ", "_")
        )
        try:
            return BaselineMode(value)
        except ValueError as exc:
            raise AnalysisError(
                f"Unsupported baseline mode: {self.baseline!s}.",
                code="E_FIT_INVALID_BASELINE",
            ) from exc


@dataclass(frozen=True, slots=True)
class FitPeak:
    """Physical metrics for one fitted peak, excluding the fitted baseline."""

    model: FitModel
    position_nm: float
    height_au: float
    area_au_nm: float
    fwhm_nm: float
    gaussian_fwhm_nm: float | None = None
    lorentzian_fwhm_nm: float | None = None
    mixing_fraction: float | None = None


@dataclass(frozen=True, slots=True)
class FitBaseline:
    """Baseline coefficients referenced to a wavelength near the window center."""

    mode: BaselineMode
    intercept_au: float
    slope_au_per_nm: float
    reference_nm: float


@dataclass(frozen=True, slots=True)
class FitResult:
    """Complete immutable output from a successful spectral fit."""

    model: FitModel
    peaks: tuple[FitPeak, ...]
    baseline: FitBaseline
    wavelength_nm: FloatArray
    observed_intensity_au: FloatArray
    processed_intensity_au: FloatArray
    fitted_intensity_au: FloatArray
    baseline_intensity_au: FloatArray
    residuals_au: FloatArray
    r_squared: float
    adjusted_r_squared: float | None
    aic: float
    bic: float
    window_min_nm: float
    window_max_nm: float
    diagnostics: tuple[str, ...] = ()
    algorithm_version: int = 1

    def __post_init__(self) -> None:
        """Own and protect result arrays from accidental downstream mutation."""

        array_fields = (
            "wavelength_nm",
            "observed_intensity_au",
            "processed_intensity_au",
            "fitted_intensity_au",
            "baseline_intensity_au",
            "residuals_au",
        )
        expected_size: int | None = None
        for field_name in array_fields:
            values = np.array(getattr(self, field_name), dtype=np.float64, copy=True)
            if values.ndim != 1:
                raise ValueError("Fit result arrays must be one-dimensional.")
            if expected_size is None:
                expected_size = values.size
            elif values.size != expected_size:
                raise ValueError("Fit result arrays must have equal lengths.")
            values.setflags(write=False)
            object.__setattr__(self, field_name, values)


@dataclass(frozen=True, slots=True)
class _CandidateFit:
    model: FitModel
    peaks: tuple[FitPeak, ...]
    baseline: FitBaseline
    fitted: FloatArray
    baseline_values: FloatArray
    residuals: FloatArray
    r_squared: float
    adjusted_r_squared: float | None
    aic: float
    bic: float
    parameter_count: int


class _CandidateFailure(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "E_FIT_OPTIMIZATION_FAILED",
    ) -> None:
        super().__init__(message)
        self.code = code


class SpectrumFitter:
    """Fit one material window without modifying the source spectrum."""

    algorithm_version = 1

    def fit(
        self,
        wavelength_nm: ArrayLike,
        intensity_au: ArrayLike,
        config: FitConfig | None = None,
    ) -> FitResult:
        """Fit peaks to raw observations, using smoothing only for initialization."""

        settings = config or FitConfig()
        settings.validate()
        model_setting = settings.resolved_model()
        baseline_mode = settings.resolved_baseline()

        wavelength, intensity, diagnostics = _prepare_arrays(
            wavelength_nm,
            intensity_au,
        )
        wavelength, intensity = _select_window(wavelength, intensity, settings)
        if settings.savgol_enabled and settings.savgol_window_length > wavelength.size:
            raise AnalysisError(
                "Savitzky-Golay window is longer than the selected data window.",
                code="E_FIT_INVALID_SAVGOL",
            )

        processed = np.array(intensity, dtype=np.float64, copy=True)
        if settings.savgol_enabled:
            _validate_savgol_wavelength_axis(wavelength)
            try:
                processed = np.asarray(
                    savgol_filter(
                        processed,
                        window_length=settings.savgol_window_length,
                        polyorder=settings.savgol_polyorder,
                        mode="interp",
                    ),
                    dtype=np.float64,
                )
            except (TypeError, ValueError) as exc:
                raise AnalysisError(
                    "Savitzky-Golay preprocessing failed.",
                    code="E_FIT_INVALID_SAVGOL",
                    detail=str(exc),
                ) from exc
            diagnostics.append("SAVGOL_APPLIED")
            diagnostics.append("SAVGOL_INITIALIZATION_ONLY")

        baseline_guess = _initial_baseline(wavelength, processed, baseline_mode)
        signal_guess = processed - baseline_guess
        signal_range = float(np.ptp(signal_guess))
        signal_scale = max(float(np.max(np.abs(processed))), 1.0)
        if signal_range <= np.finfo(np.float64).eps * signal_scale * 100.0:
            raise AnalysisError(
                "No resolvable peak signal remains after baseline estimation.",
                code="E_FIT_NO_PEAK_SIGNAL",
            )

        models = (
            (
                FitModel.GAUSSIAN,
                FitModel.LORENTZIAN,
                FitModel.PSEUDO_VOIGT,
                FitModel.VOIGT,
            )
            if model_setting is FitModel.AUTO
            else (model_setting,)
        )
        peak_counts = (
            tuple(range(1, settings.max_peaks + 1))
            if settings.peak_count == "auto"
            else (int(settings.peak_count),)
        )

        candidates: list[_CandidateFit] = []
        failure_details: list[str] = []
        failure_codes: list[str] = []
        for model in models:
            for peak_count in peak_counts:
                parameter_count = peak_count * _parameters_per_peak(
                    model
                ) + _baseline_parameter_count(baseline_mode)
                if wavelength.size <= parameter_count:
                    failure_details.append(
                        f"{model.value}/{peak_count}: insufficient degrees of freedom"
                    )
                    failure_codes.append("E_FIT_INSUFFICIENT_POINTS")
                    continue
                try:
                    candidate = _fit_candidate(
                        wavelength,
                        intensity,
                        initialization_intensity_au=processed,
                        model=model,
                        peak_count=peak_count,
                        baseline_mode=baseline_mode,
                        baseline_guess=baseline_guess,
                        config=settings,
                    )
                except _CandidateFailure as exc:
                    failure_details.append(f"{model.value}/{peak_count}: {exc!s}")
                    failure_codes.append(exc.code)
                    continue
                except Exception as exc:
                    failure_details.append(f"{model.value}/{peak_count}: {type(exc).__name__}")
                    failure_codes.append("E_FIT_OPTIMIZATION_FAILED")
                    continue
                candidates.append(candidate)

        if not candidates:
            failure_code_set = set(failure_codes)
            if failure_code_set == {"E_FIT_INSUFFICIENT_POINTS"}:
                error_code = "E_FIT_INSUFFICIENT_POINTS"
            elif "E_FIT_UNRESOLVED_PEAK" in failure_code_set:
                error_code = "E_FIT_UNRESOLVED_PEAK"
            else:
                error_code = "E_FIT_OPTIMIZATION_FAILED"
            raise AnalysisError(
                "No fit candidate converged for the selected data window.",
                code=error_code,
                detail="; ".join(failure_details[:12]),
            )

        selected = min(
            candidates,
            key=lambda candidate: (
                candidate.bic,
                candidate.parameter_count,
                _model_preference(candidate.model),
            ),
        )
        if model_setting is FitModel.AUTO:
            diagnostics.append(f"AUTO_MODEL_SELECTED:{selected.model.value}")
        if settings.peak_count == "auto":
            diagnostics.append(f"AUTO_PEAK_COUNT_SELECTED:{len(selected.peaks)}")

        return FitResult(
            model=selected.model,
            peaks=selected.peaks,
            baseline=selected.baseline,
            wavelength_nm=wavelength,
            observed_intensity_au=intensity,
            processed_intensity_au=processed,
            fitted_intensity_au=selected.fitted,
            baseline_intensity_au=selected.baseline_values,
            residuals_au=selected.residuals,
            r_squared=selected.r_squared,
            adjusted_r_squared=selected.adjusted_r_squared,
            aic=selected.aic,
            bic=selected.bic,
            window_min_nm=float(wavelength[0]),
            window_max_nm=float(wavelength[-1]),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            algorithm_version=self.algorithm_version,
        )


def gaussian_peak(
    wavelength_nm: ArrayLike,
    height_au: float,
    position_nm: float,
    fwhm_nm: float,
) -> FloatArray:
    """Evaluate a unit-baseline Gaussian parameterized by physical FWHM."""

    wavelength = np.asarray(wavelength_nm, dtype=np.float64)
    exponent = -4.0 * math.log(2.0) * ((wavelength - position_nm) / fwhm_nm) ** 2
    return np.asarray(height_au * np.exp(exponent), dtype=np.float64)


def lorentzian_peak(
    wavelength_nm: ArrayLike,
    height_au: float,
    position_nm: float,
    fwhm_nm: float,
) -> FloatArray:
    """Evaluate a unit-baseline Lorentzian parameterized by physical FWHM."""

    wavelength = np.asarray(wavelength_nm, dtype=np.float64)
    scaled = 2.0 * (wavelength - position_nm) / fwhm_nm
    return np.asarray(height_au / (1.0 + scaled**2), dtype=np.float64)


def voigt_peak(
    wavelength_nm: ArrayLike,
    height_au: float,
    position_nm: float,
    gaussian_fwhm_nm: float,
    lorentzian_fwhm_nm: float,
) -> FloatArray:
    """Evaluate a peak-height-normalized Voigt profile."""

    wavelength = np.asarray(wavelength_nm, dtype=np.float64)
    sigma = gaussian_fwhm_nm / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    gamma = lorentzian_fwhm_nm / 2.0
    center_value = float(voigt_profile(0.0, sigma, gamma))
    values = voigt_profile(wavelength - position_nm, sigma, gamma)
    return np.asarray(height_au * values / center_value, dtype=np.float64)


def pseudo_voigt_peak(
    wavelength_nm: ArrayLike,
    height_au: float,
    position_nm: float,
    fwhm_nm: float,
    mixing_fraction: float,
) -> FloatArray:
    """Evaluate a height-normalized Gaussian/Lorentzian mixture."""

    gaussian = gaussian_peak(wavelength_nm, 1.0, position_nm, fwhm_nm)
    lorentzian = lorentzian_peak(wavelength_nm, 1.0, position_nm, fwhm_nm)
    return np.asarray(
        height_au * ((1.0 - mixing_fraction) * gaussian + mixing_fraction * lorentzian),
        dtype=np.float64,
    )


def _prepare_arrays(
    wavelength_nm: ArrayLike,
    intensity_au: ArrayLike,
) -> tuple[FloatArray, FloatArray, list[str]]:
    try:
        wavelength = np.asarray(wavelength_nm, dtype=np.float64)
        intensity = np.asarray(intensity_au, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnalysisError(
            "Wavelength and intensity must contain numeric values.",
            code="E_FIT_NON_NUMERIC",
        ) from exc

    if wavelength.ndim != 1 or intensity.ndim != 1:
        raise AnalysisError(
            "Wavelength and intensity must be one-dimensional.",
            code="E_FIT_SHAPE",
        )
    if wavelength.size != intensity.size:
        raise AnalysisError(
            "Wavelength and intensity lengths do not match.",
            code="E_FIT_LENGTH_MISMATCH",
        )
    if wavelength.size < 5:
        raise AnalysisError(
            "At least five spectral points are required for fitting.",
            code="E_FIT_INSUFFICIENT_POINTS",
        )

    diagnostics: list[str] = []
    finite = np.isfinite(wavelength) & np.isfinite(intensity)
    if not np.all(finite):
        wavelength = wavelength[finite]
        intensity = intensity[finite]
        diagnostics.append("NONFINITE_PAIRS_DROPPED")
    if wavelength.size == 0:
        raise AnalysisError(
            "No finite wavelength/intensity pairs remain.",
            code="E_FIT_NO_FINITE_DATA",
        )
    if wavelength.size < 5:
        raise AnalysisError(
            "Fewer than five finite spectral points remain.",
            code="E_FIT_INSUFFICIENT_POINTS",
        )

    order = np.argsort(wavelength, kind="stable")
    if not np.array_equal(order, np.arange(order.size)):
        diagnostics.append("WAVELENGTH_SORTED")
    wavelength = wavelength[order]
    intensity = intensity[order]

    unique_wavelengths, starts, counts = np.unique(
        wavelength,
        return_index=True,
        return_counts=True,
    )
    if np.any(counts > 1):
        merged_intensity = np.empty(unique_wavelengths.size, dtype=np.float64)
        for index, (start, count) in enumerate(zip(starts, counts, strict=True)):
            merged_intensity[index] = float(np.mean(intensity[start : start + count]))
        wavelength = unique_wavelengths
        intensity = merged_intensity
        diagnostics.append("DUPLICATE_WAVELENGTH_AVERAGED")

    if wavelength.size < 5:
        raise AnalysisError(
            "Fewer than five unique wavelength values remain.",
            code="E_FIT_INSUFFICIENT_POINTS",
        )
    if float(wavelength[-1] - wavelength[0]) <= 0:
        raise AnalysisError(
            "Wavelength values must span a non-zero interval.",
            code="E_FIT_DEGENERATE_AXIS",
        )
    return wavelength, intensity, diagnostics


def _select_window(
    wavelength_nm: FloatArray,
    intensity_au: FloatArray,
    config: FitConfig,
) -> tuple[FloatArray, FloatArray]:
    minimum = float(wavelength_nm[0]) if config.search_min_nm is None else config.search_min_nm
    maximum = float(wavelength_nm[-1]) if config.search_max_nm is None else config.search_max_nm
    if minimum >= maximum:
        raise AnalysisError(
            "The effective fit window has no positive span.",
            code="E_FIT_INVALID_WINDOW",
        )

    mask = (wavelength_nm >= minimum) & (wavelength_nm <= maximum)
    if not np.any(mask):
        raise AnalysisError(
            "No spectral data falls inside the selected fit window.",
            code="E_FIT_NO_DATA_IN_WINDOW",
        )
    selected_wavelength = np.array(wavelength_nm[mask], dtype=np.float64, copy=True)
    selected_intensity = np.array(intensity_au[mask], dtype=np.float64, copy=True)
    if selected_wavelength.size < 5:
        raise AnalysisError(
            "The selected fit window contains fewer than five points.",
            code="E_FIT_INSUFFICIENT_POINTS",
        )
    return selected_wavelength, selected_intensity


def _validate_savgol_wavelength_axis(wavelength_nm: FloatArray) -> None:
    """Require effectively uniform wavelength spacing for Savitzky-Golay."""

    steps = np.diff(wavelength_nm)
    median_step = float(np.median(steps))
    absolute_tolerance = (
        np.finfo(np.float64).eps * max(float(np.max(np.abs(wavelength_nm))), 1.0) * 64.0
    )
    if not np.allclose(
        steps,
        median_step,
        rtol=1e-3,
        atol=absolute_tolerance,
    ):
        raise AnalysisError(
            "Savitzky-Golay requires a uniformly spaced wavelength axis.",
            code="E_FIT_SAVGOL_NONUNIFORM_AXIS",
        )


def _initial_baseline(
    wavelength_nm: FloatArray,
    intensity_au: FloatArray,
    mode: BaselineMode,
) -> FloatArray:
    if mode is BaselineMode.NONE:
        return np.zeros_like(intensity_au)
    if mode is BaselineMode.CONSTANT:
        return np.full_like(intensity_au, float(np.percentile(intensity_au, 10.0)))

    edge_count = max(2, min(wavelength_nm.size // 8, 20))
    left_x = wavelength_nm[:edge_count]
    right_x = wavelength_nm[-edge_count:]
    left_y = intensity_au[:edge_count]
    right_y = intensity_au[-edge_count:]
    left_center = float(np.mean(left_x))
    right_center = float(np.mean(right_x))
    slope = float(np.median(right_y) - np.median(left_y)) / (right_center - left_center)
    reference = float(np.mean(wavelength_nm))
    edge_x = np.concatenate((left_x, right_x))
    edge_y = np.concatenate((left_y, right_y))
    intercept = float(np.median(edge_y - slope * (edge_x - reference)))
    return np.asarray(intercept + slope * (wavelength_nm - reference), dtype=np.float64)


def _fit_candidate(
    wavelength_nm: FloatArray,
    intensity_au: FloatArray,
    *,
    initialization_intensity_au: FloatArray,
    model: FitModel,
    peak_count: int,
    baseline_mode: BaselineMode,
    baseline_guess: FloatArray,
    config: FitConfig,
) -> _CandidateFit:
    initial, lower, upper, reference_nm = _initial_parameters(
        wavelength_nm,
        initialization_intensity_au,
        model=model,
        peak_count=peak_count,
        baseline_mode=baseline_mode,
        baseline_guess=baseline_guess,
        config=config,
    )
    intensity_scale = max(float(np.ptp(intensity_au)), float(np.std(intensity_au)), 1.0)

    def residual_function(parameters: FloatArray) -> FloatArray:
        fitted = _evaluate_model(
            wavelength_nm,
            parameters,
            model=model,
            peak_count=peak_count,
            baseline_mode=baseline_mode,
            reference_nm=reference_nm,
        )
        return np.asarray((fitted - intensity_au) / intensity_scale, dtype=np.float64)

    try:
        optimization = least_squares(
            residual_function,
            initial,
            bounds=(lower, upper),
            method="trf",
            x_scale="jac",
            max_nfev=config.max_nfev,
            ftol=1e-10,
            xtol=1e-10,
            gtol=1e-10,
        )
    except (ArithmeticError, RuntimeError, TypeError, ValueError) as exc:
        raise _CandidateFailure(type(exc).__name__) from exc

    if (
        not optimization.success
        or not np.all(np.isfinite(optimization.x))
        or not math.isfinite(float(optimization.cost))
    ):
        raise _CandidateFailure("optimizer did not converge")

    fitted = _evaluate_model(
        wavelength_nm,
        optimization.x,
        model=model,
        peak_count=peak_count,
        baseline_mode=baseline_mode,
        reference_nm=reference_nm,
    )
    if not np.all(np.isfinite(fitted)):
        raise _CandidateFailure("non-finite fitted values")

    peaks = _extract_peaks(optimization.x, model=model, peak_count=peak_count)
    if any(peak.height_au <= 0 or peak.fwhm_nm <= 0 for peak in peaks):
        raise _CandidateFailure("non-positive fitted peak")
    _validate_peak_resolvability(
        wavelength_nm,
        intensity_au,
        peaks,
        configured_minimum_distance_nm=float(config.min_peak_distance_nm),
    )

    baseline = _extract_baseline(
        optimization.x,
        model=model,
        peak_count=peak_count,
        mode=baseline_mode,
        reference_nm=reference_nm,
    )
    baseline_values = _baseline_values(wavelength_nm, baseline)
    residuals = np.asarray(intensity_au - fitted, dtype=np.float64)
    sse = float(np.dot(residuals, residuals))
    centered = intensity_au - float(np.mean(intensity_au))
    total_sum_squares = float(np.dot(centered, centered))
    if total_sum_squares <= 0:
        raise _CandidateFailure("constant target data")
    r_squared = 1.0 - sse / total_sum_squares

    parameter_count = optimization.x.size
    residual_degrees_of_freedom = wavelength_nm.size - parameter_count
    adjusted_r_squared = (
        1.0 - (1.0 - r_squared) * (wavelength_nm.size - 1) / residual_degrees_of_freedom
        if residual_degrees_of_freedom > 0
        else None
    )
    metric_floor = np.finfo(np.float64).eps * wavelength_nm.size * max(intensity_scale**2, 1.0)
    metric_sse = max(sse, metric_floor)
    log_likelihood_term = wavelength_nm.size * math.log(metric_sse / wavelength_nm.size)
    aic = log_likelihood_term + 2.0 * parameter_count
    bic = log_likelihood_term + parameter_count * math.log(wavelength_nm.size)

    return _CandidateFit(
        model=model,
        peaks=peaks,
        baseline=baseline,
        fitted=np.asarray(fitted, dtype=np.float64),
        baseline_values=baseline_values,
        residuals=residuals,
        r_squared=r_squared,
        adjusted_r_squared=adjusted_r_squared,
        aic=aic,
        bic=bic,
        parameter_count=parameter_count,
    )


def _validate_peak_resolvability(
    wavelength_nm: FloatArray,
    intensity_au: FloatArray,
    peaks: tuple[FitPeak, ...],
    *,
    configured_minimum_distance_nm: float,
) -> None:
    """Reject fitted metrics that the sampled wavelength axis cannot resolve."""

    intensity_range = float(np.ptp(intensity_au))
    intensity_scale = max(float(np.max(np.abs(intensity_au))), 1.0)
    minimum_height = max(
        intensity_range * 1e-6,
        np.finfo(np.float64).eps * intensity_scale * 100.0,
    )

    local_steps: dict[float, float] = {}
    for peak in peaks:
        if peak.height_au <= minimum_height:
            raise _CandidateFailure(
                "fitted peak amplitude is not identifiable",
                code="E_FIT_UNRESOLVED_PEAK",
            )

        local_step = _local_sampling_interval(wavelength_nm, peak.position_nm)
        local_steps[peak.position_nm] = local_step
        minimum_resolvable_fwhm = 2.0 * local_step
        if peak.fwhm_nm <= minimum_resolvable_fwhm * 1.01:
            raise _CandidateFailure(
                "fitted FWHM is below the wavelength sampling resolution",
                code="E_FIT_UNRESOLVED_PEAK",
            )

        half_width = peak.fwhm_nm / 2.0
        within_fwhm = wavelength_nm[
            (wavelength_nm >= peak.position_nm - half_width)
            & (wavelength_nm <= peak.position_nm + half_width)
        ]
        if (
            within_fwhm.size < 3
            or not np.any(within_fwhm < peak.position_nm)
            or not np.any(within_fwhm > peak.position_nm)
        ):
            raise _CandidateFailure(
                "fitted peak is not sampled on both sides of its half maximum",
                code="E_FIT_UNRESOLVED_PEAK",
            )

    for left, right in zip(peaks, peaks[1:], strict=False):
        sampling_separation = max(
            local_steps[left.position_nm],
            local_steps[right.position_nm],
        )
        required_separation = max(
            configured_minimum_distance_nm,
            sampling_separation,
        )
        if right.position_nm - left.position_nm <= required_separation * 1.01:
            raise _CandidateFailure(
                "fitted peak centers are not separately sampled",
                code="E_FIT_UNRESOLVED_PEAK",
            )


def _local_sampling_interval(
    wavelength_nm: FloatArray,
    position_nm: float,
) -> float:
    insertion_index = int(np.searchsorted(wavelength_nm, position_nm))
    step_indexes = {
        max(0, min(wavelength_nm.size - 2, insertion_index - 1)),
        max(0, min(wavelength_nm.size - 2, insertion_index)),
    }
    return max(float(wavelength_nm[index + 1] - wavelength_nm[index]) for index in step_indexes)


def _initial_parameters(
    wavelength_nm: FloatArray,
    intensity_au: FloatArray,
    *,
    model: FitModel,
    peak_count: int,
    baseline_mode: BaselineMode,
    baseline_guess: FloatArray,
    config: FitConfig,
) -> tuple[FloatArray, FloatArray, FloatArray, float]:
    reference_nm = float(np.mean(wavelength_nm))
    span = float(wavelength_nm[-1] - wavelength_nm[0])
    maximum_width = span * 2.0

    signal = np.asarray(intensity_au - baseline_guess, dtype=np.float64)
    low_signal = float(np.percentile(signal, 5.0))
    peak_signal = np.asarray(signal - low_signal, dtype=np.float64)
    indexes = _initial_peak_indexes(
        wavelength_nm,
        peak_signal,
        peak_count=peak_count,
        min_peak_distance_nm=config.min_peak_distance_nm,
    )
    signal_range = max(float(np.ptp(peak_signal)), np.finfo(np.float64).eps)
    upper_height = max(
        float(np.max(np.abs(intensity_au))) * 100.0,
        signal_range * 100.0,
        1.0,
    )

    initial: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    for index in indexes:
        estimated_width = _estimate_initial_width(
            wavelength_nm,
            peak_signal,
            index=index,
            default_width=span / max(5.0, 2.0 * peak_count),
        )
        local_step = _local_sampling_interval(
            wavelength_nm,
            float(wavelength_nm[index]),
        )
        minimum_width = max(local_step * 2.0, span * 1e-6)
        estimated_width = min(max(estimated_width, minimum_width * 1.01), maximum_width)
        height = min(
            max(float(peak_signal[index]), signal_range * 0.05),
            upper_height * 0.9,
        )
        position = float(wavelength_nm[index])

        if model in (FitModel.GAUSSIAN, FitModel.LORENTZIAN):
            initial.extend((height, position, estimated_width))
            lower.extend((0.0, float(wavelength_nm[0]), minimum_width))
            upper.extend((upper_height, float(wavelength_nm[-1]), maximum_width))
        elif model is FitModel.PSEUDO_VOIGT:
            initial.extend((height, position, estimated_width, 0.5))
            lower.extend((0.0, float(wavelength_nm[0]), minimum_width, 0.0))
            upper.extend((upper_height, float(wavelength_nm[-1]), maximum_width, 1.0))
        elif model is FitModel.VOIGT:
            component_width = estimated_width / 2.0
            minimum_component_width = max(
                local_step * 1e-6,
                span * 1e-9,
            )
            initial.extend((height, position, component_width, component_width))
            lower.extend(
                (
                    0.0,
                    float(wavelength_nm[0]),
                    minimum_component_width,
                    minimum_component_width,
                )
            )
            upper.extend(
                (
                    upper_height,
                    float(wavelength_nm[-1]),
                    maximum_width,
                    maximum_width,
                )
            )
        else:
            raise _CandidateFailure("unsupported candidate model")

    baseline_parameters = _baseline_initial_parameters(
        wavelength_nm,
        baseline_guess,
        mode=baseline_mode,
        reference_nm=reference_nm,
    )
    initial.extend(baseline_parameters)
    lower.extend([-np.inf] * len(baseline_parameters))
    upper.extend([np.inf] * len(baseline_parameters))
    return (
        np.asarray(initial, dtype=np.float64),
        np.asarray(lower, dtype=np.float64),
        np.asarray(upper, dtype=np.float64),
        reference_nm,
    )


def _initial_peak_indexes(
    wavelength_nm: FloatArray,
    signal: FloatArray,
    *,
    peak_count: int,
    min_peak_distance_nm: float,
) -> tuple[int, ...]:
    median_step = float(np.median(np.diff(wavelength_nm)))
    distance_samples = max(
        1,
        int(math.ceil(min_peak_distance_nm / median_step)),
    )
    prominence = max(float(np.ptp(signal)) * 0.01, np.finfo(np.float64).eps)
    detected, properties = find_peaks(
        signal,
        prominence=prominence,
        distance=distance_samples,
    )
    if detected.size:
        ranked = detected[np.argsort(properties["prominences"], kind="stable")[::-1]].tolist()
    else:
        ranked = []

    selected: list[int] = []
    physical_separation = max(min_peak_distance_nm, median_step)
    for index in ranked:
        if all(
            abs(float(wavelength_nm[index] - wavelength_nm[existing])) >= physical_separation
            for existing in selected
        ):
            selected.append(int(index))
            if len(selected) == peak_count:
                break

    if len(selected) < peak_count:
        for index in np.argsort(signal, kind="stable")[::-1]:
            if all(
                abs(float(wavelength_nm[index] - wavelength_nm[existing])) >= physical_separation
                for existing in selected
            ):
                selected.append(int(index))
                if len(selected) >= peak_count:
                    break

    if len(selected) < peak_count:
        raise _CandidateFailure("cannot initialize distinct peaks")
    return tuple(sorted(selected, key=lambda index: wavelength_nm[index]))


def _estimate_initial_width(
    wavelength_nm: FloatArray,
    signal: FloatArray,
    *,
    index: int,
    default_width: float,
) -> float:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _, _, left_ips, right_ips = peak_widths(
                signal,
                np.asarray([index], dtype=np.int64),
                rel_height=0.5,
            )
        sample_axis = np.arange(wavelength_nm.size, dtype=np.float64)
        left_nm = float(np.interp(float(left_ips[0]), sample_axis, wavelength_nm))
        right_nm = float(np.interp(float(right_ips[0]), sample_axis, wavelength_nm))
        width = right_nm - left_nm
        if math.isfinite(width) and width > 0:
            return width
    except (IndexError, TypeError, ValueError):
        pass
    return default_width


def _baseline_initial_parameters(
    wavelength_nm: FloatArray,
    baseline_guess: FloatArray,
    *,
    mode: BaselineMode,
    reference_nm: float,
) -> tuple[float, ...]:
    if mode is BaselineMode.NONE:
        return ()
    if mode is BaselineMode.CONSTANT:
        return (float(np.median(baseline_guess)),)
    slope, intercept = np.polyfit(
        wavelength_nm - reference_nm,
        baseline_guess,
        deg=1,
    )
    return (float(intercept), float(slope))


def _evaluate_model(
    wavelength_nm: FloatArray,
    parameters: FloatArray,
    *,
    model: FitModel,
    peak_count: int,
    baseline_mode: BaselineMode,
    reference_nm: float,
) -> FloatArray:
    values = np.zeros_like(wavelength_nm)
    parameters_per_peak = _parameters_per_peak(model)
    for peak_index in range(peak_count):
        start = peak_index * parameters_per_peak
        peak_parameters = parameters[start : start + parameters_per_peak]
        values += _evaluate_peak(wavelength_nm, model, peak_parameters)

    baseline_start = peak_count * parameters_per_peak
    if baseline_mode is BaselineMode.CONSTANT:
        values += parameters[baseline_start]
    elif baseline_mode is BaselineMode.LINEAR:
        values += parameters[baseline_start]
        values += parameters[baseline_start + 1] * (wavelength_nm - reference_nm)
    return np.asarray(values, dtype=np.float64)


def _evaluate_peak(
    wavelength_nm: FloatArray,
    model: FitModel,
    parameters: FloatArray,
) -> FloatArray:
    if model is FitModel.GAUSSIAN:
        return gaussian_peak(wavelength_nm, *parameters)
    if model is FitModel.LORENTZIAN:
        return lorentzian_peak(wavelength_nm, *parameters)
    if model is FitModel.PSEUDO_VOIGT:
        return pseudo_voigt_peak(wavelength_nm, *parameters)
    if model is FitModel.VOIGT:
        return voigt_peak(wavelength_nm, *parameters)
    raise _CandidateFailure("unsupported candidate model")


def _extract_peaks(
    parameters: FloatArray,
    *,
    model: FitModel,
    peak_count: int,
) -> tuple[FitPeak, ...]:
    fitted_peaks: list[FitPeak] = []
    parameters_per_peak = _parameters_per_peak(model)
    gaussian_area_factor = math.sqrt(math.pi) / (2.0 * math.sqrt(math.log(2.0)))
    lorentzian_area_factor = math.pi / 2.0

    for peak_index in range(peak_count):
        start = peak_index * parameters_per_peak
        peak_parameters = parameters[start : start + parameters_per_peak]
        height = float(peak_parameters[0])
        position = float(peak_parameters[1])

        if model is FitModel.GAUSSIAN:
            fwhm = float(peak_parameters[2])
            fitted_peak = FitPeak(
                model=model,
                position_nm=position,
                height_au=height,
                area_au_nm=height * fwhm * gaussian_area_factor,
                fwhm_nm=fwhm,
                gaussian_fwhm_nm=fwhm,
            )
        elif model is FitModel.LORENTZIAN:
            fwhm = float(peak_parameters[2])
            fitted_peak = FitPeak(
                model=model,
                position_nm=position,
                height_au=height,
                area_au_nm=height * fwhm * lorentzian_area_factor,
                fwhm_nm=fwhm,
                lorentzian_fwhm_nm=fwhm,
            )
        elif model is FitModel.PSEUDO_VOIGT:
            fwhm = float(peak_parameters[2])
            mixing_fraction = float(peak_parameters[3])
            area_factor = (
                1.0 - mixing_fraction
            ) * gaussian_area_factor + mixing_fraction * lorentzian_area_factor
            fitted_peak = FitPeak(
                model=model,
                position_nm=position,
                height_au=height,
                area_au_nm=height * fwhm * area_factor,
                fwhm_nm=fwhm,
                mixing_fraction=mixing_fraction,
            )
        elif model is FitModel.VOIGT:
            gaussian_fwhm = float(peak_parameters[2])
            lorentzian_fwhm = float(peak_parameters[3])
            fwhm = 0.5346 * lorentzian_fwhm + math.sqrt(
                0.2166 * lorentzian_fwhm**2 + gaussian_fwhm**2
            )
            sigma = gaussian_fwhm / (2.0 * math.sqrt(2.0 * math.log(2.0)))
            gamma = lorentzian_fwhm / 2.0
            center_value = float(voigt_profile(0.0, sigma, gamma))
            fitted_peak = FitPeak(
                model=model,
                position_nm=position,
                height_au=height,
                area_au_nm=height / center_value,
                fwhm_nm=fwhm,
                gaussian_fwhm_nm=gaussian_fwhm,
                lorentzian_fwhm_nm=lorentzian_fwhm,
            )
        else:
            raise _CandidateFailure("unsupported candidate model")
        fitted_peaks.append(fitted_peak)

    return tuple(sorted(fitted_peaks, key=lambda peak: peak.position_nm))


def _extract_baseline(
    parameters: FloatArray,
    *,
    model: FitModel,
    peak_count: int,
    mode: BaselineMode,
    reference_nm: float,
) -> FitBaseline:
    start = peak_count * _parameters_per_peak(model)
    if mode is BaselineMode.NONE:
        intercept = 0.0
        slope = 0.0
    elif mode is BaselineMode.CONSTANT:
        intercept = float(parameters[start])
        slope = 0.0
    else:
        intercept = float(parameters[start])
        slope = float(parameters[start + 1])
    return FitBaseline(
        mode=mode,
        intercept_au=intercept,
        slope_au_per_nm=slope,
        reference_nm=reference_nm,
    )


def _baseline_values(
    wavelength_nm: FloatArray,
    baseline: FitBaseline,
) -> FloatArray:
    return np.asarray(
        baseline.intercept_au + baseline.slope_au_per_nm * (wavelength_nm - baseline.reference_nm),
        dtype=np.float64,
    )


def _parameters_per_peak(model: FitModel) -> int:
    return 4 if model in (FitModel.VOIGT, FitModel.PSEUDO_VOIGT) else 3


def _baseline_parameter_count(mode: BaselineMode) -> int:
    if mode is BaselineMode.NONE:
        return 0
    return 1 if mode is BaselineMode.CONSTANT else 2


def _model_preference(model: FitModel) -> int:
    order = {
        FitModel.GAUSSIAN: 0,
        FitModel.LORENTZIAN: 1,
        FitModel.PSEUDO_VOIGT: 2,
        FitModel.VOIGT: 3,
    }
    return order[model]
