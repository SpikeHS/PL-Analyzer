"""Direct, non-fitting peak measurements for raw PL spectra."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.signal import find_peaks, peak_widths

from core.errors import AnalysisError
from core.models import PeakAnalysisResult, PeakResult, SpectrumSeries


@dataclass(frozen=True, slots=True)
class RawPeakConfig:
    """Controls for direct peak detection in wavelength units."""

    search_min_nm: float
    search_max_nm: float
    relative_prominence: float = 0.02
    min_prominence_au: float | None = None
    noise_sigma_factor: float = 3.0
    min_distance_nm: float = 0.0
    max_peaks: int = 20
    gap_factor: float = 10.0

    def validate(self) -> None:
        """Raise a stable error for invalid operator input."""

        numeric_values = (
            self.search_min_nm,
            self.search_max_nm,
            self.relative_prominence,
            self.noise_sigma_factor,
            self.min_distance_nm,
            self.gap_factor,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise AnalysisError(
                "Peak settings must contain finite numbers.",
                code="E_PEAK_INVALID_CONFIG",
            )
        if self.search_min_nm >= self.search_max_nm:
            raise AnalysisError(
                "Search minimum must be smaller than search maximum.",
                code="E_PEAK_INVALID_WINDOW",
            )
        if not 0 <= self.relative_prominence <= 1:
            raise AnalysisError(
                "Relative prominence must be between 0 and 1.",
                code="E_PEAK_INVALID_CONFIG",
            )
        if self.min_prominence_au is not None and (
            not math.isfinite(self.min_prominence_au) or self.min_prominence_au < 0
        ):
            raise AnalysisError(
                "Absolute prominence cannot be negative.",
                code="E_PEAK_INVALID_CONFIG",
            )
        if (
            self.noise_sigma_factor < 0
            or self.min_distance_nm < 0
            or self.max_peaks < 1
            or self.gap_factor <= 1
        ):
            raise AnalysisError(
                "Peak settings contain an invalid limit.",
                code="E_PEAK_INVALID_CONFIG",
            )


class RawPeakAnalyzer:
    """Measure sampled maxima and half-prominence widths without fitting."""

    algorithm_version = 1

    def analyze(
        self,
        wavelength_nm: ArrayLike,
        intensity_au: ArrayLike,
        config: RawPeakConfig,
    ) -> PeakAnalysisResult:
        """Analyze one spectrum while preserving its original sampled values."""

        config.validate()
        wavelength, intensity, diagnostics = _prepare_arrays(wavelength_nm, intensity_au)
        center_mask = (
            (wavelength >= config.search_min_nm)
            & (wavelength <= config.search_max_nm)
            & np.isfinite(intensity)
        )
        center_values = intensity[center_mask]
        if center_values.size == 0:
            raise AnalysisError(
                "No finite spectral data falls inside the search window.",
                code="E_PEAK_NO_FINITE_DATA",
            )

        segments, segment_diagnostics = _continuous_segments(
            wavelength,
            intensity,
            gap_factor=config.gap_factor,
        )
        diagnostics.extend(segment_diagnostics)
        effective_prominence = _effective_prominence(
            center_values,
            segments,
            config,
        )

        candidates: list[PeakResult] = []
        for segment_slice in segments:
            x_segment = wavelength[segment_slice]
            y_segment = intensity[segment_slice]
            candidates.extend(
                self._segment_peaks(
                    x_segment,
                    y_segment,
                    config=config,
                    effective_prominence=effective_prominence,
                )
            )

        retained = _apply_physical_distance_and_limit(candidates, config)
        return PeakAnalysisResult(
            peaks=tuple(sorted(retained, key=lambda peak: peak.position_nm)),
            effective_prominence_au=effective_prominence,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            algorithm_version=self.algorithm_version,
        )

    def analyze_spectrum(
        self,
        spectrum: SpectrumSeries,
        config: RawPeakConfig,
    ) -> PeakAnalysisResult:
        """Convenience adapter for the shared spectrum domain model."""

        return self.analyze(spectrum.wavelength_nm, spectrum.intensity_au, config)

    @staticmethod
    def _segment_peaks(
        wavelength_nm: NDArray[np.float64],
        intensity_au: NDArray[np.float64],
        *,
        config: RawPeakConfig,
        effective_prominence: float,
    ) -> list[PeakResult]:
        candidates: list[PeakResult] = []
        if wavelength_nm.size >= 3:
            peak_indexes, properties = find_peaks(
                intensity_au,
                prominence=0.0,
                plateau_size=True,
            )
            if peak_indexes.size:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    widths, width_levels, left_ips, right_ips = peak_widths(
                        intensity_au,
                        peak_indexes,
                        rel_height=0.5,
                        prominence_data=(
                            properties["prominences"],
                            properties["left_bases"],
                            properties["right_bases"],
                        ),
                    )

                sample_axis = np.arange(wavelength_nm.size, dtype=np.float64)
                for result_index, peak_index in enumerate(peak_indexes):
                    position_nm = float(wavelength_nm[peak_index])
                    prominence = float(properties["prominences"][result_index])
                    if not _inside_search_window(position_nm, config):
                        continue
                    if prominence < effective_prominence:
                        continue

                    left_nm = float(
                        np.interp(float(left_ips[result_index]), sample_axis, wavelength_nm)
                    )
                    right_nm = float(
                        np.interp(float(right_ips[result_index]), sample_axis, wavelength_nm)
                    )
                    fwhm_nm = right_nm - left_nm
                    flags: list[str] = []
                    if int(properties["plateau_sizes"][result_index]) > 1:
                        flags.append("PLATEAU")
                    if not math.isfinite(fwhm_nm) or fwhm_nm <= 0 or widths[result_index] <= 0:
                        fwhm_value: float | None = None
                        flags.append("WIDTH_UNRESOLVED")
                    else:
                        fwhm_value = fwhm_nm
                    candidates.append(
                        PeakResult(
                            position_nm=position_nm,
                            height_au=float(intensity_au[peak_index]),
                            fwhm_nm=fwhm_value,
                            prominence_au=prominence,
                            width_level_au=float(width_levels[result_index]),
                            quality_flags=tuple(flags),
                        )
                    )

        if wavelength_nm.size >= 2:
            left_prominence = float(intensity_au[0] - np.min(intensity_au))
            if (
                intensity_au[0] > intensity_au[1]
                and left_prominence >= effective_prominence
                and _inside_search_window(float(wavelength_nm[0]), config)
            ):
                candidates.append(
                    PeakResult(
                        position_nm=float(wavelength_nm[0]),
                        height_au=float(intensity_au[0]),
                        fwhm_nm=None,
                        prominence_au=left_prominence,
                        width_level_au=None,
                        quality_flags=("TRUNCATED_LEFT",),
                    )
                )

            right_prominence = float(intensity_au[-1] - np.min(intensity_au))
            if (
                intensity_au[-1] > intensity_au[-2]
                and right_prominence >= effective_prominence
                and _inside_search_window(float(wavelength_nm[-1]), config)
            ):
                candidates.append(
                    PeakResult(
                        position_nm=float(wavelength_nm[-1]),
                        height_au=float(intensity_au[-1]),
                        fwhm_nm=None,
                        prominence_au=right_prominence,
                        width_level_au=None,
                        quality_flags=("TRUNCATED_RIGHT",),
                    )
                )
        return candidates


def _prepare_arrays(
    wavelength_nm: ArrayLike,
    intensity_au: ArrayLike,
) -> tuple[NDArray[np.float64], NDArray[np.float64], list[str]]:
    wavelength = np.asarray(wavelength_nm, dtype=np.float64)
    intensity = np.asarray(intensity_au, dtype=np.float64)
    if wavelength.ndim != 1 or intensity.ndim != 1:
        raise AnalysisError(
            "Wavelength and intensity must be one-dimensional.",
            code="E_PEAK_SHAPE",
        )
    if wavelength.size != intensity.size:
        raise AnalysisError(
            "Wavelength and intensity lengths do not match.",
            code="E_PEAK_LENGTH_MISMATCH",
        )
    if wavelength.size < 3:
        raise AnalysisError(
            "At least three spectral points are required.",
            code="E_PEAK_INSUFFICIENT_POINTS",
        )

    diagnostics: list[str] = []
    finite_wavelength = np.isfinite(wavelength)
    if not np.all(finite_wavelength):
        wavelength = wavelength[finite_wavelength]
        intensity = intensity[finite_wavelength]
        diagnostics.append("NONFINITE_WAVELENGTH_DROPPED")
    if wavelength.size < 3:
        raise AnalysisError(
            "Fewer than three finite wavelength values remain.",
            code="E_PEAK_INSUFFICIENT_POINTS",
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
            values = intensity[start : start + count]
            finite_values = values[np.isfinite(values)]
            merged_intensity[index] = (
                float(np.mean(finite_values)) if finite_values.size else np.nan
            )
        wavelength = unique_wavelengths
        intensity = merged_intensity
        diagnostics.append("DUPLICATE_WAVELENGTH_AVERAGED")

    if wavelength.size < 3:
        raise AnalysisError(
            "Fewer than three unique wavelength values remain.",
            code="E_PEAK_INSUFFICIENT_POINTS",
        )
    if np.count_nonzero(np.isfinite(intensity)) < 2:
        raise AnalysisError(
            "No usable finite intensity data remains.",
            code="E_PEAK_NO_FINITE_DATA",
        )
    return wavelength, intensity, diagnostics


def _continuous_segments(
    wavelength_nm: NDArray[np.float64],
    intensity_au: NDArray[np.float64],
    *,
    gap_factor: float,
) -> tuple[list[slice], list[str]]:
    finite_intensity = np.isfinite(intensity_au)
    positive_steps = np.diff(wavelength_nm)
    median_step = float(np.median(positive_steps[positive_steps > 0]))
    gap_threshold = gap_factor * median_step

    segments: list[slice] = []
    diagnostics: list[str] = []
    start: int | None = None
    saw_nonfinite = False
    saw_large_gap = False
    for index in range(wavelength_nm.size):
        if not finite_intensity[index]:
            saw_nonfinite = True
            if start is not None:
                segments.append(slice(start, index))
                start = None
            continue
        if (
            start is not None
            and index > 0
            and wavelength_nm[index] - wavelength_nm[index - 1] > gap_threshold
        ):
            saw_large_gap = True
            segments.append(slice(start, index))
            start = index
            continue
        if start is None:
            start = index
    if start is not None:
        segments.append(slice(start, wavelength_nm.size))

    segments = [segment for segment in segments if segment.stop - segment.start >= 2]
    if saw_nonfinite:
        diagnostics.append("NONFINITE_INTENSITY_SEGMENTED")
    if saw_large_gap:
        diagnostics.append("LARGE_WAVELENGTH_GAP_SEGMENTED")
    return segments, diagnostics


def _effective_prominence(
    center_values: NDArray[np.float64],
    segments: list[slice],
    config: RawPeakConfig,
) -> float:
    if config.min_prominence_au is not None:
        return float(config.min_prominence_au)

    dynamic_range = float(np.max(center_values) - np.percentile(center_values, 10))
    if dynamic_range <= 0:
        return 0.0

    # Segments is retained in the API so the estimator can evolve without changing
    # the public result contract. The cap prevents a steep physical peak from being
    # misclassified as noise on short spectra.
    _ = segments
    differences = np.diff(center_values)
    if differences.size:
        median_difference = float(np.median(differences))
        mad = float(np.median(np.abs(differences - median_difference)))
        noise_sigma = mad / (0.6744897501960817 * math.sqrt(2.0))
    else:
        noise_sigma = 0.0
    noise_threshold = min(
        config.noise_sigma_factor * noise_sigma,
        0.25 * dynamic_range,
    )
    return max(config.relative_prominence * dynamic_range, noise_threshold)


def _apply_physical_distance_and_limit(
    candidates: list[PeakResult],
    config: RawPeakConfig,
) -> list[PeakResult]:
    prioritized = sorted(
        candidates,
        key=lambda peak: (peak.prominence_au, peak.height_au),
        reverse=True,
    )
    retained: list[PeakResult] = []
    for candidate in prioritized:
        if all(
            abs(candidate.position_nm - existing.position_nm) >= config.min_distance_nm
            for existing in retained
        ):
            retained.append(candidate)
            if len(retained) >= config.max_peaks:
                break
    return retained


def _inside_search_window(position_nm: float, config: RawPeakConfig) -> bool:
    return config.search_min_nm <= position_nm <= config.search_max_nm
