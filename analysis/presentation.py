"""Display-assisted whole-spectrum metrics for annotated presentation plots.

These metrics intentionally remain separate from Raw Peak and model-fit results.
The presentation FWHM is measured at half height above an estimated baseline after
light Gaussian smoothing; it is not the Raw Peak half-prominence width.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import trapezoid
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from core.errors import AnalysisError
from core.models import SpectrumSeries

HC_EV_NM = 1239.8419843320026


@dataclass(frozen=True, slots=True)
class SecondaryFeature:
    """One secondary peak or shoulder retained for plot annotation."""

    wavelength_nm: float
    intensity_au: float
    relative_height: float
    prominence_au: float
    energy_ev: float


@dataclass(frozen=True, slots=True)
class PresentationMetrics:
    """Whole-spectrum quick metrics shown on a reference-style plot."""

    peak_wavelength_nm: float
    peak_intensity_au: float
    peak_energy_ev: float
    baseline_level_au: float
    half_max_level_au: float
    fwhm_left_nm: float
    fwhm_right_nm: float
    presentation_fwhm_nm: float
    integrated_intensity_au_nm: float
    spectral_centroid_nm: float
    noise_sigma_au: float
    snr_estimate: float
    secondary_features: tuple[SecondaryFeature, ...]
    smoothing_sigma_points: float
    quality_flags: tuple[str, ...] = ()
    algorithm_version: int = 1


@dataclass(frozen=True, slots=True)
class PresentationAnalysis:
    """Metrics plus the display-only smoothed spectrum used to derive them."""

    metrics: PresentationMetrics
    smoothed_intensity_au: NDArray[np.float64]


class PresentationAnalyzer:
    """Calculate explicit display-assisted metrics across one complete spectrum."""

    algorithm_version = 1

    def analyze(
        self,
        spectrum: SpectrumSeries,
        *,
        smoothing_sigma_points: float = 1.5,
    ) -> PresentationAnalysis:
        """Return quick metrics without changing stored raw intensity arrays."""

        if not math.isfinite(smoothing_sigma_points) or smoothing_sigma_points < 0:
            raise AnalysisError(
                "Presentation smoothing sigma must be a finite non-negative number.",
                code="E_PRESENTATION_INVALID_SMOOTHING",
            )
        wavelength = spectrum.wavelength_nm
        intensity = spectrum.intensity_au
        if wavelength.size < 5:
            raise AnalysisError(
                "At least five spectral points are required for presentation analysis.",
                code="E_PRESENTATION_TOO_FEW_POINTS",
            )

        smoothed = (
            gaussian_filter1d(intensity, smoothing_sigma_points, mode="reflect")
            if smoothing_sigma_points > 0
            else intensity.astype(np.float64, copy=True)
        )
        smoothed = np.asarray(smoothed, dtype=np.float64)
        smoothed.setflags(write=False)
        peak_index = int(np.argmax(smoothed))
        baseline = _baseline_level(smoothed)
        peak_amplitude = float(smoothed[peak_index] - baseline)
        if peak_amplitude <= 0:
            raise AnalysisError(
                "No PL peak rises above the estimated presentation baseline.",
                code="E_PRESENTATION_NO_PEAK",
            )

        left_nm, right_nm, half_level, quality_flags = _half_height_width(
            wavelength,
            smoothed,
            peak_index,
            baseline,
        )
        noise_sigma = _noise_sigma(wavelength, intensity, smoothed)
        positive = np.clip(smoothed - baseline, 0.0, None)
        integrated = float(trapezoid(positive, wavelength))
        centroid = (
            float(trapezoid(wavelength * positive, wavelength) / integrated)
            if integrated > 0
            else float(wavelength[peak_index])
        )
        secondary = _secondary_features(
            wavelength,
            smoothed,
            peak_index=peak_index,
            baseline=baseline,
            noise_sigma=noise_sigma,
        )
        metrics = PresentationMetrics(
            peak_wavelength_nm=float(wavelength[peak_index]),
            peak_intensity_au=float(smoothed[peak_index]),
            peak_energy_ev=float(HC_EV_NM / wavelength[peak_index]),
            baseline_level_au=baseline,
            half_max_level_au=half_level,
            fwhm_left_nm=left_nm,
            fwhm_right_nm=right_nm,
            presentation_fwhm_nm=right_nm - left_nm,
            integrated_intensity_au_nm=integrated,
            spectral_centroid_nm=centroid,
            noise_sigma_au=noise_sigma,
            snr_estimate=float(peak_amplitude / noise_sigma),
            secondary_features=secondary,
            smoothing_sigma_points=float(smoothing_sigma_points),
            quality_flags=quality_flags,
            algorithm_version=self.algorithm_version,
        )
        return PresentationAnalysis(metrics=metrics, smoothed_intensity_au=smoothed)


def _baseline_level(smoothed: NDArray[np.float64]) -> float:
    edge_count = min(max(3, int(round(0.04 * smoothed.size))), smoothed.size // 2)
    edge_pool = np.concatenate((smoothed[:edge_count], smoothed[-edge_count:]))
    baseline = float(max(np.percentile(smoothed, 2), np.percentile(edge_pool, 10)))
    peak = float(np.max(smoothed))
    if baseline > float(np.min(smoothed)) + 0.12 * float(np.ptp(smoothed)):
        baseline = float(np.percentile(smoothed, 1))
    return min(baseline, peak)


def _half_height_width(
    wavelength_nm: NDArray[np.float64],
    smoothed: NDArray[np.float64],
    peak_index: int,
    baseline: float,
) -> tuple[float, float, float, tuple[str, ...]]:
    half_level = baseline + 0.5 * (float(smoothed[peak_index]) - baseline)
    flags: list[str] = []

    left_index = peak_index
    while left_index > 0 and smoothed[left_index] >= half_level:
        left_index -= 1
    if left_index == 0 and smoothed[left_index] >= half_level:
        left_nm = float(wavelength_nm[0])
        flags.append("PRESENTATION_WIDTH_TRUNCATED_LEFT")
    else:
        left_nm = _linear_crossing(
            float(wavelength_nm[left_index]),
            float(smoothed[left_index]),
            float(wavelength_nm[left_index + 1]),
            float(smoothed[left_index + 1]),
            half_level,
        )

    right_index = peak_index
    last_index = smoothed.size - 1
    while right_index < last_index and smoothed[right_index] >= half_level:
        right_index += 1
    if right_index == last_index and smoothed[right_index] >= half_level:
        right_nm = float(wavelength_nm[-1])
        flags.append("PRESENTATION_WIDTH_TRUNCATED_RIGHT")
    else:
        right_nm = _linear_crossing(
            float(wavelength_nm[right_index - 1]),
            float(smoothed[right_index - 1]),
            float(wavelength_nm[right_index]),
            float(smoothed[right_index]),
            half_level,
        )
    return left_nm, right_nm, half_level, tuple(flags)


def _linear_crossing(x1: float, y1: float, x2: float, y2: float, target: float) -> float:
    if y2 == y1:
        return 0.5 * (x1 + x2)
    return x1 + (target - y1) * (x2 - x1) / (y2 - y1)


def _noise_sigma(
    wavelength_nm: NDArray[np.float64],
    intensity: NDArray[np.float64],
    smoothed: NDArray[np.float64],
) -> float:
    residual = intensity - smoothed
    threshold = min(
        650.0,
        float(wavelength_nm[0]) + 0.15 * float(np.ptp(wavelength_nm)),
    )
    noise_values = residual[wavelength_nm <= threshold]
    if noise_values.size < 8:
        noise_values = residual[: max(3, residual.size // 10)]
    center = float(np.median(noise_values))
    sigma = float(1.4826 * np.median(np.abs(noise_values - center)))
    if sigma <= 0:
        sigma = float(np.std(noise_values))
    return max(sigma, float(np.finfo(np.float64).eps))


def _secondary_features(
    wavelength_nm: NDArray[np.float64],
    smoothed: NDArray[np.float64],
    *,
    peak_index: int,
    baseline: float,
    noise_sigma: float,
) -> tuple[SecondaryFeature, ...]:
    main_amplitude = float(smoothed[peak_index] - baseline)
    step_nm = float(np.median(np.diff(wavelength_nm)))
    distance_points = max(1, int(round(12.0 / step_nm)))
    minimum_prominence = max(4.0 * noise_sigma, 0.012 * main_amplitude)
    indexes, properties = find_peaks(
        smoothed,
        prominence=minimum_prominence,
        distance=distance_points,
    )
    candidates: list[SecondaryFeature] = []
    for result_index, index in enumerate(indexes):
        if index == peak_index or abs(float(wavelength_nm[index] - wavelength_nm[peak_index])) < 5:
            continue
        amplitude = float(smoothed[index] - baseline)
        if amplitude < 0.025 * main_amplitude:
            continue
        candidates.append(
            SecondaryFeature(
                wavelength_nm=float(wavelength_nm[index]),
                intensity_au=float(smoothed[index]),
                relative_height=float(amplitude / main_amplitude),
                prominence_au=float(properties["prominences"][result_index]),
                energy_ev=float(HC_EV_NM / wavelength_nm[index]),
            )
        )
    candidates.sort(key=lambda item: item.intensity_au, reverse=True)
    return tuple(candidates[:4])
